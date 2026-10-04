"""Μαζική δημιουργία PDF αναφορών (ένα PDF ανά καλώδιο, μία σελίδα ανά ίνα).

Η σελίδα κάθε ίνας ακολουθεί την αναφορά του οργάνου Grandway FHO5000:
launch cable με αρνητικές αποστάσεις, συμβάν (S) στο 0, πίνακας συμβάντων με
γραμμές τμημάτων και αθροιστική απώλεια από το (S).
"""
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
from .settings import ReportSettings, evaluate, event_ok, is_dead_fiber, prepare
from .sor import SorError, SorFile, downsample, parse_sor

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
        "cable": "Καλώδιο", "fiber": "Μέτρηση", "customer": "Πελάτης", "project": "Έργο",
        "operator": "Τεχνικός", "date": "Ημερομηνία", "file": "Αρχείο",
        "wl": "λ (nm)", "pulse": "Παλμός (ns)", "ior": "IOR", "launch": "Launch",
        "length": "Μήκος", "loss": "Απώλεια (dB)", "att": "dB/km", "orl": "ORL (dB)",
        "result": "Αποτέλεσμα", "events": "Συμβάντα", "no": "#", "type": "Τύπος",
        "dist": "Απόσταση", "eloss": "Απώλεια (dB)", "refl": "Ανάκλαση (dB)", "cum": "Αθρ. απώλεια (dB)",
        "missing": "λείπει", "incomplete_v": "ΕΛΛΙΠΗΣ",
        "page": "Σελίδα", "fibers": "Μετρήσεις", "pass": "PASS", "fail": "FAIL",
        "otdr": "Όργανο", "generated": "Δημιουργήθηκε", "incomplete": "Μετρήσεις χωρίς όλα τα μήκη κύματος",
        "types": {"Αρχή": "Αρχή", "Τέλος": "Τέλος", "Ανακλαστικό": "Ανακλαστικό",
                  "Μη ανακλ.": "Μη ανακλ.", "Launch": "Launch", "seg": "Τμήμα"},
        "dead": "Νεκρή ίνα στα {wl} nm: δεν βρέθηκε ίνα μετά το launch cable (FAIL).",
        "slope": "Κλίση (dB/km)", "criteria": "Κριτήρια PASS", "launch_cable": "Launch cable", "link_map": "Link map",
        "prepared": "Συντάχθηκε από", "verified": "Ελέγχθηκε από", "approved": "Εγκρίθηκε από",
    },
    "en": {
        "title": "OTDR Test Report",
        "summary": "Cable summary",
        "cable": "Cable", "fiber": "Measurement", "customer": "Customer", "project": "Project",
        "operator": "Operator", "date": "Date", "file": "File",
        "wl": "λ (nm)", "pulse": "Pulse (ns)", "ior": "IOR", "launch": "Launch",
        "length": "Length", "loss": "Loss (dB)", "att": "dB/km", "orl": "ORL (dB)",
        "result": "Result", "events": "Events", "no": "#", "type": "Type",
        "dist": "Distance", "eloss": "Loss (dB)", "refl": "Reflect. (dB)", "cum": "T.Loss (dB)",
        "missing": "missing", "incomplete_v": "INCOMPLETE",
        "page": "Page", "fibers": "Measurements", "pass": "PASS", "fail": "FAIL",
        "otdr": "Instrument", "generated": "Generated", "incomplete": "Measurements missing a wavelength",
        "types": {"Αρχή": "Start", "Τέλος": "End", "Ανακλαστικό": "Reflective",
                  "Μη ανακλ.": "Non-refl.", "Launch": "Launch", "seg": "Seg."},
        "dead": "Dead fiber at {wl} nm: no fiber found after the launch cable (FAIL).",
        "slope": "Slope (dB/km)", "criteria": "PASS criteria", "launch_cable": "Launch cable", "link_map": "Link map",
        "prepared": "Prepared by", "verified": "Verified by", "approved": "Approved by",
    },
}

