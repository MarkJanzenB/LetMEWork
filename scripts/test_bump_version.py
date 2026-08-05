# Assert bump_version rewrites lockstep fields (no pytest fixtures).
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump_version.py"


def test_bump_version_script_dry():
    """Run bump against a temp copy of the four files and check values."""
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        # Minimal stubs matching replace patterns
        (t / "user_data.py").write_text('APP_VERSION = "0.0.0"\n', encoding="utf-8")
        (t / "pyproject.toml").write_text('version = "0.0.0"\n', encoding="utf-8")
        (t / "frontend").mkdir()
        (t / "frontend" / "package.json").write_text('{"version": "0.0.0"}\n', encoding="utf-8")
        (t / "packaging").mkdir()
        (t / "packaging" / "LetMeWork.iss").write_text(
            '#define MyAppVersion "0.0.0"\nVersionInfoVersion=0.0.0.0\n',
            encoding="utf-8",
        )
        # Inline the replace logic by running script with patched ROOT — invoke functions
        sys.path.insert(0, str(ROOT / "scripts"))
        import bump_version as bv

        old_root = bv.ROOT
        bv.ROOT = t
        try:
            sys.argv = ["bump_version.py", "0.1.0-beta.2"]
            bv.main()
        finally:
            bv.ROOT = old_root

        assert 'APP_VERSION = "0.1.0-beta.2"' in (t / "user_data.py").read_text(encoding="utf-8")
        assert 'version = "0.1.0-beta.2"' in (t / "pyproject.toml").read_text(encoding="utf-8")
        assert '"version": "0.1.0-beta.2"' in (t / "frontend" / "package.json").read_text(
            encoding="utf-8"
        )
        iss = (t / "packaging" / "LetMeWork.iss").read_text(encoding="utf-8")
        assert '#define MyAppVersion "0.1.0-beta.2"' in iss
        assert "VersionInfoVersion=0.1.0.2" in iss


if __name__ == "__main__":
    test_bump_version_script_dry()
    print("ok")
