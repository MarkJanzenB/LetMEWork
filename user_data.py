"""Local desktop settings: AppData paths, keys on-disk (never uploaded).

Keys live only on this PC under the user data directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "LetMeWork"
APP_VERSION = "0.1.0-beta.4"
FIRECRAWL_KEYS_URL = "https://www.firecrawl.dev/app/api-keys"
OPENROUTER_KEYS_URL = "https://openrouter.ai/keys"
OLLAMA_KEYS_URL = "https://ollama.com/settings/keys"
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
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except PdfReadError as exc:
        raise ValueError(
            f"Could not read PDF ({exc}). Use a text PDF from Word/Google Docs — "
            "scanned image PDFs are not supported yet."
        ) from exc
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
    ollama_key: str | None = None,
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
    _set("OLLAMA_API_KEY", ollama_key)

    lines = [
        "# Let Me Work — keys stored ONLY on this PC (never uploaded).",
        f"# Location: {env_path()}",
        "",
    ]
    for k in (
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_KEY_BACKUP",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
    ):
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


def refresh_path_from_registry() -> None:
    """Merge User/Machine PATH into this process (GUI launches often miss npm)."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
    parts: list[str] = []
    for root, subkey in (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ):
        try:
            with winreg.OpenKey(root, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        for p in str(val).split(";"):
            t = p.strip()
            if t and t not in parts:
                parts.append(t)
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        npm = str(Path(appdata) / "npm")
        if Path(npm).is_dir() and npm not in parts:
            parts.append(npm)
    for p in os.environ.get("PATH", "").split(";"):
        t = p.strip()
        if t and t not in parts:
            parts.append(t)
    if parts:
        os.environ["PATH"] = ";".join(parts)


def _opencode_template_path() -> Path | None:
    """Shipping job-agent template (packaging/ or frozen MEIPASS — not personal repo file)."""
    candidates = [Path(__file__).resolve().parent / "packaging" / "opencode.json"]
    if is_frozen():
        candidates.insert(0, resource_dir() / "opencode.json")
    for p in candidates:
        if p.is_file():
            return p
    return None


_JOB_AGENT_FALLBACK = {
    "description": (
        "Job hunting agent — reads resume and jobs files, "
        "outputs JSON analysis and cover letters"
    ),
    "mode": "primary",
    "permission": {
        "read": "allow",
        "edit": "deny",
        "bash": "deny",
        "glob": "deny",
        "grep": "deny",
        "task": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "todowrite": "deny",
        "skill": "deny",
    },
}


def opencode_config_path() -> Path:
    """Writable opencode.json OpenCode loads (AppData when packaged)."""
    return user_data_dir() / "opencode.json"


def ensure_opencode_config() -> Path:
    """Seed/merge job-agent into AppData opencode.json; return its path."""
    dest = opencode_config_path()
    template = _opencode_template_path()
    tpl: dict = {}
    if template is not None:
        try:
            tpl = json.loads(template.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            tpl = {}

    cfg: dict = {}
    if dest.is_file():
        try:
            cfg = json.loads(dest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = {}
    elif tpl:
        cfg = dict(tpl)
    else:
        cfg = {"$schema": "https://opencode.ai/config.json", "agent": {}}

    agent = cfg.setdefault("agent", {})
    if not isinstance(agent, dict):
        agent = {}
        cfg["agent"] = agent
    if "job-agent" not in agent:
        job = None
        if isinstance(tpl.get("agent"), dict):
            job = tpl["agent"].get("job-agent")
        agent["job-agent"] = job if isinstance(job, dict) else dict(_JOB_AGENT_FALLBACK)

    if "$schema" not in cfg and isinstance(tpl.get("$schema"), str):
        cfg["$schema"] = tpl["$schema"]

    dest.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return dest


def opencode_run_env() -> dict[str, str]:
    """Env for `opencode run`: refreshed PATH + OPENCODE_CONFIG → job-agent."""
    refresh_path_from_registry()
    apply_env_to_process()
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(ensure_opencode_config())
    return env


def opencode_argv(*args: str) -> list[str] | None:
    """Build argv for OpenCode. Prefer .exe; wrap .cmd/.bat via cmd.exe."""
    exe = find_opencode()
    if not exe:
        return None
    lower = exe.lower()
    if lower.endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe, *args]
    return [exe, *args]


def find_opencode() -> str | None:
    """Resolve OpenCode binary via env, install dir, PATH, then per-user npm/scoop.

    Uses %APPDATA% / %LOCALAPPDATA% / home — never a hardcoded username.
    """
    refresh_path_from_registry()
    forced = os.environ.get("OPENCODE_PATH", "").strip()
    if forced and Path(forced).exists():
        return str(Path(forced).resolve())

    names = ("opencode.exe", "opencode")
    for base in (install_dir(), resource_dir(), install_dir() / "bin"):
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return str(candidate.resolve())

    which = shutil.which("opencode")
    if which:
        return which

    # Prefer real binaries over .cmd shims (CreateProcess cannot run .cmd alone)
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA", "").strip()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if appdata:
        npm = Path(appdata) / "npm"
        candidates += [npm / "opencode.exe", npm / "opencode.cmd"]
    if local:
        candidates.append(Path(local) / "Programs" / "opencode" / "opencode.exe")
        candidates.append(Path(local) / "Programs" / "opencode" / "bin" / "opencode.exe")
    candidates.append(Path.home() / "scoop" / "shims" / "opencode.exe")
    candidates.append(Path.home() / "scoop" / "apps" / "opencode" / "current" / "opencode.exe")
    for c in candidates:
        if c.is_file():
            return str(c.resolve())
    return None


def install_opencode_script_path() -> Path | None:
    """PowerShell soft-installer shipped next to the app or in packaging/."""
    for p in (
        install_dir() / "install_opencode.ps1",
        resource_dir() / "install_opencode.ps1",
        Path(__file__).resolve().parent / "packaging" / "install_opencode.ps1",
    ):
        if p.is_file():
            return p
    return None


def soft_install_opencode() -> dict:
    """Detect OpenCode; if missing, run official soft-install script (network)."""
    found = find_opencode()
    if found:
        return {
            "ok": True,
            "already_present": True,
            "path": found,
            "message": f"OpenCode already on this PC: {found}",
            "exit_code": 0,
        }

    script = install_opencode_script_path()
    if not script:
        return {
            "ok": False,
            "already_present": False,
            "path": None,
            "message": "Install script missing. Run: npm install -g opencode-ai",
            "exit_code": -1,
        }

    if os.name != "nt":
        return {
            "ok": False,
            "already_present": False,
            "path": None,
            "message": "Soft install is Windows-only. Install OpenCode from https://opencode.ai/docs/",
            "exit_code": -1,
        }

    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    cmd = [
        str(ps),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        exit_code = int(proc.returncode)
        log = ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        exit_code = -1
        log = "OpenCode soft install timed out after 10 minutes."
    except OSError as exc:
        exit_code = -1
        log = str(exc)

    found = find_opencode()
    if found:
        return {
            "ok": True,
            "already_present": False,
            "path": found,
            "message": f"OpenCode ready: {found}",
            "exit_code": exit_code,
            "log_tail": log[-2000:] if log else "",
        }
    return {
        "ok": False,
        "already_present": False,
        "path": None,
        "message": "OpenCode still not found after soft install.",
        "exit_code": exit_code,
        "log_tail": log[-2000:] if log else "",
    }


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
    olk = keys.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY", "")
    oc = find_opencode()
    resume = resume_path()
    repo_resume = resource_dir() / "resume.md"
    has_resume = resume.exists() or repo_resume.exists()
    resume_usable = resume_is_usable()
    pdf = resume_pdf_path()
    settings_pdf_name = settings.get("resume_pdf_name") or (pdf.name if pdf.exists() else "")
    ready = bool(fc or fc_backup) and resume_usable and bool(oc)
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
        "has_ollama_key": bool(olk),
        "firecrawl_masked": mask_key(fc),
        "firecrawl_backup_masked": mask_key(fc_backup),
        "openrouter_masked": mask_key(ork),
        "ollama_masked": mask_key(olk),
        "opencode_path": oc,
        "opencode_found": bool(oc),
        "has_resume": has_resume,
        "resume_usable": resume_usable,
        "resume_path": str(resume if resume.exists() else repo_resume),
        "has_resume_pdf": pdf.exists(),
        "resume_pdf_path": str(pdf) if pdf.exists() else "",
        "resume_pdf_name": settings_pdf_name if pdf.exists() else "",
        "firecrawl_keys_url": FIRECRAWL_KEYS_URL,
        "openrouter_keys_url": OPENROUTER_KEYS_URL,
        "ollama_keys_url": OLLAMA_KEYS_URL,
        "opencode_install_url": OPENCODE_INSTALL_URL,
        "frozen": is_frozen(),
        "ready": ready,
        "auto_update": bool(settings.get("auto_update", False)),
    }


def save_resume_text(text: str) -> Path:
    path = resume_path()
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def resume_is_usable(text: str | None = None) -> bool:
    """False for missing/empty/placeholder resumes that break query generation.

    Stub like `# New Resume\\nUpdated` counts as present on disk but is unusable.
    """
    if text is None:
        path = resume_path()
        if not path.exists():
            repo = resource_dir() / "resume.md"
            path = repo if repo.exists() else path
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8")
    stripped = (text or "").strip()
    if len(stripped) < 80:
        return False
    low = stripped.lower()
    # Onboarding placeholder from setup tests / empty wizard save
    if low.startswith("# new resume") and len(stripped) < 200:
        return False
    if "paste your resume" in low[:120] or "your resume here" in low[:120]:
        return False
    return True