PASS_C = colors.HexColor("#1a7f37")
FAIL_C = colors.HexColor("#cf222e")
WARN_C = colors.HexColor("#9a6700")
HEAD_BG = colors.HexColor("#0b3d6e")
GRID_C = colors.HexColor("#c8d1dc")
ZEBRA = colors.HexColor("#f3f6f9")
MUTED = colors.HexColor("#57606a")
LAUNCH_C = colors.HexColor("#cf222e")


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


class Units:
    """Μέτρα για μικρές ίνες (όπως το όργανο), km για μεγάλες."""

    def __init__(self, max_km: float):
        self.m = max_km < 20
        self.name = "m" if self.m else "km"

    def fmt(self, km: float | None) -> str:
        if km is None:
            return "–"
        return f"{km * 1000:.1f}" if self.m else f"{km:.4f}"

    def axis(self, km: float) -> float:
        return km * 1000 if self.m else km


class TraceChart(Flowable):
    """Γράφημα OTDR με μία ή περισσότερες καμπύλες, σημάδια συμβάντων και launch cable."""

    def __init__(self, sors: list[SorFile], width: float, height: float, units: Units,
                 title: str = "", launch_label: str = "Launch cable"):
        super().__init__()
        self.sors = sors
        self.width = width
        self.height = height
        self.units = units
        self.title = title
        self.launch_label = launch_label

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        u = self.units
        left, bottom, right, top = 38, 22, 8, 14
        pw, ph = self.width - left - right, self.height - bottom - top

        sors = [s for s in self.sors if len(s.trace)]
        launch = max((s.launch_km for s in sors), default=0.0)
        max_len = max((s.length_km for s in sors), default=0)
        xmax = max_len * 1.08 if max_len > 0 else max(
            (len(s.trace) * s.resolution_km - s.launch_km for s in sors), default=1.0)
        xmax = max(xmax, 0.02)
        xmin = -launch * 1.04 if launch else 0.0
        series = []
        for s in sors:
            x, y = downsample(s, 900, xmax)
            keep = x >= xmin
            series.append((s, x[keep], y[keep]))
        ys = np.concatenate([y for _, _, y in series]) if series else np.array([0.0])
        if not len(ys):
            ys = np.array([0.0])
        ymin = max(0.0, float(np.percentile(ys, 1)) - 1.5)
        ymax = float(np.max(ys)) + 1.5
        if ymax - ymin < 5:
            ymin = max(0.0, ymax - 5)
        ymax += (ymax - ymin) * 0.22  # χώρος για ονόματα αρχείων / launch cable

        def tx(v): return left + (v - xmin) / (xmax - xmin) * pw
        def ty(v): return bottom + (v - ymin) / (ymax - ymin) * ph

        c.saveState()
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#7d8590"))
        c.setLineWidth(0.6)
        c.rect(left, bottom, pw, ph, fill=1, stroke=1)

        c.setFont("DejaVu", 6.5)
        c.setFillColor(colors.HexColor("#444c56"))
        for v in _nice_ticks(u.axis(xmin), u.axis(xmax), 8):
            X = tx(v / 1000 if u.m else v)
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
        c.drawRightString(left + pw, 4, u.name)
        c.saveState()
        c.translate(9, bottom + ph / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, "dB")
        c.restoreState()

        if launch:
            # Περιοχή launch cable και αρχή ίνας (S) στο 0
            c.setFillColor(colors.HexColor("#fff1f0"))
            c.rect(tx(xmin), bottom, tx(0) - tx(xmin), ph, fill=1, stroke=0)
            c.setStrokeColor(LAUNCH_C); c.setLineWidth(0.6); c.setDash(3, 2)
            c.line(tx(0), bottom, tx(0), bottom + ph)
            c.setDash()

        p = c.beginPath()
        p.rect(left, bottom, pw, ph)
        c.clipPath(p, stroke=0, fill=0)
        for s, x, y in series:
            c.setStrokeColor(WL_COLORS.get(s.wavelength, colors.black))
            c.setLineWidth(0.55)
            path = c.beginPath()
            for i, (xi, yi) in enumerate(zip(x, y)):
                if i:
                    path.lineTo(tx(xi), ty(yi))
                else:
                    path.moveTo(tx(xi), ty(yi))
            c.drawPath(path, stroke=1, fill=0)
        c.restoreState()

        c.saveState()
        if sors:
            ref = sors[0]
            c.setFont("DejaVu", 5.5)
            for i, e in enumerate(ref.events):
                if not xmin - 1e-9 <= e.rel_km <= xmax:
                    continue
                X = tx(e.rel_km)
                c.setStrokeColor(MUTED)
                c.setLineWidth(0.4)
                c.line(X, bottom + ph - 9, X, bottom + ph)
                c.setFillColor(colors.HexColor("#24292f"))
                c.drawCentredString(X, bottom + ph - 15, str(i))
        # Όπως στην οθόνη του οργάνου: όνομα αρχείου και launch cable πάνω δεξιά
        labels = [(s.path.name, "DejaVu", 6.5, WL_COLORS.get(s.wavelength, colors.black))
                  for s in sors if s.path]
        if sors and sors[0].launch_km:
            labels.append((f"{self.launch_label}: {sors[0].launch_km * 1000:.1f} m", "DejaVu-Bold", 7, LAUNCH_C))
        if labels:
            box_w = max(c.stringWidth(txt, f, fs) for txt, f, fs, _ in labels) + 6
            box_h = 8.5 * len(labels) + 3
            c.setFillColor(colors.white)
            c.setStrokeColor(GRID_C)
            c.setLineWidth(0.3)
            c.rect(left + pw - 2 - box_w, bottom + ph - 18 - box_h, box_w, box_h, fill=1, stroke=1)
            ly = bottom + ph - 18 - 8.5
            for txt, f, fs, col in labels:
                c.setFont(f, fs)
                c.setFillColor(col)
                c.drawRightString(left + pw - 5, ly, txt)
                ly -= 8.5

        # Υπόμνημα
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


