"""3.5.0: live μετρήσεις 1625/1650 και splitters."""
import pytest

from otdr_report import overrides
from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import ReportBuilder, TraceChart, criteria_text, generate_reports
from otdr_report.settings import SPLITTER_DEFAULTS, ReportSettings, Thresholds, evaluate, event_ok, prepare
from otdr_report.sor import parse_sor, parse_sor_bytes
from otdr_report.synthetic import build_sor, make_cable


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = overrides.OverrideStore(tmp_path / "ov.json")
    monkeypatch.setattr(overrides, "STORE", s)
    return s


def _live(tmp_path, wl=1625, loss=10.2, name="PON1_SCP1", n=1):
    """Live μέτρηση: ένα συμβάν στα 0.5 km με απώλεια τύπου splitter."""
    d = tmp_path / "in"
    d.mkdir(exist_ok=True)
    for k in range(1, n + 1):
        (d / f"{name}_{wl}_{k:04d}.sor").write_bytes(
            build_sor(wl, 2.0, [(0.5, loss, 0), (1.2, 0.1, 0)], seed=k, cable=name, fiber=f"{k:04d}"))
    p = Project()
    p.load(find_sor_files(d))
    return p


# ---------- πληρότητα: μια live μέτρηση δεν «λείπει» 1310/1550 ----------
@pytest.mark.parametrize("wl", [1625, 1650])
def test_live_only_is_not_incomplete(tmp_path, wl):
    p = _live(tmp_path, wl, n=2)
    c = p.sorted_cables()[0]
    assert c.incomplete() == [] and c.wavelengths == [wl]
    f = c.sorted_fibers()[0]
    assert f.is_live and c.required_for(f) == {wl}


def test_mixed_cable(tmp_path):
    make_cable(tmp_path / "a", "MIX_SCP1", 2, skip={(2, 1550)})
    make_cable(tmp_path / "b", "MIX_SCP1", 3, wavelengths=(1625,))      # 0003 μόνο 1625
    p = Project()
    p.load(find_sor_files(tmp_path))
    c = p.cables["MIX_SCP1"]
    inc = [f.display for f in c.incomplete()]
    assert inc == ["MIX_SCP1_0002"]                                     # λείπει 1550 → ελλιπής
    f3 = next(f for f in c.sorted_fibers() if f.display.endswith("0003"))
    assert f3.is_live and c.required_for(f3) == {1625}


# ---------- splitter: τύπος συμβάντος μόνο σε live, όρια ανά λόγο ----------
def test_splitter_kinds_validated(store):
    assert overrides.valid_kind("splitter:8") and overrides.valid_kind("splitter:128")
    assert not overrides.valid_kind("splitter:3") and not overrides.valid_kind("splitter:256")
    with pytest.raises(ValueError):
        store.set("abc", 0.5, "splitter:3")


def test_splitter_only_on_live(store):
    live = prepare(parse_sor_bytes(build_sor(1625, 2.0, [(0.5, 10.2, 0)])), ReportSettings())
    normal = prepare(parse_sor_bytes(build_sor(1310, 2.0, [(0.5, 10.2, 0)])), ReportSettings())
    ev = next(e for e in live.events if e.role == "event")
    assert overrides.toggle_event([live, normal], ev.distance_km, "splitter:8") == 1
    for s in (live, normal):
        store.apply(s)
    e_live = next(e for e in live.events if e.role == "event")
    e_norm = next(e for e in normal.events if e.role == "event")
    assert e_live.splitter_ratio == 8 and e_live.type_name == "Splitter 1:8"
    assert e_norm.splitter_ratio is None                                  # όχι σε 1310


@pytest.mark.parametrize("ratio,loss,ok", [(8, 10.2, True), (8, 10.6, False), (32, 16.9, True),
                                           (128, 23.9, True), (128, 24.5, False), (2, 4.1, False)])
def test_splitter_thresholds(store, ratio, loss, ok):
    s = prepare(parse_sor_bytes(build_sor(1625, 2.0, [(0.5, loss, 0)])), ReportSettings())
    e = next(e for e in s.events if e.role == "event")
    overrides.toggle_event([s], e.distance_km, f"splitter:{ratio}")
    store.apply(s)
    th = Thresholds()
    assert event_ok(e, th) is ok and evaluate(s, th) is ok
    th.check_splitter = False
    assert event_ok(e, th) is None


def test_splitter_defaults_and_settings_roundtrip():
    assert SPLITTER_DEFAULTS == {"2": 4.0, "4": 7.4, "8": 10.5, "16": 13.8, "32": 17.1, "64": 21.0, "128": 24.0}
    rs = ReportSettings()
    rs.thresholds.max_splitter_loss["8"] = 11.0
    back = ReportSettings.from_json(rs.to_json())
    assert back.thresholds.max_splitter_loss["8"] == 11.0 and back.thresholds.check_splitter
    old = ReportSettings.from_json('{"thresholds": {"check_splice": true}}')     # παλιές ρυθμίσεις
    assert old.thresholds.max_splitter_loss == SPLITTER_DEFAULTS


# ---------- PDF: live χωρίς γράφημα, με splitter ----------
def test_live_pdf_without_chart_and_with_splitter(tmp_path, store):
    pypdf = pytest.importorskip("pypdf")
    p = _live(tmp_path)
    c = p.sorted_cables()[0]
    f = c.sorted_fibers()[0]
    sor = prepare(parse_sor(f.measurements[1625].path), ReportSettings())
    ev = next(e for e in sor.events if e.role == "event")
    overrides.toggle_event([sor], ev.distance_km, "splitter:8")
    s = ReportSettings(summary_page=False)
    read = {f.key: {1625: prepare(parse_sor(f.measurements[1625].path), s)}}
    story = ReportBuilder(s).fiber_story(c, f, read[f.key])
    assert not any(isinstance(x, TraceChart) for x in story)              # κανένα γράφημα X-Y
    out = generate_reports([(c, [f])], tmp_path / "out", s)
    assert len(out) == 1 and out.excluded == []                           # δεν θεωρείται ελλιπής
    txt = " ".join(pg.extract_text() for pg in pypdf.PdfReader(out[0]).pages)
    assert "Splitter 1:8" in txt and "1:8" in txt and "splitter 1:8 ≤ 10.5 dB" in txt
    assert "1310" not in txt and "1550 nm" not in txt


def test_criteria_text_only_used_splitters():
    th = Thresholds()
    assert "splitter" not in criteria_text(th, "en")
    assert criteria_text(th, "en", [32, 8, 8]).endswith("splitter 1:8 ≤ 10.5 dB, splitter 1:32 ≤ 17.1 dB")
