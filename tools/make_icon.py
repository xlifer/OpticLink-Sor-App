"""Φτιάχνει όλα τα εικονίδια της εφαρμογής από μία πηγή: otdr_report/assets/program_icon.png.

    python tools/make_icon.py

Παράγει:
  * otdr_report/icon.ico            – 16, 32, 48, 256 px (exe του PyInstaller και Setup.exe του Inno Setup)
  * otdr_report/assets/app_icon_<N>.png – τα ίδια μεγέθη σε PNG (παράθυρο / γραμμή εργασιών μέσω Qt)

Το σχέδιο και η διαφάνεια μένουν ίδια. Αφαιρείται μόνο το διάφανο περιθώριο γύρω από το σχέδιο,
ώστε να μη χάνεται στα 16/32 px, και το σχέδιο κεντράρεται σε τετράγωνο.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "otdr_report" / "assets" / "program_icon.png"
ICO = ROOT / "otdr_report" / "icon.ico"
SIZES = (16, 32, 48, 256)


def square_source() -> Image.Image:
    im = Image.open(SRC).convert("RGBA")
    box = im.getchannel("A").getbbox() or (0, 0, *im.size)
    im = im.crop(box)
    side = max(im.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq


def frames() -> dict[int, Image.Image]:
    sq = square_source()
    return {n: sq.resize((n, n), Image.LANCZOS) for n in SIZES}


def main():
    fr = frames()
    for n, im in fr.items():
        im.save(ICO.parent / "assets" / f"app_icon_{n}.png")
    # το μεγαλύτερο πρώτο· τα υπόλοιπα από τα έτοιμα frames, ώστε να είναι ίδια με τα PNG
    fr[256].save(ICO, format="ICO", sizes=[(n, n) for n in SIZES], append_images=[fr[n] for n in SIZES[:-1]])
    print("OK", ICO, [Image.open(ICO).info.get("sizes")])


if __name__ == "__main__":
    main()