class LinkMap(Flowable):
    """Σχηματική απεικόνιση της ζεύξης: launch → (S) → συμβάντα → (E)."""

    def __init__(self, sor: SorFile, width: float, units: Units, th, launch_label: str):
        super().__init__()
        self.sor = sor
        self.width = width
        self.height = 17 * mm
        self.units = units
        self.th = th
        self.launch_label = launch_label

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        s, u = self.sor, self.units
        nodes = [(i, e) for i, e in enumerate(s.events) if e.role not in ("launch",)]
        if not nodes:
            return
        y = self.height / 2
        x0 = 30 * mm if s.launch_km else 8 * mm
        x1 = self.width - 8 * mm
        step = (x1 - x0) / max(1, len(nodes) - 1)
        xs = [x0 + k * step for k in range(len(nodes))]
        c.saveState()
        if s.launch_km:
            c.setStrokeColor(LAUNCH_C); c.setLineWidth(1.2); c.setDash(3, 2)
            c.line(4 * mm, y, x0, y)
            c.setDash()
            c.setFont("DejaVu", 6.5); c.setFillColor(LAUNCH_C)
            c.drawCentredString((4 * mm + x0) / 2, y + 4, f"{self.launch_label}")
            c.drawCentredString((4 * mm + x0) / 2, y - 9, f"{s.launch_km * 1000:.1f} m")
        c.setStrokeColor(colors.HexColor("#1f6feb")); c.setLineWidth(1.6)
        c.line(x0, y, xs[-1], y)
        c.setFont("DejaVu", 6.5)
        for k, ((i, e), x) in enumerate(zip(nodes, xs)):
            ok = event_ok(e, self.th)
            fill = PASS_C if ok else FAIL_C if ok is False else colors.HexColor("#8c959f")
            c.setFillColor(fill); c.setStrokeColor(colors.white); c.setLineWidth(0.8)
            if e.reflective:
                c.rect(x - 4, y - 4, 8, 8, fill=1, stroke=1)
            else:
                c.circle(x, y, 4, fill=1, stroke=1)
            c.setFillColor(colors.black)
            tag = {"start": " (S)", "end": " (E)"}.get(e.role, "")
            c.drawCentredString(x, y + 8, f"{i}{tag}")
            c.setFillColor(MUTED)
            c.drawCentredString(x, y - 13, u.fmt(e.rel_km))
            if k:
                c.setFillColor(colors.HexColor("#0a3069"))
                c.drawCentredString((xs[k - 1] + x) / 2, y + 3, u.fmt(e.section_km))
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


