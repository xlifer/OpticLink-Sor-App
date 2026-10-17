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
    _dispose(w, qapp)


def _dispose(w, qapp):
    """Κλείνει και καταστρέφει το παράθυρο, ώστε να μη μαζεύονται παράθυρα από τα προηγούμενα tests."""
    w.close()
    w.setParent(None)
    w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


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


def test_job_runs_without_qt_objects_in_the_worker_thread(qapp):
    """Το «σποραδικό πάγωμα»: κανένα αντικείμενο Qt δεν ζει/καταστρέφεται στο νήμα της εργασίας."""
    import threading
    seen = []
    parent = QtWidgets.QWidget()

    def job(w):
        seen.append((threading.current_thread() is not threading.main_thread(), type(w).__mro__))
        w.progress.emit(1, 2, "x")
        return 1
    j = appmod.run_with_progress(parent, "test", job, lambda res, cancelled: seen.append(res))
    wait(qapp, lambda: len(seen) == 2)
    in_thread, mro = seen[0]
    assert in_thread and appmod.QObject not in mro and seen[1] == 1
    wait(qapp, lambda: not j.thread.isRunning())


def test_finished_job_is_not_reported_as_cancelled(qapp):
    """δ) Το κλείσιμο του παραθύρου προόδου δεν πρέπει να μετράει ως «Ακύρωση»."""
    got = []
    parent = QtWidgets.QWidget()        # όπως στην εφαρμογή: γονέας το κύριο παράθυρο
    j = appmod.run_with_progress(parent, "test", lambda w: 42, lambda res, cancelled: got.append((res, cancelled)))
    wait(qapp, lambda: got)
    assert got == [(42, False)]
    wait(qapp, lambda: not j.thread.isRunning())


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
    wait(qapp, lambda: not j.thread.isRunning())


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
    j = appmod.run_with_progress(win, "test", job, lambda res, cancelled: got.append(res))
    wait(qapp, lambda: started)
    win.close()
    assert not j.thread.isRunning()                    # το κλείσιμο περίμενε το νήμα να σταματήσει
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


def test_linkmap_changes_splice_to_connector(qapp, tmp_path, monkeypatch):
    """Link map: μια «κόλληση» 0.50 dB (FAIL ως κόλληση) γίνεται connector (≤ 0.75 → PASS), στα δύο λ."""
    from otdr_report import overrides
    from otdr_report.synthetic import build_sor
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: default)
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: None)
    monkeypatch.setattr(overrides, "STORE", overrides.OverrideStore(tmp_path / "ov.json"))
    for wl in (1310, 1550):
        (tmp_path / f"L_SCP1_{wl}_0001.sor").write_bytes(
            build_sor(wl, 1.0, [(0.4, 0.50, 0)], seed=wl, launch_m=0))
    w = appmod.MainWindow()
    w.resize(1200, 800)
    w.show()
    w.load_paths([tmp_path])
    wait(qapp, lambda: w.project.file_count == 2)
    rc = col(w, "Αποτέλεσμα")
    assert w.table.item(0, rc).text() == "FAIL"
    splice = next(e for e in w.linkmap.sor.events if e.role == "event")
    assert not splice.reflective
    texts = [a.text() for a in w.linkmap.build_menu(splice).actions()]
    assert texts[:2] == ["Connector (ανακλαστικό)", "Κόλληση (μη ανακλαστικό)"]
    assert texts[-1] == "Ανανέωση μέτρησης"                                  # δεξί κλικ
    assert [a.text() for a in w.linkmap.build_menu(None).actions()] == ["Ανανέωση μέτρησης"]
    w.linkmap.set_measurement(None, None)
    w.linkmap.refreshRequested.emit()
    assert w.linkmap.sor is not None                                         # ξαναπήρε την επιλεγμένη
    w._change_event_type(splice.distance_km, "connector")
    assert w.table.item(0, rc).text() == "PASS"
    assert all(next(e for e in s.events if e.role == "event").reflective for s in w._current_sors)
    # μόνιμο: νέα αποθήκη από το ίδιο αρχείο
    store2 = overrides.OverrideStore(tmp_path / "ov.json")
    s0 = w._current_sors[0]
    assert store2.get(s0.digest, next(e for e in s0.events if e.role == "event").distance_km) == "connector"
    # επαναφορά
    w._change_event_type(splice.distance_km, None)
    assert w.table.item(0, rc).text() == "FAIL"
    _dispose(w, qapp)


def test_export_all_in_one(qapp, tmp_path):
    from otdr_report.matching import Project, find_sor_files
    from otdr_report.settings import ReportSettings
    from otdr_report.synthetic import make_cable
    make_cable(tmp_path, "A_SCP1", 2)
    make_cable(tmp_path, "B_SCP2", 3)
    p = Project()
    p.load(find_sor_files(tmp_path))
    dlg = appmod.ExportDialog(p, ReportSettings(), str(tmp_path), ["A_SCP1"])
    dlg.from_f.setValue(2)
    assert len(dlg.parts()) == 1
    dlg.all_in_one.setChecked(True)
    assert not dlg.per_cable.isChecked() and not dlg.cables.isEnabled()
    assert sum(len(f) for _, f in dlg.parts()) == 5


