# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for iPhone Mirror (Windows --onedir build)."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
RUST_FAIRPLAY_PY = ROOT / "rust" / "fairplay-rs" / "python"
RUST_STREAM_PY = ROOT / "rust" / "stream-ops-rs" / "python"

datas = []
binaries = []
hiddenimports = [
    "fairplay_rs",
    "stream_ops_rs",
    "iphone_mirror",
    "iphone_mirror.__main__",
    "iphone_mirror.usbvideo",
    "iphone_mirror.recorder",
    "iphone_mirror.stream_ops",
    "iphone_mirror.control",
    "iphone_mirror.control.hid",
    "iphone_mirror.control.usb",
    "iphone_mirror.control.wda",
    "iphone_mirror.control.wifi_wda",
    "ifaddr",
    "zeroconf",
    "sounddevice",
    "_sounddevice_data",
    "opack2",
    "qh3",
    "pmd_pytcp",
    "pmd_net_addr",
    "pmd_net_proto",
    "pytun_pmd3",
    "sslpsk_pmd3",
    "lzfse",
    "remotezip2",
    "ipsw_parser",
    "pyimg4",
    "bpylist2",
    "win32api",
    "win32con",
    "win32file",
    "pywintypes",
]

for pkg in (
    "av",
    "pymobiledevice3",
    "developer_disk_image",
    "cryptography",
    "pyimg4",
    "ipsw_parser",
    "pykdebugparser",
    "pytun_pmd3",
    "pycrashreport",
    "pyiosbackup",
    "qh3",
    "pmd_pytcp",
    "opack2",
    "sslpsk_pmd3",
    "certifi",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

for dist_pkg in ("pymobiledevice3", "av", "zeroconf", "sounddevice"):
    try:
        datas += copy_metadata(dist_pkg, recursive=True)
    except Exception:
        pass

try:
    datas += collect_data_files("_sounddevice_data")
except Exception:
    pass

hiddenimports += collect_submodules("zeroconf")

for rust_dir in (RUST_FAIRPLAY_PY, RUST_STREAM_PY):
    if rust_dir.is_dir():
        for ext in ("*.pyd", "*.dll"):
            for item in rust_dir.glob(ext):
                binaries.append((str(item), "."))

icon_file = Path(SPECPATH) / "iPhoneMirror.ico"

a = Analysis(
    [str(Path(SPECPATH) / "launcher.py")],
    pathex=[str(ROOT), str(RUST_FAIRPLAY_PY), str(RUST_STREAM_PY)],
    binaries=binaries,
    datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "IPython",
        "jedi",
        "parso",
        "tkinter",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtMultimedia",
        "PySide6.QtPdf",
        "PySide6.QtCharts",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iPhoneMirror",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="iPhoneMirror",
)
