"""Βοηθητικά για τα tests «μία σελίδα έως 8 συμβάντα»."""
from pathlib import Path

from otdr_report import fiber_info
from otdr_report.matching import Project, find_sor_files
from otdr_report.settings import ReportSettings
from otdr_report.synthetic import build_sor

LONG = "FARM1.R01_" + "VERYLONGCABLENAME" * 3 + "_SCP31"


def events_8(length_km=2.0):
    """Launch (0) + (S) στα 100 m + 6 ενδιάμεσα + (E): 8 συμβάντα εκτός launch, 9 γραμμές συμβάντων."""
    return [(0.1, 0.30, -50.0)] + [(0.3 + k * 0.25, 0.12, (-45.0 if k % 2 else 0)) for k in range(6)]


def make_project(tmp_path: Path, name="C1_SCP31", fibers=2, long_fields=False) -> Project:
    d = tmp_path / "in"
    d.mkdir(parents=True, exist_ok=True)
    for k in range(1, fibers + 1):
        for wl in (1310, 1550):
            (d / f"{name}_{wl}_{k:04d}.sor").write_bytes(build_sor(
                wl, 2.0, events_8(), seed=k * 10 + wl, launch_m=100.0, cable="301.1", fiber=f"{k:03d}",
                loc_a=("FARM1.R01_SCP31_" + "LOCATIONTEXT " * 6) if long_fields else "FARM1.R01_SCP31",
                loc_b=("FARM1.R01_SDP31_301.1_" + "ENDLOCATION " * 6) if long_fields else "FARM1.R01_SDP31_301.1"))
    p = Project()
    p.load(find_sor_files(d))
    return p


def settings_combo(lang, chart, sig, company):
    s = ReportSettings(summary_page=False, language=lang, chart_mode=chart, signatures=sig)
    if company:
        s.company = "Grandway Fiber Services S.A. – Technical Department"
        s.company_info = "Λεωφόρος Παραδείγματος 123, 12345 Αθήνα\nΤηλ. 210 0000000 · info@example.com\nΑΦΜ 000000000"
        s.customer = "Πελάτης με αρκετά μεγάλο όνομα εταιρείας Α.Ε."
        s.project = "Έργο FTTH περιοχής – Φάση 2"
        s.operator = "Τεχνικός Μετρήσεων"
    return s
