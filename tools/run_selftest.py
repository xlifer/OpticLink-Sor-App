"""Τρέχει το OTDRBatchReport.exe που έφτιαξε το PyInstaller με --selftest (για το CI)."""
import subprocess
import sys
from pathlib import Path

exe = Path("dist/OTDRBatchReport/OTDRBatchReport.exe")
out = Path("build/selftest").resolve()
rc = subprocess.run([str(exe), "--selftest", str(out)], timeout=300).returncode
log = out / "selftest.log"
print(log.read_text(encoding="utf-8") if log.exists() else "χωρίς log")
pdfs = list(out.glob("*.pdf"))
print("PDF:", [p.name for p in pdfs])
sys.exit(rc or (0 if pdfs else 1))
