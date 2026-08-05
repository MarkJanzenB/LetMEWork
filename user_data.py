"""Local desktop settings: AppData paths, keys on-disk (never uploaded).

Keys live only on this PC under the user data directory.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "LetMeWork"
APP_VERSION = "0.1.0-beta.2"
FIRECRAWL_KEYS_URL = "https://www.firecrawl.dev/app/api-keys"
OPENROUTER_KEYS_URL = "https://openrouter.ai/keys"
OPENCODE_INSTALL_URL = "https://opencode.ai"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Bundled read-only assets (ui/, prompts/) — PyInstaller _MEIPASS or repo root."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def install_dir() -> Path:
    """Directory that contains the EXE / project root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def env_path() -> Path:
    return user_data_dir() / ".env"


def resume_path() -> Path:
    return user_data_dir() / "resume.md"


def resume_pdf_path() -> Path:
    """Original uploaded PDF (kept for the user; models use resume.md text)."""
    return user_data_dir() / "resume.pdf"


MAX_RESUME_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


def extract_pdf_text(data: bytes) -> str:
    """Extract text layer from a PDF. No OCR (Word→PDF text PDFs only)."""
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError(
            "No text found in PDF. Export from Word as PDF with selectable text "
            "(scanned image PDFs are not supported yet)."
        )
    return text


def save_resume_pdf(data: bytes, *, original_name: str = "") -> dict:
    """Store original PDF and write extracted text to resume.md for the AI."""
    if len(data) > MAX_RESUME_PDF_BYTES:
        raise ValueError(f"PDF too large (max {MAX_RESUME_PDF_BYTES // (1024 * 1024)} MB)")
    if not data.startswith(b"%PDF"):
        raise ValueError("File does not look like a PDF")

    text = extract_pdf_text(data)
    pdf_path = resume_pdf_path()
    pdf_path.write_bytes(data)
    md_path = save_resume_text(text)
    if original_name:
        save_settings({"resume_pdf_name": Path(original_name).name})
    return {
        "pdf_path": str(pdf_path),
        "resume_path": str(md_path),
        "content": text,
        "original_name": Path(original_name).name if original_name else pdf_path.name,
    }


def default_settings() -> dict:
    return {
        "onboarding_complete": False,
        "version_seen": APP_VERSION,
        "auto_update": False,
    }


def load_settings() -> dict:
    path = settings_path()
    data = default_settings()
    if path.exists():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_settings(updates: dict) -> dict:
    data = load_settings()
    data.update(updates)
    settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def read_env_keys() -> dict[str, str]:
    return _parse_env_file(env_path())


def apply_env_to_process() -> None:
    """Load repo .env then AppData .env (later files win)."""
    for path in (resource_dir() / ".env", install_dir() / ".env", env_path()):
        for k, v in _parse_env_file(path).items():
            if v:
                os.environ[k] = v


def write_env_keys(
    *,
    firecrawl_key: str | None = None,
    firecrawl_backup_key: str | None = None,
    openrouter_key: str | None = None,
) -> None:
    """Update keys in AppData .env. Pass None to leave unchanged; "" to clear."""
    current = read_env_keys()

    def _set(name: str, value: str | None) -> None:
        if value is None:
            return
        if value:
            current[name] = value
        else:
            current.pop(name, None)
            os.environ.pop(name, None)

    _set("FIRECRAWL_API_KEY", firecrawl_key)
    _set("FIRECRAWL_API_KEY_BACKUP", firecrawl_backup_key)
    _set("OPENROUTER_API_KEY", openrouter_key)

    lines = [
        "# Let Me Work — keys stored ONLY on this PC (never uploaded).",
        f"# Location: {env_path()}",
        "",
    ]
    for k in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_KEY_BACKUP", "OPENROUTER_API_KEY"):
        if k in current and current[k]:
            lines.append(f"{k}={current[k]}")
    env_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
    apply_env_to_process()


def firecrawl_api_keys() -> list[str]:
    """Primary then backup Firecrawl keys (deduped, non-empty)."""
    apply_env_to_process()
    out: list[str] = []
    for name in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_KEY_BACKUP"):
        v = (os.environ.get(name) or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def mask_key(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return value[:4] + "••••" + value[-4:]


def find_opencode() -> str | None:
    """Resolve OpenCode binary: OPENCODE_PATH → install dir → PATH."""
    forced = os.environ.get("OPENCODE_PATH", "").strip()
    if forced and Path(forced).exists():
        return str(Path(forced).resolve())

    names = ("opencode.exe", "opencode")
    for base in (install_dir(), resource_dir(), install_dir() / "bin"):
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return str(candidate.resolve())

    return shutil.which("opencode")


def setup_status() -> dict:
    apply_env_to_process()
    settings = load_settings()
    keys = read_env_keys()
    # Also reflect process env (dev .env)
    fc = keys.get("FIRECRAWL_API_KEY") or os.environ.get("FIRECRAWL_API_KEY", "")
    fc_backup = keys.get("FIRECRAWL_API_KEY_BACKUP") or os.environ.get(
        "FIRECRAWL_API_KEY_BACKUP", ""
    )
    ork = keys.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
    oc = find_opencode()
    resume = resume_path()
    repo_resume = resource_dir() / "resume.md"
    has_resume = resume.exists() or repo_resume.exists()
    pdf = resume_pdf_path()
    settings_pdf_name = settings.get("resume_pdf_name") or (pdf.name if pdf.exists() else "")
    ready = bool(fc or fc_backup) and has_resume and bool(oc)
    onboarding_complete = bool(settings.get("onboarding_complete"))
    # Packaged: always wizard until marked done. Dev: skip if already configured.
    needs_onboarding = (not onboarding_complete) and (is_frozen() or not ready)
    return {
        "version": APP_VERSION,
        "app_name": APP_NAME,
        "onboarding_complete": onboarding_complete,
        "needs_onboarding": needs_onboarding,
        "user_data_dir": str(user_data_dir()),
        "keys_path": str(env_path()),
        "keys_local_only": True,
        "has_firecrawl": bool(fc or fc_backup),
        "has_firecrawl_backup": bool(fc_backup),
        "has_openrouter": bool(ork),
        "firecrawl_masked": mask_key(fc),
        "firecrawl_backup_masked": mask_key(fc_backup),
        "openrouter_masked": mask_key(ork),
        "opencode_path": oc,
        "opencode_found": bool(oc),
        "has_resume": has_resume,
        "resume_path": str(resume if resume.exists() else repo_resume),
        "has_resume_pdf": pdf.exists(),
        "resume_pdf_path": str(pdf) if pdf.exists() else "",
        "resume_pdf_name": settings_pdf_name if pdf.exists() else "",
        "firecrawl_keys_url": FIRECRAWL_KEYS_URL,
        "openrouter_keys_url": OPENROUTER_KEYS_URL,
        "opencode_install_url": OPENCODE_INSTALL_URL,
        "frozen": is_frozen(),
        "ready": ready,
        "auto_update": bool(settings.get("auto_update", False)),
    }


def save_resume_text(text: str) -> Path:
    path = resume_path()
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path