def fiber_verdict(fiber: Fiber, required, th, sors: dict[int, SorFile] | None = None) -> bool | str | None:
    """True=PASS, False=FAIL, "missing"=λείπει υποχρεωτικό μήκος κύματος, None=χωρίς κριτήρια.

    `required`: τα υποχρεωτικά μήκη κύματος (Cable.required, δηλ. 1310 και 1550).

    Με `sors` κρίνονται οι μετρήσεις όπως διαβάστηκαν τώρα από τον δίσκο (για το PDF)·
    χωρίς αυτό, όπως φορτώθηκαν (για την οθόνη).
    """
    if sors is None:
        sors = {w: m.sor for w, m in fiber.measurements.items()}
    results = [evaluate(s, th) for s in sors.values()]
    if any(r is False for r in results):
        return False
    if not set(required) <= set(sors):
        return "missing"
    if results and all(r is None for r in results):
        return None
    return True


class _Cancelled(Exception):
    pass


class _CancellableDoc(SimpleDocTemplate):
    """Ελέγχει για ακύρωση και κατά το γράψιμο του PDF (όχι μόνο πριν)."""

    def __init__(self, *args, keep_going=None, **kw):
        super().__init__(*args, **kw)
        self._keep_going = keep_going
        self._count = 0

    def afterFlowable(self, flowable):
        self._count += 1
        if self._keep_going and self._count % 20 == 0 and not self._keep_going():
            raise _Cancelled()


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
            "small": ParagraphStyle("s", fontName="DejaVu", fontSize=6.5, leading=8, textColor=MUTED),
            "right": ParagraphStyle("r", fontName="DejaVu", fontSize=7.5, leading=9.5, alignment=TA_RIGHT),
        }

    # ---------- κοινά στοιχεία ----------
    def _verdict_para(self, v):
        t = self.t
        if v is None:
            return None
        text, col = {True: (t["pass"], PASS_C), False: (t["fail"], FAIL_C)}.get(
            v, (t["incomplete_v"], WARN_C))
        return Paragraph(f'<font color="{col.hexval()}"><b>{text}</b></font>',
                         ParagraphStyle("v", fontName="DejaVu-Bold", fontSize=20, leading=23,
                                        alignment=TA_RIGHT))

    def _header(self, title: str, subtitle: str, verdict=None):
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
        left = [Paragraph(_esc(title), self.st["h1"]), Paragraph(subtitle, self.st["n"])]
        meta = []
        if self.s.customer:
            meta.append(f"{t['customer']}: <b>{_esc(self.s.customer)}</b>")
        if self.s.project:
            meta.append(f"{t['project']}: <b>{_esc(self.s.project)}</b>")
        if meta:
            left.append(Paragraph(" &nbsp; · &nbsp; ".join(meta), self.st["n"]))
        right = []
        vp = self._verdict_para(verdict)
        if vp:
            right.append(vp)
        if logo:
            right.append(logo)
        if right_lines:
            right.append(Paragraph("<br/>".join(right_lines), self.st["right"]))
        tbl = Table([[left, right or ""]], colWidths=[None, 62 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, HEAD_BG),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return tbl

    def _table(self, rows, col_widths, result_col=None, font_size=7, muted_rows=()):
        head_style = ParagraphStyle("th", fontName="DejaVu-Bold", fontSize=font_size,
                                    leading=font_size + 1.5, textColor=colors.white, alignment=1)
        rows = [[Paragraph(_esc(str(h)), head_style) for h in rows[0]]] + rows[1:]
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, -1), "DejaVu", font_size),
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]
        for i in range(1, len(rows)):
            if i in muted_rows:
                style.append(("TEXTCOLOR", (0, i), (-1, i), MUTED))
                style.append(("FONT", (0, i), (-1, i), "DejaVu", font_size - 0.5))
            elif i % 2 == 0 and not muted_rows:
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
                        style.append(("TEXTCOLOR", (col, i), (col, i), WARN_C))
        tbl.setStyle(TableStyle(style))
        return tbl

    def _verdict(self, ok):
        if ok == "missing":
            return self.t["missing"]
        if ok is None:
            return "–"
        return self.t["pass"] if ok else self.t["fail"]

    # ---------- σελίδα σύνοψης ----------
    def summary_story(self, cable: Cable, fibers: list[Fiber], read: dict):
        t = self.t
        th = self.s.thresholds
        wls = cable.wavelengths
        units = Units(max((s.length_km for f in fibers for s in read[f.key].values()), default=0))
        story = [self._header(t["title"], f"{t['summary']}: <b>{_esc(cable.name)}</b>"), Spacer(1, 4 * mm)]
        info = f"{t['cable']}: <b>{_esc(cable.name)}</b> &nbsp; · &nbsp; {t['fibers']}: <b>{len(fibers)}</b>"
        info += " &nbsp; · &nbsp; λ: <b>" + ", ".join(f"{w} nm" for w in wls) + "</b>"
        story.append(Paragraph(info, self.st["n"]))
        story.append(Spacer(1, 3 * mm))

        head = [t["fiber"]]
        for w in wls:
            head += [f"{w} – {t['length']} ({units.name})", f"{w} – {t['loss']}", f"{w} – {t['att']}",
                     f"{w} – {t['result']}"]
        head.append(t["result"])
        rows = [head]
        result_cols = [4 * i + 4 for i in range(len(wls))] + [len(head) - 1]
        name_style = ParagraphStyle("nm", fontName="DejaVu", fontSize=6.5, leading=7.5)   # αναδίπλωση
        n_pass = n_fail = 0
        for f in fibers:
            row = [Paragraph(_esc(f.display), name_style)]
            sors = read[f.key]
            for w in wls:
                sor = sors.get(w)
                if sor is None:
                    row += ["–", "–", "–", t["missing"]]
                    continue
                row += [units.fmt(sor.length_km), _fmt(sor.total_loss, 2),
                        _fmt(sor.attenuation, 3), self._verdict(evaluate(sor, th))]
            v = fiber_verdict(f, cable.required, th, sors)
            row.append(self._verdict(v))
            n_pass += v is True
            n_fail += v is False
            rows.append(row)
        avail = A4[0] - 24 * mm
        first = min(45 * mm, max(16 * mm, max(len(f.display) for f in fibers) * 1.35 * mm + 4 * mm))
        rest = (avail - first - 21 * mm) / max(1, 4 * len(wls))
        widths = [first] + [rest] * (4 * len(wls)) + [21 * mm]
        story.append(self._table(rows, widths, result_col=result_cols, font_size=6.5))
        story.append(Spacer(1, 3 * mm))
        crit = criteria_text(th, self.s.language)
        if crit:
            story.append(Paragraph(
                f"{t['pass']}: <b>{n_pass}</b> &nbsp; · &nbsp; {t['fail']}: <b>{n_fail}</b>", self.st["n"]))
            story.append(Paragraph(f"{t['criteria']}: {_esc(crit)}", self.st["small"]))
        miss = [f.display for f in fibers if not cable.required <= set(read[f.key])]
        if miss:
            story.append(Paragraph(f"{t['incomplete']}: " + ", ".join(miss), self.st["small"]))
        story.append(PageBreak())
        return story

    # ---------- σελίδα ίνας ----------
    def fiber_story(self, cable: Cable, fiber: Fiber, sors: dict[int, SorFile]):
        t = self.t
        th = self.s.thresholds
        wls = cable.wavelengths
        present = [sors[w] for w in wls if w in sors]
        units = Units(max((s.length_km for s in present), default=0))
        subtitle = f"{t['cable']}: {_esc(cable.name)} &nbsp; · &nbsp; {t['fiber']}: <b>{_esc(fiber.display)}</b>"
        story = [self._header(t["title"], subtitle, fiber_verdict(fiber, cable.required, th, sors)), Spacer(1, 3 * mm)]

        head = [t["wl"], t["file"], t["date"], t["pulse"], t["ior"], f"{t['launch']} (m)",
                f"{t['length']} ({units.name})", t["loss"], t["att"], t["result"]]
        rows = [head]
        for w in wls:
            s = sors.get(w)
            if s is None:
                rows.append([str(w), t["missing"], "", "", "", "", "", "", "", ""])
                continue
            rows.append([
                str(w), _short(s.path.name if s.path else "", 34),
                s.date.strftime("%d/%m/%Y %H:%M") if s.date else "–",
                str(s.pulse_width_ns), f"{s.ior:.4f}",
                f"{s.launch_km * 1000:.1f}" if s.launch_km else "–",
                units.fmt(s.length_km), _fmt(s.total_loss, 3), _fmt(s.attenuation, 3),
                self._verdict(evaluate(s, th)),
            ])
        widths = [11 * mm, 45 * mm, 23 * mm, 13 * mm, 13 * mm, 14 * mm, 16 * mm, 16 * mm, 12 * mm, 23 * mm]
        story.append(self._table(rows, widths, result_col=9))
        for s in present:
            if th.enabled and is_dead_fiber(s):
                story.append(Paragraph(f'<font color="{FAIL_C.hexval()}"><b>{_esc(t["dead"].format(wl=s.wavelength))}</b></font>',
                                       self.st["n"]))
        story.append(Spacer(1, 2 * mm))

        chart_w = A4[0] - 24 * mm
        if present:
            story.append(LinkMap(present[0], chart_w, units, th, t["launch_cable"]))
        if self.s.chart_mode == "separate" and len(present) > 1:
            h = 52 * mm if len(present) == 2 else 40 * mm
            for s in present:
                story.append(TraceChart([s], chart_w, h, units, f"{s.wavelength} nm", t["launch_cable"]))
                story.append(Spacer(1, 1.5 * mm))
        elif present:
            story.append(TraceChart(present, chart_w, 72 * mm, units, "", t["launch_cable"]))
            story.append(Spacer(1, 1.5 * mm))

        for s in present:
            story.append(KeepTogether([
                Paragraph(f"{t['events']} – {s.wavelength} nm", self.st["h2"]),
                self._events_table(s, units),
            ]))
        foot = []
        if s_inst := next((x for x in present if x.supplier or x.otdr_model), None):
            foot.append(f"{t['otdr']}: {_esc(' '.join(filter(None, [s_inst.supplier, s_inst.otdr_model, s_inst.otdr_sn])))}")
        if self.s.operator:
            foot.append(f"{t['operator']}: {_esc(self.s.operator)}")
        crit = criteria_text(th, self.s.language)
        if crit:
            foot.append(f"{t['criteria']}: {_esc(crit)}")
        if foot:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(" &nbsp; · &nbsp; ".join(foot), self.st["small"]))
        story.append(PageBreak())
        return story

    def _events_table(self, s: SorFile, units: Units):
        """Συμβάντα με τις γραμμές τμημάτων ανάμεσα, όπως στην αναφορά του οργάνου."""
        t = self.t
        rows = [event_headers(t, units)]
        muted = set()
        for cells, _ok, is_seg in event_rows(s, self.s.thresholds, t, units):
            rows.append(cells)
            if is_seg:
                muted.add(len(rows) - 1)
        w = A4[0] - 24 * mm
        widths = [8 * mm, 32 * mm] + [(w - 40 * mm - 20 * mm) / 5] * 5 + [20 * mm]
        return self._table(rows, widths, result_col=7, muted_rows=muted)

    # ---------- κατασκευή αρχείου ----------
    def build(self, out_path: Path, parts: list[tuple[Cable, list[Fiber], dict]],
              progress: Callable[[str], bool] | None = None,
              keep_going: Callable[[], bool] | None = None) -> bool:
        """parts: (καλώδιο, μετρήσεις, read) όπου read[fiber.key] = {λ: SorFile διαβασμένο τώρα}."""
        story = []
        for cable, fibers, read in parts:
            if self.s.summary_page:
                story += self.summary_story(cable, fibers, read)
            for fiber in fibers:
                story += self.fiber_story(cable, fiber, read[fiber.key])
                if progress and progress(f"{cable.name} / {fiber.display}") is False:
                    return False
        if story and isinstance(story[-1], PageBreak):
            story.pop()

        t = self.t
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        signatures = self.s.signatures

        def on_page(c, doc):
            c.saveState()
            c.setFont("DejaVu", 6.5)
            c.setFillColor(MUTED)
            c.drawString(12 * mm, 8 * mm, f"{t['generated']}: {stamp}")
            c.drawRightString(A4[0] - 12 * mm, 8 * mm, f"{t['page']} {doc.page}")
            if signatures:
                c.setFont("DejaVu", 7.5)
                c.setFillColor(colors.black)
                y = 15 * mm
                for k, key in enumerate(("prepared", "verified", "approved")):
                    c.drawString(12 * mm + k * 64 * mm, y, f"{t[key]}: ____________________")
            c.restoreState()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".part.pdf")
        doc = _CancellableDoc(str(tmp), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                              topMargin=10 * mm, bottomMargin=(21 if signatures else 14) * mm,
                              title=f"{t['title']} – " + ", ".join(p[0].name for p in parts),
                              author=self.s.company or "", keep_going=keep_going)
        try:
            doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        except _Cancelled:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(out_path)
        return True


