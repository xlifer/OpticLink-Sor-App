"""Πραγματική αναβάθμιση στα Windows (CI): παλιά έκδοση εγκατεστημένη → νέος installer.

    python tools/check_upgrade.py <παλιό Setup.exe> <νέο Setup.exe> <νέο dist φάκελος> <φάκελος αποτελεσμάτων>

Ελέγχει ότι:
  1. με το πρόγραμμα ανοιχτό, ο νέος installer δεν αλλάζει τίποτα (ζητά να κλείσει)·
  2. με το πρόγραμμα κλειστό, αναβαθμίζει στον ίδιο φάκελο, χωρίς Uninstall·
  3. τα αρχεία του προγράμματος είναι ακριβώς της νέας έκδοσης (όσα καταργήθηκαν σβήστηκαν)·
  4. ρυθμίσεις (μητρώο), διορθώσεις (%APPDATA%), .sor και PDF του χρήστη έμειναν ίδια·
  5. υπάρχει μία εγγραφή στις Εφαρμογές των Windows με τη νέα έκδοση, και η συντόμευση δείχνει στο νέο exe.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

APP_ID = "{6E2C1B7A-3F4D-4B8E-9C11-0A7E5D2F9B31}_is1"
EXE = "GrandwayBatchReport.exe"
SETTINGS_KEY = r"Software\OTDRBatchReport\OTDR Batch Report"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"]

bad = 0


def check(ok: bool, msg: str):
    global bad
    print(f"{'OK  ' if ok else 'FAIL'} {msg}", flush=True)
    bad += not ok


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def files(root: Path) -> set[str]:
    return {str(p.relative_to(root)).lower() for p in root.rglob("*") if p.is_file()}


def file_version(p: Path) -> str:
    import pefile
    pe = pefile.PE(str(p), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    for fi in getattr(pe, "FileInfo", []) or []:
        for entry in fi:
            for st in getattr(entry, "StringTable", []):
                v = st.entries.get(b"FileVersion")
                if v:
                    return v.decode()
    return ""


def uninstall_entries() -> list[tuple[str, str, str]]:
    """Όλες οι εγγραφές του προγράμματος στις Εφαρμογές (HKCU/HKLM, 64/32 bit)."""
    out = []
    for hive, hname in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                k = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    sk = winreg.OpenKey(k, name)
                    disp = winreg.QueryValueEx(sk, "DisplayName")[0]
                except OSError:
                    continue
                if "Grandway Batch Report" in disp or "OTDR Batch Report" in disp:
                    try:
                        ver = winreg.QueryValueEx(sk, "DisplayVersion")[0]
                    except OSError:
                        ver = ""
                    out.append((f"{hname}\\{name}", disp, ver))
    return sorted(set(out))


def install_dir() -> Path | None:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{UNINSTALL}\{APP_ID}")
        return Path(winreg.QueryValueEx(k, "InstallLocation")[0].rstrip("\\"))
    except OSError:
        return None


def shortcut_target(lnk: Path) -> str:
    ps = f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').TargetPath"
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()


def run_setup(setup: str, log: Path, extra=()):
    return subprocess.run([setup, *SILENT, f"/LOG={log}", *extra], timeout=900).returncode


def main(old_setup: str, new_setup: str, new_dist: str, out_dir: str) -> int:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "Grandway Batch Report"

    # 1. Εγκατάσταση της παλιάς έκδοσης
    rc = run_setup(old_setup, out / "old-setup.log", [f"/DIR={target}"])
    exe = target / EXE
    old_version = file_version(exe) if exe.exists() else ""
    check(rc == 0 and exe.exists(), f"παλιά έκδοση εγκαταστάθηκε ({old_version}) στο {target}")
    old_entries = uninstall_entries()
    print("   Εφαρμογές πριν:", old_entries)

    # αρχείο που υπήρχε μόνο στην παλιά έκδοση (π.χ. βιβλιοθήκη που καταργήθηκε)
    obsolete = target / "_internal" / "obsolete_from_old_version.dll"
    obsolete.write_bytes(b"old")

    # 2. Δεδομένα χρήστη που πρέπει να μείνουν
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    winreg.SetValueEx(k, "upgradeProbe", 0, winreg.REG_SZ, "keep-me")
    appdata = Path(os.environ["APPDATA"]) / "OTDRBatchReport" / "OTDR Batch Report"
    appdata.mkdir(parents=True, exist_ok=True)
    (appdata / "fiber_info.json").write_text('{"abc": {"fiber_id": "001", "cable_id": "301.1"}}', encoding="utf-8")
    (appdata / "event_overrides.json").write_text('{"abc": {"125.0": "connector"}}', encoding="utf-8")
    user = out / "user-data"
    user.mkdir(exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from otdr_report.synthetic import build_sor
    (user / "C1_1310_0001.sor").write_bytes(build_sor(1310, 1.0, [(0.3, 0.1, 0)]))
    (user / "C1_0001-0001.pdf").write_bytes(b"%PDF-1.4 user report")
    keep = {p: sha(p) for p in [*user.iterdir(), appdata / "fiber_info.json", appdata / "event_overrides.json"]}

    # 3. Νέος installer ενώ τρέχει το πρόγραμμα: δεν αλλάζει τίποτα
    before = {p: sha(p) for p in target.rglob("*") if p.is_file()}
    app = subprocess.Popen([str(exe)])
    time.sleep(8)
    rc_open = run_setup(new_setup, out / "new-setup-app-open.log")
    after = {p: sha(p) for p in target.rglob("*") if p.is_file()}
    check(rc_open != 0 and before == after,
          f"με το πρόγραμμα ανοιχτό η αναβάθμιση σταμάτησε χωρίς αλλαγές (κωδικός {rc_open})")
    app.kill()
    app.wait(30)
    time.sleep(2)

    # 4. Αναβάθμιση με το πρόγραμμα κλειστό, χωρίς /DIR και χωρίς Uninstall
    rc = run_setup(new_setup, out / "new-setup.log")
    check(rc == 0, f"αναβάθμιση ολοκληρώθηκε (κωδικός {rc})")
    check(install_dir() == target, f"ίδιος φάκελος εγκατάστασης ({install_dir()})")
    new_version = file_version(exe)
    want = file_version(Path(new_dist) / EXE)
    check(new_version == want and new_version != old_version, f"έκδοση exe {old_version} → {new_version}")
    check(not obsolete.exists(), "αρχείο που καταργήθηκε σβήστηκε")
    extra = {f for f in files(target) - files(Path(new_dist)) if not f.startswith("unins")}
    missing = files(Path(new_dist)) - files(target)
    check(not extra and not missing, f"αρχεία προγράμματος = νέα έκδοση (περισσεύουν {sorted(extra)[:5]}, "
                                     f"λείπουν {sorted(missing)[:5]})")

    # 5. Δεδομένα χρήστη ίδια
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    check(winreg.QueryValueEx(k, "upgradeProbe")[0] == "keep-me", "ρυθμίσεις (μητρώο) διατηρήθηκαν")
    check(all(p.exists() and sha(p) == h for p, h in keep.items()),
          "διορθώσεις (%APPDATA%), .sor και PDF του χρήστη ίδια")

    # 6. Μία εγγραφή στις Εφαρμογές, νέα έκδοση, σωστή συντόμευση
    entries = uninstall_entries()
    print("   Εφαρμογές μετά:", entries)
    from otdr_report import __version__
    check(len(entries) == 1 and entries[0][2] == __version__, f"μία εγγραφή στις Εφαρμογές, έκδοση {__version__}: {entries}")
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    links = list(programs.rglob("Grandway Batch Report.lnk"))
    check(len(links) == 1 and Path(shortcut_target(links[0])) == exe,
          f"συντόμευση Έναρξης → {shortcut_target(links[0]) if links else '-'}")
    check(not list(programs.rglob("OTDR Batch Report*.lnk")), "καμία παλιά συντόμευση")

    # 7. Η νέα έκδοση ανοίγει
    app = subprocess.Popen([str(exe)])
    time.sleep(10)
    check(app.poll() is None, "η αναβαθμισμένη εφαρμογή ξεκινά")
    app.kill()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(*sys.argv[1:5]))
