"""Ο αριθμός έκδοσης είναι ίδιος στην εφαρμογή, στα στοιχεία του exe και στο πρόγραμμα εγκατάστασης."""
import re
from pathlib import Path

from otdr_report import __version__

ROOT = Path(__file__).parent.parent


def test_version_is_consistent():
    major, minor, patch = (int(x) for x in __version__.split("."))
    info = (ROOT / "installer" / "version_info.txt").read_text(encoding="utf-8")
    assert f"filevers=({major}, {minor}, {patch}, 0)" in info
    assert f"prodvers=({major}, {minor}, {patch}, 0)" in info
    assert re.findall(r"'(?:File|Product)Version', '([\d.]+)'", info) == [__version__, __version__]
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{__version__}"' in iss
