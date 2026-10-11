"""Start/End Location, Cable ID, Fiber ID: από το .sor, διόρθωση ατομικά/μαζικά, μόνιμη, στο PDF."""
from pathlib import Path

import pytest

from otdr_report import fiber_info
from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import generate_reports
from otdr_report.settings import ReportSettings, prepare
from otdr_report.sor import parse_sor, parse_sor_bytes
from otdr_report.synthetic import build_sor


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = fiber_info.InfoStore(tmp_path / "fiber_info.json")
    monkeypatch.setattr(fiber_info, "STORE", s)
    return s


def _scp(tmp_path, n=3):
    """Μία SCP με n μετρήσεις 1310+1550, με στοιχεία μέσα στα .sor."""
    d = tmp_path / "in"
    d.mkdir()
    for k in range(1, n + 1):
        for wl in (1310, 1550):
            (d / f"FARM1.R01_SCP31_{wl}_{k:04d}.sor").write_bytes(build_sor(
                wl, 0.5, [(0.2, 0.1, 0)], seed=k * 10 + wl, cable="100", fiber=f"{k:03d}",
                loc_a="FARM1.R01_SCP31", loc_b=f"SDP{k}"))
    p = Project()
    p.load(find_sor_files(d))
    cable = p.sorted_cables()[0]
    for f in cable.fibers.values():
        for m in f.measurements.values():
            prepare(m.sor, ReportSettings())
    return p, cable


def _sors(f):
    return [m.sor for m in f.measurements.values()]


def test_values_come_from_sor_as_text(store, tmp_path):
    s = parse_sor_bytes(build_sor(1310, 0.5, [], cable="105.3", fiber="001", loc_a="X", loc_b="Y"))
    assert (s.location_a, s.location_b, s.cable_id, s.fiber_id) == ("X", "Y", "105.3", "001")
    _, cable = _scp(tmp_path)
    f = cable.sorted_fibers()[1]
    assert fiber_info.info_of(_sors(f)) == {"start_location": "FARM1.R01_SCP31", "end_location": "SDP2",
                                             "cable_id": "100", "fiber_id": "002"}


def test_single_edit_applies_to_both_wavelengths_and_keeps_text(store, tmp_path):
    _, cable = _scp(tmp_path)
    f = cable.sorted_fibers()[0]
    fiber_info.set_info(_sors(f), {"end_location": "FARM1.R01_SDP31_301.1", "cable_id": "301.1", "fiber_id": "001"})
    for s in _sors(f):
        assert (s.location_a, s.location_b, s.cable_id, s.fiber_id) == \
            ("FARM1.R01_SCP31", "FARM1.R01_SDP31_301.1", "301.1", "001")


def test_bulk_edit_only_chosen_fields(store, tmp_path):
    _, cable = _scp(tmp_path)
    fibers = cable.sorted_fibers()
    for f in fibers:                              # μαζικά: μόνο Start Location και Cable ID
        fiber_info.set_info(_sors(f), {"start_location": "FARM1.R01_SCP99", "cable_id": "213.1"})
    for k, f in enumerate(fibers, 1):
        info = fiber_info.info_of(_sors(f))
        assert info["start_location"] == "FARM1.R01_SCP99" and info["cable_id"] == "213.1"
        assert info["fiber_id"] == f"{k:03d}" and info["end_location"] == f"SDP{k}"   # δεν άλλαξαν


def test_corrections_persist_and_never_touch_sor(store, tmp_path):
    p, cable = _scp(tmp_path)
    f = cable.sorted_fibers()[2]
    before = [m.path.read_bytes() for m in f.measurements.values()]
    fiber_info.set_info(_sors(f), {"fiber_id": "999", "cable_id": "301.1"})
    assert [m.path.read_bytes() for m in f.measurements.values()] == before          # .sor ανέγγιχτο
    again = fiber_info.InfoStore(tmp_path / "fiber_info.json")                       # «κλείσιμο - άνοιγμα»
    for m in f.measurements.values():
        s = again.apply(parse_sor(m.path))
        assert (s.fiber_id, s.cable_id) == ("999", "301.1")
    # επαναφορά στις τιμές του .sor
    store.clear([s.digest for s in _sors(f)])
    for s in _sors(f):
        store.apply(s)
        assert (s.fiber_id, s.cable_id) == ("003", "100")


def test_corrections_in_pdf(store, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    _, cable = _scp(tmp_path, 1)
    f = cable.sorted_fibers()[0]
    fiber_info.set_info(_sors(f), {"start_location": "FARM1.R01_SCP31", "end_location": "FARM1.R01_SDP31_301.1",
                                   "cable_id": "301.1", "fiber_id": "001"})
    out = generate_reports([(cable, cable.sorted_fibers())], tmp_path / "out", ReportSettings(summary_page=False))
    txt = " ".join(pg.extract_text() for pg in pypdf.PdfReader(out[0]).pages)
    assert "FARM1.R01_SDP31_301.1" in txt and txt.count("301.1") >= 3 and "001" in txt


# ---------- Έλεγχος Codex 904dd60: μεγάλο όνομα στην επικεφαλίδα συνέχειας ----------
def test_long_name_stays_inside_page_on_continuation(tmp_path):
    import copy
    pdfplumber = pytest.importorskip("pdfplumber")
    from otdr_report.pdf_report import ReportBuilder
    from otdr_report.synthetic import make_cable
    name = "FARM1.R01_" + "LONGNAME" * 7 + "_SCP31"
    make_cable(tmp_path / "in", name, 1)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    c = p.sorted_cables()[0]
    s = ReportSettings(summary_page=False)
    read = {}
    for f in c.sorted_fibers():
        sors = {w: prepare(parse_sor(m.path), s) for w, m in f.measurements.items()}
        for sor in sors.values():
            mid = sor.events[1]
            extra = []
            for k in range(40):
                e = copy.copy(mid)
                e.distance_km = mid.distance_km + 0.0005 * (k + 1)
                extra.append(e)
            sor.events = sor.events[:2] + extra + sor.events[2:]
            sor.apply_launch(sor.user_offset_km)
        read[f.key] = sors
    out = tmp_path / "long.pdf"
    ReportBuilder(s).build(out, [(c, c.sorted_fibers(), read)])
    right_limit = 595.28 - 12 * 72 / 25.4 + 0.5
    with pdfplumber.open(out) as pdf:
        assert len(pdf.pages) > 1
        for page in pdf.pages[1:]:
            words = page.extract_words()
            table_top = min(w["top"] for w in words if w["text"] in ("Events", "#"))
            head = [w for w in words if w["bottom"] <= table_top]
            assert max(w["x1"] for w in head) <= right_limit                    # μέσα στα περιθώρια
            text = "".join(w["text"] for w in head)
            assert f"{name}_0001" in text and "(continued)" in text            # ολόκληρη η ταυτότητα
            cont = next(w for w in head if w["text"] == "(continued)")
            assert all(w["x1"] < cont["x0"] or w["bottom"] < cont["top"] or w["top"] > cont["bottom"]
                       for w in head if w is not cont)                          # χωρίς επικάλυψη
