"""Link map στο παράθυρο: η ζεύξη από το (S) μέχρι το (E), με αλλαγή κόλλησης ↔ connector."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSizePolicy, QToolTip, QWidget

from .linkmap import (KINDS, STATES, asset_dir, icon_path, linkmap_events,  # noqa: F401
                      node_kind, node_state)
from .sor import Event, SorFile

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

    typeChangeRequested = Signal(float, object)     # (απόσταση συμβάντος km από το OTDR, "connector"/"splice"/None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sor: SorFile | None = None
        self.th = None
        self.units_m = True
        self._hits: list[tuple[QRectF, int, Event]] = []
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)
        self._icons = {f"{k}_{st}": load_icon(f"{k}_{st}") for k in KINDS for st in STATES}
        self._line = load_icon("line")

    def set_measurement(self, sor: SorFile | None, th, units_m: bool = True):
        self.sor, self.th, self.units_m = sor, th, units_m
        self.update()

    def _fmt(self, km: float) -> str:
        return f"{km * 1000:.1f}" if self.units_m else f"{km:.4f}"

    # ---------- σχεδίαση
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
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
        size = max(22, min(40, int(h * 0.38)))
        y = h * 0.5
        x0, x1 = 30 + size / 2, w - 30 - size / 2
        step = (x1 - x0) / max(1, len(nodes) - 1)
        xs = [x0 + k * step for k in range(len(nodes))] if len(nodes) > 1 else [(x0 + x1) / 2]
        if self._line:
            lh = max(6, int(size * 0.3))
            p.drawPixmap(QRectF(xs[0], y - lh / 2, xs[-1] - xs[0], lh).toRect(), self._line)
        else:
            p.setPen(QPen(QColor("#1f6feb"), 3))
            p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        for k, ((i, e), x) in enumerate(zip(nodes, xs)):
            rect = QRectF(x - size / 2, y - size / 2, size, size)
            kind = node_kind(e)
            state = node_state(e, self.sor, self.th)
            icon = self._icons.get(f"{kind}_{state}")
            if icon:
                p.drawPixmap(rect.toRect(), icon)
            else:
                border = {"pass": PASS_C, "fail": FAIL_C}.get(state, GREY_C)
                p.setPen(QPen(border, 2.5))
                p.setBrush(QColor("white"))
                p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 5, 5)
                self._draw_fallback(p, rect, kind)
            if e.override:
                p.setPen(QPen(QColor("#e9af36"), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(rect.right() + 2, rect.top() - 2), 4, 4)
            tag = {"start": " (S)", "end": " (E)"}.get(kind, "")
            p.setPen(QColor("#24292f"))
            p.drawText(QRectF(x - 60, rect.top() - 22, 120, 16), Qt.AlignCenter, f"{i}{tag}")
            p.setPen(QColor("#57606a"))
            p.drawText(QRectF(x - 60, rect.bottom() + 4, 120, 16), Qt.AlignCenter, self._fmt(e.rel_km))
            if k:
                p.setPen(QColor("#0a3069"))
                p.drawText(QRectF((xs[k - 1] + x) / 2 - 60, y - 20, 120, 16), Qt.AlignCenter,
                           self._fmt(e.section_km))
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

    def mouseMoveEvent(self, ev):
        hit = self._hit(ev.position())
        if hit and hit[1].role == "event":
            self.setCursor(Qt.PointingHandCursor)
            e = hit[1]
            kind = "Connector" if e.reflective else "Κόλληση"
            extra = " (διορθωμένο)" if e.override else ""
            QToolTip.showText(ev.globalPosition().toPoint(),
                              f"{kind}{extra} – {self._fmt(e.rel_km)} · απώλεια {e.splice_loss:.3f} dB\n"
                              "Κλικ για αλλαγή τύπου", self)
        else:
            self.unsetCursor()

    def mousePressEvent(self, ev):
        hit = self._hit(ev.position())
        if not hit or hit[1].role != "event":
            return
        menu = self.build_menu(hit[1])
        menu.exec(ev.globalPosition().toPoint())

    def build_menu(self, e: Event) -> QMenu:
        menu = QMenu(self)
        a_con = QAction("Connector (ανακλαστικό)", menu, checkable=True, checked=e.reflective)
        a_spl = QAction("Κόλληση (μη ανακλαστικό)", menu, checkable=True, checked=not e.reflective)
        a_con.triggered.connect(lambda: self.typeChangeRequested.emit(e.distance_km, "connector"))
        a_spl.triggered.connect(lambda: self.typeChangeRequested.emit(e.distance_km, "splice"))
        menu.addAction(a_con)
        menu.addAction(a_spl)
        if e.override:
            menu.addSeparator()
            natural = "Connector" if e.raw_reflective else "Κόλληση"
            menu.addAction(f"Επαναφορά όπως το όργανο ({natural})",
                           lambda: self.typeChangeRequested.emit(e.distance_km, None))
        return menu
