"""Κύριο παράθυρο της εφαρμογής (PySide6)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__
from .matching import Cable, Fiber, Project, find_sor_files
from .pdf_report import generate_reports
from .settings import ReportSettings, evaluate, event_ok
from .sor import parse_sor

APP_NAME = "OTDR Batch Report"
WL_QCOLORS = {1310: "#1f6feb", 1550: "#d1242f", 1625: "#8250df", 1490: "#1a7f37", 850: "#bf8700"}
PASS_BG, FAIL_BG, MISS_BG = QColor("#dafbe1"), QColor("#ffebe9"), QColor("#fff8c5")


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for p in (base / name, base / "otdr_report" / name, Path(__file__).parent / name):
        if p.exists():
            return p
    return base / name


def open_folder(path: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ---------------------------------------------------------------- εργασίες στο παρασκήνιο
class Worker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancelled = False

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.fn(self))
        except Exception as e:  # noqa: BLE001 – εμφανίζεται στον χρήστη
            self.failed.emit(f"{type(e).__name__}: {e}")


class _Job(QObject):
    """Ζει στο κύριο νήμα και ενημερώνει το παράθυρο προόδου με ασφάλεια."""

    def __init__(self, parent, title, on_done):
        super().__init__(parent)
        self.title = title
        self.on_done = on_done
        self.dlg = QProgressDialog(title, "Ακύρωση", 0, 0, parent)
        self.dlg.setWindowTitle(APP_NAME)
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.setMinimumDuration(0)
        self.dlg.setMinimumWidth(420)
        self.dlg.setAutoClose(False)
        self.dlg.setAutoReset(False)

    @Slot(int, int, str)
    def progress(self, done, total, label):
        self.dlg.setMaximum(total)
        self.dlg.setValue(done)
        self.dlg.setLabelText(f"{self.title}\n{label}" if label else self.title)

    @Slot(object)
    def finished(self, result):
        self.dlg.close()
        self.thread.quit()
        self.on_done(result, self.worker.cancelled)

    @Slot(str)
    def failed(self, msg):
        self.dlg.close()
        self.thread.quit()
        QMessageBox.critical(self.parent(), APP_NAME, msg)


def run_with_progress(parent, title: str, fn, on_done):
    job = _Job(parent, title, on_done)
    thread = QThread(parent)
    worker = Worker(fn)
    worker.moveToThread(thread)
    job.thread, job.worker = thread, worker
    worker.progress.connect(job.progress)
    worker.finished.connect(job.finished)
    worker.failed.connect(job.failed)
    job.dlg.canceled.connect(lambda: setattr(worker, "cancelled", True))
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(job.deleteLater)
    thread.start()
    job.dlg.show()
    return job


# ---------------------------------------------------------------- ρυθμίσεις
class SettingsDialog(QDialog):
    def __init__(self, s: ReportSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ρυθμίσεις αναφοράς")
        self.s = s
        lay = QVBoxLayout(self)

        g1 = QGroupBox("Στοιχεία αναφοράς")
        f1 = QFormLayout(g1)
        self.company = QLineEdit(s.company)
        self.company_info = QPlainTextEdit(s.company_info)
        self.company_info.setFixedHeight(54)
        self.company_info.setPlaceholderText("Διεύθυνση, τηλέφωνο, email…")
        self.logo = QLineEdit(s.logo_path)
        b_logo = QPushButton("…")
        b_logo.setFixedWidth(30)
        b_logo.clicked.connect(self._pick_logo)
        row = QHBoxLayout(); row.addWidget(self.logo); row.addWidget(b_logo)
        self.customer = QLineEdit(s.customer)
        self.project = QLineEdit(s.project)
        self.operator = QLineEdit(s.operator)
        self.language = QComboBox()
        self.language.addItem("Ελληνικά", "el"); self.language.addItem("English", "en")
        self.language.setCurrentIndex(0 if s.language == "el" else 1)
        self.chart = QComboBox()
        self.chart.addItem("1310 + 1550 στο ίδιο γράφημα", "overlay")
        self.chart.addItem("Ξεχωριστό γράφημα ανά μήκος κύματος", "separate")
        self.chart.setCurrentIndex(0 if s.chart_mode == "overlay" else 1)
        f1.addRow("Εταιρεία", self.company)
        f1.addRow("Στοιχεία εταιρείας", self.company_info)
        f1.addRow("Λογότυπο", row)
        f1.addRow("Πελάτης", self.customer)
        f1.addRow("Έργο", self.project)
        f1.addRow("Τεχνικός", self.operator)
        f1.addRow("Γλώσσα PDF", self.language)
        f1.addRow("Γράφημα", self.chart)
        lay.addWidget(g1)

        th = s.thresholds
        g2 = QGroupBox("Κριτήρια Pass / Fail")
        g2.setCheckable(True)
        g2.setChecked(th.enabled)
        self.g2 = g2
        f2 = QFormLayout(g2)

        def dspin(val, lo, hi, step=0.01, dec=2, suffix=""):
            w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(dec)
            w.setSingleStep(step); w.setValue(val); w.setSuffix(suffix)
            return w
        self.splice = dspin(th.max_splice_loss, 0, 5, suffix=" dB")
        self.conn = dspin(th.max_connector_loss, 0, 5, suffix=" dB")
        self.refl = dspin(th.max_reflectance, -80, 0, 0.5, 1, " dB")
        self.att1310 = dspin(th.max_attenuation.get("1310", 0.4), 0, 5, 0.01, 3, " dB/km")
        self.att1550 = dspin(th.max_attenuation.get("1550", 0.3), 0, 5, 0.01, 3, " dB/km")
        self.att1625 = dspin(th.max_attenuation.get("1625", 0.35), 0, 5, 0.01, 3, " dB/km")
        self.total = dspin(th.max_total_loss, 0, 60, 0.1, 2, " dB")
        self.total.setSpecialValueText("χωρίς έλεγχο")
        f2.addRow("Μέγ. απώλεια κόλλησης", self.splice)
        f2.addRow("Μέγ. απώλεια connector", self.conn)
        f2.addRow("Μέγ. ανάκλαση", self.refl)
        f2.addRow("Μέγ. εξασθένηση 1310", self.att1310)
        f2.addRow("Μέγ. εξασθένηση 1550", self.att1550)
        f2.addRow("Μέγ. εξασθένηση 1625", self.att1625)
        f2.addRow("Μέγ. συνολική απώλεια", self.total)
        lay.addWidget(g2)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick_logo(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Λογότυπο", "", "Εικόνες (*.png *.jpg *.jpeg)")
        if fn:
            self.logo.setText(fn)

    def result_settings(self) -> ReportSettings:
        s = self.s
        s.company = self.company.text().strip()
        s.company_info = self.company_info.toPlainText().strip()
        s.logo_path = self.logo.text().strip()
        s.customer = self.customer.text().strip()
        s.project = self.project.text().strip()
        s.operator = self.operator.text().strip()
        s.language = self.language.currentData()
        s.chart_mode = self.chart.currentData()
        th = s.thresholds
        th.enabled = self.g2.isChecked()
        th.max_splice_loss = self.splice.value()
        th.max_connector_loss = self.conn.value()
        th.max_reflectance = self.refl.value()
        th.max_attenuation.update({"1310": self.att1310.value(), "1550": self.att1550.value(),
                                   "1625": self.att1625.value()})
        th.max_total_loss = self.total.value()
        return s


# ---------------------------------------------------------------- εξαγωγή
class ExportDialog(QDialog):
    def __init__(self, project: Project, s: ReportSettings, out_dir: str, checked: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Δημιουργία PDF")
        self.setMinimumWidth(520)
        self.project = project
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Καλώδια για εξαγωγή:"))
        self.cables = QTreeWidget()
        self.cables.setHeaderLabels(["Καλώδιο", "Ίνες", "Ελλιπείς"])
        self.cables.setRootIsDecorated(False)
        for c in project.sorted_cables():
            it = QTreeWidgetItem([c.name, str(len(c.fibers)), str(len(c.incomplete()))])
            it.setCheckState(0, Qt.Checked if (not checked or c.name in checked) else Qt.Unchecked)
            it.setData(0, Qt.UserRole, c.name)
            self.cables.addTopLevelItem(it)
        self.cables.header().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.cables)

        form = QFormLayout()
        nums = [f.number for c in project.cables.values() for f in c.fibers.values()] or [0]
        self.from_f = QSpinBox(); self.from_f.setRange(0, 999999); self.from_f.setValue(min(nums))
        self.to_f = QSpinBox(); self.to_f.setRange(0, 999999); self.to_f.setValue(max(nums))
        rng = QHBoxLayout()
        rng.addWidget(QLabel("από")); rng.addWidget(self.from_f)
        rng.addWidget(QLabel("έως")); rng.addWidget(self.to_f); rng.addStretch()
        form.addRow("Ίνες", rng)
        self.only_complete = QCheckBox("Μόνο ίνες που έχουν όλα τα μήκη κύματος")
        form.addRow("", self.only_complete)
        self.per_cable = QCheckBox("Ένα PDF ανά καλώδιο (αλλιώς ένα PDF για όλα)")
        self.per_cable.setChecked(s.one_pdf_per_cable)
        form.addRow("", self.per_cable)
        self.summary = QCheckBox("Σελίδα σύνοψης στην αρχή κάθε καλωδίου")
        self.summary.setChecked(s.summary_page)
        form.addRow("", self.summary)
        self.out = QLineEdit(out_dir)
        b = QPushButton("…"); b.setFixedWidth(30); b.clicked.connect(self._pick)
        row = QHBoxLayout(); row.addWidget(self.out); row.addWidget(b)
        form.addRow("Φάκελος PDF", row)
        lay.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Δημιουργία")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Φάκελος PDF", self.out.text())
        if d:
            self.out.setText(d)

    def _ok(self):
        if not self.out.text().strip():
            QMessageBox.warning(self, APP_NAME, "Διάλεξε φάκελο για τα PDF.")
            return
        if not self.parts():
            QMessageBox.warning(self, APP_NAME, "Δεν υπάρχουν ίνες με αυτές τις επιλογές.")
            return
        self.accept()

    def parts(self) -> list[tuple[Cable, list[Fiber]]]:
        lo, hi = self.from_f.value(), self.to_f.value()
        out = []
        for i in range(self.cables.topLevelItemCount()):
            it = self.cables.topLevelItem(i)
            if it.checkState(0) != Qt.Checked:
                continue
            c = self.project.cables[it.data(0, Qt.UserRole)]
            wls = set(c.wavelengths)
            fibers = [f for f in c.sorted_fibers() if lo <= f.number <= hi
                      and (not self.only_complete.isChecked() or set(f.measurements) == wls)]
            if fibers:
                out.append((c, fibers))
        return out


# ---------------------------------------------------------------- κύριο παράθυρο
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        icon = resource("icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1400, 860)
        self.setAcceptDrops(True)
        self.qs = QSettings("OTDRBatchReport", APP_NAME)
        try:
            self.settings = ReportSettings.from_json(self.qs.value("report", "", str) or "{}")
        except Exception:
            self.settings = ReportSettings()
        self.project = Project()
        self.current_cable: Cable | None = None

        tb = self.addToolBar("main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        st = self.style()

        def act(text, icon, slot, shortcut=None):
            a = QAction(st.standardIcon(icon), text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            tb.addAction(a)
            return a
        act("Άνοιγμα φακέλου", st.StandardPixmap.SP_DirOpenIcon, self.open_folder, QKeySequence.Open)
        act("Προσθήκη αρχείων", st.StandardPixmap.SP_FileIcon, self.add_files)
        act("Καθαρισμός", st.StandardPixmap.SP_DialogResetButton, self.clear)
        tb.addSeparator()
        act("Ρυθμίσεις αναφοράς", st.StandardPixmap.SP_FileDialogDetailedView, self.edit_settings)
        self.act_pdf = act("Δημιουργία PDF", st.StandardPixmap.SP_DialogSaveButton, self.export, "Ctrl+P")

        # Αριστερά: καλώδια
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Καλώδιο", "Ίνες", "Ελλιπείς", "FAIL"])
        self.tree.setRootIsDecorated(False)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._cable_selected)

        # Κέντρο: ίνες
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._fiber_selected)

        # Κάτω: γράφημα + συμβάντα
        pg.setConfigOptions(antialias=True, background="w", foreground="#333")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Απόσταση", units="km")
        self.plot.setLabel("left", "dB")
        self.plot.addLegend(offset=(-10, 10))
        self.events_tabs = QTabWidget()

        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self.plot)
        bottom.addWidget(self.events_tabs)
        bottom.setSizes([850, 550])

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.table)
        right.addWidget(bottom)
        right.setSizes([380, 440])

        main = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Σύρε εδώ φάκελο ή αρχεία .sor")
        hint.setStyleSheet("color:#57606a; padding:4px")
        ll.addWidget(self.tree)
        ll.addWidget(hint)
        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([380, 1020])
        self.setCentralWidget(main)
        self._refresh()

    # ---------- φόρτωση
    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Φάκελος με αρχεία .sor", self.qs.value("lastDir", "", str))
        if d:
            self.qs.setValue("lastDir", d)
            self.load_paths([Path(d)])

    def add_files(self):
        fns, _ = QFileDialog.getOpenFileNames(self, "Αρχεία .sor", self.qs.value("lastDir", "", str),
                                              "OTDR (*.sor *.SOR)")
        if fns:
            self.qs.setValue("lastDir", str(Path(fns[0]).parent))
            self.load_paths([Path(f) for f in fns])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.load_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    def load_paths(self, paths: list[Path]):
        project = self.project

        def job(w: Worker):
            files: list[Path] = []
            for p in paths:
                if p.is_dir():
                    w.progress.emit(0, 0, f"Αναζήτηση σε {p}…")
                    files += find_sor_files(p)
                elif p.suffix.lower() == ".sor":
                    files.append(p)
            before = len(project.errors)

            def prog(i, n):
                if i % 25 == 0 or i == n:
                    w.progress.emit(i, n, f"{i} / {n}")
                return not w.cancelled
            project.load(files, prog)
            return len(files), project.errors[before:]

        def done(res, cancelled):
            self._refresh()
            if not res:
                return
            n, errs = res
            msg = f"Φορτώθηκαν {n - len(errs)} αρχεία."
            if errs:
                msg += f"\n\n{len(errs)} αρχεία δεν διαβάστηκαν:\n" + "\n".join(
                    f"• {p.name}: {e}" for p, e in errs[:15])
                QMessageBox.warning(self, APP_NAME, msg)
            self.statusBar().showMessage(msg.splitlines()[0], 8000)

        run_with_progress(self, "Φόρτωση αρχείων…", job, done)

    def clear(self):
        self.project = Project()
        self.current_cable = None
        self._refresh()

    # ---------- προβολή
    def _refresh(self):
        self.tree.clear()
        th = self.settings.thresholds
        for c in self.project.sorted_cables():
            fails = sum(1 for f in c.fibers.values()
                        if any(evaluate(m.sor, th) is False for m in f.measurements.values()))
            it = QTreeWidgetItem([c.name, str(len(c.fibers)), str(len(c.incomplete())), str(fails)])
            it.setData(0, Qt.UserRole, c.name)
            if c.incomplete():
                it.setBackground(2, QBrush(MISS_BG))
            if fails:
                it.setBackground(3, QBrush(FAIL_BG))
            self.tree.addTopLevelItem(it)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self._show_cable(None)
        n = self.project.file_count
        self.statusBar().showMessage(
            f"{len(self.project.cables)} καλώδια · {n} αρχεία" if n else "Άνοιξε έναν φάκελο με μετρήσεις .sor")
        self.act_pdf.setEnabled(bool(self.project.cables))

    def _cable_selected(self, cur, _prev=None):
        name = cur.data(0, Qt.UserRole) if cur else None
        self._show_cable(self.project.cables.get(name))

    def _show_cable(self, cable: Cable | None):
        self.current_cable = cable
        self.table.clear()
        self.table.setRowCount(0)
        if not cable:
            self.table.setColumnCount(0)
            self._show_fiber(None)
            return
        wls = cable.wavelengths
        heads = ["Ίνα"]
        for w in wls:
            heads += [f"{w} Μήκος (km)", f"{w} Απώλεια (dB)", f"{w} dB/km", f"{w}"]
        heads += ["Αρχεία"]
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        fibers = cable.sorted_fibers()
        self.table.setRowCount(len(fibers))
        th = self.settings.thresholds
        for r, f in enumerate(fibers):
            it = QTableWidgetItem(f.label or str(f.number))
            it.setData(Qt.UserRole, f.number)
            self.table.setItem(r, 0, it)
            col = 1
            for w in wls:
                m = f.measurements.get(w)
                if not m:
                    for k in range(4):
                        x = QTableWidgetItem("λείπει" if k == 3 else "")
                        x.setBackground(QBrush(MISS_BG))
                        self.table.setItem(r, col + k, x)
                else:
                    ok = evaluate(m.sor, th)
                    vals = [f"{m.sor.length_km:.3f}",
                            f"{m.sor.total_loss:.2f}" if m.sor.total_loss is not None else "",
                            f"{m.sor.attenuation:.3f}" if m.sor.attenuation is not None else "",
                            "–" if ok is None else ("PASS" if ok else "FAIL")]
                    for k, v in enumerate(vals):
                        x = QTableWidgetItem(v)
                        x.setTextAlignment(Qt.AlignCenter)
                        if k == 3 and ok is not None:
                            x.setBackground(QBrush(PASS_BG if ok else FAIL_BG))
                        self.table.setItem(r, col + k, x)
                col += 4
            names = ", ".join(m.path.name for m in f.measurements.values())
            if f.duplicates:
                names += f"   (+{len(f.duplicates)} διπλότυπα)"
            self.table.setItem(r, col, QTableWidgetItem(names))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        if fibers:
            self.table.selectRow(0)

    def _fiber_selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or not self.current_cable:
            self._show_fiber(None)
            return
        num = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        self._show_fiber(self.current_cable.fibers.get(num))

    def _show_fiber(self, fiber: Fiber | None):
        self.plot.clear()
        self.events_tabs.clear()
        if not fiber:
            return
        th = self.settings.thresholds
        max_len = 0.0
        for w in fiber.wavelengths:
            m = fiber.measurements[w]
            try:
                s = parse_sor(m.path)
            except Exception as e:  # noqa: BLE001
                self.statusBar().showMessage(f"{m.path.name}: {e}", 8000)
                continue
            y = s.trace.copy()
            y[y <= -65.0] = float("nan")
            pen = pg.mkPen(WL_QCOLORS.get(w, "#000"), width=1.2)
            self.plot.plot(s.distance_axis, y, pen=pen, name=f"{w} nm", connect="finite")
            max_len = max(max_len, s.length_km)
            for i, e in enumerate(s.events, 1):
                line = pg.InfiniteLine(e.distance_km, angle=90,
                                       pen=pg.mkPen("#8c959f", width=0.8, style=Qt.DashLine))
                if w == fiber.wavelengths[0]:
                    line.label = pg.InfLineLabel(line, str(i), position=0.95, color="#24292f")
                    self.plot.addItem(line)

            t = QTableWidget(len(s.events), 8)
            t.setHorizontalHeaderLabels(["Τύπος", "Απόσταση (km)", "Τμήμα (km)", "Απώλεια (dB)",
                                         "Ανάκλαση (dB)", "dB/km", "Αθρ. (dB)", "Αποτ."])
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            for r, e in enumerate(s.events):
                ok = event_ok(e, th)
                vals = [e.type_name, f"{e.distance_km:.4f}", f"{e.section_km:.4f}",
                        f"{e.splice_loss:.3f}" if r else "–",
                        f"{e.reflectance:.2f}" if e.reflectance else "–",
                        f"{e.slope:.3f}" if r and e.slope else "–", f"{e.cumulative_loss:.3f}",
                        "" if ok is None else ("PASS" if ok else "FAIL")]
                for k, v in enumerate(vals):
                    x = QTableWidgetItem(v)
                    x.setTextAlignment(Qt.AlignCenter)
                    if k == 7 and ok is not None:
                        x.setBackground(QBrush(PASS_BG if ok else FAIL_BG))
                    t.setItem(r, k, x)
            t.resizeColumnsToContents()
            att = f"{s.attenuation:.3f}" if s.attenuation is not None else "–"
            info = QLabel(f"{m.path.name}   ·   Μήκος {s.length_km:.3f} km   ·   "
                          f"Απώλεια {s.total_loss or 0:.2f} dB   ·   {att} dB/km   ·   Παλμός {s.pulse_width_ns} ns")
            info.setStyleSheet("padding:4px")
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(info)
            bl.addWidget(t)
            self.events_tabs.addTab(box, f"{w} nm")
        if max_len:
            self.plot.setXRange(0, max_len * 1.08)

    # ---------- ρυθμίσεις & εξαγωγή
    def _save_settings(self):
        self.qs.setValue("report", self.settings.to_json())

    def edit_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings()
            self._save_settings()
            cur = self.tree.currentItem()
            name = cur.data(0, Qt.UserRole) if cur else None
            self._refresh()
            for i in range(self.tree.topLevelItemCount()):
                if self.tree.topLevelItem(i).data(0, Qt.UserRole) == name:
                    self.tree.setCurrentItem(self.tree.topLevelItem(i))

    def export(self):
        if not self.project.cables:
            return
        checked = [self.current_cable.name] if self.current_cable and len(self.project.cables) > 1 else []
        dlg = ExportDialog(self.project, self.settings,
                           self.qs.value("outDir", self.qs.value("lastDir", "", str), str), checked, self)
        if not dlg.exec():
            return
        out_dir = Path(dlg.out.text().strip())
        self.qs.setValue("outDir", str(out_dir))
        self.settings.one_pdf_per_cable = dlg.per_cable.isChecked()
        self.settings.summary_page = dlg.summary.isChecked()
        self._save_settings()
        parts = dlg.parts()
        settings = self.settings

        def job(w: Worker):
            def prog(done, total, label):
                w.progress.emit(done, total, label)
                return not w.cancelled
            return generate_reports(parts, out_dir, settings, prog)

        def done(written, cancelled):
            if cancelled and not written:
                self.statusBar().showMessage("Η δημιουργία PDF ακυρώθηκε.", 6000)
                return
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Information)
            box.setText(f"Δημιουργήθηκαν {len(written)} PDF στον φάκελο:\n{out_dir}"
                        + ("\n\n(Η διαδικασία ακυρώθηκε πριν τελειώσει.)" if cancelled else ""))
            b_open = box.addButton("Άνοιγμα φακέλου", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is b_open:
                open_folder(out_dir)

        run_with_progress(self, "Δημιουργία PDF…", job, done)


def selftest(out_dir: Path) -> int:
    """Έλεγχος του εκτελέσιμου χωρίς παράθυρο: συνθετικά .sor → αντιστοίχιση → PDF."""
    import tempfile

    from .synthetic import make_cable
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "selftest.log"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            make_cable(Path(tmp), "SELFTEST.R01_SCP01", 12, skip={(5, 1550)})
            project = Project()
            project.load(find_sor_files(tmp))
            cable = project.cables["SELFTEST.R01_SCP01"]
            assert len(cable.fibers) == 12 and [f.number for f in cable.incomplete()] == [5]
            written = generate_reports([(cable, cable.sorted_fibers())], out_dir, ReportSettings())
            assert written and written[0].stat().st_size > 10_000
        log.write_text("OK\n", encoding="utf-8")
        return 0
    except Exception as e:  # noqa: BLE001
        log.write_text(f"FAIL {type(e).__name__}: {e}\n", encoding="utf-8")
        return 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest(Path(sys.argv[2] if len(sys.argv) > 2 else "selftest_out")))
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OTDRBatchReport.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OTDRBatchReport")
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    args = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    if args:
        w.load_paths(args)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
