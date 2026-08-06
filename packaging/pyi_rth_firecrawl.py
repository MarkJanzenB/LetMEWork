# PyInstaller runtime hook: firecrawl.v2.utils.get_version reads
# firecrawl/__init__.py from disk; one-file extracts often omit that source.
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_firecrawl_init() -> None:
    mei = getattr(sys, "_MEIPASS", None)
    if not mei:
        return
    init = Path(mei) / "firecrawl" / "__init__.py"
    if init.is_file():
        return
    ver = "0.0.0"
    try:
        from importlib.metadata import version

        ver = version("firecrawl-py")
    except Exception:
        pass
    init.parent.mkdir(parents=True, exist_ok=True)
    init.write_text(f'__version__ = "{ver}"\n', encoding="utf-8")


_ensure_firecrawl_init()
