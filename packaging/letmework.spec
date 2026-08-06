# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packaging/letmework.spec
# OpenCode is NOT bundled — Inno post-install runs official CLI install.

from pathlib import Path

import firecrawl as _firecrawl
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent

# Source tree on disk under _MEI (get_version reads __init__.py as a file)
_fc_dir = str(Path(_firecrawl.__file__).resolve().parent)
fc_datas, fc_binaries, fc_hidden = collect_all("firecrawl")

a = Analysis(
    [str(ROOT / "server.py")],
    pathex=[str(ROOT)],
    binaries=fc_binaries,
    datas=[
        (str(ROOT / "ui"), "ui"),
        (str(ROOT / "prompts"), "prompts"),
        (str(ROOT / "packaging" / "opencode.json"), "."),
        (str(ROOT / "packaging" / "install_opencode.ps1"), "."),
        (_fc_dir, "firecrawl"),
    ]
    + fc_datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "pypdf",
        "firecrawl",
    ]
    + fc_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "pyi_rth_firecrawl.py")],
    excludes=[],
    noarchive=False,
    module_collection_mode={"firecrawl": "py"},
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LetMeWork",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX packing often trips AV heuristics — leave off for unsigned builds
    upx=False,
    console=True,  # scrape logs during beta
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
