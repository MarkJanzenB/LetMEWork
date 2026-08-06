# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packaging/letmework.spec
# OpenCode is NOT bundled — Inno post-install runs official CLI install.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "server.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "ui"), "ui"),
        (str(ROOT / "prompts"), "prompts"),
    ],
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
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
