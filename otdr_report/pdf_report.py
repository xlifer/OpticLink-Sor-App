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
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Flowable, Image, KeepInFrame, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from .linkmap import (asset_dir, fit_labels, icon_path, line_band, linkmap_events, node_kind, node_positions,
                      node_state, scale_positions)
from .matching import WAVELENGTH_TOLERANCE_NM, Cable, Fiber
from .settings import ReportSettings, evaluate, event_ok, is_dead_fiber, prepare
from .sor import SorError, SorFile, downsample, is_live_wavelength, parse_sor

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
        "thr": "Όρια", "thr_cols": ["Απώλεια κόλλησης", "Απώλεια connector", "Ανάκλαση", "Κλίση dB/km",
                                    "Απώλεια ζεύξης"],
        "thr_split": "Όρια splitter", "thr_type": "Τύπος", "thr_max_loss": "{wl} Μέγ. απώλεια dB",
        "thr_max_refl": "{wl} Μέγ. ανάκλαση dB",
        "slope": "Κλίση (dB/km)", "criteria": "Κριτήρια PASS", "launch_cable": "Launch cable", "link_map": "Link map",
        "prepared": "Συντάχθηκε από", "verified": "Ελέγχθηκε από", "approved": "Εγκρίθηκε από",
        "machine": "Στοιχεία οργάνου", "module": "Μοντέλο", "serial": "Αρ. σειράς",
        "config": "Ρυθμίσεις μέτρησης", "test_wave": "Μήκος κύματος (nm)", "pw": "Παλμός (ns)",
        "distance": "Απόσταση (km)", "test_time": "Χρόνος μέτρησης (s)", "resolution": "Ανάλυση (m)",
        "scatter": "Σκέδαση (dB)", "start_loc": "Αρχή", "end_loc": "Τέλος", "location": "Τοποθεσία",
        "continued": "συνέχεια",
        "cable_id": "Cable ID", "fiber_id": "Fiber ID", "measurement": "Μέτρηση",
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
        "thr": "Threshold", "thr_cols": ["Splice loss", "Connector loss", "Reflection", "Slope dB/km", "Span loss"],
        "thr_split": "Splitter Threshold", "thr_type": "Type", "thr_max_loss": "{wl}Max Loss dB",
        "thr_max_refl": "{wl}Max Reflection dB",
        "slope": "Slope (dB/km)", "criteria": "PASS criteria", "launch_cable": "Launch cable", "link_map": "Link map",
        "prepared": "Prepared by", "verified": "Verified by", "approved": "Approved by",
        "machine": "Machine Information", "module": "Module", "serial": "Serial No.",
        "config": "Configuration of Test", "test_wave": "Test Wave (nm)", "pw": "PW (ns)",
        "distance": "Distance (km)", "test_time": "Test Time (s)", "resolution": "Resolution (m)",
        "scatter": "Backscatter (dB)", "start_loc": "Start Location", "end_loc": "End Location",
        "continued": "continued",
        "location": "Location", "cable_id": "Cable ID", "fiber_id": "Fiber ID", "measurement": "Measurement",
    },
}

PASS_C = colors.HexColor("#1a7f37")
FAIL_C = colors.HexColor("#cf222e")
WARN_C = colors.HexColor("#9a6700")
GOLD = colors.HexColor("#e9af36")          # χρώματα Grandway
STEEL = colors.HexColor("#767b80")
HEAD_BG = GOLD                               # επικεφαλίδες πινάκων (σκούρο κείμενο για αντίθεση)
HEAD_FG = colors.HexColor("#1f2328")
LABEL_BG = colors.HexColor("#f1f2f3")
GRID_C = colors.HexColor("#c9ccd0")
ZEBRA = colors.HexColor("#fbf5e6")
MUTED = colors.HexColor("#57606a")
LAUNCH_C = colors.HexColor("#cf222e")


TOP_MARGIN = 10 * mm
CONT_LOGO_H = 8 * mm        # logo στις σελίδες συνέχειας
ONE_PAGE_EVENTS = 8         # έως τόσα συμβάντα ανά λ (χωρίς launch / «Seg.»): ΠΑΝΤΑ μία σελίδα
CHART_MIN = (35 * mm, 30 * mm, 28 * mm)   # ύψος γραφήματος ανά επίπεδο διάταξης (0 = κανονική)
CHART_MAX = (55 * mm, 45 * mm, 45 * mm)


NARROW_HEADS = {
    "en": ["#", "Type", "Dist. ({u})", "Loss (dB)", "T.Loss (dB)", "Slope (dB/km)", "Refl. (dB)", "Result"],
    "el": ["#", "Τύπος", "Απόστ. ({u})", "Απώλ. (dB)", "Αθρ. (dB)", "Κλίση (dB/km)", "Ανάκλ. (dB)", "Αποτ."],
}


def event_count(sor) -> int:
    """Συμβάντα της μέτρησης όπως μετράνε για τη «μία σελίδα»: χωρίς το launch cable."""
    return sum(1 for e in sor.events if e.role != "launch")


def _height(flowables, width) -> float:
    return sum(f.wrap(width, 10_000)[1] + f.getSpaceBefore() + f.getSpaceAfter() for f in flowables)
