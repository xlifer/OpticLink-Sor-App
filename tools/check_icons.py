"""Έλεγχος εικονιδίων στο CI των Windows (μετά το PyInstaller και το Inno Setup).

    python tools/check_icons.py exe dist/GrandwayBatchReport/GrandwayBatchReport.exe dist/GrandwayBatch...-Setup-X.exe
    python tools/check_icons.py installed dist/GrandwayBatchReport-Setup-X.exe build/icon-check

* exe: τα εικονίδια που είναι ενσωματωμένα στο κάθε .exe (RT_GROUP_ICON / RT_ICON) πρέπει να είναι
  byte-προς-byte τα frames του otdr_report/icon.ico (16, 32, 48, 256), που βγαίνει από το
  otdr_report/assets/program_icon.png.
* installed: εγκαθιστά σιωπηλά το Setup.exe, ανοίγει το εγκατεστημένο πρόγραμμα και διαβάζει από τα
  Windows το εικονίδιο του παραθύρου του (WM_GETICON / κλάση), δηλαδή αυτό που δείχνει η γραμμή
  εργασιών. Το σχεδιάζει και το συγκρίνει με το app_icon_<N>.png. Κρατά και στιγμιότυπο οθόνης.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "otdr_report" / "icon.ico"
SIZES = (16, 32, 48, 256)
TITLE = "Grandway Batch Report"


# ---------------------------------------------------------------- .ico και .exe
def ico_frames(path: Path = ICO) -> dict[int, bytes]:
    data = path.read_bytes()
    _, _, count = struct.unpack_from("<HHH", data, 0)
    out = {}
    for k in range(count):
        w, h, _c, _r, _p, _b, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * k)
        out[w or 256] = data[off:off + size]
    return out


def exe_icon_groups(path: Path) -> list[dict[int, bytes]]:
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    icons, groups = {}, []

    def leaf_data(entry):
        for lang in entry.directory.entries:
            d = lang.data.struct
            return pe.get_data(d.OffsetToData, d.Size)

    for typ in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id == 3:                                     # RT_ICON
            for e in typ.directory.entries:
                icons[e.id] = leaf_data(e)
    for typ in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id == 14:                                    # RT_GROUP_ICON
            for e in typ.directory.entries:
                g = leaf_data(e)
                _, _, count = struct.unpack_from("<HHH", g, 0)
                frames = {}
                for k in range(count):
                    w, h, _c, _r, _p, _b, _size, icon_id = struct.unpack_from("<BBBBHHIH", g, 6 + 14 * k)
                    frames[w or 256] = icons.get(icon_id, b"")
                groups.append(frames)
    return groups


def check_exe(paths: list[str]) -> int:
    ref = ico_frames()
    assert sorted(ref) == list(SIZES), f"icon.ico: μεγέθη {sorted(ref)}"
    bad = 0
    for p in map(Path, paths):
        groups = exe_icon_groups(p)
        ok = any(g == ref for g in groups)
        print(f"{'OK  ' if ok else 'FAIL'} {p.name}: {len(groups)} ομάδες εικονιδίων, "
              f"μεγέθη {[sorted(g) for g in groups]} – {'ίδια με το icon.ico' if ok else 'ΔΙΑΦΟΡΕΤΙΚΑ από το icon.ico'}")
        bad += not ok
    return 1 if bad else 0


# ---------------------------------------------------------------- εγκατεστημένο πρόγραμμα
def _win_icon_image(hicon, n):
    """Σχεδιάζει ένα HICON σε n×n πάνω σε λευκό και το επιστρέφει ως εικόνα RGB."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int,
                                  ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bmi = BITMAPINFOHEADER(40, n, -n, 1, 32, 0, 0, 0, 0, 0, 0)
    screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    hbm = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    gdi32.SelectObject(hdc, hbm)
    ctypes.memset(bits, 0xFF, n * n * 4)
    if not user32.DrawIconEx(hdc, 0, 0, hicon, n, n, 0, None, 3):        # DI_NORMAL
        raise RuntimeError("DrawIconEx απέτυχε")
    raw = ctypes.string_at(bits, n * n * 4)
    return Image.frombuffer("RGBA", (n, n), raw, "raw", "BGRA", 0, 1).convert("RGB")