def event_headers(t: dict, units: Units) -> list[str]:
    return [t["no"], t["type"], f"{t['dist']} ({units.name})", t["eloss"], t["cum"], t["slope"],
            t["refl"], t["result"]]


def event_rows(s: SorFile, th, t: dict, units: Units):
    """Γραμμές πίνακα συμβάντων: (κελιά, αποτέλεσμα, είναι_τμήμα). Κοινές για PDF και οθόνη."""
    out = []
    verdict = {True: t["pass"], False: t["fail"], None: ""}
    for i, e in enumerate(s.events):
        if i:
            out.append((["", t["types"]["seg"], units.fmt(e.section_km), _fmt(e.segment_loss, 3),
                         _fmt(e.segment_cum, 3), _fmt(e.slope, 3) if e.slope else "–", "–", ""], None, True))
        ok = event_ok(e, th)
        name = t["types"].get(e.type_name, e.type_name)
        if e.role == "start":
            name = f"{t['types']['Ανακλαστικό'] if e.reflective else t['types']['Μη ανακλ.']} (S)"
        elif e.role == "end":
            name += " (E)"
        show_loss = e.role not in ("origin", "launch", "end")
        out.append(([
            str(i), name, units.fmt(e.rel_km),
            _fmt(e.splice_loss, 3) if show_loss else "–",
            _fmt(e.cumulative_loss, 3),
            "–",
            _fmt(e.reflectance, 3) if e.reflectance else "–",
            verdict[ok],
        ], ok, False))
    return out


