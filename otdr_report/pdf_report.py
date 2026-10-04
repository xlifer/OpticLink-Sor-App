"""Μαζική δημιουργία PDF αναφορών (ένα PDF ανά καλώδιο, μία σελίδα ανά ίνα)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Flowable, Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .matching import Cable, Fiber
from .settings import ReportSettings, evaluate, event_ok
from .sor import SorFile, downsample, parse_sor

FONT_DIR = Path(__file__).parent / "fonts"
_fonts_ready = False

WL_COLORS = {
    1310: colors.HexColor("#1f6feb"),
    1550: colors.HexColor("#d1242f"),
    1625: colors.HexColor("#8250df"),
    1490: colors.HexColor("#1a7f37"),
    850: colors.HexColor("#bf8700"),
    1300: colors.HexColor("#0a7ea4"),
}

TEXT = {
    "el": {
        "title": "Αναφορά μέτρησης OTDR",
        "summary": "Σύνοψη καλωδίου",
        "cable": "Καλώδιο", "fiber": "Ίνα", "customer": "Πελάτης", "project": "Έργο",
        "operator": "Τεχνικός", "date": "Ημερομηνία", "file": "Αρχείο",
        "wl": "λ (nm)", "pulse": "Παλμός (ns)", "ior": "IOR", "avg": "Μέσοι όροι",
        "length": "Μήκος (km)", "loss": "Απώλεια (dB)", "att": "dB/km", "orl": "ORL (dB)",
        "result": "Αποτέλεσμα", "events": "Συμβάντα", "no": "Α/Α", "type": "Τύπος",
        "dist": "Απόσταση (km)", "section": "Τμήμα (km)", "eloss": "Απώλεια (dB)",
        "refl": "Ανάκλαση (dB)", "cum": "Αθρ. (dB)", "missing": "λείπει",
        "page": "Σελίδα", "of": "από", "fibers": "Ίνες", "pass": "PASS", "fail": "FAIL",
        "otdr": "Όργανο", "generated": "Δημιουργήθηκε", "incomplete": "Ίνες χωρίς όλα τα μήκη κύματος",
        "types": {"Αρχή": "Αρχή", "Τέλος": "Τέλος", "Ανακλαστικό": "Ανακλαστικό", "Μη ανακλ.": "Μη ανακλ."},
        "signature": "Υπογραφή",
    },
    "en": {
        "title": "OTDR Test Report",
        "summary": "Cable summary",
        "cable": "Cable", "fiber": "Fiber", "customer": "Customer", "project": "Project",
        "operator": "Operator", "date": "Date", "file": "File",
        "wl": "λ (nm)", "pulse": "Pulse (ns)", "ior": "IOR", "avg": "Averages",
        "length": "Length (km)", "loss": "Loss (dB)", "att": "dB/km", "orl": "ORL (dB)",
        "result": "Result", "events": "Events", "no": "No", "type": "Type",
        "dist": "Distance (km)", "section": "Section (km)", "eloss": "Loss (dB)",
        "refl": "Reflect. (dB)", "cum": "Cum. (dB)", "missing": "missing",
        "page": "Page", "of": "of", "fibers": "Fibers", "pass": "PASS", "fail": "FAIL",
        "otdr": "Instrument", "generated": "Generated", "incomplete": "Fibers missing a wavelength",
        "types": {"Αρχή": "Start", "Τέλος": "End", "Ανακλαστικό": "Reflective", "Μη ανακλ.": "Non-refl."},
        "signature": "Signature",
    },
}

PASS_C = colors.HexColor("#1a7f37")
FAIL_C = colors.HexColor("#cf222e")
HEAD_BG = colors.HexColor("#0b3d6e")
GRID_C = colors.HexColor("#c8d1dc")
ZEBRA = colors.HexColor("#f3f6f9")


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")
    _fonts_ready = True


def _fmt(v, digits=3, dash="–"):
    if v is None:
        return dash
    return f"{v:.{digits}f}"


class TraceChart(Flowable):
    """Γράφημα OTDR με μία ή περισσότερες καμπύλες και σημάδια συμβάντων."""

    def __init__(self, sors: list[SorFile], width: float, height: float, title: str = ""):
        super().__init__()
        self.sors = sors
        self.width = width
        self.height = height
        self.title = title

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        left, bottom, right, top = 38, 22, 8, 14 if self.title else 6
        pw, ph = self.width - left - right, self.height - bottom - top

        sors = [s for s in self.sors if len(s.trace)]
        max_len = max((s.length_km for s in sors), default=0)
        xmax = max_len * 1.08 if max_len > 0 else max(
            (len(s.trace) * s.resolution_km for s in sors), default=1.0)
        xmax = max(xmax, 0.05)
        series = []
        for s in sors:
            x, y = downsample(s, 900, xmax)
            valid = y > -65.0  # 0xFFFF = μη έγκυρο/κορεσμένο σημείο
            series.append((s, x, np.where(valid, y, np.nan)))
        ys = np.concatenate([y[~np.isnan(y)] for _, _, y in series]) if series else np.array([0.0])
        if not len(ys):
            ys = np.array([0.0])
        ymax = float(np.max(ys)) + 1.5
        ymin = float(np.percentile(ys, 1)) - 1.5
        if ymax - ymin < 5:
            ymin = ymax - 5

        def tx(v): return left + (v / xmax) * pw
        def ty(v): return bottom + (v - ymin) / (ymax - ymin) * ph

        c.saveState()
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#7d8590"))
        c.setLineWidth(0.6)
        c.rect(left, bottom, pw, ph, fill=1, stroke=1)

        c.setFont("DejaVu", 6.5)
        c.setFillColor(colors.HexColor("#444c56"))
        for v in _nice_ticks(0, xmax, 8):
            X = tx(v)
            c.setStrokeColor(GRID_C); c.setLineWidth(0.3); c.setDash(1, 2)
            c.line(X, bottom, X, bottom + ph)
            c.setDash()
            c.drawCentredString(X, bottom - 9, _tick_label(v))
        for v in _nice_ticks(ymin, ymax, 6):
            Y = ty(v)
            c.setStrokeColor(GRID_C); c.setLineWidth(0.3); c.setDash(1, 2)
            c.line(left, Y, left + pw, Y)
            c.setDash()
            c.drawRightString(left - 3, Y - 2, _tick_label(v))
        c.drawRightString(left + pw, 4, "km")
        c.saveState()
        c.translate(9, bottom + ph / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, "dB")
        c.restoreState()

        p = c.beginPath()
        p.rect(left, bottom, pw, ph)
        c.clipPath(p, stroke=0, fill=0)
        for s, x, y in series:
            col = WL_COLORS.get(s.wavelength, colors.black)
            c.setStrokeColor(col)
            c.setLineWidth(0.55)
            path = c.beginPath()
            pen = False
            for xi, yi in zip(x, y):
                if np.isnan(yi):
                    pen = False
                    continue
                if pen:
                    path.lineTo(tx(xi), ty(yi))
                else:
                    path.moveTo(tx(xi), ty(yi))
                    pen = True
            c.drawPath(path, stroke=1, fill=0)
        c.restoreState()

        # Σημάδια συμβάντων στην πρώτη καμπύλη, για να μη γεμίζει το γράφημα
        if sors:
            ref = sors[0]
            c.saveState()
            c.setFont("DejaVu", 5.5)
            for i, e in enumerate(ref.events, 1):
                if e.distance_km > xmax:
                    continue
                X = tx(e.distance_km)
                c.setStrokeColor(colors.HexColor("#57606a"))
                c.setLineWidth(0.4)
                c.line(X, bottom + ph - 9, X, bottom + ph)
                c.setFillColor(colors.HexColor("#24292f"))
                c.drawCentredString(X, bottom + ph - 15, str(i))
            c.restoreState()

        # Υπόμνημα
        c.saveState()
        c.setFont("DejaVu-Bold", 7)
        lx = left + pw - 4
        for s in reversed(sors):
            label = f"{s.wavelength} nm"
            w = c.stringWidth(label, "DejaVu-Bold", 7)
            c.setFillColor(WL_COLORS.get(s.wavelength, colors.black))
            c.drawRightString(lx, bottom + ph + 3, label)
            c.rect(lx - w - 11, bottom + ph + 3.5, 8, 2.5, fill=1, stroke=0)
            lx -= w + 18
        if self.title:
            c.setFillColor(colors.black)
            c.drawString(left, bottom + ph + 3, self.title)
        c.restoreState()


def _nice_ticks(lo, hi, n):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** np.floor(np.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = np.ceil(lo / step) * step
    out = []
    v = start
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _tick_label(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


class ReportBuilder:
    def __init__(self, settings: ReportSettings):
        _register_fonts()
        self.s = settings
        self.t = TEXT.get(settings.language, TEXT["el"])
        self.st = {
            "h1": ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=13, leading=16, spaceAfter=2),
            "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=9.5, leading=12,
                                 spaceBefore=6, spaceAfter=3, textColor=HEAD_BG),
            "n": ParagraphStyle("n", fontName="DejaVu", fontSize=8, leading=10),
            "small": ParagraphStyle("s", fontName="DejaVu", fontSize=6.5, leading=8,
                                    textColor=colors.HexColor("#57606a")),
            "right": ParagraphStyle("r", fontName="DejaVu", fontSize=7.5, leading=9.5, alignment=TA_RIGHT),
        }

    # ---------- κοινά στοιχεία ----------
    def _header(self, title: str, subtitle: str):
        t = self.t
        logo = None
        if self.s.logo_path and Path(self.s.logo_path).is_file():
            try:
                img = Image(self.s.logo_path)
                ratio = img.imageWidth / float(img.imageHeight or 1)
                h = 14 * mm
                img.drawHeight, img.drawWidth = h, min(h * ratio, 50 * mm)
                logo = img
            except Exception:
                logo = None
        right_lines = [f"<b>{_esc(self.s.company)}</b>"] if self.s.company else []
        if self.s.company_info:
            right_lines += [_esc(x) for x in self.s.company_info.splitlines()]
        left = [Paragraph(_esc(title), self.st["h1"]), Paragraph(_esc(subtitle), self.st["n"])]
        meta = []
        if self.s.customer:
            meta.append(f"{t['customer']}: <b>{_esc(self.s.customer)}</b>")
        if self.s.project:
            meta.append(f"{t['project']}: <b>{_esc(self.s.project)}</b>")
        if meta:
            left.append(Paragraph(" &nbsp; · &nbsp; ".join(meta), self.st["n"]))
        right = [logo] if logo else []
        right.append(Paragraph("<br/>".join(right_lines), self.st["right"]))
        tbl = Table([[left, right]], colWidths=[None, 62 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, HEAD_BG),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return tbl

    def _table(self, rows, col_widths, result_col=None, font_size=7):
        head_style = ParagraphStyle("th", fontName="DejaVu-Bold", fontSize=font_size,
                                    leading=font_size + 1.5, textColor=colors.white, alignment=1)
        rows = [[Paragraph(_esc(str(h)), head_style) for h in rows[0]]] + rows[1:]
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, -1), "DejaVu", font_size),
            ("FONT", (0, 0), (-1, 0), "DejaVu-Bold", font_size),
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
            if result_col is not None:
                for col in ([result_col] if isinstance(result_col, int) else result_col):
                    val = rows[i][col]
                    if val == self.t["pass"]:
                        style.append(("TEXTCOLOR", (col, i), (col, i), PASS_C))
                        style.append(("FONT", (col, i), (col, i), "DejaVu-Bold", font_size))
                    elif val == self.t["fail"]:
                        style.append(("TEXTCOLOR", (col, i), (col, i), FAIL_C))
                        style.append(("FONT", (col, i), (col, i), "DejaVu-Bold", font_size))
                    elif val == self.t["missing"]:
                        style.append(("TEXTCOLOR", (col, i), (col, i), colors.HexColor("#9a6700")))
        tbl.setStyle(TableStyle(style))
        return tbl

    def _verdict(self, ok):
        if ok is None:
            return "–"
        return self.t["pass"] if ok else self.t["fail"]

    # ---------- σελίδα σύνοψης ----------
    def summary_story(self, cable: Cable, fibers: list[Fiber]):
        t = self.t
        wls = cable.wavelengths
        story = [self._header(t["title"], f"{t['summary']}: {cable.name}"), Spacer(1, 4 * mm)]
        info = f"{t['cable']}: <b>{_esc(cable.name)}</b> &nbsp; · &nbsp; {t['fibers']}: <b>{len(fibers)}</b>"
        info += " &nbsp; · &nbsp; λ: <b>" + ", ".join(f"{w} nm" for w in wls) + "</b>"
        story.append(Paragraph(info, self.st["n"]))
        story.append(Spacer(1, 3 * mm))

        head = [t["fiber"]]
        for w in wls:
            head += [f"{w} – {t['length']}", f"{w} – {t['loss']}", f"{w} – {t['att']}", f"{w} – {t['result']}"]
        head.append(t["result"])
        rows = [head]
        result_cols = [4 * i + 4 for i in range(len(wls))] + [len(head) - 1]
        n_pass = n_fail = 0
        for f in fibers:
            row = [f.label or str(f.number)]
            overall = True
            for w in wls:
                m = f.measurements.get(w)
                if not m:
                    row += ["–", "–", "–", t["missing"]]
                    overall = False
                    continue
                ok = evaluate(m.sor, self.s.thresholds)
                row += [_fmt(m.sor.length_km, 3), _fmt(m.sor.total_loss, 2),
                        _fmt(m.sor.attenuation, 3), self._verdict(ok)]
                if ok is False:
                    overall = False
                elif ok is None and overall is True:
                    overall = None
            row.append(self._verdict(overall))
            n_pass += overall is True
            n_fail += overall is False
            rows.append(row)
        avail = A4[0] - 24 * mm
        first = 16 * mm
        rest = (avail - first - 21 * mm) / max(1, 4 * len(wls))
        widths = [first] + [rest] * (4 * len(wls)) + [21 * mm]
        story.append(self._table(rows, widths, result_col=result_cols, font_size=6.5))
        story.append(Spacer(1, 3 * mm))
        if self.s.thresholds.enabled:
            story.append(Paragraph(
                f"{t['pass']}: <b>{n_pass}</b> &nbsp; · &nbsp; {t['fail']}: <b>{n_fail}</b>", self.st["n"]))
        miss = [f.label or str(f.number) for f in fibers if set(f.measurements) != set(wls)]
        if miss:
            story.append(Paragraph(f"{t['incomplete']}: " + ", ".join(miss), self.st["small"]))
        story.append(PageBreak())
        return story

    # ---------- σελίδα ίνας ----------
    def fiber_story(self, cable: Cable, fiber: Fiber, sors: dict[int, SorFile]):
        t = self.t
        wls = cable.wavelengths
        title = f"{t['cable']}: {cable.name}   ·   {t['fiber']}: {fiber.label or fiber.number}"
        story = [self._header(t["title"], title), Spacer(1, 3 * mm)]

        # Πίνακας στοιχείων μέτρησης
        head = [t["wl"], t["file"], t["date"], t["pulse"], t["ior"], t["length"],
                t["loss"], t["att"], t["orl"], t["result"]]
        rows = [head]
        present = []
        for w in wls:
            s = sors.get(w)
            if s is None:
                rows.append([str(w), t["missing"], "", "", "", "", "", "", "", ""])
                continue
            present.append(s)
            rows.append([
                str(w), _short(s.path.name if s.path else "", 34),
                s.date.strftime("%d/%m/%Y %H:%M") if s.date else "–",
                str(s.pulse_width_ns), f"{s.ior:.4f}", _fmt(s.length_km, 3),
                _fmt(s.total_loss, 2), _fmt(s.attenuation, 3), _fmt(s.orl, 1) if s.orl else "–",
                self._verdict(evaluate(s, self.s.thresholds)),
            ])
        widths = [12 * mm, 45 * mm, 23 * mm, 15 * mm, 13 * mm, 15 * mm, 15 * mm, 12 * mm, 13 * mm, 23 * mm]
        story.append(self._table(rows, widths, result_col=9))
        story.append(Spacer(1, 3 * mm))

        chart_w = A4[0] - 24 * mm
        if self.s.chart_mode == "separate" and len(present) > 1:
            h = 58 * mm if len(present) == 2 else 42 * mm
            for s in present:
                story.append(TraceChart([s], chart_w, h, f"{s.wavelength} nm"))
                story.append(Spacer(1, 2 * mm))
        elif present:
            story.append(TraceChart(present, chart_w, 82 * mm))
            story.append(Spacer(1, 2 * mm))

        for s in present:
            story.append(KeepTogether([
                Paragraph(f"{t['events']} – {s.wavelength} nm", self.st["h2"]),
                self._events_table(s),
            ]))
        foot = []
        if s_inst := next((x for x in present if x.supplier or x.otdr_model), None):
            foot.append(f"{t['otdr']}: {_esc(' '.join(filter(None, [s_inst.supplier, s_inst.otdr_model, s_inst.otdr_sn])))}")
        if self.s.operator:
            foot.append(f"{t['operator']}: {_esc(self.s.operator)}")
        if foot:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(" &nbsp; · &nbsp; ".join(foot), self.st["small"]))
        story.append(PageBreak())
        return story

    def _events_table(self, s: SorFile):
        t = self.t
        rows = [[t["no"], t["type"], t["dist"], t["section"], t["eloss"], t["refl"],
                 t["att"], t["cum"], t["result"]]]
        for i, e in enumerate(s.events, 1):
            ok = event_ok(e, self.s.thresholds)
            rows.append([
                str(i), t["types"].get(e.type_name, e.type_name), f"{e.distance_km:.4f}",
                f"{e.section_km:.4f}", _fmt(e.splice_loss, 3) if i > 1 else "–",
                _fmt(e.reflectance, 2) if e.reflectance else "–",
                _fmt(e.slope, 3) if i > 1 and e.slope else "–",
                _fmt(e.cumulative_loss, 3), self._verdict(ok) if ok is not None else "",
            ])
        w = (A4[0] - 24 * mm) / 9
        return self._table(rows, [w] * 9, result_col=8)

    # ---------- κατασκευή αρχείου ----------
    def build(self, out_path: Path, parts: list[tuple[Cable, list[Fiber]]],
              progress: Callable[[int, int, str], bool] | None = None) -> bool:
        total = sum(len(f) for _, f in parts)
        done = 0
        story = []
        for cable, fibers in parts:
            if self.s.summary_page:
                story += self.summary_story(cable, fibers)
            for fiber in fibers:
                sors = {}
                for w, m in fiber.measurements.items():
                    try:
                        sors[w] = parse_sor(m.path)
                    except Exception:
                        pass
                story += self.fiber_story(cable, fiber, sors)
                done += 1
                if progress and progress(done, total, f"{cable.name} / {fiber.label}") is False:
                    return False
        if story and isinstance(story[-1], PageBreak):
            story.pop()

        t = self.t
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M")

        def on_page(c, doc):
            c.saveState()
            c.setFont("DejaVu", 6.5)
            c.setFillColor(colors.HexColor("#57606a"))
            c.drawString(12 * mm, 8 * mm, f"{t['generated']}: {stamp}")
            c.drawRightString(A4[0] - 12 * mm, 8 * mm, f"{t['page']} {doc.page}")
            c.restoreState()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".part.pdf")
        doc = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=10 * mm, bottomMargin=14 * mm,
                                title=f"{t['title']} – " + ", ".join(c.name for c, _ in parts),
                                author=self.s.company or "")
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        tmp.replace(out_path)
        return True


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-(n - 1):]


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "report"


def generate_reports(parts: list[tuple[Cable, list[Fiber]]], out_dir: Path, settings: ReportSettings,
                     progress: Callable[[int, int, str], bool] | None = None) -> list[Path]:
    """Δημιουργεί τα PDF. Επιστρέφει τις διαδρομές που γράφτηκαν."""
    out_dir = Path(out_dir)
    builder = ReportBuilder(settings)
    written: list[Path] = []
    if settings.one_pdf_per_cable:
        total = sum(len(f) for _, f in parts)
        offset = 0
        for cable, fibers in parts:
            if not fibers:
                continue
            def sub(done, _tot, label, _o=offset):
                return progress(_o + done, total, label) if progress else True
            out = out_dir / f"{safe_filename(cable.name)}{_range_suffix(fibers)}.pdf"
            if not builder.build(out, [(cable, fibers)], sub):
                return written
            written.append(out)
            offset += len(fibers)
    else:
        out = out_dir / f"OTDR_report_{datetime.now():%Y%m%d_%H%M}.pdf"
        if builder.build(out, [p for p in parts if p[1]], progress):
            written.append(out)
    return written


def _range_suffix(fibers: list[Fiber]) -> str:
    nums = [f.number for f in fibers]
    if not nums:
        return ""
    width = max(len(f.label) for f in fibers) or 1
    return f"_{min(nums):0{width}d}-{max(nums):0{width}d}"
