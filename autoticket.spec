# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = collect_submodules("extract_msg")
datas = collect_data_files("extract_msg")
datas += [("servicenow_config.json", ".")]


a = Analysis(
    ["autoticket.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6",
        "PySide2",
        "PySide6",
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
        "test",
        "tests",
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="autoticket",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["QtWebEngineProcess.exe"],
    name="autoticket-portable",
)
