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
    # PDF στα αγγλικά: το pdftotext των Windows δεν βγάζει ελληνικά κείμενα
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out2",
                           ReportSettings(allow_incomplete=True, language="en"))
    txt = pdf_text(out[0])
    verdict_pass = re.findall(r"\bPASS\b(?!:| criteria)", txt)       # όχι «PASS: 0» / «PASS criteria»
    assert verdict_pass == [] and "INCOMPLETE" in txt and "PASS: 0" in txt


def test_replaced_file_uses_new_measurement(tmp_path):
    make_cable(tmp_path, "C2", 2)
    p = Project()
    p.load(find_sor_files(tmp_path))
    # ξαναμέτρηση της 0002 στα 1550 με κακή κόλληση 0.95 dB
    bad = build_sor(1550, 2.0, [(0.25, 0.3, -48.0), (0.9, 0.95, 0)], seed=7, cable="C2", fiber="0002")
    (tmp_path / "C2_1550_0002.sor").write_bytes(bad)
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out",
                           ReportSettings(language="en"))
    txt = pdf_text(out[0])
    summary = txt.split("\f")[0]
    row = next(line for line in summary.splitlines() if "C2_0002" in line)
    assert row.rstrip().endswith("FAIL")                   # η σύνοψη βλέπει τη νέα μέτρηση
    assert "PASS: 1" in summary and "FAIL: 1" in summary
    page = next(pg for pg in txt.split("\f") if "Measurement: C2_0002" in pg)
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


# ---------- Έλεγχος Codex #2 (βήμα 4): αλλοιωμένο SOR δεν δίνει ποτέ αποτέλεσμα ----------
def _fail_file() -> bytes:
    # κακή κόλληση 0.95 dB (FAIL) ως τελευταίο συμβάν πριν από το τέλος
    return build_sor(1310, 2.0, [(0.25, 0.3, -48.0), (1.5, 0.95, 0)], seed=3)


def _keyevents_count_offset(data: bytes) -> int:
    from otdr_report.sor import _Reader, _read_map
    _v2, _ver, blocks = _read_map(_Reader(data))
    return blocks["KeyEvents"][0] + len(b"KeyEvents\0")


def test_reduced_event_count_is_rejected():
    from otdr_report.sor import SorError
    good = _fail_file()
    assert evaluate(prepare(parse_sor_bytes(good), ReportSettings()), ReportSettings().thresholds) is False
    off = _keyevents_count_offset(good)
    n = int.from_bytes(good[off:off + 2], "little")
    bad = good[:off] + (n - 2).to_bytes(2, "little") + good[off + 2:]   # «χάνονται» το FAIL και το τέλος
    with pytest.raises(SorError):
        parse_sor_bytes(bad)


def test_corrupted_event_code_and_order_are_rejected():
    from otdr_report.sor import SorError
    good = _fail_file()
    i = good.index(b"0F9999LS")
    with pytest.raises(SorError):
        parse_sor_bytes(good[:i] + b"\x00F" + good[i + 2:])                 # σκουπίδι στον κωδικό
    off = _keyevents_count_offset(good) + 2 + 2                              # πρώτο συμβάν: tof
    with pytest.raises(SorError):
        parse_sor_bytes(good[:off] + (10**9).to_bytes(4, "little") + good[off + 4:])  # εκτός σειράς


def test_shifted_block_is_rejected():
    from otdr_report.sor import SorError
    good = _fail_file()
    i = good.index(b"KeyEvents\0", 100)                                       # το ίδιο το τμήμα, όχι ο χάρτης
    with pytest.raises(SorError):
        parse_sor_bytes(good[:i] + b"XeyEvents\0" + good[i + 10:])


def test_corrupted_file_is_reported_on_load(tmp_path):
    good = _fail_file()
    off = _keyevents_count_offset(good)
    bad = good[:off] + (1).to_bytes(2, "little") + good[off + 2:]
    (tmp_path / "K_1310_0001.sor").write_bytes(bad)
    res = Project().load([tmp_path / "K_1310_0001.sor"])
    assert len(res.failed) == 1 and "Κατεστραμμένο" in res.failed[0][1]


# ---------- Έλεγχος Codex #3: δύο 1310 δεν γίνονται ζεύγος ----------
def test_name_wavelength_must_match_measurement(tmp_path):
    make_cable(tmp_path, "P_SCP1", 1)
    shutil.copy(tmp_path / "P_SCP1_1310_0001.sor", tmp_path / "P_SCP1_1550_0001.sor")   # «1550» που είναι 1310
    p = Project()
    res = p.load(find_sor_files(tmp_path))
    assert [x[0].name for x in res.failed] == ["P_SCP1_1550_0001.sor"]
    assert "1550 nm" in res.failed[0][1] and "1310 nm" in res.failed[0][1]
    assert [f.number for f in p.cables["P_SCP1"].incomplete()] == [1]


# ---------- Έλεγχος Codex #4: C1 και c1 δεν σβήνουν το ένα το άλλο ----------
def test_case_only_cable_names_get_distinct_pdfs(tmp_path):
    make_cable(tmp_path / "a", "C1", 1)
    make_cable(tmp_path / "b", "c1", 1, seed=5)
    p = Project()
    p.load(find_sor_files(tmp_path))
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out", ReportSettings())
    names = [x.name for x in out]
    assert len(names) == 2 and len({n.casefold() for n in names}) == 2
    assert all(x.exists() for x in out)


# ---------- Έλεγχος Codex #6: η ακύρωση ισχύει και την ώρα που γράφεται το PDF ----------
def test_cancel_during_rendering(tmp_path):
    make_cable(tmp_path / "in", "R1", 30)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out",
                           ReportSettings(), lambda d, t, label: label != "Γράφεται το PDF…")
    assert out.cancelled and out == []
    assert not list((tmp_path / "out").glob("*.pdf"))                       # ούτε μισό .part.pdf
