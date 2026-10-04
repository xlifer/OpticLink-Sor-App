"""Κύριο παράθυρο της εφαρμογής (PySide6)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QSpinBox, QSplitter, QStyle, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__
from .matching import Cable, Fiber, Project, _natural_key, find_sor_files
from .pdf_report import TEXT, Units, event_headers, event_rows, fiber_verdict, generate_reports
from .settings import ReportSettings, evaluate, is_dead_fiber, prepare
from .sor import parse_sor

APP_NAME = "OTDR Batch Report"
WL_QCOLORS = {1310: "#1f6feb", 1550: "#d1242f", 1625: "#8250df", 1490: "#1a7f37", 850: "#bf8700"}
# Ίδια χρώματα με το PDF, ως συμπαγές φόντο με άσπρα έντονα γράμματα: διαβάζονται
# το ίδιο καθαρά σε ανοιχτό και σε σκοτεινό θέμα των Windows.
PASS_C, FAIL_C, MISS_C = QColor("#1a7f37"), QColor("#cf222e"), QColor("#9a6700")
VERDICT_TEXT = {True: "PASS", False: "FAIL", "missing": "ΕΛΛΙΠΗΣ", None: "–"}
VERDICT_SORT = {False: 0, "missing": 1, True: 2, None: 3}   # ταξινόμηση: πρώτα τα FAIL


def paint_verdict(item: QTableWidgetItem, verdict) -> None:
    """Χρωματίζει κελί: PASS πράσινο, FAIL κόκκινο, ελλιπής πορτοκαλί (άσπρα έντονα γράμματα)."""
    if verdict is True:
        color = PASS_C
    elif verdict is False:
        color = FAIL_C
    elif verdict == "missing":
        color = MISS_C
    else:
        return
    font = QFont(item.font())
    font.setBold(True)
    item.setBackground(QBrush(color))
    item.setForeground(QBrush(QColor("white")))
    item.setFont(font)


def paint_tree_cell(item: QTreeWidgetItem, col: int, color: QColor) -> None:
    font = QFont(item.font(col))
    font.setBold(True)
    item.setBackground(col, QBrush(color))
    item.setForeground(col, QBrush(QColor("white")))
    item.setFont(col, font)
    item.setTextAlignment(col, Qt.AlignCenter)


class KeepColorDelegate(QStyledItemDelegate):
    """Τα χρωματισμένα κελιά (PASS/FAIL) κρατούν το χρώμα τους και όταν η γραμμή είναι επιλεγμένη."""

    def paint(self, painter, option, index):
        if index.data(Qt.BackgroundRole) is not None and option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        super().paint(painter, option, index)


class SortItem(QTableWidgetItem):
    """Κελί που ταξινομείται με αριθμητικό/φυσικό κλειδί αντί για το κείμενο."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        self._key = key if key is not None else text

    def __lt__(self, other):
        other_key = getattr(other, "_key", other.text())
        try:
            return self._key < other_key
        except TypeError:
            return str(self._key) < str(other_key)


def reveal_file(path: Path):
    """Ανοίγει τον φάκελο του αρχείου με το αρχείο επιλεγμένο (Windows) ή απλώς τον φάκελο."""
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_folder(path.parent)


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

    def _close_dialog(self) -> bool:
        """Κλείνει το παράθυρο προόδου και επιστρέφει αν ο χρήστης πάτησε «Ακύρωση».

        Το QProgressDialog.close() στέλνει κι αυτό σήμα canceled, οπότε η ακύρωση
        διαβάζεται πριν από το κλείσιμο και το σήμα αποσυνδέεται.
        """
        cancelled = self.worker.cancelled
        try:
            self.dlg.canceled.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.dlg.close()
        return cancelled

    @Slot(object)
    def finished(self, result):
        cancelled = self._close_dialog()
        self.thread.quit()
        if not getattr(self.parent(), "_closing", False):   # το παράθυρο κλείνει: χωρίς μηνύματα
            self.on_done(result, cancelled)

    @Slot(str)
    def failed(self, msg):
        self._close_dialog()
        self.thread.quit()
        QMessageBox.critical(self.parent(), APP_NAME, msg)


