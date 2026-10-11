"""Ένα εικονίδιο παντού: όλα βγαίνουν από το otdr_report/assets/program_icon.png."""
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_icons  # noqa: E402
import make_icon  # noqa: E402

SIZES = [16, 32, 48, 256]


def test_ico_has_required_sizes_with_transparency():
    ico = Image.open(ROOT / "otdr_report" / "icon.ico")
    assert sorted(ico.info["sizes"]) == [(n, n) for n in SIZES]
    for n in SIZES:
        ico.size = (n, n)
        ico.load()
        assert ico.mode == "RGBA" and ico.getchannel("A").getextrema()[0] == 0    # διάφανο φόντο
    assert sorted(check_icons.ico_frames()) == SIZES


def test_icons_are_generated_from_program_icon():
    """Το icon.ico και τα PNG είναι ακριβώς αυτά που παράγει το tools/make_icon.py από το program_icon.png."""
    fresh = make_icon.frames()
    ico = Image.open(ROOT / "otdr_report" / "icon.ico")
    for n in SIZES:
        png = Image.open(ROOT / "otdr_report" / "assets" / f"app_icon_{n}.png").convert("RGBA")
        assert ImageChops.difference(png, fresh[n]).getbbox() is None, f"app_icon_{n}.png δεν είναι ενημερωμένο"
        ico.size = (n, n)
        ico.load()
        assert ImageChops.difference(ico.convert("RGBA"), png).getbbox() is None, f"icon.ico {n}px ≠ PNG"


def test_build_and_installer_use_the_same_icon():
    spec = (ROOT / "GrandwayBatchReport.spec").read_text(encoding="utf-8")
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert 'icon="otdr_report/icon.ico"' in spec and '"otdr_report/assets"' in spec
    assert "SetupIconFile=..\\otdr_report\\icon.ico" in iss
    assert iss.count('AppUserModelID: "GrandwayBatchReport.App"') == 2
    app = (ROOT / "otdr_report" / "app.py").read_text(encoding="utf-8")
    assert 'SetCurrentProcessExplicitAppUserModelID("GrandwayBatchReport.App")' in app
