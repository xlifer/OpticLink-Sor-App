"""Πραγματικές μετρήσεις Grandway FHO5000 (2026)."""
from pathlib import Path

import pytest

from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import generate_reports
from otdr_report.settings import ReportSettings, evaluate
from otdr_report.sor import parse_sor

DATA = Path(__file__).parent / "data"


def _scp51_files():
    return sorted(DATA.glob("scp51_*.sor"))


def test_fho5000_file():
    s = parse_sor(DATA / "scp51_dis_101_1310_0001.sor")
    assert s.wavelength == 1310
    assert s.otdr_model.startswith("FHO5000")
    assert s.pulse_width_ns == 10
    assert len(s.trace) == 3917
    assert [e.type_name for e in s.events] == ["Αρχή", "Ανακλαστικό", "Τέλος"]
    assert s.events[1].distance_km == pytest.approx(0.1008, abs=1e-4)
    assert s.events[1].splice_loss == pytest.approx(0.449)
    assert s.length_km == pytest.approx(0.1489, abs=1e-4)
    assert s.total_loss == pytest.approx(0.464)


def test_auto_grouping_puts_scp51_together():
    p = Project()
    p.load(_scp51_files())
    assert not p.errors
    assert [c.name for c in p.sorted_cables()] == ["scp51"]
    c = p.cables["scp51"]
    assert [(f.display, f.wavelengths) for f in c.sorted_fibers()] == [
        ("0001 · dis_101", [1310, 1550]), ("0100 · dis_207", [1310, 1550])]


def test_manual_grouping_levels():
    p = Project()
    p.load(_scp51_files())
    assert p.level_examples() == [(1, "scp51"), (2, "scp51_dis"), (3, "scp51_dis_101")]
    p.group_level = 1
    p.regroup()
    assert [f.display for f in p.cables["scp51"].sorted_fibers()] == ["0001 · dis_101", "0100 · dis_207"]
    p.group_level = 3
    p.regroup()
    assert sorted(p.cables) == ["scp51_dis_101", "scp51_dis_207"]
    assert p.cables["scp51_dis_101"].fiber(1).wavelengths == [1310, 1550]


def test_default_criteria_only_splice_and_connector():
    th = ReportSettings().thresholds
    assert (th.check_splice, th.check_connector) == (True, True)
    assert not (th.check_reflectance or th.check_attenuation or th.check_total_loss)
    for f in _scp51_files():
        s = parse_sor(f)
        assert evaluate(s, th) is True          # connector ~0.36–0.45 dB ≤ 0.75
    s = parse_sor(DATA / "scp51_dis_101_1550_0001.sor")
    th.check_attenuation = True                 # 1550: 0.358 dB/km > 0.30
    assert evaluate(s, th) is False
    th.check_attenuation = False
    th.max_connector_loss = 0.40                # connector 0.409 dB > 0.40
    assert evaluate(s, th) is False
    th.check_connector = False
    assert evaluate(s, th) is True
    th.check_splice = False
    assert evaluate(s, th) is None              # κανένα ενεργό κριτήριο
    th.check_splice = th.check_connector = True
    th.enabled = False
    assert evaluate(s, th) is None


def test_pdf_from_real_files(tmp_path):
    p = Project()
    p.load(_scp51_files())
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path, ReportSettings())
    assert [x.name for x in out] == ["scp51_0001-0100.pdf"]
    assert out[0].stat().st_size > 20_000


def test_auto_grouping_mixed_folder(tmp_path):
    from otdr_report.synthetic import make_cable
    files = make_cable(tmp_path, "FARM1.R01_SCP31", 6) + _scp51_files()
    p = Project()
    p.load(files)
    assert {c.name: len(c.fibers) for c in p.sorted_cables()} == {"FARM1.R01_SCP31": 6, "scp51": 2}