BOTTOM = 14 * mm
BOTTOM_SIG = 21 * mm
LOGO_H = 12 * mm            # Grandway logo πάνω αριστερά, δίπλα στον τίτλο


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
        ymax += (ymax - ymin) * 0.10  # χώρος για τους αριθμούς των συμβάντων

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
            marks = [(i, tx(e.rel_km)) for i, e in enumerate(ref.events) if xmin - 1e-9 <= e.rel_km <= xmax]
            mw = [c.stringWidth(str(i), "DejaVu", 5.5) for i, _ in marks]
            show = fit_labels([X - w / 2 for (_, X), w in zip(marks, mw)], mw, 1.5)
            for (i, X), vis in zip(marks, show):
                c.setStrokeColor(MUTED)
                c.setLineWidth(0.4)
                c.line(X, bottom + ph - 9, X, bottom + ph)
                if vis:                 # αριθμοί που δεν χωράνε παραλείπονται (υπάρχουν στον πίνακα)
                    c.setFillColor(colors.HexColor("#24292f"))
                    c.drawCentredString(X, bottom + ph - 15, str(i))
        # Μέσα στο γράφημα δεν γράφονται ονόματα αρχείων ούτε το launch cable

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
    """Σχηματική ζεύξη όπως στο όργανο: από το (S) στο 0 έως το (E), χωρίς το launch cable.

    Πάνω μπάρα κλίμακας με τα συμβάντα στην πραγματική τους θέση (κόκκινο = FAIL) και το
    συνολικό μήκος· από κάτω τα εικονίδια με αριθμό και απόσταση, και τα μήκη των τμημάτων.
    """

    def __init__(self, sor: SorFile, width: float, units: Units, th, height: float = 30 * mm):
        super().__init__()
        self.sor = sor
        self.width = width
        self.height = height
        self.units = units
        self.th = th

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        s, u = self.sor, self.units
        nodes = linkmap_events(s)
        if not nodes:
            return
        kms = [e.rel_km for _, e in nodes]
        # με πολλά συμβάντα τα εικονίδια μικραίνουν ώστε να μην πέφτουν το ένα πάνω στο άλλο
        span = self.width - 8 * mm
        size = min(9 * mm, max(3 * mm, span / max(1, len(nodes)) * 0.8), self.height - 14 * mm)
        states = [node_state(e, s, self.th) for _, e in nodes]
        c.saveState()
        # μπάρα κλίμακας
        total = f"{u.fmt(kms[-1])}{u.name}"
        c.setFont("DejaVu", 6.5)
        bx0, bx1 = 4 * mm, self.width - 4 * mm - c.stringWidth(total, "DejaVu", 6.5) - 2
        by = self.height - 5 * mm
        c.setStrokeColor(STEEL); c.setLineWidth(1.4)
        c.line(bx0, by, bx1, by)
        c.setStrokeColor(colors.HexColor("#3b4a8c")); c.setLineWidth(0.5)
        c.line(bx0, by, bx1, by)
        sx = scale_positions(kms, bx0, bx1)
        tw = [c.stringWidth(str(i), "DejaVu", 6.5) for i, _ in nodes]
        show = fit_labels([x - w / 2 for x, w in zip(sx, tw)], tw, 1.5)
        for (i, _e), x, st, vis in zip(nodes, sx, states, show):
            col = FAIL_C if st == "fail" else colors.HexColor("#24292f")
            c.setStrokeColor(col); c.setLineWidth(0.7)
            c.line(x, by - 2, x, by + 2)
            if vis or st == "fail":
                c.setFillColor(col)
                c.drawCentredString(x, by + 3, str(i))
        c.setFillColor(colors.black)
        c.drawString(bx1 + 2, by - 2, total)
        # εικονίδια: από κάτω τα μήκη τμημάτων, από πάνω αριθμός/απόσταση και μετά η μπάρα κλίμακας
        y = 3.2 * mm + size / 2
        xs = node_positions(kms, 4 * mm + size / 2, self.width - 4 * mm - size / 2, size + min(6 * mm, size * 0.7))
        c.setFont("DejaVu", 6.5)
        idx_w = [c.stringWidth(str(i), "DejaVu", 6.5) for i, _ in nodes]
        dist_w = [c.stringWidth(u.fmt(e.rel_km), "DejaVu", 6.5) for _, e in nodes]
        show_idx = fit_labels([x - size / 2 for x in xs], idx_w)
        show_dist = fit_labels([x - size / 2 for x in xs], dist_w)
        mids = [(xs[k - 1] + xs[k]) / 2 for k in range(1, len(xs))]
        sec_w = [c.stringWidth(u.fmt(e.section_km), "DejaVu", 6.5) for _, e in nodes[1:]]
        show_sec = fit_labels([m - w / 2 for m, w in zip(mids, sec_w)], sec_w) if mids else []
        line = icon_path("line")
        if line and len(xs) > 1:
            off, lh = line_band(size)              # ίδια ευθεία και πάχος με το καλώδιο των εικονιδίων
            c.drawImage(str(line), xs[0], y + size / 2 - off - lh, xs[-1] - xs[0], lh, mask="auto")
        else:
            c.setStrokeColor(STEEL); c.setLineWidth(1.6)
            c.line(xs[0], y, xs[-1], y)
        for k, ((i, e), x, state) in enumerate(zip(nodes, xs, states)):
            kind = node_kind(e)
            icon = icon_path(f"{kind}_{state}")
            if icon:
                c.drawImage(str(icon), x - size / 2, y - size / 2, size, size, mask="auto")
            else:
                ok = {"pass": PASS_C, "fail": FAIL_C}.get(state, colors.HexColor("#8c959f"))
                c.setFillColor(ok); c.setStrokeColor(colors.white); c.setLineWidth(0.8)
                if kind == "connector":
                    c.rect(x - 4, y - 4, 8, 8, fill=1, stroke=1)
                else:
                    c.circle(x, y, 4, fill=1, stroke=1)
            if kind == "splitter" and e.splitter_ratio:              # λόγος διαίρεσης πάνω δεξιά
                c.setFont("DejaVu-Bold", 5.5); c.setFillColor(colors.black)
                c.drawRightString(x + size / 2 - 0.6, y + size / 2 - 5.5, f"1:{e.splitter_ratio}")
            if kind in ("start", "end") and size >= 6 * mm:
                c.setFont("DejaVu-Bold", 6.5); c.setFillColor(FAIL_C)
                c.drawString(x - size / 2 + 1.2, y - size / 2 + 1.2, "S" if kind == "start" else "E")
            c.setFont("DejaVu", 6.5); c.setFillColor(colors.black)
            if show_idx[k]:
                c.drawString(x - size / 2, y + size / 2 + 9.5, str(i))
            if show_dist[k]:
                c.drawString(x - size / 2, y + size / 2 + 2.5, u.fmt(e.rel_km))
            if k and show_sec[k - 1]:
                c.setFillColor(colors.black)
                c.drawCentredString((xs[k - 1] + x) / 2, y - size / 2 - 7, u.fmt(e.section_km))
        c.restoreState()