def run_with_progress(parent, title: str, fn, on_done):
    job = _Job(parent, title, on_done)
    if parent is not None:
        jobs = parent.__dict__.setdefault("_running_jobs", [])
        jobs.append(job)
        job.destroyed.connect(lambda *_: jobs.remove(job) if job in jobs else None)
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
        self.launch_mode = QComboBox()
        self.launch_mode.addItem("Από το αρχείο (όπως το έχει ρυθμίσει το όργανο)", "file")
        self.launch_mode.addItem("Χειροκίνητα", "manual")
        self.launch_mode.addItem("Χωρίς launch cable", "none")
        self.launch_mode.setCurrentIndex(max(0, self.launch_mode.findData(s.launch_mode)))
        self.launch_m = QDoubleSpinBox()
        self.launch_m.setRange(0, 50000); self.launch_m.setDecimals(1); self.launch_m.setSuffix(" m")
        self.launch_m.setValue(s.launch_m)
        self.launch_m.setEnabled(s.launch_mode == "manual")
        self.launch_mode.currentIndexChanged.connect(
            lambda _i: self.launch_m.setEnabled(self.launch_mode.currentData() == "manual"))
        lrow = QHBoxLayout(); lrow.addWidget(self.launch_mode, 1); lrow.addWidget(self.launch_m)
        f1.addRow("Launch cable", lrow)
        self.signatures = QCheckBox("Γραμμές υπογραφών (Συντάχθηκε / Ελέγχθηκε / Εγκρίθηκε)")
        self.signatures.setChecked(s.signatures)
        f1.addRow("", self.signatures)
        self.allow_incomplete = QCheckBox(
            "Να επιτρέπεται PDF για μετρήσεις χωρίς 1310 ΚΑΙ 1550 (με ευθύνη του χρήστη)")
        self.allow_incomplete.setChecked(s.allow_incomplete)
        self.allow_incomplete.setStyleSheet(f"color: {FAIL_C.name()}; font-weight: bold;")
        self.allow_incomplete.toggled.connect(self._confirm_incomplete)
        f1.addRow("", self.allow_incomplete)
        lay.addWidget(g1)

        th = s.thresholds
        g2 = QGroupBox("Κριτήρια Pass / Fail (ξετσέκαρε για καθόλου PASS/FAIL)")
        g2.setCheckable(True)
        g2.setChecked(th.enabled)
        self.g2 = g2
        f2 = QFormLayout(g2)

        def dspin(val, lo, hi, step=0.01, dec=2, suffix=""):
            w = QDoubleSpinBox(); w.setRange(lo, hi); w.setDecimals(dec)
            w.setSingleStep(step); w.setValue(val); w.setSuffix(suffix)
            return w

        def row(text, checked, *spins):
            cb = QCheckBox(text)
            cb.setChecked(checked)
            box = QHBoxLayout()
            for sp in spins:
                box.addWidget(sp)
                sp.setEnabled(checked)
                cb.toggled.connect(sp.setEnabled)
            box.addStretch()
            f2.addRow(cb, box)
            return cb
        self.splice = dspin(th.max_splice_loss, 0, 5, suffix=" dB")
        self.conn = dspin(th.max_connector_loss, 0, 5, suffix=" dB")
        self.refl = dspin(th.max_reflectance, -80, 0, 0.5, 1, " dB")
        self.att1310 = dspin(th.max_attenuation.get("1310", 0.4), 0, 5, 0.01, 3, " dB/km")
        self.att1550 = dspin(th.max_attenuation.get("1550", 0.3), 0, 5, 0.01, 3, " dB/km")
        self.att1625 = dspin(th.max_attenuation.get("1625", 0.35), 0, 5, 0.01, 3, " dB/km")
        for sp, lbl in ((self.att1310, "1310: "), (self.att1550, "1550: "), (self.att1625, "1625: ")):
            sp.setPrefix(lbl)
        self.total = dspin(th.max_total_loss, 0, 60, 0.1, 2, " dB")
        self.cb_splice = row("Μέγ. απώλεια κόλλησης", th.check_splice, self.splice)
        self.cb_conn = row("Μέγ. απώλεια connector", th.check_connector, self.conn)
        self.cb_refl = row("Μέγ. ανάκλαση", th.check_reflectance, self.refl)
        self.cb_att = row("Μέγ. εξασθένηση", th.check_attenuation, self.att1310, self.att1550, self.att1625)
        self.cb_total = row("Μέγ. συνολική απώλεια", th.check_total_loss, self.total)
        note = QLabel("Το PASS/FAIL βγαίνει μόνο από τα κριτήρια με τσεκ.")
        note.setStyleSheet("color:#57606a")
        f2.addRow(note)
        lay.addWidget(g2)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _confirm_incomplete(self, on: bool):
        if not on:
            return
        ans = QMessageBox.warning(
            self, APP_NAME,
            "Μέτρηση χωρίς και τα δύο μήκη κύματος (1310 και 1550) ΔΕΝ είναι έγκυρη.\n\n"
            "Αν το ενεργοποιήσεις, τέτοιες μετρήσεις θα μπαίνουν στο PDF με την ένδειξη ΕΛΛΙΠΗΣ, "
            "με δική σου ευθύνη.\n\nΝα ενεργοποιηθεί;",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            self.allow_incomplete.blockSignals(True)
            self.allow_incomplete.setChecked(False)
            self.allow_incomplete.blockSignals(False)

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
        s.launch_mode = self.launch_mode.currentData()
        s.launch_m = self.launch_m.value()
        s.signatures = self.signatures.isChecked()
        s.allow_incomplete = self.allow_incomplete.isChecked()
        th = s.thresholds
        th.enabled = self.g2.isChecked()
        th.check_splice = self.cb_splice.isChecked()
        th.check_connector = self.cb_conn.isChecked()
        th.check_reflectance = self.cb_refl.isChecked()
        th.check_attenuation = self.cb_att.isChecked()
        th.check_total_loss = self.cb_total.isChecked()
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
        self.only_complete = QCheckBox("Μόνο μετρήσεις που έχουν 1310 και 1550")
        n_inc = sum(len(c.incomplete()) for c in project.cables.values())
        if s.allow_incomplete:
            self.only_complete.setChecked(False)
            note = QLabel(f"Προσοχή: έχεις επιτρέψει PDF για ελλιπείς μετρήσεις ({n_inc}).")
            note.setStyleSheet(f"color: {FAIL_C.name()}; font-weight: bold;")
        else:
            self.only_complete.setChecked(True)
            self.only_complete.setEnabled(False)
            note = QLabel(f"{n_inc} μετρήσεις χωρίς 1310 και 1550 δεν θα μπουν στο PDF "
                          "(αλλάζει από τις Ρυθμίσεις αναφοράς)." if n_inc else
                          "Όλες οι μετρήσεις έχουν 1310 και 1550.")
            if n_inc:
                note.setStyleSheet(f"color: {MISS_C.name()}; font-weight: bold;")
        note.setWordWrap(True)
        form.addRow("", self.only_complete)
        form.addRow("", note)
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
                      and (not self.only_complete.isChecked() or wls <= set(f.measurements))]
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
        self.project = Project(group_level=self._saved_level())
        self.current_cable: Cable | None = None
        self._row_fibers: list[Fiber] = []
        self._removed: list[Path] = []          # για "Επαναφορά αφαιρεμένων"
        self._filter = "all"                    # all | fail | missing | pass
        self._want_fiber: str | None = None     # μέτρηση που ξαναεπιλέγεται μετά από ανανέωση
        self._sort = (0, Qt.AscendingOrder)

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
        tb.addSeparator()
        tb.addWidget(QLabel("  Καλώδιο = "))
        self.group_combo = QComboBox()
        self.group_combo.setMinimumWidth(260)
        self.group_combo.setToolTip(
            "Ποιο μέρος του ονόματος αρχείου (πριν από το 1310/1550) είναι το καλώδιο.\n"
            "Ό,τι περισσεύει εμφανίζεται δίπλα στον αριθμό της ίνας.")
        self.group_combo.activated.connect(self._group_changed)
        tb.addWidget(self.group_combo)

        # Αριστερά: καλώδια
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Καλώδιο", "Μετρήσεις", "Ελλιπείς", "FAIL"])
        self.tree.setRootIsDecorated(False)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._cable_selected)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)

        # Κέντρο: ίνες
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._fiber_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self._keep_color = KeepColorDelegate(self.table)
        self.table.setItemDelegate(self._keep_color)
        self.table.horizontalHeader().sortIndicatorChanged.connect(
            lambda col, order: setattr(self, "_sort", (col, order)))
        self._del_shortcut = QShortcut(QKeySequence(QKeySequence.Delete), self.table)
        self._del_shortcut.activated.connect(self._remove_selected)

        # Γρήγορο φίλτρο πάνω από τον πίνακα
        filter_bar = QWidget()
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(4, 2, 4, 2)
        fl.addWidget(QLabel("Εμφάνιση:"))
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        styles = {"fail": FAIL_C, "missing": MISS_C, "pass": PASS_C}
        for key in ("all", "fail", "missing", "pass"):
            b = QPushButton()
            b.setCheckable(True)
            b.setMinimumWidth(110)
            # Πάντα γεμάτα με το χρώμα τους (καθαρά και σε σκοτεινό θέμα). Το επιλεγμένο έχει χοντρό περίγραμμα.
            c = styles[key].name() if key in styles else "#57606a"
            b.setStyleSheet(
                f"QPushButton {{ background: {c}; color: white; font-weight: bold; border: 2px solid {c};"
                f" border-radius: 4px; padding: 3px 10px; }}"
                f"QPushButton:checked {{ border: 3px solid palette(text); }}")
            self.filter_group.addButton(b)
            self.filter_buttons[key] = b
            b.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            fl.addWidget(b)
        self.filter_buttons["all"].setChecked(True)
        fl.addStretch()
        hint_r = QLabel("Δεξί κλικ σε μέτρηση: αφαίρεση / επαναφορά / προσθήκη")
        hint_r.setStyleSheet("color:#6e7781")
        fl.addWidget(hint_r)
        table_box = QWidget()
        tl = QVBoxLayout(table_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(filter_bar)
        tl.addWidget(self.table)

        # Κάτω: γράφημα + συμβάντα
        pg.setConfigOptions(antialias=True, background="w", foreground="#333")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Απόσταση (km)")
        self.plot.setLabel("left", "dB")
        self.plot.addLegend(offset=(70, 10), labelTextSize="8pt")
        self.events_tabs = QTabWidget()

        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self.plot)
        bottom.addWidget(self.events_tabs)
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)
        self.events_tabs.setMinimumWidth(300)
        bottom.setSizes([850, 550])

        right = QSplitter(Qt.Vertical)
        right.addWidget(table_box)
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

    def closeEvent(self, e):
        """Αν τρέχει φόρτωση ή PDF, τη σταματάμε και περιμένουμε να τελειώσει πριν κλείσουμε.

        Χωρίς αυτό, το νήμα συνέχιζε ενώ το παράθυρο καταστρεφόταν και η εφαρμογή έπεφτε.
        """
        running = [j for j in self.__dict__.get("_running_jobs", []) if j.thread.isRunning()]
        if running:
            self._closing = True
            self.statusBar().showMessage("Σταματάω την εργασία που τρέχει…")
            for j in running:
                j.worker.cancelled = True
            for j in running:
                while j.thread.isRunning():
                    QApplication.processEvents()
                    j.thread.wait(50)
        super().closeEvent(e)

    # ---------- φόρτωση
    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Φάκελος με αρχεία .sor", self.qs.value("lastDir", "", str))
        if d:
            self.qs.setValue("lastDir", d)
            self.load_paths([Path(d)])

    def add_files(self, start_dir: str | None = None):
        fns, _ = QFileDialog.getOpenFileNames(self, "Αρχεία .sor", start_dir or self.qs.value("lastDir", "", str),
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
            def prog(i, n):
                if i % 25 == 0 or i == n:
                    w.progress.emit(i, n, f"{i} / {n}")
                return not w.cancelled
            return project.load(files, prog)

        def done(res, cancelled):
            self._refresh()
            if not res:
                return
            msg = load_message(res)
            if res.failed:
                msg += f"\n\n{len(res.failed)} αρχεία δεν διαβάστηκαν (θα ξαναδοκιμαστούν στην επόμενη φόρτωση):\n" \
                    + "\n".join(f"• {p.name}: {e}" for p, e in res.failed[:15])
                QMessageBox.warning(self, APP_NAME, msg)
            self.statusBar().showMessage(msg.splitlines()[0], 10000)

        run_with_progress(self, "Φόρτωση αρχείων…", job, done)

    def _saved_level(self) -> int | None:
        v = int(self.qs.value("groupLevel", 0) or 0)
        return v or None

    def _fill_group_combo(self):
        c = self.group_combo
        c.blockSignals(True)
        c.clear()
        p = self.project
        examples = p.level_examples()
        auto_name = dict(examples).get(p.level_used, "") if p.group_level is None else ""
        c.addItem(f"Αυτόματα  →  {auto_name}" if auto_name else "Αυτόματα", 0)
        for level, name in examples:
            c.addItem(name, level)
        if p.group_level and p.group_level > len(examples):
            c.addItem(f"{p.group_level} τμήματα", p.group_level)
        idx = c.findData(p.group_level or 0)
        c.setCurrentIndex(max(idx, 0))
        c.blockSignals(False)

    def _group_changed(self, _index):
        level = self.group_combo.currentData() or None
        self.qs.setValue("groupLevel", level or 0)
        self.project.group_level = level
        self.project.regroup()
        self._refresh()

    def clear(self):
        self.project = Project(group_level=self._saved_level())
        self.current_cable = None
        self._removed = []
        self._refresh()

    # ---------- προβολή
    def _refresh(self):
        for c in self.project.cables.values():
            for f in c.fibers.values():
                for m in f.measurements.values():
                    prepare(m.sor, self.settings)
        keep_cable = self.current_cable.name if self.current_cable else None
        if self._want_fiber is None:
            cur = self._current_fiber()
            self._want_fiber = cur.display if cur else None
        self._fill_group_combo()
        self.tree.blockSignals(True)
        self.tree.clear()
        th = self.settings.thresholds
        select = None
        for c in self.project.sorted_cables():
            wls = c.wavelengths
            fails = sum(1 for f in c.fibers.values() if fiber_verdict(f, wls, th) is False)
            missing = len(c.incomplete())
            it = QTreeWidgetItem([c.name, str(len(c.fibers)), str(missing), str(fails)])
            it.setData(0, Qt.UserRole, c.name)
            for col in (1, 2, 3):
                it.setTextAlignment(col, Qt.AlignCenter)
            if missing:
                paint_tree_cell(it, 2, MISS_C)
            if fails:
                paint_tree_cell(it, 3, FAIL_C)
            self.tree.addTopLevelItem(it)
            if c.name == keep_cable:
                select = it
        self.tree.blockSignals(False)
        if select is None and self.tree.topLevelItemCount():
            select = self.tree.topLevelItem(0)
        if select is not None:
            self.tree.setCurrentItem(select)   # → _cable_selected (μία φορά, από το σήμα)
        else:
            self._show_cable(None)
        self._want_fiber = None
        n = self.project.file_count
        msg = f"{len(self.project.cables)} καλώδια · {n} αρχεία" if n else "Άνοιξε έναν φάκελο με μετρήσεις .sor"
        if self._removed:
            msg += f" · {len(self._removed)} αφαιρεμένα (δεξί κλικ → Επαναφορά)"
        self.statusBar().showMessage(msg)
        self.act_pdf.setEnabled(bool(self.project.cables))

    def _cable_selected(self, cur, _prev=None):
        name = cur.data(0, Qt.UserRole) if cur else None
        self._show_cable(self.project.cables.get(name))

    def _show_cable(self, cable: Cable | None):
        self.current_cable = cable
        self._row_fibers = []
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setRowCount(0)
        if not cable:
            self.table.setColumnCount(0)
            self.table.blockSignals(False)
            self._update_filter_counts({})
            self._show_fiber(None)
            return
        wls = cable.wavelengths
        units = Units(max((m.sor.length_km for f in cable.fibers.values()
                           for m in f.measurements.values()), default=0))
        heads = ["Μέτρηση", "Αποτέλεσμα"]
        for w in wls:
            heads += [f"{w} Μήκος ({units.name})", f"{w} Απώλεια (dB)", f"{w} dB/km", f"{w}"]
        heads += ["Αρχεία"]
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        fibers = cable.sorted_fibers()
        self._row_fibers = fibers
        self.table.setRowCount(len(fibers))
        th = self.settings.thresholds
        counts = {"all": len(fibers), "fail": 0, "missing": 0, "pass": 0}
        inf = float("inf")
        for r, f in enumerate(fibers):
            verdict = fiber_verdict(f, wls, th)
            counts["fail"] += verdict is False
            counts["missing"] += verdict == "missing"
            counts["pass"] += verdict is True
            name = SortItem(f.display, (f.number, _natural_key(f.sub), _natural_key(f.display)))
            name.setData(Qt.UserRole, r)
            name.setData(Qt.UserRole + 1, "fail" if verdict is False else "missing" if verdict == "missing"
                         else "pass" if verdict is True else "none")
            self.table.setItem(r, 0, name)
            res = SortItem(VERDICT_TEXT[verdict], VERDICT_SORT[verdict])
            res.setTextAlignment(Qt.AlignCenter)
            paint_verdict(res, verdict)
            self.table.setItem(r, 1, res)
            col = 2
            for w in wls:
                m = f.measurements.get(w)
                if not m:
                    for k in range(4):
                        x = SortItem("λείπει" if k == 3 else "", VERDICT_SORT["missing"] if k == 3 else inf)
                        x.setTextAlignment(Qt.AlignCenter)
                        if k == 3:
                            paint_verdict(x, "missing")
                        self.table.setItem(r, col + k, x)
                else:
                    ok = evaluate(m.sor, th)
                    cells = [
                        (units.fmt(m.sor.length_km), m.sor.length_km),
                        (f"{m.sor.total_loss:.2f}" if m.sor.total_loss is not None else "",
                         m.sor.total_loss if m.sor.total_loss is not None else inf),
                        (f"{m.sor.attenuation:.3f}" if m.sor.attenuation is not None else "",
                         m.sor.attenuation if m.sor.attenuation is not None else inf),
                        (VERDICT_TEXT[ok], VERDICT_SORT[ok]),
                    ]
                    for k, (v, key) in enumerate(cells):
                        x = SortItem(v, key)
                        x.setTextAlignment(Qt.AlignCenter)
                        if k == 3:
                            paint_verdict(x, ok)
                        self.table.setItem(r, col + k, x)
                col += 4
            names = ", ".join(m.path.name for m in f.measurements.values())
            if f.duplicates:
                names += f"   (+{len(f.duplicates)} διπλότυπα)"
            self.table.setItem(r, col, QTableWidgetItem(names))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        sort_col, sort_order = self._sort
        if sort_col >= self.table.columnCount():
            sort_col, sort_order = 0, Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(sort_col, sort_order)
        self.table.setSortingEnabled(True)
        self._update_filter_counts(counts)
        self._apply_filter()
        self.table.blockSignals(False)
        self._select_row_for(self._want_fiber)

    def _select_row_for(self, display: str | None):
        """Επιλέγει τη γραμμή της μέτρησης `display` (ή την πρώτη ορατή)."""
        target = None
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            if target is None:
                target = r
            if display is not None and self.table.item(r, 0).text() == display:
                target = r
                break
        self.table.blockSignals(True)
        if target is None:
            self.table.clearSelection()
        else:
            self.table.setCurrentCell(target, 0)
            self.table.selectRow(target)
            self.table.scrollToItem(self.table.item(target, 0))
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._fiber_selected()

    def _update_filter_counts(self, counts: dict):
        labels = {"all": "Όλες", "fail": "FAIL", "missing": "Ελλιπείς", "pass": "PASS"}
        for key, b in self.filter_buttons.items():
            b.setText(f"{labels[key]} ({counts.get(key, 0)})")

    def _set_filter(self, key: str):
        self._filter = key
        self.filter_buttons[key].setChecked(True)
        self.table.blockSignals(True)
        self._apply_filter()
        self.table.blockSignals(False)
        cur = self._current_fiber()
        self._select_row_for(cur.display if cur else None)

    def _apply_filter(self):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            state = item.data(Qt.UserRole + 1) if item else None
            self.table.setRowHidden(r, self._filter != "all" and state != self._filter)

    def _fiber_at(self, row: int) -> Fiber | None:
        item = self.table.item(row, 0) if row >= 0 else None
        idx = item.data(Qt.UserRole) if item else None
        return self._row_fibers[idx] if idx is not None and idx < len(self._row_fibers) else None

    def _current_fiber(self) -> Fiber | None:
        return self._fiber_at(self.table.currentRow())

    def _selected_fibers(self) -> list[Fiber]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}) \
            if self.table.selectionModel() else []
        return [f for f in (self._fiber_at(r) for r in rows if not self.table.isRowHidden(r)) if f]

    def _fiber_selected(self):
        self._show_fiber(self._current_fiber() if self.current_cable else None)

    # ---------- αφαίρεση / επαναφορά (δεξί κλικ)
    def _remove_paths(self, paths: list[Path], what: str):
        removed = self.project.remove_paths(paths)
        if not removed:
            return
        self._removed.extend(p for p in removed if p not in self._removed)
        self._refresh()
        self.statusBar().showMessage(
            f"Αφαιρέθηκε {what} ({len(removed)} αρχεία). Δεξί κλικ → «Επαναφορά αφαιρεμένων» για να ξαναμπούν.",
            10000)

    def _remove_selected(self):
        fibers = self._selected_fibers()
        if fibers:
            what = f"η μέτρηση {fibers[0].display}" if len(fibers) == 1 else f"{len(fibers)} μετρήσεις"
            self._remove_paths([p for f in fibers for p in f.paths], what)

    def _restore_removed(self):
        paths = [p for p in self._removed if p.exists()]
        missing = len(self._removed) - len(paths)
        self._removed = []
        if missing:
            QMessageBox.warning(self, APP_NAME, f"{missing} αφαιρεμένα αρχεία δεν υπάρχουν πια στον δίσκο.")
        if paths:
            self.load_paths(paths)
        else:
            self._refresh()

    def _table_menu(self, pos):
        self._build_table_menu(pos).exec(self.table.viewport().mapToGlobal(pos))

    def _build_table_menu(self, pos) -> QMenu:
        row = self.table.rowAt(pos.y())
        if row >= 0 and not self.table.item(row, 0).isSelected():
            self.table.selectRow(row)
        fibers = self._selected_fibers()
        menu = QMenu(self)
        if fibers:
            if len(fibers) == 1:
                f = fibers[0]
                menu.addAction(f"Αφαίρεση μέτρησης «{f.display}»", self._remove_selected)
                if len(f.measurements) > 1:
                    for w in f.wavelengths:
                        m = f.measurements[w]
                        menu.addAction(f"Αφαίρεση μόνο του {w} nm ({m.path.name})",
                                       lambda p=m.path, w=w, f=f: self._remove_paths([p], f"το {w} nm της {f.display}"))
            else:
                menu.addAction(f"Αφαίρεση {len(fibers)} μετρήσεων", self._remove_selected)
            menu.addSeparator()
        start = str(fibers[0].paths[0].parent) if fibers and fibers[0].paths else None
        menu.addAction("Προσθήκη αρχείων .sor…", lambda: self.add_files(start))
        if self._removed:
            menu.addAction(f"Επαναφορά αφαιρεμένων ({len(self._removed)})", self._restore_removed)
        if len(fibers) == 1 and fibers[0].paths:
            menu.addSeparator()
            for p in fibers[0].paths:
                menu.addAction(f"Άνοιγμα θέσης: {p.name}", lambda p=p: reveal_file(p))
        return menu

    def _tree_menu(self, pos):
        self._build_tree_menu(pos).exec(self.tree.viewport().mapToGlobal(pos))

    def _build_tree_menu(self, pos) -> QMenu:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        cable = self.project.cables.get(item.data(0, Qt.UserRole)) if item else None
        if cable:
            paths = [p for f in cable.fibers.values() for p in f.paths]
            menu.addAction(f"Αφαίρεση καλωδίου «{cable.name}» ({len(paths)} αρχεία)",
                           lambda: self._remove_paths(paths, f"το καλώδιο {cable.name}"))
            menu.addSeparator()
        menu.addAction("Προσθήκη αρχείων .sor…", self.add_files)
        if self._removed:
            menu.addAction(f"Επαναφορά αφαιρεμένων ({len(self._removed)})", self._restore_removed)
        return menu

    def _show_fiber(self, fiber: Fiber | None):
        self.plot.clear()
        self.plot.setTitle(None)
        self.events_tabs.clear()
        if not fiber:
            return
        th = self.settings.thresholds
        t = TEXT[self.settings.language] if self.settings.language in TEXT else TEXT["el"]
        sors = []
        for w in fiber.wavelengths:
            m = fiber.measurements[w]
            try:
                sors.append(prepare(parse_sor(m.path), self.settings))
            except Exception as e:  # noqa: BLE001
                self.statusBar().showMessage(f"{m.path.name}: {e}", 8000)
        if not sors:
            return
        units = Units(max(s.length_km for s in sors))
        scale = 1000 if units.m else 1
        self.plot.setLabel("bottom", f"Απόσταση ({units.name})")
        launch = max(s.launch_km for s in sors)
        if launch:
            region = pg.LinearRegionItem((-launch * scale, 0), movable=False,
                                         brush=pg.mkBrush(255, 235, 233, 120), pen=pg.mkPen(None))
            self.plot.addItem(region)
        for k, s in enumerate(sors):
            pen = pg.mkPen(WL_QCOLORS.get(s.wavelength, "#000"), width=1.2)
            self.plot.plot(s.distance_axis * scale, s.trace, pen=pen, name=f"{s.wavelength} nm")
            if k == 0:
                for i, e in enumerate(s.events):
                    line = pg.InfiniteLine(e.rel_km * scale, angle=90,
                                           pen=pg.mkPen("#8c959f", width=0.8, style=Qt.DashLine))
                    pg.InfLineLabel(line, str(i), position=0.95, color="#24292f")
                    self.plot.addItem(line)
            tbl = QTableWidget(0, 8)
            tbl.setItemDelegate(KeepColorDelegate(tbl))
            tbl.setHorizontalHeaderLabels(event_headers(t, units))
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.verticalHeader().setVisible(False)
            for r, (cells, ok, is_seg) in enumerate(event_rows(s, th, t, units)):
                tbl.insertRow(r)
                for c, v in enumerate(cells):
                    x = QTableWidgetItem(v)
                    x.setTextAlignment(Qt.AlignCenter)
                    if is_seg:
                        x.setForeground(QBrush(QColor("#6e7781")))
                    if c == 7 and ok is not None:
                        paint_verdict(x, ok)
                    tbl.setItem(r, c, x)
            tbl.resizeColumnsToContents()
            att = f"{s.attenuation:.3f}" if s.attenuation is not None else "–"
            launch_txt = f"Launch {s.launch_km * 1000:.1f} m   ·   " if s.launch_km else ""
            dead = (f'   <b style="color:{FAIL_C.name()}">ΝΕΚΡΗ ΙΝΑ: δεν βρέθηκε ίνα μετά το launch cable</b>'
                    if th.enabled and is_dead_fiber(s) else "")
            info = QLabel(dead + f"   {s.path.name}   ·   {launch_txt}Μήκος {units.fmt(s.length_km)} {units.name}   ·   "
                          f"Απώλεια {s.total_loss or 0:.3f} dB   ·   {att} dB/km   ·   Παλμός {s.pulse_width_ns} ns")
            info.setStyleSheet("padding:4px")
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(info)
            bl.addWidget(tbl)
            self.events_tabs.addTab(box, f"{s.wavelength} nm")
        max_len = max(s.length_km for s in sors)
        if max_len:
            self.plot.setXRange(-launch * 1.04 * scale, max_len * 1.08 * scale)
        title = f"{fiber.display}"
        if sors[0].launch_km:
            title += f'   <span style="color:#cf222e">Launch cable: {sors[0].launch_km * 1000:.1f} m</span>'
        self.plot.setTitle(title, size="9pt")

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

        def done(result, cancelled):
            # Ό,τι άλλαξε στον δίσκο (νέα μέτρηση, αρχείο που χάθηκε) φαίνεται και στην οθόνη
            self.project.load([p for _, fibers in parts for f in fibers for p in f.paths])
            self._refresh()
            if result is None:
                return
            cancelled = cancelled or result.cancelled
            if cancelled and not result:
                self.statusBar().showMessage("Η δημιουργία PDF ακυρώθηκε.", 6000)
                return
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            problems = bool(result.excluded or result.unreadable)
            box.setIcon(QMessageBox.Warning if problems or cancelled else QMessageBox.Information)
            text = f"Δημιουργήθηκαν {len(result)} PDF στον φάκελο:\n{out_dir}"
            if cancelled:
                text += "\n\nΗ δημιουργία ακυρώθηκε πριν τελειώσει."
            box.setText(text)
            details = report_problems(result)
            if details:
                box.setInformativeText(details[:1500] + ("…" if len(details) > 1500 else ""))
                box.setDetailedText(details)
            b_open = box.addButton("Άνοιγμα φακέλου", QMessageBox.AcceptRole) if result else None
            box.addButton(QMessageBox.Close)
            box.exec()
            if b_open is not None and box.clickedButton() is b_open:
                open_folder(out_dir)

        run_with_progress(self, "Δημιουργία PDF…", job, done)


