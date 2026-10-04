from otdr_report.matching import Project, find_sor_files, parse_name
from otdr_report.synthetic import make_cable


def test_parse_name_wavelength_then_fiber():
    n = parse_name("FARM1.R01_SCP31_1310_0117.sor")
    assert (n.cable, n.fiber, n.fiber_label, n.wavelength) == ("FARM1.R01_SCP31", 117, "0117", 1310)


def test_parse_name_fiber_then_wavelength():
    n = parse_name("FARM1.R01_SCP31_0117_1550.SOR")
    assert (n.cable, n.fiber, n.wavelength) == ("FARM1.R01_SCP31", 117, 1550)


def test_parse_name_without_wavelength():
    n = parse_name("FARM1.R01_SCP31_0001.sor")
    assert (n.cable, n.fiber, n.wavelength) == ("FARM1.R01_SCP31", 1, None)


def test_pairing_and_missing(tmp_path):
    make_cable(tmp_path / "a", "FARM1.R01_SCP31", 300, skip={(12, 1550), (250, 1310)})
    make_cable(tmp_path / "b", "FARM1.R01_SCP32", 5, seed=2)
    p = Project()
    p.load(find_sor_files(tmp_path))
    assert not p.errors
    assert [c.name for c in p.sorted_cables()] == ["FARM1.R01_SCP31", "FARM1.R01_SCP32"]
    c = p.cables["FARM1.R01_SCP31"]
    assert len(c.fibers) == 300
    assert c.wavelengths == [1310, 1550]
    f = c.fiber(117)
    assert {w: m.path.name for w, m in f.measurements.items()} == {
        1310: "FARM1.R01_SCP31_1310_0117.sor", 1550: "FARM1.R01_SCP31_1550_0117.sor"}
    assert [f.number for f in c.incomplete()] == [12, 250]


def test_loading_same_folder_twice_is_ignored(tmp_path):
    make_cable(tmp_path, "X_SCP1", 3)
    p = Project()
    p.load(find_sor_files(tmp_path))
    p.load(find_sor_files(tmp_path))
    assert p.file_count == 6


def test_auto_grouping_keeps_single_cable_name(tmp_path):
    make_cable(tmp_path, "FARM1.R01_SCP31", 4)
    p = Project()
    p.load(find_sor_files(tmp_path))
    assert list(p.cables) == ["FARM1.R01_SCP31"]
    assert [f.display for f in p.cables["FARM1.R01_SCP31"].sorted_fibers()] == ["0001", "0002", "0003", "0004"]