class TitledBox(Flowable):
    """Τίτλος ενότητας (αριστερά, γκρι, όπως οι άλλοι τίτλοι) και από κάτω ο πίνακας, πάντα μαζί."""

    def __init__(self, title, content):
        super().__init__()
        self.title, self.content = title, content
        self.hAlign = "CENTER"

    def wrap(self, aw, ah):
        self._tw, self._th = self.title.wrap(aw, ah)
        self._cw, self._ch = self.content.wrap(aw, ah)
        self.width = max(self._tw, self._cw)
        gap = self.title.getSpaceAfter() + self.title.getSpaceBefore()
        self._gap = gap
        self.height = self._th + gap + self._ch
        return self.width, self.height

    def draw(self):
        self.title.drawOn(self.canv, 0, self._ch + self.title.getSpaceAfter())
        self.content.drawOn(self.canv, 0, 0)


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

    `required`: τα υποχρεωτικά μήκη κύματος (Cable.required_for: 1310 και 1550, ή μόνο το live λ).

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


class _Running(Flowable):
    """Μηδενικού μεγέθους σημάδι: ορίζει την ταυτότητα (καλώδιο / μέτρηση) για τις σελίδες συνέχειας."""

    def __init__(self, holder: dict, text: str):
        super().__init__()
        self.holder, self.text = holder, text

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self.holder["text"] = self.text


class _CancellableDoc(BaseDocTemplate):
    """Ελέγχει για ακύρωση και κατά το γράψιμο του PDF (όχι μόνο πριν).

    Δύο πρότυπα σελίδας: "main" για την πρώτη σελίδα κάθε μέτρησης και "cont" για τις σελίδες
    συνέχειας, με δεσμευμένο χώρο πάνω για την ταυτότητα της μέτρησης.
    """

    def __init__(self, *args, keep_going=None, on_page=None, on_cont=None, cont_header=14 * mm, **kw):
        super().__init__(*args, **kw)
        self._keep_going = keep_going
        self._count = 0
        w = self.width
        main = Frame(self.leftMargin, self.bottomMargin, w, self.height, id="main")
        cont = Frame(self.leftMargin, self.bottomMargin, w, self.height - cont_header, id="cont")
        self.addPageTemplates([PageTemplate("main", [main], onPage=on_page),
                               PageTemplate("cont", [cont], onPage=on_cont)])

    def afterFlowable(self, flowable):
        self._count += 1
        if self._keep_going and self._count % 20 == 0 and not self._keep_going():
            raise _Cancelled()


