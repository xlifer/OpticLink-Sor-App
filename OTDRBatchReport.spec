# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm OTDRBatchReport.spec
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("otdr_report/fonts", "otdr_report/fonts"),
    ("otdr_report/icon.ico", "otdr_report"),
]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("reportlab.graphics.barcode"),
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "IPython", "scipy",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OTDRBatchReport",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="otdr_report/icon.ico",
    version="installer/version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OTDRBatchReport")
