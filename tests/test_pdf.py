import pytest
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
    assert calls[-1] == (28, 28)                      # ανάγνωση + σελίδα για κάθε μέτρηση
    # η 0003 δεν έχει 1550: μη έγκυρη, δεν μπαίνει στο PDF
    assert out.excluded == [("FARM1.R01_SCP31", "FARM1.R01_SCP31_0003", [1550])]
    assert not out.unreadable and not out.cancelled
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
    cable.fibers[(1, "")] = Fiber("GW", 1, "1", measurements={1550: Measurement(SAMPLE, 1550, sor)})
    # μόνο 1550: μη έγκυρη μέτρηση → μπαίνει στο PDF μόνο αν το επιτρέψει ο χρήστης
    assert generate_reports([(cable, [cable.fiber(1)])], tmp_path / "a", ReportSettings()) == []
    out = generate_reports([(cable, [cable.fiber(1)])], tmp_path / "b", ReportSettings(allow_incomplete=True))
    assert out[0].stat().st_size > 10_000
    th = ReportSettings().thresholds
    assert evaluate(sor, th) is False  # connector 0.796 dB > 0.75
    th.check_connector = False
    assert evaluate(sor, th) is True   # ανακλάσεις -32 dB δεν μετράνε από προεπιλογή


# ---------- 2.0.0: νέα σελίδα PDF ----------
def _pages(pdf: Path) -> int:
    import re
    return len(re.findall(rb"/Type /Page[^s]", pdf.read_bytes()))


def test_many_events_continue_on_next_page(tmp_path):
    import copy
    from otdr_report.matching import Project, find_sor_files
    from otdr_report.pdf_report import ReportBuilder
    from otdr_report.settings import prepare
    from otdr_report.sor import parse_sor
    data = Path(__file__).parent / "data"
    p = Project()
    p.load([f for f in find_sor_files(data) if "scp51" in f.name])
    cable = p.sorted_cables()[0]
    fibers = cable.sorted_fibers()
    s = ReportSettings(summary_page=False)
    read = {}
    for f in fibers:
        sors = {w: prepare(parse_sor(m.path), s) for w, m in f.measurements.items()}
        for sor in sors.values():                     # 40 ενδιάμεσα συμβάντα: δεν χωράνε κανονικά
            mid = sor.events[1]
            extra = []
            for k in range(40):
                e = copy.copy(mid)
                e.distance_km = mid.distance_km + 0.0005 * (k + 1)
                extra.append(e)
            sor.events = sor.events[:2] + extra + sor.events[2:]
            sor.apply_launch(sor.user_offset_km)
        read[f.key] = sors
    out = tmp_path / "x.pdf"
    assert ReportBuilder(s).build(out, [(cable, fibers, read)])
    assert _pages(out) > len(fibers)                 # χωρίς σμίκρυνση: συνεχίζει σε επόμενη σελίδα


def test_english_default_and_new_sections(tmp_path):
    import shutil, subprocess
    from otdr_report.matching import Project, find_sor_files
    data = Path(__file__).parent / "data"
    p = Project()
    p.load([f for f in find_sor_files(data) if "scp51_dis_101" in f.name])
    assert ReportSettings().language == "en"
    out = generate_reports([(c, c.sorted_fibers()) for c in p.sorted_cables()], tmp_path,
                           ReportSettings(summary_page=False))
    assert _pages(out[0]) == 1
    if not shutil.which("pdftotext"):
        return
    txt = subprocess.run(["pdftotext", str(out[0]), "-"], capture_output=True, text=True).stdout
    for needle in ("Machine Information", "FHO5000-T45F-LS-PM-TS-FM", "BMO2601150030017",
                   "Configuration of Test", "Start Location", "End Location", "Link map"):
        assert needle in txt, needle
    assert txt.index("1310 nm") < txt.index("1550 nm")


# ---------- Έλεγχος Codex eae9192: σελίδες συνέχειας ----------
def _with_extra_events(tmp_path, n, **kw):
    """PDF από τα πραγματικά scp51 με n επιπλέον συμβάντα ανά λ· επιστρέφει (pdf, ίνες)."""
    import copy
    from otdr_report.matching import Project, find_sor_files
    from otdr_report.pdf_report import ReportBuilder
    from otdr_report.settings import prepare
    from otdr_report.sor import parse_sor
    p = Project()
    p.load([f for f in find_sor_files(Path(__file__).parent / "data") if "scp51" in f.name])
    cable = p.sorted_cables()[0]
    fibers = cable.sorted_fibers()
    s = ReportSettings(summary_page=False, **kw)
    read = {}
    for f in fibers:
        sors = {w: prepare(parse_sor(m.path), s) for w, m in f.measurements.items()}
        for sor in sors.values():
            mid = sor.events[1]
            extra = []
            for k in range(n):
                e = copy.copy(mid)
                e.distance_km = mid.distance_km + 0.0005 * (k + 1)
                extra.append(e)
            sor.events = sor.events[:2] + extra + sor.events[2:]
            sor.apply_launch(sor.user_offset_km)
        read[f.key] = sors
    out = tmp_path / f"x{n}.pdf"
    assert ReportBuilder(s).build(out, [(cable, fibers, read)])
    return out, fibers


def _page_texts(pdf: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        return [pg.extract_text() or "" for pg in PdfReader(pdf).pages]
    except ImportError:
        import shutil, subprocess
        if not shutil.which("pdftotext"):
            pytest.skip("χρειάζεται pypdf ή pdftotext")
        return [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf), "-"],
                               capture_output=True, text=True).stdout for i in range(1, _pages(pdf) + 1)]


def test_continuation_pages_identify_measurement_and_wavelength(tmp_path):
    import re
    out, fibers = _with_extra_events(tmp_path, 40)
    texts = _page_texts(out)
    assert len(texts) > len(fibers)
    for k, txt in enumerate(texts, 1):
        assert sum(f.display in txt for f in fibers) == 1, f"σελίδα {k}: χωρίς ταυτότητα μέτρησης"
        # κάθε τμήμα πίνακα συμβάντων ξεκινά με το λ του (γραμμή τίτλου του ίδιου του πίνακα)
        assert re.search(r"Events – (1310|1550) nm", txt), f"σελίδα {k}: χωρίς ένδειξη λ"
    assert sum("(continued)" in t for t in texts) == len(texts) - len(fibers)


def test_events_title_never_left_alone(tmp_path):
    import re
    for n in range(1, 17):              # σαρώνει τα όρια αλλαγής σελίδας
        out, _ = _with_extra_events(tmp_path, n)
        for k, txt in enumerate(_page_texts(out), 1):
            lines = [x.strip() for x in txt.strip().splitlines() if x.strip()]
            for j, line in enumerate(lines):
                if re.fullmatch(r"Events – (1310|1550) nm", line):
                    # μαζί του στην ίδια σελίδα: επικεφαλίδες στηλών και τουλάχιστον μία γραμμή
                    rest = " ".join(lines[j + 1:j + 4])
                    assert "Distance" in rest or "Dist." in rest, f"{n} συμβάντα, σελίδα {k}: τίτλος χωρίς πίνακα"
                    assert len(lines) > j + 2, f"{n} συμβάντα, σελίδα {k}: τίτλος χωρίς γραμμές"