class ReportBuilder:
    def __init__(self, settings: ReportSettings):
        _register_fonts()
        self.s = settings
        self.t = TEXT.get(settings.language, TEXT["en"])
        self._running = {"text": ""}     # ταυτότητα τρέχουσας μέτρησης για τις σελίδες συνέχειας
        self._running_all: list[str] = []      # όλες, για να δεσμευτεί αρκετό ύψος (μεγάλα ονόματα)
        # ύψος περιοχής κειμένου: μία σελίδα ανά μέτρηση
        self._frame_h = A4[1] - TOP_MARGIN - (BOTTOM_SIG if settings.signatures else BOTTOM) - 12 - 1   # 12 = padding πλαισίου (6+6 pt)
        self.st = {
            "h1": ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=13, leading=16, spaceAfter=2),
            "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=9.5, leading=12,
                                 spaceBefore=4, spaceAfter=2, textColor=STEEL),
            "h2c": ParagraphStyle("h2c", fontName="DejaVu-Bold", fontSize=8.5, leading=10,
                                  spaceBefore=2, spaceAfter=1.5, textColor=STEEL),
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
        gw = _grandway_logo()
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
        if gw:                      # Grandway logo πάνω αριστερά σε κάθε σελίδα, ο τίτλος δεξιά του
            inner = Table([[gw, left]], colWidths=[gw.drawWidth + 4 * mm, None])
            inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            left = inner
        tbl = Table([[left, right or ""]], colWidths=[None, 62 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, HEAD_BG),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return tbl

    def _table(self, rows, col_widths, result_col=None, font_size=7, muted_rows=(), title=None, pad=1.6):
        head_style = ParagraphStyle("th", fontName="DejaVu-Bold", fontSize=font_size,
                                    leading=font_size + 1.5, textColor=HEAD_FG, alignment=1)
        rows = [[Paragraph(_esc(str(h)), head_style) for h in rows[0]]] + rows[1:]
        off = 0
        if title:                       # γραμμή τίτλου πάνω από τις επικεφαλίδες, επαναλαμβανόμενη
            off = 1
            tstyle = ParagraphStyle("tt", fontName="DejaVu-Bold", fontSize=min(9, font_size + 2),
                                    leading=min(11, font_size + 3.5), textColor=STEEL)
            rows = [[Paragraph(_esc(title), tstyle)] + [""] * (len(rows[0]) - 1)] + rows
            muted_rows = {i + 1 for i in muted_rows}
        tbl = Table(rows, colWidths=col_widths, repeatRows=1 + off)
        style = [
            ("FONT", (0, 0), (-1, -1), "DejaVu", font_size),
            ("BACKGROUND", (0, off), (-1, off), HEAD_BG),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]
        for i in range(1 + off, len(rows)):
            if i in muted_rows:
                style.append(("TEXTCOLOR", (0, i), (-1, i), MUTED))
                style.append(("FONT", (0, i), (-1, i), "DejaVu", font_size - 0.5))
            elif (i - off) % 2 == 0 and not muted_rows:
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
        if off:                         # ο τίτλος χωρίς πλαίσιο, όπως οι επικεφαλίδες ενοτήτων
            style = [x for x in style if x[0] != "GRID"]
            style += [("GRID", (0, 1), (-1, -1), 0.3, GRID_C), ("SPAN", (0, 0), (-1, 0)),
                      ("ALIGN", (0, 0), (-1, 0), "LEFT"), ("LEFTPADDING", (0, 0), (-1, 0), 0),
                      ("TOPPADDING", (0, 0), (-1, 0), 3)]
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
        running = f"{t['summary']}: <b>{_esc(cable.name)}</b>"
        self._running_all.append(running)
        story = [_Running(self._running, running), NextPageTemplate("cont"),
                 self._header(t["title"], f"{t['summary']}: <b>{_esc(cable.name)}</b>"), Spacer(1, 4 * mm)]
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
                    row += ["–", "–", "–", t["missing"] if w in cable.required_for(f) else "–"]
                    continue
                row += [units.fmt(sor.length_km), _fmt(sor.total_loss, 2),
                        _fmt(sor.attenuation, 3), self._verdict(evaluate(sor, th))]
            v = fiber_verdict(f, cable.required_for(f), th, sors)
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
        if th.enabled:
            story.append(Paragraph(
                f"{t['pass']}: <b>{n_pass}</b> &nbsp; · &nbsp; {t['fail']}: <b>{n_fail}</b>", self.st["n"]))
            story.append(Spacer(1, 2 * mm))
            story += self.threshold_boxes(wls, [e.splitter_ratio for f in fibers for x in read[f.key].values()
                                                for e in x.events if e.splitter_ratio])
        miss = [f.display for f in fibers if not cable.required_for(f) <= set(read[f.key])]
        if miss:
            story.append(Paragraph(f"{t['incomplete']}: " + ", ".join(miss), self.st["small"]))
        story += [NextPageTemplate("main"), PageBreak()]
        return story

    # ---------- σελίδα ίνας ----------
    def _section(self, title: str):
        return Paragraph(_esc(title), self.st["h2"])

    def _kv_block(self, title: str, pairs: list[tuple[str, str]], width: float, fs: float = 7.5):
        """Μικρός πίνακας «ετικέτα – τιμή» με τίτλο, π.χ. οι ρυθμίσεις του 1310 (οι τιμές αναδιπλώνονται)."""
        head = ParagraphStyle("kvh", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5, textColor=HEAD_FG)
        val = ParagraphStyle("kvv", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5)
        rows = [[Paragraph(_esc(title), head), ""]] + [[k, Paragraph(_esc(v), val)] for k, v in pairs]
        tbl = Table(rows, colWidths=[width * 0.48, width * 0.52])
        tbl.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "DejaVu", fs),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("BACKGROUND", (0, 1), (0, -1), LABEL_BG),
            ("TEXTCOLOR", (0, 1), (0, -1), STEEL),
            ("FONT", (1, 1), (1, -1), "DejaVu-Bold", fs),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        return tbl

    def _side_by_side(self, blocks, width: float, gap: float = 4 * mm, fs: float = 7.5):
        n = len(blocks)
        w = (width - gap * (n - 1)) / n
        cells, widths = [], []
        for k, (title, pairs) in enumerate(blocks):
            if k:
                cells.append("")
                widths.append(gap)
            cells.append(self._kv_block(title, pairs, w, fs))
            widths.append(w)
        tbl = Table([cells], colWidths=widths)
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return tbl

    def fiber_story(self, cable: Cable, fiber: Fiber, sors: dict[int, SorFile]):
        """Μία σελίδα ανά μέτρηση.

        Μέτρηση με έως ONE_PAGE_EVENTS συμβάντα σε κάθε λ (χωρίς launch και γραμμές «Seg.») χωράει
        ΠΑΝΤΑ σε μία σελίδα: δοκιμάζονται διαδοχικά πιο συμπαγείς διατάξεις (επίπεδα 0–2) χωρίς να
        κόβεται ή να χάνεται τίποτα. Με περισσότερα συμβάντα οι πίνακες συνεχίζουν στην επόμενη σελίδα.
        """
        t = self.t
        present = [sors[w] for w in cable.wavelengths if w in sors]
        running = f"{t['cable']}: <b>{_esc(cable.name)}</b><br/>{t['fiber']}: <b>{_esc(fiber.display)}</b>"
        self._running_all.append(running)
        must_fit = bool(present) and max(event_count(x) for x in present) <= ONE_PAGE_EVENTS
        width = A4[0] - 24 * mm
        for level in range(3 if must_fit else 1):
            body, tail = self._fiber_parts(cable, fiber, sors, level)
            free = self._frame_h - _height(body + tail, width) - 3 * mm
            # ξεχωριστά γραφήματα: το ένα κάτω από το άλλο, ή δίπλα-δίπλα στο πιο συμπαγές επίπεδο
            plotted = [x for x in present if not x.is_live]        # live (1625/1650): χωρίς γράφημα
            n_charts = (len(plotted) if self.s.chart_mode == "separate" and len(plotted) > 1 and level < 2
                        else min(1, len(plotted)))
            if free >= n_charts * CHART_MIN[level] or level == 2 or not must_fit:
                break
        story = body + self._charts(present, free, level) + tail
        self.last_level = level
        if must_fit and _height(story, width) > self._frame_h:
            # δίχτυ ασφαλείας: ομοιόμορφη σμίκρυνση, ποτέ αποκοπή (τα tests ελέγχουν ότι δεν χρειάζεται)
            story = [KeepInFrame(width, self._frame_h, story, mode="shrink")]
            self.last_level = 3
        return ([_Running(self._running, running), NextPageTemplate("cont")] + story
                + [NextPageTemplate("main"), PageBreak()])

    def _charts(self, present, free, level):
        """Γραφήματα OTDR· οι live μετρήσεις (1625/1650) δεν έχουν γράφημα X-Y."""
        present = [x for x in present if not x.is_live]
        if not present:
            return []
        t = self.t
        width = A4[0] - 24 * mm
        units = Units(max((x.length_km for x in present), default=0))
        out = [Spacer(1, (2 if level == 0 else 1) * mm)]
        lo, hi = CHART_MIN[level], CHART_MAX[level]
        if self.s.chart_mode == "separate" and len(present) > 1 and level == 2:
            gap = 3 * mm
            w_each = (width - gap * (len(present) - 1)) / len(present)
            h = min(hi, max(lo, free))
            out.append(self._row([TraceChart([x], w_each, h, units, f"{x.wavelength} nm", t["launch_cable"])
                                  for x in present], [w_each] * len(present), gap))
        elif self.s.chart_mode == "separate" and len(present) > 1:
            gap = 1.5 * mm
            h = min(hi * 0.75, max(lo, free / len(present) - gap))
            for x in present:
                out.append(TraceChart([x], width, h, units, f"{x.wavelength} nm", t["launch_cable"]))
                out.append(Spacer(1, gap))
        elif present:
            out.append(TraceChart(present, width, min(hi, max(lo, free)), units, "", t["launch_cable"]))
        return out

    def _fiber_parts(self, cable: Cable, fiber: Fiber, sors: dict[int, SorFile], level: int):
        """(πάνω μέρος, κάτω μέρος) της σελίδας· ανάμεσα μπαίνει το γράφημα."""
        t = self.t
        th = self.s.thresholds
        # μόνο τα μήκη κύματος της μέτρησης και όσα απαιτούνται (μια live 1625 δεν δείχνει 1310/1550)
        wls = [w for w in cable.wavelengths if w in sors or w in cable.required_for(fiber)]
        present = [sors[w] for w in wls if w in sors]
        units = Units(max((x.length_km for x in present), default=0))
        width = A4[0] - 24 * mm
        compact = level >= 1
        fs = 7.5 if not compact else 6.8           # γραμματοσειρά μικρών πινάκων
        sec = self._section_c if compact else self._section
        subtitle = f"{t['cable']}: {_esc(cable.name)} &nbsp; · &nbsp; {t['fiber']}: <b>{_esc(fiber.display)}</b>"
        body = [self._header(t["title"], subtitle, fiber_verdict(fiber, cable.required_for(fiber), th, sors)),
                Spacer(1, (2 if not compact else 1) * mm)]

        # 1. Στοιχεία οργάνου
        ref = next((x for x in present if x.otdr_model or x.otdr_sn), present[0] if present else None)
        body.append(sec(t["machine"]))
        body.append(self._machine_table(ref, width, fs))
        body.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceBefore=3 if not compact else 1.5,
                               spaceAfter=1))

        # 2–3. Ρυθμίσεις μέτρησης (1310 αριστερά, 1550 δεξιά) και αρχή / τέλος ζεύξης
        cfg_rows = [(t["test_wave"], "wl"), (t["pw"], "pw"), (t["distance"], "dist"), (t["test_time"], "tt"),
                    (t["ior"], "ior"), (t["resolution"], "res")]

        def cfg(x, key):
            if x is None:
                return t["missing"] if key == "wl" else "–"
            return {"wl": str(x.wavelength), "pw": str(x.pulse_width_ns),
                    "dist": f"{x.test_range_km:g}" if x.test_range_km else "–",
                    "tt": str(x.test_time_s) if x.test_time_s else "–", "ior": f"{x.ior:.4f}",
                    "res": f"{x.resolution_km * 1000:.3f}" if x.resolution_km else "–"}[key]

        loc = ref
        loc_rows = [(t["location"], _val(loc.location_a if loc else ""), _val(loc.location_b if loc else "")),
                    (t["cable_id"], _val(loc.cable_id if loc else ""), _val(loc.cable_id if loc else "")),
                    (t["fiber_id"], _val(loc.fiber_id if loc else ""), _val(loc.fiber_id if loc else ""))]
        body.append(sec(t["config"]))
        if not compact:
            blocks = [(f"{w} nm", [(label, cfg(sors.get(w), key)) for label, key in cfg_rows]) for w in wls]
            if blocks:
                body.append(self._side_by_side(blocks, width, fs=fs))
            body.append(Spacer(1, 1.5 * mm))
            body.append(self._side_by_side([
                (t["start_loc"], [(r[0], r[1]) for r in loc_rows]),
                (t["end_loc"], [(r[0], r[2]) for r in loc_rows])], width, fs=fs))
        else:
            # συμπαγές: ένας πίνακας ρυθμίσεων (ετικέτα | 1310 | 1550) δίπλα σε έναν πίνακα θέσεων (ετικέτα | Start | End)
            gap = 3 * mm
            half = (width - gap) / 2
            cfg_tbl = self._grid_block([""] + [f"{w} nm" for w in wls],
                                       [[label] + [cfg(sors.get(w), key) for w in wls] for label, key in cfg_rows],
                                       half, fs)
            loc_tbl = self._grid_block(["", t["start_loc"], t["end_loc"]], [list(r) for r in loc_rows], half, fs)
            body.append(self._row([cfg_tbl, loc_tbl], [half, half], gap))

        # 4. Αρχεία και αποτελέσματα (τα ονόματα αρχείων αναδιπλώνονται, δεν κόβονται)
        body.append(sec(t["measurement"]))
        fname = ParagraphStyle("fn", fontName="DejaVu", fontSize=fs - 0.5, leading=fs + 1, alignment=1)
        head = [t["wl"], t["file"], t["date"], f"{t['launch']} (m)",
                f"{t['length']} ({units.name})", t["loss"], t["att"], t["orl"], t["result"]]
        rows = [head]
        for w in wls:
            x = sors.get(w)
            if x is None:
                rows.append([str(w), t["missing"], "", "", "", "", "", "", ""])
                continue
            rows.append([
                str(w), Paragraph(_esc(x.path.name if x.path else ""), fname),
                x.date.strftime("%d/%m/%Y %H:%M") if x.date else "–",
                f"{x.launch_km * 1000:.1f}" if x.launch_km else "–",
                units.fmt(x.length_km), _fmt(x.total_loss, 3), _fmt(x.attenuation, 3), _fmt(x.orl or None, 2),
                self._verdict(evaluate(x, th)),
            ])
        widths = [11 * mm, 52 * mm, 24 * mm, 14 * mm, 17 * mm, 16 * mm, 13 * mm, 15 * mm, 24 * mm]
        body.append(self._table(rows, widths, result_col=8, font_size=7 if not compact else 6.5,
                                pad=1.6 if not compact else 1.0))
        for x in present:
            if th.enabled and is_dead_fiber(x):
                body.append(Paragraph(f'<font color="{FAIL_C.hexval()}"><b>{_esc(t["dead"].format(wl=x.wavelength))}</b></font>',
                                      self.st["n"]))

        # 5. Link map (χωρίς launch cable, από το (S) στο 0)
        if present:
            body.append(sec(t["link_map"]))
            body.append(LinkMap(present[0], width, units, th, height=(30 if not compact else 24) * mm))

        # 6. Συμβάντα ανά μήκος κύματος, κάτω-κάτω (επίπεδο 2: 1310 αριστερά, 1550 δεξιά)
        tail = []
        if level < 2 or len(present) < 2:
            for x in present:
                tail.append(Spacer(1, (2 if not compact else 1) * mm))
                tail.append(self._events_table(x, units, width, 7 if not compact else 6.5,
                                               1.6 if not compact else 0.9))
        else:
            gap = 3 * mm
            n = len(present)
            w_each = (width - gap * (n - 1)) / n
            tail.append(Spacer(1, 1 * mm))
            tail.append(self._row([self._events_table(x, units, w_each, 6.2, 0.9, narrow=True) for x in present],
                                  [w_each] * n, gap))
        foot = []
        if self.s.operator:
            foot.append(f"{t['operator']}: {_esc(self.s.operator)}")
        boxes = self.threshold_boxes([x.wavelength for x in present],
                                     [e.splitter_ratio for x in present for e in x.events if e.splitter_ratio],
                                     fs=7 if not compact else 6.5)
        if boxes:
            tail += [Spacer(1, (1.5 if not compact else 1) * mm)] + boxes
        if foot:
            tail += [Spacer(1, (1.5 if not compact else 1) * mm), Paragraph(" &nbsp; · &nbsp; ".join(foot), self.st["small"])]
        return body, tail

    def threshold_boxes(self, wavelengths, splitters=(), width: float | None = None, fs: float = 7.5):
        """Πλαίσια «Threshold» (ανά μήκος κύματος) και «Splitter Threshold» (μόνο αν υπάρχουν splitters)."""
        th = self.s.thresholds
        if not th.enabled:
            return []
        t = self.t
        width = width or A4[0] - 24 * mm
        inner = width
        sec = self._section if fs >= 7 else self._section_c

        def table(rows, widths):
            # ίδια εμφάνιση με τους υπόλοιπους πίνακες: πορτοκαλί επικεφαλίδα, γκρι πρώτη στήλη, περιγράμματα
            hstyle = ParagraphStyle("thr_h", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5,
                                    textColor=HEAD_FG, alignment=1)
            rows = [[Paragraph(_esc(h), hstyle) for h in rows[0]]] + rows[1:]
            tbl = Table(rows, colWidths=widths)
            tbl.setStyle(TableStyle([
                ("FONT", (0, 0), (-1, -1), "DejaVu", fs), ("FONT", (0, 1), (0, -1), "DejaVu-Bold", fs),
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("BACKGROUND", (0, 1), (0, -1), LABEL_BG),
                ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
            return tbl

        out = []
        rows = [[""] + list(t["thr_cols"])]
        for wl in wavelengths:
            att = th.max_attenuation.get(str(wl))
            rows.append([str(wl),
                         f"{th.max_splice_loss:.3f}" if th.check_splice else "",
                         f"{th.max_connector_loss:.3f}" if th.check_connector else "",
                         f"{th.max_reflectance:.1f}" if th.check_reflectance else "",
                         f"{att:.3f}" if th.check_attenuation and att is not None else "",
                         f"{th.max_total_loss:.3f}" if th.check_total_loss else ""])
        first = 0.12 * inner
        out.append(TitledBox(sec(t["thr"]), table(rows, [first] + [(inner - first) / 5] * 5)))
        ratios = sorted(set(splitters))
        live = [wl for wl in wavelengths if is_live_wavelength(wl)]
        if ratios and th.check_splitter and live:
            head = [t["thr_type"]]
            for wl in live:
                head += [t["thr_max_loss"].format(wl=wl), t["thr_max_refl"].format(wl=wl)]
            rows = [head]
            for n in ratios:
                lim = th.max_splitter_loss.get(str(n))
                row = [f"1:{n}"]
                for _wl in live:
                    row += [f"{lim:.1f}" if lim is not None else "",
                            f"{th.max_reflectance:.1f}" if th.check_reflectance else ""]
                rows.append(row)
            first = 0.12 * inner
            tbl = table(rows, [first] + [(inner - first) / (len(head) - 1)] * (len(head) - 1))
            out.append(Spacer(1, 1.2 * mm))
            out.append(TitledBox(sec(t["thr_split"]), tbl))
        return out

    def _section_c(self, title: str):
        return Paragraph(_esc(title), self.st["h2c"])

    @staticmethod
    def _row(cells, widths, gap):
        """Πίνακες δίπλα-δίπλα, χωρίς πλαίσιο."""
        row, ws = [], []
        for k, (c, w) in enumerate(zip(cells, widths)):
            if k:
                row.append("")
                ws.append(gap)
            row.append(c)
            ws.append(w)
        tbl = Table([row], colWidths=ws)
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return tbl

    def _grid_block(self, head, rows, width, fs):
        """Συμπαγής πίνακας: ετικέτα + στήλες τιμών, με αναδίπλωση (π.χ. μεγάλα Location)."""
        hstyle = ParagraphStyle("gh", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5, textColor=HEAD_FG,
                                alignment=1)
        lstyle = ParagraphStyle("gl", fontName="DejaVu", fontSize=fs, leading=fs + 1.5, textColor=STEEL)
        vstyle = ParagraphStyle("gv", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5)
        n = len(head)
        first = width * 0.30
        rest = (width - first) / (n - 1)
        data = [[Paragraph(_esc(h), hstyle) for h in head]]
        data += [[Paragraph(_esc(r[0]), lstyle)] + [Paragraph(_esc(v), vstyle) for v in r[1:]] for r in rows]
        tbl = Table(data, colWidths=[first] + [rest] * (n - 1))
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("BACKGROUND", (0, 1), (0, -1), LABEL_BG),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        return tbl

    def _machine_table(self, ref, width: float, fs: float = 7.5):
        t = self.t
        val = ParagraphStyle("mv", fontName="DejaVu-Bold", fontSize=fs, leading=fs + 1.5)
        rows = [[t["module"], Paragraph(_esc(_val(ref.otdr_model if ref else "")), val), t["serial"],
                 Paragraph(_esc(_val(ref.otdr_sn if ref else "")), val)]]
        tbl = Table(rows, colWidths=[width * 0.14, width * 0.40, width * 0.14, width * 0.32])
        tbl.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "DejaVu", fs),
            ("BACKGROUND", (0, 0), (0, 0), LABEL_BG), ("BACKGROUND", (2, 0), (2, 0), LABEL_BG),
            ("TEXTCOLOR", (0, 0), (0, 0), STEEL), ("TEXTCOLOR", (2, 0), (2, 0), STEEL),
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_C),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        return tbl

    def _events_table(self, s: SorFile, units: Units, width: float | None = None, font: float = 7,
                      pad: float = 1.6, narrow: bool = False):
        """Συμβάντα με τις γραμμές τμημάτων ανάμεσα, όπως στην αναφορά του οργάνου."""
        t = self.t
        rows = [event_headers(t, units)]
        if narrow:                      # στενός πίνακας (1310 | 1550 δίπλα): σύντομες επικεφαλίδες, όχι σπασμένες λέξεις
            short = NARROW_HEADS["el" if t is TEXT["el"] else "en"]
            rows = [[h.format(u=units.name) for h in short]]
        muted = set()
        tstyle = ParagraphStyle("et", fontName="DejaVu", fontSize=font, leading=font + 1.2, alignment=1)
        for cells, _ok, is_seg in event_rows(s, self.s.thresholds, t, units):
            if narrow:                  # στενός πίνακας: ο τύπος αναδιπλώνεται αντί να ξεχειλίζει
                cells = [cells[0], Paragraph(_esc(cells[1]), tstyle)] + cells[2:]
            rows.append(cells)
            if is_seg:
                muted.add(len(rows) - 1)
        w = width or A4[0] - 24 * mm
        if narrow:
            widths = [4.5 * mm, 16.5 * mm] + [(w - 21 * mm - 11 * mm) / 5] * 5 + [11 * mm]
        else:
            widths = [8 * mm, 32 * mm] + [(w - 40 * mm - 20 * mm) / 5] * 5 + [20 * mm]
        # ο τίτλος με το λ είναι γραμμή του πίνακα: επαναλαμβάνεται σε κάθε συνέχεια και δεν μένει μόνος
        return self._table(rows, widths, result_col=7, muted_rows=muted, font_size=font, pad=pad,
                           title=f"{t['events']} – {s.wavelength} nm")

    # ---------- κατασκευή αρχείου ----------
    def build(self, out_path: Path, parts: list[tuple[Cable, list[Fiber], dict]],
              progress: Callable[[str], bool] | None = None,
              keep_going: Callable[[], bool] | None = None) -> bool:
        """parts: (καλώδιο, μετρήσεις, read) όπου read[fiber.key] = {λ: SorFile διαβασμένο τώρα}."""
        story = []
        self._running_all = []          # ο ίδιος builder φτιάχνει πολλά PDF
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

        running = self._running
        logo = asset_dir() / "grandway_logo.png"
        lw = CONT_LOGO_H * 411 / 201 if logo.is_file() else 0
        label = f"({t['continued']})"
        label_w = pdfmetrics.stringWidth(label, "DejaVu", 7)
        text_x = 12 * mm + lw + 4 * mm
        text_w = A4[0] - 12 * mm - text_x - label_w - 4 * mm   # η «συνέχεια» έχει δική της στήλη δεξιά
        cont_style = ParagraphStyle("cont", fontName="DejaVu", fontSize=8.5, leading=10.5)
        text_h = max((Paragraph(h, cont_style).wrap(text_w, A4[1])[1] for h in self._running_all), default=0)
        head_h = max(CONT_LOGO_H, text_h)
        cont_header = head_h + 5 * mm                           # + γραμμή και κενό πριν από τον πίνακα

        def on_cont(c, doc):
            """Σελίδα συνέχειας: logo, ταυτότητα μέτρησης και «συνέχεια» πάνω, μετά το κανονικό υποσέλιδο."""
            on_page(c, doc)
            c.saveState()
            top = A4[1] - TOP_MARGIN
            if lw:
                c.drawImage(str(logo), 12 * mm, top - CONT_LOGO_H, lw, CONT_LOGO_H, mask="auto",
                            preserveAspectRatio=True)
            par = Paragraph(running["text"], cont_style)
            _, ph = par.wrap(text_w, A4[1])
            par.drawOn(c, text_x, top - ph)
            c.setFont("DejaVu", 7)
            c.setFillColor(MUTED)
            c.drawRightString(A4[0] - 12 * mm, top - 7, label)
            c.setStrokeColor(GOLD)
            c.setLineWidth(1)
            c.line(12 * mm, top - head_h - 2 * mm, A4[0] - 12 * mm, top - head_h - 2 * mm)
            c.restoreState()

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
                              topMargin=TOP_MARGIN, bottomMargin=BOTTOM_SIG if signatures else BOTTOM,
                              title=f"{t['title']} – " + ", ".join(p[0].name for p in parts),
                              author=self.s.company or "", keep_going=keep_going,
                              on_page=on_page, on_cont=on_cont, cont_header=cont_header)
        try:
            doc.build(story)
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