def _reference(n):
    from PIL import Image
    p = Image.open(ROOT / "otdr_report" / "assets" / f"app_icon_{n}.png").convert("RGBA")
    bg = Image.new("RGBA", p.size, (255, 255, 255, 255))
    bg.alpha_composite(p)
    return bg.convert("RGB")


def _diff(a, b) -> float:
    from PIL import ImageChops, ImageStat
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def _find_window(pid: int, timeout=90):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if user32.IsWindowVisible(hwnd) and buf.value.startswith(TITLE):
            found.append((hwnd, wpid.value, buf.value))
        return True

    end = time.time() + timeout
    while time.time() < end:
        found.clear()
        user32.EnumWindows(proc(cb), 0)
        if found:
            return found[0]
        time.sleep(1)
    return None


def check_installed(setup: str, out_dir: str) -> int:
    import ctypes
    from ctypes import wintypes
    from PIL import ImageGrab
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "install"
    rc = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                         f"/DIR={target}", f"/LOG={out / 'setup.log'}"], timeout=600).returncode
    exe = target / "GrandwayBatchReport.exe"
    print(f"Εγκατάσταση: rc={rc}, {exe} {'υπάρχει' if exe.exists() else 'ΔΕΝ υπάρχει'}")
    if rc or not exe.exists():
        return 1
    bad = check_exe([str(exe)])
    proc = subprocess.Popen([str(exe)])
    try:
        win = _find_window(proc.pid)
        if not win:
            print("FAIL δεν βρέθηκε παράθυρο του προγράμματος")
            return 1
        hwnd, _, title = win
        print(f"Παράθυρο: «{title}»")
        user32 = ctypes.windll.user32
        user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                               wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        user32.GetClassLongPtrW.restype = ctypes.c_size_t
        user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.LoadIconW.restype = wintypes.HICON
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        generic = user32.LoadIconW(None, ctypes.c_void_p(32512))            # IDI_APPLICATION
        time.sleep(3)
        for kind, n, cls in (("ICON_BIG", 32, -14), ("ICON_SMALL", 16, -34)):
            res = ctypes.c_size_t(0)
            user32.SendMessageTimeoutW(hwnd, 0x7F, 1 if n == 32 else 0, 0, 2, 3000, ctypes.byref(res))
            hicon = res.value or user32.GetClassLongPtrW(hwnd, cls)
            if not hicon:
                print(f"FAIL {kind}: το παράθυρο δεν έχει εικονίδιο")
                bad += 1
                continue
            img = _win_icon_image(hicon, n)
            ref = _reference(n)
            gen = _win_icon_image(generic, n)
            d_ref, d_gen = _diff(img, ref), _diff(img, gen)
            img.resize((n * 4, n * 4)).save(out / f"window_{kind}.png")
            ref.resize((n * 4, n * 4)).save(out / f"reference_{n}.png")
            ok = d_ref < 12 and d_ref < d_gen
            print(f"{'OK  ' if ok else 'FAIL'} {kind} {n}px: διαφορά από program_icon {d_ref:.1f}, "
                  f"από το γενικό εικονίδιο των Windows {d_gen:.1f}")
            bad += not ok
        try:
            shot = ImageGrab.grab(all_screens=True)
            shot.save(out / "screen.png")
            shot.crop((0, max(0, shot.height - 80), shot.width, shot.height)).save(out / "taskbar.png")
        except Exception as e:  # noqa: BLE001
            print(f"(στιγμιότυπο οθόνης: {e})")
    finally:
        proc.kill()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")        # η κονσόλα των Windows (cp1252) δεν γράφει ελληνικά
    mode = sys.argv[1]
    if mode == "exe":
        sys.exit(check_exe(sys.argv[2:]))
    if mode == "installed":
        sys.exit(check_installed(sys.argv[2], sys.argv[3]))
    sys.exit(f"άγνωστη εντολή {mode}")
