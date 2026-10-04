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
    assert [f.display for f in p.cables["FARM1.R01_SCP31"].sorted_fibers()] == [
        "FARM1.R01_SCP31_0001", "FARM1.R01_SCP31_0002", "FARM1.R01_SCP31_0003", "FARM1.R01_SCP31_0004"]


def test_name_with_only_wavelength_pairs():
    from otdr_report.matching import pair_name
    n = parse_name("ROUTE7_1550.sor")
    assert (n.cable, n.fiber, n.wavelength) == ("ROUTE7", 0, 1550)
    assert pair_name("ROUTE7_1550.sor") == "ROUTE7"


def test_synthetic_launch_cable(tmp_path):
    from otdr_report.settings import ReportSettings, prepare
    make_cable(tmp_path, "L_SCP1", 2, launch_m=100.0)
    p = Project()
    p.load(find_sor_files(tmp_path))
    m = p.cables["L_SCP1"].fiber(1).measurements[1310]
    s = prepare(m.sor, ReportSettings())
    assert abs(s.launch_km - 0.1) < 0.002
    assert s.events[0].role == "launch" and s.events[1].role == "start"
    assert s.events[1].rel_km == 0


def test_remove_and_readd(tmp_path):
    make_cable(tmp_path, "R_SCP1", 3)
    p = Project()
    p.load(find_sor_files(tmp_path))
    f2 = p.cables["R_SCP1"].fiber(2)
    removed = p.remove_paths(f2.paths)
    assert len(removed) == 2 and p.file_count == 4
    assert p.cables["R_SCP1"].fiber(2) is None
    p.load(find_sor_files(tmp_path))                 # ξανά ολόκληρος ο φάκελος: μπαίνουν μόνο τα 2
    assert p.file_count == 6 and p.cables["R_SCP1"].fiber(2).wavelengths == [1310, 1550]


def test_remove_one_wavelength_and_duplicate_promotion(tmp_path):
    import shutil
    make_cable(tmp_path / "a", "D_SCP1", 2)
    dup = tmp_path / "b" / "D_SCP1_1550_0001.sor"
    dup.parent.mkdir()
    shutil.copy(tmp_path / "a" / "D_SCP1_1550_0001.sor", dup)
    p = Project()
    p.load(find_sor_files(tmp_path))
    f1 = p.cables["D_SCP1"].fiber(1)
    assert len(f1.duplicates) == 1
    first = f1.measurements[1550].path
    p.remove_paths([first])
    f1 = p.cables["D_SCP1"].fiber(1)
    assert f1.measurements[1550].path != first and not f1.duplicates   # το διπλότυπο πήρε τη θέση
    p.remove_paths([f1.measurements[1550].path])
    assert p.cables["D_SCP1"].fiber(1).wavelengths == [1310]
    assert [f.number for f in p.cables["D_SCP1"].incomplete()] == [1]


def test_remove_unknown_path_is_noop(tmp_path):
    make_cable(tmp_path, "N_SCP1", 1)
    p = Project()
    p.load(find_sor_files(tmp_path))
    assert p.remove_paths([tmp_path / "nope.sor"]) == [] and p.file_count == 2