def criteria_text(th, lang: str = "el", splitters=()) -> str:
    """Σύντομη περιγραφή των ενεργών κριτηρίων, π.χ. "κόλληση ≤ 0.30 dB, connector ≤ 0.75 dB".

    `splitters`: οι λόγοι (π.χ. 8, 32) των splitter της μέτρησης· γράφονται μόνο τα δικά τους όρια.
    """
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
    if th.check_splitter:
        for n in sorted(set(splitters)):
            lim = th.max_splitter_loss.get(str(n))
            if lim is not None:
                out.append(f"splitter 1:{n} ≤ {lim:.1f} dB")
    return ", ".join(out)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _grandway_logo():
    p = asset_dir() / "grandway_logo.png"
    if not p.is_file():
        return None
    from reportlab.lib.utils import ImageReader
    w, h = ImageReader(str(p)).getSize()
    return Image(str(p), width=LOGO_H * w / float(h or 1), height=LOGO_H)


def _val(s: str) -> str:
    return (s or "").strip() or "–"


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


def _pdf_stem(cable: Cable, fibers: list[Fiber], settings: ReportSettings) -> str:
    if settings.one_pdf_per_cable:
        return f"{safe_filename(cable.name)}{_range_suffix(fibers)}"
    return f"OTDR_report_{datetime.now():%Y%m%d_%H%M}"


