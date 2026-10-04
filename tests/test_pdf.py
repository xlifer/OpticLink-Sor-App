from pathlib import Path

from otdr_report.matching import Cable, Fiber, Measurement, Project, find_sor_files
from otdr_report.pdf_report import generate_reports
from otdr_report.settings import ReportSettings, evaluate
from otdr_report.sor import parse_sor
from otdr_report.synthetic import make_cable

SAMPLE = Path(__file__).parent / "data" / "grandway_sample_1550.sor"


def _pages(pdf: Path) -> int:
    return pdf.read_bytes().count(b"/Type /Page\n") or pdf.read_bytes().count(b"/Type /Page ")


def test_one_pdf_per_cable(tmp_path):
    make_cable(tmp_path / "in", "FARM1.R01_SCP31", 20, skip={(3, 1550)})
    make_cable(tmp_path / "in", "FARM1.R01_SCP32", 4, seed=2)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    parts = [(c, [f for f in c.sorted_fibers() if 1 <= f.number <= 10]) for c in p.sorted_cables()]
    calls = []
    out = generate_reports(parts, tmp_path / "out", ReportSettings(),
                           lambda d, t, l: calls.append((d, t)) or True)
    assert [x.name for x in out] == ["FARM1.R01_SCP31_0001-0010.pdf", "FARM1.R01_SCP32_0001-0004.pdf"]
    assert calls[-1] == (14, 14)
    assert all(x.stat().st_size > 20_000 for x in out)


def test_single_pdf_english_separate_charts(tmp_path):
    make_cable(tmp_path / "in", "C1", 3)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    s = ReportSettings(language="en", chart_mode="separate", one_pdf_per_cable=False, summary_page=False)
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path / "out", s)
    assert len(out) == 1 and out[0].exists()


def test_cancel_stops_without_file(tmp_path):
    make_cable(tmp_path / "in", "C1", 5)
    p = Project()
    p.load(find_sor_files(tmp_path / "in"))
    out = generate_reports([(p.cables["C1"], p.cables["C1"].sorted_fibers())], tmp_path / "out",
                           ReportSettings(), lambda d, t, l: d < 2)
    assert out == []
    assert not list((tmp_path / "out").glob("*.pdf"))


def test_real_grandway_file_in_report(tmp_path):
    sor = parse_sor(SAMPLE, with_trace=False)
    cable = Cable("GW")
    cable.fibers[1] = Fiber("GW", 1, "1", {1550: Measurement(SAMPLE, 1550, sor)})
    out = generate_reports([(cable, [cable.fibers[1]])], tmp_path, ReportSettings())
    assert out[0].stat().st_size > 10_000
    assert evaluate(sor, ReportSettings().thresholds) is False  # connector 0.796 dB > 0.75
