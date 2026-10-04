"""Δοκιμές του παραθύρου χωρίς οθόνη (QT_QPA_PLATFORM=offscreen)."""
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Σε Linux χωρίς libEGL το PySide6 δίνει ImportError (όχι ModuleNotFoundError): τα tests παραλείπονται
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from otdr_report import app as appmod  # noqa: E402
from otdr_report.synthetic import make_cable  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: default)
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: None)
    # 40 ίνες: η 37 είναι FAIL (κακή κόλληση), η 12 δεν έχει 1550
    make_cable(tmp_path / "data", "W_SCP1", 40, skip={(12, 1550)})
    w = appmod.MainWindow()
    w.resize(1400, 800)
    w.show()
    w.load_paths([tmp_path / "data"])
    wait(qapp, lambda: w.project.file_count == 79)
    yield w
    w.close()


def wait(app, cond, timeout=30):
    end = time.time() + timeout
    while not cond():
        if time.time() > end:
            raise AssertionError("timeout")
        app.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        app.processEvents()


def col(w, title):
    for c in range(w.table.columnCount()):
        if w.table.horizontalHeaderItem(c).text() == title:
            return c
    raise KeyError(title)


def row_of(w, display):
    for r in range(w.table.rowCount()):
        if w.table.item(r, 0).text() == display:
            return r
    return None


def test_result_column_and_strong_colours(win):
    rc = col(win, "Αποτέλεσμα")
    assert rc == 1
    fail = win.table.item(row_of(win, "W_SCP1_0037"), rc)
    ok = win.table.item(row_of(win, "W_SCP1_0001"), rc)
    miss = win.table.item(row_of(win, "W_SCP1_0012"), rc)
    assert (fail.text(), ok.text(), miss.text()) == ("FAIL", "PASS", "ΕΛΛΙΠΗΣ")
    assert fail.background().color() == appmod.FAIL_C and fail.foreground().color().name() == "#ffffff"
    assert ok.background().color() == appmod.PASS_C and ok.font().bold()
    assert miss.background().color() == appmod.MISS_C
    item = win.tree.topLevelItem(0)
    assert item.text(3) == "1" and item.background(3).color() == appmod.FAIL_C
    assert item.text(2) == "1" and item.background(2).color() == appmod.MISS_C


def test_filter_buttons(win):
    b = win.filter_buttons
    assert [b[k].text() for k in ("all", "fail", "missing", "pass")] == \
        ["Όλες (40)", "FAIL (1)", "Ελλιπείς (1)", "PASS (38)"]
    win._set_filter("fail")
    visible = [win.table.item(r, 0).text() for r in range(win.table.rowCount()) if not win.table.isRowHidden(r)]
    assert visible == ["W_SCP1_0037"]
    assert win._current_fiber().display == "W_SCP1_0037"       # επιλέγεται αυτόματα η ορατή
    win._set_filter("all")
    assert sum(not win.table.isRowHidden(r) for r in range(win.table.rowCount())) == 40


def test_sort_by_result_keeps_row_mapping(win):
    win.table.sortItems(1, Qt.AscendingOrder)
    assert win.table.item(0, 1).text() == "FAIL" and win.table.item(1, 1).text() == "ΕΛΛΙΠΗΣ"
    for r in (0, 1, 5, 39):
        win.table.setCurrentCell(r, 0)
        assert win._current_fiber().display == win.table.item(r, 0).text()
    # αριθμητική ταξινόμηση (όχι αλφαβητική) στη στήλη απώλειας
    c = col(win, "1310 Απώλεια (dB)")
    win.table.sortItems(c, Qt.AscendingOrder)
    vals = [float(win.table.item(r, c).text()) for r in range(win.table.rowCount())]
    assert vals == sorted(vals)


def test_remove_and_restore(win, qapp):
    win.table.setCurrentCell(row_of(win, "W_SCP1_0005"), 0)
    win.table.selectRow(row_of(win, "W_SCP1_0005"))
    win._remove_selected()
    assert row_of(win, "W_SCP1_0005") is None and win.project.file_count == 77
    assert len(win._removed) == 2
    win._restore_removed()
    wait(qapp, lambda: win.project.file_count == 79)
    assert row_of(win, "W_SCP1_0005") is not None and win._removed == []


def test_remove_single_wavelength_marks_incomplete(win):
    f = win.project.cables["W_SCP1"].fiber(3)
    win._remove_paths([f.measurements[1550].path], "test")
    r = row_of(win, "W_SCP1_0003")
    assert win.table.item(r, 1).text() == "ΕΛΛΙΠΗΣ"
    assert win.filter_buttons["missing"].text() == "Ελλιπείς (2)"


