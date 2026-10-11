"""Έλεγχος Codex 2.1.0 (7e220ca): εγκυρότητα αποτελεσμάτων και διατήρηση παραδοτέων."""
import hashlib
import shutil
import struct

import pytest

from otdr_report import fiber_info, overrides
from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import existing_pdf_conflicts, generate_reports
from otdr_report.settings import ReportSettings
from otdr_report.sor import SorError, _read_map, _Reader, parse_sor_bytes
from otdr_report.synthetic import build_sor, make_cable

RS = ReportSettings(summary_page=False)


def _parts(p):
    return [(c, c.sorted_fibers()) for c in p.sorted_cables()]


# ---------- #1: το 1550 αντικαταστάθηκε με 1310 μετά τη φόρτωση ----------
def test_wrong_wavelength_after_load_is_not_exported(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for w in (1310, 1550):
        (src / f"C1_{w}_0001.sor").write_bytes(build_sor(
            w, 1.0, [(0.25, 0.1, -48), (0.7, 0.95 if w == 1550 else 0.1, 0)], cable="C1", fiber="0001"))
    p = Project()
    p.load(find_sor_files(src))
    f = p.sorted_cables()[0].sorted_fibers()[0]
    shutil.copyfile(f.measurements[1310].path, f.measurements[1550].path)   # ίδιο όνομα, άλλο λ
    r = generate_reports(_parts(p), tmp_path / "out", RS)
    assert list(r) == []                                                     # όχι PDF με «PASS»
    assert r.excluded == [("C1", "C1_0001", [1550])]
    assert any("1550" in msg and "1310" in msg for _, msg in r.unreadable)


# ---------- #2: χωριστές εξαγωγές δεν σβήνουν προηγούμενο PDF ----------
def test_separate_exports_never_overwrite_existing_pdf(tmp_path):
    make_cable(tmp_path / "in" / "a", "C1", 1, seed=1)
    make_cable(tmp_path / "in" / "b", "c1", 1, seed=7)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    out = tmp_path / "out"
    first = generate_reports([(p.cables["C1"], p.cables["C1"].sorted_fibers())], out, RS)[0]
    before = hashlib.sha256(first.read_bytes()).hexdigest()
    parts = [(p.cables["c1"], p.cables["c1"].sorted_fibers())]
    assert existing_pdf_conflicts(parts, out, RS) == [first]                # η εφαρμογή ρωτά τον χρήστη
    second = generate_reports(parts, out, RS)[0]
    assert second.name.casefold() != first.name.casefold() and "(2)" in second.name
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before          # αμετάβλητο
    assert len(list(out.glob("*.pdf"))) == 2
    # μόνο με ρητή έγκριση αντικατάστασης
    third = generate_reports([(p.cables["C1"], p.cables["C1"].sorted_fibers())], out, RS, overwrite=True)[0]
    assert third.name == first.name and len(list(out.glob("*.pdf"))) == 2


# ---------- #3: αλλοιωμένο πλήθος σημείων στο DataPts ----------
@pytest.mark.parametrize("with_trace", [True, False])
@pytest.mark.parametrize("field_offset", [0, 6])          # συνολικό πλήθος / πλήθος ομάδας
def test_corrupt_datapts_count_is_rejected(with_trace, field_offset):
    d = bytearray(build_sor(1550, 1.0, [(0.25, 0.1, -48)]))
    _, _, blocks = _read_map(_Reader(bytes(d)))
    off, _ = blocks["DataPts"]
    struct.pack_into("<I", d, off + len(b"DataPts\0") + field_offset, 0xFFFFFFFF)
    with pytest.raises(SorError):
        parse_sor_bytes(bytes(d), with_trace=with_trace)


def test_corrupt_datapts_pair_is_not_exported(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for w in (1310, 1550):
        d = bytearray(build_sor(w, 1.0, [(0.25, 0.1, -48)], cable="BAD", fiber="0001"))
        _, _, blocks = _read_map(_Reader(bytes(d)))
        struct.pack_into("<I", d, blocks["DataPts"][0] + len(b"DataPts\0") + 6, 0xFFFFFFFF)
        (src / f"BAD_{w}_0001.sor").write_bytes(d)
    p = Project()
    res = p.load(find_sor_files(src))
    assert len(res.failed) == 2 and not p.cables


def test_valid_trace_unchanged_by_strict_datapts():
    s = parse_sor_bytes(build_sor(1310, 1.0, [(0.25, 0.1, -48)]))
    assert len(s.trace) > 100


# ---------- #4: αλλοιωμένα αρχεία αποθήκευσης δεν εμποδίζουν την εκκίνηση ----------
@pytest.mark.parametrize("content", ["[]", "null", "42", '"x"', "{not json",
                                     '{"abc": 5, "def": {"cable_id": [1], "fiber_id": "001"}}'])
@pytest.mark.parametrize("cls", [fiber_info.InfoStore, overrides.OverrideStore])
def test_bad_store_file_is_recovered(tmp_path, content, cls):
    path = tmp_path / "store.json"
    path.write_text(content, encoding="utf-8")
    store = cls(path)                                   # δεν σκάει
    if content.startswith('{"abc"'):
        if cls is fiber_info.InfoStore:                 # κρατά μόνο τις έγκυρες τιμές
            assert store.get("def") == {"fiber_id": "001"} and store.get("abc") == {}
        assert store.load_error is None
    else:
        assert store.load_error and "αγνοήθηκε" in store.load_error
        backups = list(tmp_path.glob("store.corrupt-*.json"))
        assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == content   # για ανάκτηση