def default_pdf_name(parts: list[tuple[Cable, list[Fiber]]], one_pdf_per_cable: bool) -> str | None:
    """Το προεπιλεγμένο όνομα (χωρίς .pdf) όταν η εξαγωγή βγάζει ΕΝΑ αρχείο· None αν βγάζει πολλά."""
    if not parts or (one_pdf_per_cable and len(parts) > 1):
        return None
    cable, fibers = parts[0]
    s = ReportSettings(one_pdf_per_cable=one_pdf_per_cable)
    return _pdf_stem(cable, fibers, s)


def existing_pdf_conflicts(parts: list[tuple[Cable, list[Fiber]]], out_dir: Path,
                           settings: ReportSettings, name: str | None = None) -> list[Path]:
    """PDF που υπάρχουν ήδη στον φάκελο με το όνομα που θα έπαιρνε η εξαγωγή (χωρίς διάκριση πεζών/κεφαλαίων)."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    on_disk = {p.name.casefold(): p for p in out_dir.glob("*.pdf")}
    groups = [[p] for p in parts] if settings.one_pdf_per_cable else [parts]
    found = []
    for group in groups:
        cable, fibers = group[0]
        stem = safe_filename(name) if name and len(groups) == 1 else _pdf_stem(cable, fibers, settings)
        hit = on_disk.get(f"{stem}.pdf".casefold())
        if hit and hit not in found:
            found.append(hit)
    return found


def generate_reports(parts: list[tuple[Cable, list[Fiber]]], out_dir: Path, settings: ReportSettings,
                     progress: Callable[[int, int, str], bool] | None = None,
                     overwrite: bool = False, name: str | None = None) -> ReportResult:
    """Δημιουργεί τα PDF.

    Κάθε αρχείο ξαναδιαβάζεται τώρα από τον δίσκο και αυτό που διαβάστηκε χρησιμοποιείται
    παντού (σύνοψη, σελίδα, PASS/FAIL). Μέτρηση χωρίς όλα τα μήκη κύματος (π.χ. 1310 και 1550),
    είτε γιατί λείπει είτε γιατί δεν διαβάζεται πια, δεν μπαίνει στο PDF εκτός αν
    `settings.allow_incomplete` (επιλογή του χρήστη, με δική του ευθύνη).

    Υπάρχον PDF στον φάκελο δεν αντικαθίσταται ποτέ σιωπηλά: χωρίς `overwrite` το νέο παίρνει
    όνομα «… (2).pdf». Η σύγκριση γίνεται χωρίς διάκριση πεζών/κεφαλαίων, όπως στα Windows.
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
                    sor = parse_sor(m.path)
                except (SorError, OSError, ValueError) as e:
                    result.unreadable.append((m.path, str(e)))
                    continue
                # Το αρχείο μπορεί να άλλαξε μετά τη φόρτωση: το πραγματικό λ πρέπει να είναι αυτό
                # της θέσης του, αλλιώς δύο 1310 θα περνούσαν για πλήρες ζεύγος 1310+1550 (PASS).
                if not sor.wavelength or abs(sor.wavelength - w) > WAVELENGTH_TOLERANCE_NM:
                    result.unreadable.append((m.path, f"Αναμενόταν μέτρηση {w} nm, το αρχείο είναι πλέον "
                                                      f"{sor.wavelength} nm"))
                    continue
                sors[w] = prepare(sor, settings)
            missing = sorted(set(cable.required_for(f)) - set(sors))
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
    on_disk = {p.name.casefold() for p in out_dir.glob("*.pdf")} if out_dir.is_dir() and not overwrite else set()
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
        cable, fibers, _ = prepared[0]
        # όνομα που έδωσε ο χρήστης: μόνο όταν η εξαγωγή βγάζει ένα αρχείο
        stem = safe_filename(name) if name and len(groups) == 1 else _pdf_stem(cable, fibers, settings)
        name, k = stem, 2
        while name.casefold() in used or f"{name}.pdf".casefold() in on_disk:
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