def criteria_text(th, lang: str = "el") -> str:
    """Σύντομη περιγραφή των ενεργών κριτηρίων, π.χ. "κόλληση ≤ 0.30 dB, connector ≤ 0.75 dB"."""
    if not th.enabled:
        return ""
    el = lang == "el"
    out = []
    if th.check_splice:
        out.append(f"{'κόλληση' if el else 'splice'} ≤ {th.max_splice_loss:.2f} dB")
    if th.check_connector:
        out.append(f"connector ≤ {th.max_connector_loss:.2f} dB")
    if th.check_reflectance:
        out.append(f"{'ανάκλαση' if el else 'reflectance'} ≤ {th.max_reflectance:.1f} dB")
    if th.check_attenuation:
        att = ", ".join(f"{k}: {v:.3f}" for k, v in sorted(th.max_attenuation.items()))
        out.append(f"{'εξασθένηση' if el else 'attenuation'} ≤ {att} dB/km")
    if th.check_total_loss:
        out.append(f"{'συνολική απώλεια' if el else 'total loss'} ≤ {th.max_total_loss:.2f} dB")
    return ", ".join(out)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-(n - 1):]


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "report"


class ReportResult(list):
    """Τα PDF που γράφτηκαν (λίστα διαδρομών), μαζί με όσα δεν μπήκαν και γιατί."""

    def __init__(self):
        super().__init__()
        self.excluded: list[tuple[str, str, list[int]]] = []   # (καλώδιο, μέτρηση, λ που λείπουν)
        self.unreadable: list[tuple[Path, str]] = []            # αρχεία που δεν διαβάστηκαν τώρα
        self.cancelled = False


