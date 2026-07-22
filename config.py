"""Centralized configuration for the job scraper pipeline.

All constants and configuration values are defined here.
"""

import json
from pathlib import Path

# ── paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
PROMPTS_DIR = BASE_DIR / "prompts"

# Database
DB_PATH = DATA_DIR / "jobs.db"

# Files
RESUME_FILE = BASE_DIR / "resume.md"
CONFIG_FILE = BASE_DIR / "config.json"

# ── pipeline settings ──────────────────────────────────
THRESHOLD = 70  # Minimum score for "apply" verdict

# ── free model rotation ────────────────────────────────
# Models are discovered dynamically by model_prober.py and cached in
# data/healthy_models.json. No hardcoded list needed.
MAX_RETRIES = 3  # Retries per model before moving to next
STALL_TIMEOUT = 600  # Hard cap on total runtime per attempt (10 minutes)
STALL_SILENCE_TIMEOUT = 90  # Kill if no output for this long (seconds)
PROBE_CACHE_TTL = 3600  # Re-probe models after this many seconds (1 hour)

# ── scraping settings ──────────────────────────────────
MAX_PAGES_TO_SCRAPE = 20
SCRAPE_TIMEOUT_MS = 120000  # listing pages (JobStreet, LinkedIn) are JS-heavy

# ── status lifecycle ───────────────────────────────────
VALID_STATUSES = ("none", "applied", "ignored", "interviewed", "rejected", "hired")

# ── default search config ──────────────────────────────
DEFAULT_CONFIG = {
    "job_boards": [
        "linkedin.com/jobs",
        "indeed.com",
        "wellfound.com",
        "glassdoor.com",
        "jobstreet.com",
        "onlinejobs.ph",
    ],
    "reddit_groups": [
        {"name": "Job boards", "subreddits": ["jobbit", "remotejobs", "WorkOnline"]},
        {"name": "Freelance/gig", "subreddits": ["freelance", "Upwork"]},
        {
            "name": "Community",
            "subreddits": ["forhire", "digitalnomad", "remotework"],
            "extra_terms": "hiring",
        },
    ],
}


def validate_config() -> bool:
    """Validate the configuration file and required environment variables.

    Returns True if valid, raises ValueError with details if invalid.
    """
    # Check required files
    if not RESUME_FILE.exists():
        raise ValueError(f"Resume file not found: {RESUME_FILE}")

    # Validate config.json if it exists
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("config.json must be a JSON object")

            # Validate job_boards if present
            if "job_boards" in cfg:
                if not isinstance(cfg["job_boards"], list):
                    raise ValueError("job_boards must be a list")
                for board in cfg["job_boards"]:
                    if not isinstance(board, str):
                        raise ValueError(f"Invalid job board: {board}")

            # Validate reddit_groups if present
            if "reddit_groups" in cfg:
                if not isinstance(cfg["reddit_groups"], list):
                    raise ValueError("reddit_groups must be a list")
                for group in cfg["reddit_groups"]:
                    if not isinstance(group, dict):
                        raise ValueError(f"Invalid reddit group: {group}")
                    if "name" not in group or "subreddits" not in group:
                        raise ValueError(f"Reddit group missing required fields: {group}")
                    if not isinstance(group["subreddits"], list):
                        raise ValueError(f"subreddits must be a list: {group}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config.json: {e}")

    # Validate database directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    return True
