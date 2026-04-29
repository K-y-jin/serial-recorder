# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Sensor Recorder
# Build:  pyinstaller SensorRecorder.spec

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

hiddenimports = [
    "serial.tools.list_ports_linux",
    "serial.tools.list_ports_posix",
    "serial.tools.list_ports_windows",
    "serial.tools.list_ports_osx",
]

datas = []
datas += collect_data_files("matplotlib", includes=["mpl-data/**/*"])

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "jupyter", "notebook", "pytest",
        "scipy", "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SensorRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SensorRecorder",
)