def generate_reports(parts: list[tuple[Cable, list[Fiber]]], out_dir: Path, settings: ReportSettings,
                     progress: Callable[[int, int, str], bool] | None = None) -> ReportResult:
    """Δημιουργεί τα PDF.

    Κάθε αρχείο ξαναδιαβάζεται τώρα από τον δίσκο και αυτό που διαβάστηκε χρησιμοποιείται
    παντού (σύνοψη, σελίδα, PASS/FAIL). Μέτρηση χωρίς όλα τα μήκη κύματος (π.χ. 1310 και 1550),
    είτε γιατί λείπει είτε γιατί δεν διαβάζεται πια, δεν μπαίνει στο PDF εκτός αν
    `settings.allow_incomplete` (επιλογή του χρήστη, με δική του ευθύνη).
    """
    out_dir = Path(out_dir)
    builder = ReportBuilder(settings)
    result = ReportResult()
    total = 2 * sum(len(f) for _, f in parts)
    step = 0

    def tick(label: str) -> bool:
        nonlocal step
        step += 1
        return progress(step, total, label) if progress else True

    def keep_going() -> bool:      # έλεγχος ακύρωσης χωρίς να προχωρά η μπάρα
        return progress(step, total, "Γράφεται το PDF…") is not False if progress else True

    def read_cable(cable: Cable, fibers: list[Fiber]):
        keep, read = [], {}
        for f in fibers:
            sors = {}
            for w, m in f.measurements.items():
                try:
                    sors[w] = prepare(parse_sor(m.path), settings)
                except (SorError, OSError, ValueError) as e:
                    result.unreadable.append((m.path, str(e)))
            missing = sorted(set(cable.required) - set(sors))
            if missing and not settings.allow_incomplete:
                result.excluded.append((cable.name, f.display, missing))
                tick("")                                  # δεν θα χτιστεί σελίδα
            else:
                keep.append(f)
                read[f.key] = sors
            if not tick(f"Ανάγνωση: {cable.name} / {f.display}"):
                return None
        return cable, keep, read

    groups = [[p] for p in parts] if settings.one_pdf_per_cable else [parts]
    used: set[str] = set()      # τα Windows δεν ξεχωρίζουν κεφαλαία/πεζά: C1 και c1 = ίδιο αρχείο
    for group in groups:
        prepared = []
        for cable, fibers in group:
            r = read_cable(cable, fibers)
            if r is None:
                result.cancelled = True
                return result
            if r[1]:
                prepared.append(r)
        if not prepared:
            continue
        if settings.one_pdf_per_cable:
            cable, fibers, _ = prepared[0]
            stem = f"{safe_filename(cable.name)}{_range_suffix(fibers)}"
        else:
            stem = f"OTDR_report_{datetime.now():%Y%m%d_%H%M}"
        name, k = stem, 2
        while name.casefold() in used:
            name, k = f"{stem} ({k})", k + 1
        used.add(name.casefold())
        out = out_dir / f"{name}.pdf"
        if not builder.build(out, prepared, tick, keep_going):
            result.cancelled = True
            return result
        result.append(out)
    return result


def _range_suffix(fibers: list[Fiber]) -> str:
    nums = [f.number for f in fibers]
    if not nums:
        return ""
    width = max(len(f.label) for f in fibers) or 1
    return f"_{min(nums):0{width}d}-{max(nums):0{width}d}"