def test_app_and_window_icon_from_program_icon(qapp, monkeypatch):
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: default)
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: None)
    icon = appmod.app_icon()
    assert sorted(s.width() for s in icon.availableSizes()) == [16, 32, 48, 256]
    w = appmod.MainWindow()
    assert sorted(s.width() for s in w.windowIcon().availableSizes()) == [16, 32, 48, 256]
    _dispose(w, qapp)


def test_info_dialog_single_and_bulk(qapp, tmp_path, monkeypatch):
    from otdr_report import fiber_info
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: default)
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: None)
    monkeypatch.setattr(fiber_info, "STORE", fiber_info.InfoStore(tmp_path / "fi.json"))
    make_cable(tmp_path / "d", "I_SCP1", 3)
    w = appmod.MainWindow()
    w.show()
    w.load_paths([tmp_path / "d"])
    wait(qapp, lambda: w.project.file_count == 6)
    fibers = w.current_cable.sorted_fibers()
    # μία μέτρηση: αλλάζουν μόνο τα πεδία που άλλαξε ο χρήστης
    dlg = appmod.InfoDialog([fibers[0]], w)
    dlg.edits["fiber_id"].setText("001")
    dlg.edits["cable_id"].setText("105.3")
    assert dlg.values() == {"fiber_id": "001", "cable_id": "105.3"}
    w.apply_info([fibers[0]], dlg.values())
    # μαζικά: μόνο τα τσεκαρισμένα πεδία
    dlg = appmod.InfoDialog(fibers, w)
    dlg.edits["start_location"].setText("FARM1.R01_SCP31")
    dlg.edits["start_location"].textEdited.emit("FARM1.R01_SCP31")
    assert dlg.values() == {"start_location": "FARM1.R01_SCP31"}
    w.apply_info(fibers, dlg.values())
    c = col(w, "Fiber ID")
    ids = {w.table.item(r, 0).text(): w.table.item(r, c).text() for r in range(w.table.rowCount())}
    assert ids["I_SCP1_0001"] == "001" and ids["I_SCP1_0002"] == "0002"       # τα υπόλοιπα κράτησαν το δικό τους
    s0 = col(w, "Start Location")
    assert {w.table.item(r, s0).text() for r in range(w.table.rowCount())} == {"FARM1.R01_SCP31"}
    menu = [a.text() for a in w._build_table_menu(w.table.visualItemRect(w.table.item(0, 0)).center()).actions()]
    assert any(t.startswith("Στοιχεία μέτρησης") for t in menu)
    _dispose(w, qapp)


def test_cables_panel_resizes_independently_and_layout_persists(qapp, monkeypatch):
    store = {}
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: store.get(key, default))
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: store.__setitem__(key, value))
    w = appmod.MainWindow()
    w.resize(1400, 860)
    w.show()
    qapp.processEvents()
    events_before = w.bottom_split.sizes()
    total = sum(w.top_split.sizes())
    # σύρσιμο του διαχωριστικού των καλωδίων τέρμα δεξιά: κλείνει εντελώς
    w.top_split.moveSplitter(total, 1)
    qapp.processEvents()
    assert w.top_split.sizes()[1] == 0 and not w.cables_visible()
    assert w.bottom_split.sizes() == events_before                          # οι μετρήσεις δεν επηρεάστηκαν
    assert w.events_tabs.width() >= w.events_tabs.minimumSizeHint().width()
    assert not w.act_cables.isChecked()
    # αποθήκευση / επαναφορά μετά το κλείσιμο
    w._save_layout()
    w2 = appmod.MainWindow()
    w2.resize(1400, 860)
    w2.show()
    qapp.processEvents()
    assert w2.top_split.sizes()[1] == 0 and w2.bottom_split.sizes()[1] > 0
    # εύκολο άνοιγμα ξανά από το κουμπί «Καλώδια»
    w2.act_cables.trigger()
    qapp.processEvents()
    assert w2.cables_visible() and w2.top_split.sizes()[1] >= 200 and w2.act_cables.isChecked()
    # και μικρό, ανεξάρτητο πλάτος
    w2.top_split.setSizes([sum(w2.top_split.sizes()) - 60, 60])
    assert w2.top_split.sizes()[1] == 60 and w2.bottom_split.sizes()[1] > 60
    _dispose(w, qapp)
    _dispose(w2, qapp)


