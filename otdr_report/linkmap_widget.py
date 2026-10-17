"""Link map στο παράθυρο: η ζεύξη από το (S) μέχρι το (E), με αλλαγή κόλλησης ↔ connector ↔ splitter."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSizePolicy, QToolTip, QWidget

from .linkmap import (KINDS, STATES, asset_dir, icon_path, linkmap_events,  # noqa: F401
                      fit_labels, line_band, node_kind, node_positions, node_state,
                      scale_positions)
from .sor import SPLITTER_RATIOS, Event, SorFile

PASS_C, FAIL_C, GREY_C = QColor("#1a7f37"), QColor("#cf222e"), QColor("#8c959f")


def load_icon(name: str) -> QPixmap | None:
    """Εικονίδιο από otdr_report/assets/icons/<name>.png (π.χ. "splice_pass"), αν υπάρχει."""
    p = icon_path(name)
    if p:
        pm = QPixmap(str(p))
        return pm if not pm.isNull() else None
    return None


class LinkMapWidget(QWidget):
    """Σχηματική ζεύξη. Κλικ σε ενδιάμεσο συμβάν → αλλαγή τύπου (connector / κόλληση)."""

    refreshRequested = Signal()                     # δεξί κλικ → «Ανανέωση μέτρησης»
    eventSelected = Signal(int)                     # αριστερό κλικ σε συμβάν → αριθμός συμβάντος στο .sor
    typeChangeRequested = Signal(float, object)     # (απόσταση συμβάντος km από το OTDR, "connector"/"splice"/None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sor: SorFile | None = None
        self.th = None
        self.units_m = True
        self._hits: list[tuple[QRectF, int, Event]] = []
        self.selected: int | None = None            # επιλεγμένο συμβάν (γαλάζιο περίγραμμα)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)
        self._icons = {f"{k}_{st}": load_icon(f"{k}_{st}") for k in KINDS for st in STATES}
        self._line = load_icon("line")

    def set_measurement(self, sor: SorFile | None, th, units_m: bool = True):
        self.sor, self.th, self.units_m = sor, th, units_m
        self.update()

    def set_selected(self, index: int | None):
        """Επιλογή συμβάντος απ' έξω (π.χ. από τον πίνακα συμβάντων), χωρίς σήμα."""
        if index != self.selected:
            self.selected = index
            self.update()

    def _fmt(self, km: float) -> str:
        return f"{km * 1000:.1f}" if self.units_m else f"{km:.4f}"

    # ---------- σχεδίαση
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("white"))
        self._hits = []
        if not self.sor:
            p.setPen(GREY_C)
            p.drawText(self.rect(), Qt.AlignCenter, "Link map: επίλεξε μέτρηση")
            return
        nodes = linkmap_events(self.sor)
        if not nodes:
            return
        w, h = self.width(), self.height()
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        fm = p.fontMetrics()
        kms = [e.rel_km for _, e in nodes]
        states = [node_state(e, self.sor, self.th) for _, e in nodes]
        unit = "m" if self.units_m else "km"
        # μπάρα κλίμακας: συμβάντα στην πραγματική τους θέση, κόκκινο = FAIL
        total = f"{self._fmt(kms[-1])}{unit}"
        bx0, bx1 = 14.0, w - 18.0 - fm.horizontalAdvance(total)
        by = fm.height() + 6
        p.setPen(QPen(QColor("#3b4a8c"), 2))
        p.drawLine(QPointF(bx0, by), QPointF(bx1, by))
        sx = scale_positions(kms, bx0, bx1)
        tw = [fm.horizontalAdvance(str(i)) for i, _ in nodes]
        show = fit_labels([x - w / 2 for x, w in zip(sx, tw)], tw, 3)
        for (i, _e), x, st, vis in zip(nodes, sx, states, show):
            col = FAIL_C if st == "fail" else QColor("#24292f")
            p.setPen(QPen(col, 1.2))
            p.drawLine(QPointF(x, by - 4), QPointF(x, by + 4))
            if vis or st == "fail":
                p.drawText(QRectF(x - 20, by - fm.height() - 4, 40, fm.height()), Qt.AlignCenter, str(i))
        p.setPen(QColor("#24292f"))
        p.drawText(QPointF(bx1 + 4, by + fm.ascent() / 2 - 1), total)
        # εικονίδια: κατά προσέγγιση αναλογικά, με ελάχιστη απόσταση
        top = by + 16 + 2 * fm.height()
        size = max(26, min(54, int(h - top - fm.height() - 10)))
        size = max(12, min(size, int((w - 28) / max(1, len(nodes)) * 0.8)))   # πολλά συμβάντα → μικρότερα
        y = top + size / 2
        xs = node_positions(kms, 14 + size / 2, w - 14 - size / 2, size + min(24, size * 0.7))
        show_idx = fit_labels([x - size / 2 for x in xs], [fm.horizontalAdvance(str(i)) for i, _ in nodes])
        show_dist = fit_labels([x - size / 2 for x in xs],
                               [fm.horizontalAdvance(self._fmt(e.rel_km)) for _, e in nodes])
        mids = [(xs[k - 1] + xs[k]) / 2 for k in range(1, len(xs))]
        sec_w = [fm.horizontalAdvance(self._fmt(e.section_km)) for _, e in nodes[1:]]
        show_sec = fit_labels([m - sw / 2 for m, sw in zip(mids, sec_w)], sec_w, 4) if mids else []
        if self._line and len(xs) > 1:
            off, lh = line_band(size)              # ίδια ευθεία και πάχος με το καλώδιο των εικονιδίων
            p.drawPixmap(QRectF(xs[0], y - size / 2 + off, xs[-1] - xs[0], lh), self._line,
                         QRectF(self._line.rect()))
        else:
            p.setPen(QPen(QColor("#767b80"), 3))
            p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
        for k, ((i, e), x, state) in enumerate(zip(nodes, xs, states)):
            rect = QRectF(x - size / 2, y - size / 2, size, size)
            kind = node_kind(e)
            icon = self._icons.get(f"{kind}_{state}")
            if icon:
                p.drawPixmap(rect, icon, QRectF(icon.rect()))
            else:
                border = {"pass": PASS_C, "fail": FAIL_C}.get(state, GREY_C)
                p.setPen(QPen(border, 2.5))
                p.setBrush(QColor("white"))
                p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 5, 5)
                self._draw_fallback(p, rect, kind)
            if kind == "splitter" and e.splitter_ratio:            # λόγος διαίρεσης πάνω δεξιά
                f2 = QFont(p.font()); f2.setBold(True); f2.setPointSizeF(max(6.0, p.font().pointSizeF() - 1))
                p.save(); p.setFont(f2); p.setPen(QColor("#24292f"))
                p.drawText(rect.adjusted(0, 1, -2, 0), Qt.AlignRight | Qt.AlignTop, f"1:{e.splitter_ratio}")
                p.restore()
            if i == self.selected:                                  # επιλογή: γαλάζιο περίγραμμα
                p.setPen(QPen(QColor("#38a8f5"), 3))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 6, 6)
            if kind in ("start", "end") and size >= 22:
                p.setPen(FAIL_C)
                p.drawText(rect.adjusted(3, 0, 0, -2), Qt.AlignLeft | Qt.AlignBottom, "S" if kind == "start" else "E")
            if e.override:
                p.setPen(QPen(QColor("#e9af36"), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(rect.right() + 2, rect.top() - 2), 4, 4)
            p.setPen(QColor("#24292f"))
            if show_idx[k]:
                p.drawText(QPointF(rect.left(), rect.top() - 4 - fm.height() - fm.descent()), str(i))
            if show_dist[k]:
                p.drawText(QPointF(rect.left(), rect.top() - 4 - fm.descent()), self._fmt(e.rel_km))
            if k and show_sec[k - 1]:
                p.drawText(QRectF((xs[k - 1] + x) / 2 - 60, rect.bottom() + 4, 120, fm.height()),
                           Qt.AlignCenter, self._fmt(e.section_km))
            self._hits.append((rect.adjusted(-6, -6, 6, 6), i, e))

    @staticmethod
    def _draw_fallback(p: QPainter, rect: QRectF, kind: str):
        c = rect.center()
        if kind == "connector":
            p.setPen(QPen(QColor("#24292f"), 1.5)); p.setBrush(QColor("#d0d7de"))
            p.drawRect(rect.adjusted(rect.width() * 0.25, rect.height() * 0.15, -rect.width() * 0.25, -rect.height() * 0.15))
            p.setBrush(QColor("#e9af36"))
            p.drawRect(QRectF(c.x() - rect.width() * 0.12, rect.top() + 2, rect.width() * 0.24, rect.height() - 4))
        elif kind == "splice":
            p.setPen(Qt.NoPen); p.setBrush(QColor("#fb8f44"))
            p.drawRoundedRect(QRectF(c.x() - rect.width() * 0.3, c.y() - rect.height() * 0.15,
                                     rect.width() * 0.6, rect.height() * 0.3), 3, 3)
        else:
            p.setPen(QPen(QColor("#24292f"), 1.5)); p.setBrush(QColor("#57606a"))
            p.drawRect(rect.adjusted(rect.width() * 0.3, rect.height() * 0.1, -rect.width() * 0.3, -rect.height() * 0.1))

    # ---------- αλληλεπίδραση
    def _hit(self, pos) -> tuple[int, Event] | None:
        for rect, i, e in self._hits:
            if rect.contains(pos):
                return i, e
        return None

    def mousePressEvent(self, ev):
        """Αριστερό κλικ σε συμβάν: επιλογή (και στον πίνακα συμβάντων)."""
        if ev.button() == Qt.LeftButton:
            hit = self._hit(ev.position())
            if hit:
                self.selected = hit[0]
                self.update()
                self.eventSelected.emit(hit[0])
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        hit = self._hit(ev.position())
        if hit and hit[1].role == "event":
            e = hit[1]
            kind = (f"Splitter 1:{e.splitter_ratio}" if e.splitter_ratio
                    else "Connector" if e.reflective else "Κόλληση")
            extra = " (διορθωμένο)" if e.override else ""
            QToolTip.showText(ev.globalPosition().toPoint(),
                              f"{kind}{extra} – {self._fmt(e.rel_km)} · απώλεια {e.splice_loss:.3f} dB\n"
                              "Δεξί κλικ για αλλαγή τύπου", self)

    def contextMenuEvent(self, ev):
        """Δεξί κλικ: αλλαγή τύπου (πάνω σε ενδιάμεσο συμβάν) και «Ανανέωση μέτρησης»."""
        hit = self._hit(QPointF(ev.pos()))
        menu = self.build_menu(hit[1] if hit and hit[1].role == "event" else None)
        menu.exec(ev.globalPos())

    def build_menu(self, e: Event | None) -> QMenu:
        menu = QMenu(self)
        if e is not None:
            ratio = e.splitter_ratio
            a_con = QAction("Connector (ανακλαστικό)", menu, checkable=True, checked=not ratio and e.reflective)
            a_spl = QAction("Κόλληση (μη ανακλαστικό)", menu, checkable=True, checked=not ratio and not e.reflective)
            a_con.triggered.connect(lambda: self.typeChangeRequested.emit(e.distance_km, "connector"))
            a_spl.triggered.connect(lambda: self.typeChangeRequested.emit(e.distance_km, "splice"))
            menu.addAction(a_con)
            menu.addAction(a_spl)
            if self.sor is not None and self.sor.is_live:        # splitters μόνο σε live μέτρηση 1625/1650
                sub = menu.addMenu("Splitter")
                for n in SPLITTER_RATIOS:
                    a = QAction(f"Splitter 1:{n}", sub, checkable=True, checked=ratio == n)
                    a.triggered.connect(lambda _c=False, n=n: self.typeChangeRequested.emit(e.distance_km, f"splitter:{n}"))
                    sub.addAction(a)
            if e.override:
                natural = "Connector" if e.raw_reflective else "Κόλληση"
                menu.addAction(f"Επαναφορά όπως το όργανο ({natural})",
                               lambda: self.typeChangeRequested.emit(e.distance_km, None))
            menu.addSeparator()
        menu.addAction("Ανανέωση μέτρησης", self.refreshRequested.emit)
        return menu