def test_context_menu_entries(win):
    r = row_of(win, "W_SCP1_0002")
    win.table.selectRow(r)
    pos = win.table.visualItemRect(win.table.item(r, 0)).center()
    texts = [a.text() for a in win._build_table_menu(pos).actions()]
    assert "Αφαίρεση μέτρησης «W_SCP1_0002»" in texts
    assert any(t.startswith("Αφαίρεση μόνο του 1310 nm") for t in texts)
    assert "Προσθήκη αρχείων .sor…" in texts
    assert not any(t.startswith("Επαναφορά") for t in texts)        # τίποτα αφαιρεμένο ακόμα
    remove = next(a for a in win._build_table_menu(pos).actions() if a.text().startswith("Αφαίρεση μέτρησης"))
    remove.trigger()
    assert row_of(win, "W_SCP1_0002") is None
    texts = [a.text() for a in win._build_table_menu(pos).actions()]
    assert "Επαναφορά αφαιρεμένων (2)" in texts
    tree_pos = win.tree.visualItemRect(win.tree.topLevelItem(0)).center()
    assert win._build_tree_menu(tree_pos).actions()[0].text() == "Αφαίρεση καλωδίου «W_SCP1» (77 αρχεία)"


def test_remove_whole_cable_from_tree(win):
    paths = [p for f in win.project.cables["W_SCP1"].fibers.values() for p in f.paths]
    win._remove_paths(paths, "test")
    assert win.project.file_count == 0 and win.tree.topLevelItemCount() == 0
    assert len(win._removed) == 79


def test_finished_job_is_not_reported_as_cancelled(qapp):
    """δ) Το κλείσιμο του παραθύρου προόδου δεν πρέπει να μετράει ως «Ακύρωση»."""
    got = []
    parent = QtWidgets.QWidget()        # όπως στην εφαρμογή: γονέας το κύριο παράθυρο
    appmod.run_with_progress(parent, "test", lambda w: 42, lambda res, cancelled: got.append((res, cancelled)))
    wait(qapp, lambda: got)
    assert got == [(42, False)]
    wait(qapp, lambda: all(not t.isRunning() for t in parent.findChildren(appmod.QThread)))


def test_cancel_button_is_reported(qapp):
    got = []

    def job(w):
        deadline = time.time() + 20          # ποτέ ατέρμονος βρόχος, ακόμη κι αν χαθεί το σήμα
        while not w.cancelled and time.time() < deadline:
            time.sleep(0.01)
        return "stopped" if w.cancelled else "timeout"
    parent = QtWidgets.QWidget()
    j = appmod.run_with_progress(parent, "test", job, lambda res, cancelled: got.append((res, cancelled)))
    wait(qapp, lambda: j.dlg.isVisible())
    j.dlg.canceled.emit()                # όπως το κλικ στο κουμπί «Ακύρωση»
    wait(qapp, lambda: got)
    assert got == [("stopped", True)]
    wait(qapp, lambda: all(not t.isRunning() for t in parent.findChildren(appmod.QThread)))


def test_load_message_texts():
    from otdr_report.matching import LoadResult
    assert appmod.load_message(LoadResult(found=40, loaded=35, unchanged=5)) == \
        "Φορτώθηκαν 35 νέα αρχεία, 5 ήταν ήδη φορτωμένα."
    msg = appmod.load_message(LoadResult(found=40, loaded=5, cancelled=True, not_processed=35))
    assert msg.startswith("Η φόρτωση ακυρώθηκε: φορτώθηκαν 5 από 40 αρχεία.")


def test_close_while_job_runs_waits_for_it(win, qapp):
    """Codex #1: κλείσιμο ενώ τρέχει εργασία → σταματά το νήμα, χωρίς crash και χωρίς μηνύματα."""
    got, started = [], []

    def job(w):
        started.append(1)
        deadline = time.time() + 20
        while not w.cancelled and time.time() < deadline:
            time.sleep(0.01)
        return "stopped"
    appmod.run_with_progress(win, "test", job, lambda res, cancelled: got.append(res))
    wait(qapp, lambda: started)
    win.close()
    assert all(not t.isRunning() for t in win.findChildren(appmod.QThread))
    for _ in range(20):
        qapp.processEvents()
    assert got == []                                   # on_done δεν καλείται σε παράθυρο που κλείνει


def test_switching_fibers_does_not_accumulate_tables(win, qapp):
    """Codex #5: οι πίνακες συμβάντων των προηγούμενων μετρήσεων διαγράφονται."""
    from PySide6.QtWidgets import QTableWidget
    for r in range(15):
        win.table.setCurrentCell(r, 0)
        qapp.processEvents()
    for _ in range(5):
        qapp.processEvents()
    assert len(win.events_tabs.findChildren(QTableWidget)) == 2              # μόνο 1310 + 1550 της τρέχουσας
