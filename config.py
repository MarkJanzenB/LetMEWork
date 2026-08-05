"""Centralized configuration for the job scraper pipeline.

All constants and configuration values are defined here.
"""

import json
import sys
from pathlib import Path

import user_data

# ── paths ──────────────────────────────────────────────
# Read-only bundled assets (ui, prompts) vs writable user data when packaged
BASE_DIR = user_data.resource_dir()
INSTALL_DIR = user_data.install_dir()

if user_data.is_frozen():
    _writable = user_data.user_data_dir()
    DATA_DIR = _writable / "data"
    OUTPUT_DIR = _writable / "output"
    CONFIG_FILE = _writable / "config.json"
    RESUME_FILE = user_data.resume_path()
else:
    # Dev: keep using the repo tree so existing local DBs still work
    DATA_DIR = Path(__file__).resolve().parent / "data"
    OUTPUT_DIR = Path(__file__).resolve().parent / "output"
    CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
    RESUME_FILE = (
        user_data.resume_path()
        if user_data.resume_path().exists()
        else Path(__file__).resolve().parent / "resume.md"
    )

PROMPTS_DIR = BASE_DIR / "prompts"
DB_PATH = DATA_DIR / "jobs.db"

# Dev fallbacks referenced by bootstrap()
_REPO_RESUME = Path(__file__).resolve().parent / "resume.md"
_REPO_CONFIG = Path(__file__).resolve().parent / "config.json"

# ── app metadata ───────────────────────────────────────
APP_VERSION = user_data.APP_VERSION

# ── pipeline settings ──────────────────────────────────
THRESHOLD = 70  # Minimum score for "apply" verdict
# ponytail: off by default — on-demand / bulk Generate in the UI is cheaper
GENERATE_COVER_LETTERS_IN_PIPELINE = False

# ── free model rotation ────────────────────────────────
# Models are discovered dynamically by model_prober.py and cached in
# data/healthy_models.json. No hardcoded list needed.
MAX_RETRIES = 3  # Retries per model before moving to next
# Hard ceiling across all models/re-probes — prevents infinite rotation
MAX_OPENCODE_ATTEMPTS = 15
STALL_TIMEOUT = 600  # Hard cap on total runtime per attempt (10 minutes)
STALL_SILENCE_TIMEOUT = 90  # Kill if no output for this long (seconds)
PROBE_CACHE_TTL = 7 * 24 * 3600  # Re-probe healthy models after 1 week

# ── scraping settings ──────────────────────────────────
MAX_PAGES_TO_SCRAPE = 20
SCRAPE_TIMEOUT_MS = 120000  # listing pages (JobStreet, LinkedIn) are JS-heavy

# ── status lifecycle ───────────────────────────────────
VALID_STATUSES = ("none", "applied", "ignored", "interviewed", "rejected", "hired", "closed")

# ── default search config ──────────────────────────────
# OnlineJobs.ph stays available in Settings but off by default —
# many PH users can't apply until the site verifies their account.
AVAILABLE_JOB_BOARDS = [
    {"id": "indeed.com", "label": "Indeed"},
    {"id": "jobstreet.com", "label": "JobStreet"},
    {"id": "onlinejobs.ph", "label": "OnlineJobs.ph (JobsPH)"},
    {"id": "linkedin.com/jobs", "label": "LinkedIn Jobs"},
    {"id": "wellfound.com", "label": "Wellfound"},
    {"id": "glassdoor.com", "label": "Glassdoor"},
]

DEFAULT_CONFIG = {
    "job_boards": [
        "linkedin.com/jobs",
        "indeed.com",
        "wellfound.com",
        "glassdoor.com",
        "jobstreet.com",
    ],
}


def writable_config_path() -> Path:
    """User-editable search config (AppData in both dev and release)."""
    return user_data.user_data_dir() / "config.json"


def load_search_config() -> dict:
    """DEFAULT_CONFIG overridden by AppData config.json, else repo config.json."""
    cfg = dict(DEFAULT_CONFIG)
    for path in (writable_config_path(), _REPO_CONFIG):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.pop("reddit_groups", None)  # legacy key ignored
                    cfg.update(data)
            except (json.JSONDecodeError, OSError):
                pass
            break
    cfg.pop("reddit_groups", None)
    return cfg


def save_job_boards(boards: list[str]) -> dict:
    """Persist enabled job boards. Always writes AppData config.json."""
    global CONFIG_FILE
    allowed = {b["id"] for b in AVAILABLE_JOB_BOARDS}
    cleaned = []
    for b in boards:
        if not isinstance(b, str) or not b.strip():
            continue
        bid = b.strip()
        if bid not in allowed:
            raise ValueError(f"Unknown job board: {bid}")
        if bid not in cleaned:
            cleaned.append(bid)
    if not cleaned:
        raise ValueError("Select at least one job board")

    cfg = load_search_config()
    cfg["job_boards"] = cleaned
    path = writable_config_path()
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    CONFIG_FILE = path
    return cfg


def sources_payload() -> dict:
    cfg = load_search_config()
    enabled = set(cfg.get("job_boards", []))
    return {
        "boards": [
            {**b, "enabled": b["id"] in enabled} for b in AVAILABLE_JOB_BOARDS
        ],
        "job_boards": list(cfg.get("job_boards", [])),
        "config_path": str(writable_config_path()),
    }


def bootstrap() -> None:
    """Load local keys and ensure writable dirs exist. Call at process start."""
    global RESUME_FILE, CONFIG_FILE, DB_PATH
    user_data.apply_env_to_process()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = DATA_DIR / "jobs.db"

    if user_data.resume_path().exists():
        RESUME_FILE = user_data.resume_path()
    elif _REPO_RESUME.exists():
        RESUME_FILE = _REPO_RESUME
    else:
        RESUME_FILE = user_data.resume_path()

    appdata_cfg = user_data.user_data_dir() / "config.json"
    if appdata_cfg.exists():
        CONFIG_FILE = appdata_cfg
    elif _REPO_CONFIG.exists():
        CONFIG_FILE = _REPO_CONFIG


def resolve_prompt(prompt_file: str) -> Path:
    """Resolve prompt path whether given relative or absolute."""
    p = Path(prompt_file)
    if p.is_file():
        return p
    bundled = PROMPTS_DIR / p.name if p.name == p.as_posix() else BASE_DIR / prompt_file
    if bundled.is_file():
        return bundled
    return BASE_DIR / prompt_file


def validate_config() -> bool:
    """Validate the configuration file and required environment variables.

    Returns True if valid, raises ValueError with details if invalid.
    """
    bootstrap()
    if not RESUME_FILE.exists():
        raise ValueError(
            f"Resume file not found: {RESUME_FILE}. "
            "Complete onboarding or add resume.md."
        )

    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("config.json must be a JSON object")

            if "job_boards" in cfg:
                if not isinstance(cfg["job_boards"], list):
                    raise ValueError("job_boards must be a list")
                for board in cfg["job_boards"]:
                    if not isinstance(board, str):
                        raise ValueError(f"Invalid job board: {board}")
            # reddit_groups ignored if present (legacy)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config.json: {e}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return True


# Apply on import so db/agent see correct paths when possible
try:
    bootstrap()
except Exception:
    if "pytest" not in sys.modules:
        pass