def load_message(res) -> str:
    """Κείμενο αποτελέσματος φόρτωσης, π.χ. «Φορτώθηκαν 120 νέα αρχεία, 2 ενημερώθηκαν.»."""
    if res.cancelled:
        msg = f"Η φόρτωση ακυρώθηκε: φορτώθηκαν {res.loaded + res.updated} από {res.found} αρχεία."
        if res.not_processed:
            msg += f" {res.not_processed} δεν φορτώθηκαν· φόρτωσε ξανά τον φάκελο για να μπουν."
        return msg
    parts = [f"Φορτώθηκαν {res.loaded} νέα αρχεία"]
    if res.updated:
        parts.append(f"{res.updated} ξαναδιαβάστηκαν επειδή άλλαξαν")
    if res.unchanged:
        parts.append(f"{res.unchanged} ήταν ήδη φορτωμένα")
    if res.failed:
        parts.append(f"{len(res.failed)} δεν διαβάστηκαν")
    return ", ".join(parts) + "."


def report_problems(result) -> str:
    """Λίστα με όσα δεν μπήκαν στο PDF και αρχεία που δεν διαβάστηκαν τη στιγμή της εξαγωγής."""
    lines = []
    if result.excluded:
        lines.append(f"{len(result.excluded)} μετρήσεις ΔΕΝ μπήκαν στο PDF (λείπει μήκος κύματος — "
                     "μη έγκυρες χωρίς 1310 και 1550):")
        lines += [f"• {name}: λείπει {', '.join(f'{w} nm' for w in miss)}" for _c, name, miss in result.excluded]
    if result.unreadable:
        if lines:
            lines.append("")
        lines.append(f"{len(result.unreadable)} αρχεία δεν διαβάστηκαν τώρα (μετακινήθηκαν, σβήστηκαν ή χάλασαν):")
        lines += [f"• {p.name}: {e}" for p, e in result.unreadable]
    return "\n".join(lines)


def selftest(out_dir: Path) -> int:
    """Έλεγχος του εκτελέσιμου χωρίς παράθυρο: συνθετικά .sor → αντιστοίχιση → PDF."""
    import tempfile

    from .synthetic import make_cable
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "selftest.log"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            make_cable(Path(tmp), "SELFTEST.R01_SCP01", 12, skip={(5, 1550)}, launch_m=100.0)
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
