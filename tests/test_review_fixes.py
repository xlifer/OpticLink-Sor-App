"""Διορθώσεις από τον έλεγχο του Codex (βήμα 3)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import fiber_verdict, generate_reports
from otdr_report.settings import ReportSettings, evaluate, is_dead_fiber, prepare
from otdr_report.sor import parse_sor_bytes
from otdr_report.synthetic import build_sor, make_cable

DATA = Path(__file__).parent / "data"


def pdf_text(path: Path) -> str:
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext δεν υπάρχει")
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout


# ---------- α) το PDF κρίνει ό,τι διαβάζει τώρα από τον δίσκο ----------
def test_moved_files_never_pass(tmp_path):
    src = tmp_path / "site"
    make_cable(src, "C1", 3)
    p = Project()
    p.load(find_sor_files(src))
    shutil.move(str(src), str(tmp_path / "moved"))
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out", ReportSettings())
    assert out == []                                       # τίποτα δεν διαβάζεται → καμία έγκυρη μέτρηση
    assert len(out.unreadable) == 6 and len(out.excluded) == 3
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out2",
                           ReportSettings(allow_incomplete=True))
    txt = pdf_text(out[0])
    verdict_pass = re.findall(r"(?<!Κριτήρια )\bPASS\b(?!:)", txt)   # όχι «PASS: 0» / «Κριτήρια PASS»
    assert verdict_pass == [] and "ΕΛΛΙΠΗΣ" in txt and "PASS: 0" in txt


def test_replaced_file_uses_new_measurement(tmp_path):
    make_cable(tmp_path, "C2", 2)
    p = Project()
    p.load(find_sor_files(tmp_path))
    # ξαναμέτρηση της 0002 στα 1550 με κακή κόλληση 0.95 dB
    bad = build_sor(1550, 2.0, [(0.25, 0.3, -48.0), (0.9, 0.95, 0)], seed=7, cable="C2", fiber="0002")
    (tmp_path / "C2_1550_0002.sor").write_bytes(bad)
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out", ReportSettings())
    txt = pdf_text(out[0])
    summary = txt.split("\f")[0]
    row = next(line for line in summary.splitlines() if "C2_0002" in line)
    assert row.rstrip().endswith("FAIL")                   # η σύνοψη βλέπει τη νέα μέτρηση
    assert "PASS: 1" in summary and "FAIL: 1" in summary
    page = next(pg for pg in txt.split("\f") if "Μέτρηση: C2_0002" in pg)
    assert "FAIL" in page.splitlines()[0] or "FAIL" in page[:400]
    # και η επόμενη φόρτωση ξαναδιαβάζει το αρχείο που άλλαξε
    res = p.load(find_sor_files(tmp_path))
    assert res.updated == 1 and res.unchanged == 3
    f2 = p.cables["C2"].fiber(2)
    assert fiber_verdict(f2, p.cables["C2"].wavelengths, ReportSettings().thresholds) is False


# ---------- β) ακύρωση / σφάλμα ανάγνωσης: η επόμενη φόρτωση τα φέρνει ----------
def test_cancelled_load_can_be_completed(tmp_path):
    make_cable(tmp_path, "C3", 20)
    files = find_sor_files(tmp_path)
    p = Project()
    res = p.load(files, progress=lambda i, n: i < 5, workers=1)
    assert res.cancelled and p.file_count == 5 and res.not_processed == 35
    res = p.load(files)
    assert p.file_count == 40 and res.loaded == 35 and res.unchanged == 5


def test_failed_file_is_retried(tmp_path):
    make_cable(tmp_path, "C4", 2)
    f = tmp_path / "C4_1550_0002.sor"
    good = f.read_bytes()
    f.write_bytes(good[:100])                               # μισοαντιγραμμένο
    p = Project()
    res = p.load(find_sor_files(tmp_path))
    assert len(res.failed) == 1 and p.file_count == 3
    f.write_bytes(good)
    res = p.load(find_sor_files(tmp_path))
    assert res.loaded == 1 and p.file_count == 4


def test_file_that_breaks_after_loading_is_dropped(tmp_path):
    make_cable(tmp_path, "C5", 1)
    p = Project()
    p.load(find_sor_files(tmp_path))
    (tmp_path / "C5_1310_0001.sor").write_bytes(b"broken")
    res = p.load(find_sor_files(tmp_path))
    assert len(res.failed) == 1 and p.file_count == 1
    assert p.cables["C5"].fiber(1).wavelengths == [1550]


# ---------- γ) νεκρή ίνα → FAIL ----------
def test_dead_fiber_fails():
    rs = ReportSettings()
    dead = prepare(parse_sor_bytes(build_sor(1310, 0.1008, [], launch_m=100.8)), rs)
    assert is_dead_fiber(dead) and dead.length_km < 0.002
    assert evaluate(dead, rs.thresholds) is False
    rs.thresholds.check_splice = rs.thresholds.check_connector = False   # ακόμη και χωρίς κριτήρια
    assert evaluate(dead, rs.thresholds) is False
    rs.thresholds.enabled = False                                        # γενικός διακόπτης κλειστός
    assert evaluate(dead, rs.thresholds) is None
    ok = prepare(parse_sor_bytes(build_sor(1310, 0.5, [], launch_m=100.8)), ReportSettings())
    assert not is_dead_fiber(ok) and evaluate(ok, ReportSettings().thresholds) is True


# ---------- 1310 + 1550 υποχρεωτικά ----------
def test_cable_missing_all_1550_is_incomplete(tmp_path):
    make_cable(tmp_path, "X_SCP1", 3)
    make_cable(tmp_path, "X_SCP2", 3, wavelengths=(1310,), seed=2)
    p = Project()
    p.load(find_sor_files(tmp_path))
    c2 = p.cables["X_SCP2"]
    assert c2.wavelengths == [1310, 1550]
    assert [f.number for f in c2.incomplete()] == [1, 2, 3]
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out", ReportSettings())
    assert [x.name for x in out] == ["X_SCP1_0001-0003.pdf"]
    assert [e[1] for e in out.excluded] == ["X_SCP2_0001", "X_SCP2_0002", "X_SCP2_0003"]


def test_real_files_need_both_wavelengths():
    p = Project()
    p.load([DATA / "scp51_dis_101_1310_0001.sor", DATA / "scp51_dis_207_1310_0100.sor",
            DATA / "scp51_dis_207_1550_0100.sor"])
    c = p.cables["scp51"]
    assert [f.display for f in c.incomplete()] == ["scp51_dis_101_0001"]