def test_two_workspaces_live_splitter_and_event_selection(qapp, tmp_path, monkeypatch):
    """Δύο καρτέλες: 1310/1550 και live 1625/1650· splitter μόνο στη live· επιλογή συμβάντος παντού."""
    from otdr_report import overrides
    from otdr_report.synthetic import build_sor
    monkeypatch.setattr(appmod.QSettings, "value", lambda self, key, default=None, type=None: default)
    monkeypatch.setattr(appmod.QSettings, "setValue", lambda self, key, value: None)
    monkeypatch.setattr(overrides, "STORE", overrides.OverrideStore(tmp_path / "ov.json"))
    (tmp_path / "PON_SCP1_1625_0001.sor").write_bytes(build_sor(1625, 2.0, [(0.5, 10.2, 0), (1.2, 0.1, 0)]))
    (tmp_path / "N_SCP1_1310_0001.sor").write_bytes(build_sor(1310, 2.0, [(0.5, 0.1, 0), (1.0, 0.1, 0)]))
    (tmp_path / "N_SCP1_1550_0001.sor").write_bytes(build_sor(1550, 2.0, [(0.5, 0.1, 0), (1.0, 0.1, 0)]))
    app = appmod.AppWindow()
    app.show()
    app.tabs.setCurrentWidget(app.standard)
    app.load_paths([tmp_path])                  # ένας φάκελος με τα δύο είδη
    wait(qapp, lambda: app.standard.project.file_count == 2 and app.live.project.file_count == 1)
    assert list(app.standard.project.cables) == ["N_SCP1"] and list(app.live.project.cables) == ["PON_SCP1"]
    assert not app.live.plot.isVisible() and app.standard.plot.isVisible()     # live: χωρίς γράφημα

    # live: όχι «ελλιπής», splitter στο μενού
    w = app.live
    app.tabs.setCurrentWidget(w)
    live = w.project.cables["PON_SCP1"]
    assert live.incomplete() == []
    w._show_cable(live)
    w.table.selectRow(0)
    qapp.processEvents()
    ev = next(e for e in w.linkmap.sor.events if e.role == "event")
    sub = next(a.menu() for a in w.linkmap.build_menu(ev).actions() if a.text() == "Splitter")
    assert [a.text() for a in sub.actions()] == [f"Splitter 1:{n}" for n in (2, 4, 8, 16, 32, 64, 128)]
    w._change_event_type(ev.distance_km, "splitter:8")
    qapp.processEvents()
    ev = next(e for e in w.linkmap.sor.events if e.role == "event")
    assert ev.splitter_ratio == 8
    assert w.table.item(0, col(w, "Αποτέλεσμα")).text() == "PASS"           # 10.2 ≤ 10.5 dB (1:8)

    # 1310/1550: χωρίς splitter, και επιλογή συμβάντος Link map ↔ πίνακας (και στις δύο καρτέλες)
    for ws in (app.standard, app.live):
        app.tabs.setCurrentWidget(ws)
        ws._show_cable(ws.project.sorted_cables()[0])
        ws.table.selectRow(0)
        qapp.processEvents()
        e = next(x for x in ws.linkmap.sor.events if x.role == "event")
        if ws is app.standard:
            assert "Splitter" not in [a.text() for a in ws.linkmap.build_menu(e).actions()]
        idx = ws.linkmap.sor.events.index(e)
        ws.linkmap.eventSelected.emit(idx)                                  # κλικ στο Link map
        tbl = ws._current_events_table()
        assert {i.row() for i in tbl.selectedItems()} == {2 * idx} and ws.linkmap.selected == idx
        tbl.selectRow(0)                                                    # κλικ στον πίνακα
        qapp.processEvents()
        assert ws.linkmap.selected == 0
    app.close()
    for ws in app.workspaces.values():
        _dispose(ws, qapp)
    _dispose(app, qapp)


def test_settings_dialog_splitter_limits(qapp):
    from otdr_report.settings import ReportSettings
    s = ReportSettings()
    dlg = appmod.SettingsDialog(s)
    dlg.split[8].setValue(11.0)
    dlg.cb_split.setChecked(False)
    out = dlg.result_settings()
    assert out.thresholds.max_splitter_loss["8"] == 11.0 and not out.thresholds.check_splitter
    import shiboken6
    shiboken6.delete(dlg)                    # χωρίς γονέα: να μην καταστραφεί μετά το QApplication


def test_theme_light_dark_auto(qapp):
    from PySide6.QtGui import QPalette
    from otdr_report import theme
    try:
        assert theme.apply_theme(qapp, "dark") == "dark"
        assert qapp.palette().color(QPalette.Window).lightness() < 80                # σκούρο
        assert theme.apply_theme(qapp, "light") == "light"
        assert qapp.palette().color(QPalette.Window).lightness() > 200               # λευκό
        assert qapp.palette().color(QPalette.Text).lightness() < 80                  # σκούρα γράμματα
        assert theme.apply_theme(qapp, "nonsense") == theme.DEFAULT_THEME == "light"
        assert theme.apply_theme(qapp, "auto") == "auto"
        from otdr_report.settings import ReportSettings
        dlg = appmod.SettingsDialog(ReportSettings())
        assert [dlg.theme.itemData(i) for i in range(dlg.theme.count())] == ["light", "dark", "auto"]
        import shiboken6
        shiboken6.delete(dlg)
    finally:
        theme.apply_theme(qapp, "light")
