# PyInstaller spec for the Windows build of the pressure-monitoring server.
#
# Build (on Windows, from the repo root, with server/requirements-build.txt
# installed):
#     pyinstaller server.spec
#
# Produces dist/pressure-server/pressure-server.exe (onedir build -- safer than
# onefile for a Flask app since template/static files stay on disk next to
# the exe and load fast).
import sys

block_cipher = None

a = Analysis(
    ["server/win_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("server/templates", "server/templates"),
        ("server/mock_warning_data.json", "server"),
    ],
    hiddenimports=[
        "server.app", "server.alert", "server.connection_monitor",
        "server.grid", "server.state", "server.warning_store",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pressure-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name="pressure-server",
)
