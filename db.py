"""SQLite database layer for the job scraper pipeline.

Provides schema creation, CRUD operations, and migration helpers.
All data previously stored in flat JSON files now lives here.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config

DB_PATH = config.DB_PATH
VALID_STATUSES = config.VALID_STATUSES


# ── connection ────────────────────────────────────────────
@contextmanager
def get_db():
    """Yield a connection with WAL mode, foreign keys, and auto-commit."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── schema ────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    jobs_found      INTEGER DEFAULT 0,
    above_threshold INTEGER DEFAULT 0,
    model_used      TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT '',
    posted_date     TEXT NOT NULL DEFAULT '',
    first_seen_run  INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    run_id          INTEGER REFERENCES runs(id),
    score           INTEGER NOT NULL DEFAULT 0,
    verdict         TEXT NOT NULL DEFAULT 'skip',
    work_arrangement TEXT NOT NULL DEFAULT '',
    match_reasons   TEXT NOT NULL DEFAULT '[]',
    red_flags       TEXT NOT NULL DEFAULT '[]',
    suggested_angle TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cover_letters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    run_id     INTEGER REFERENCES runs(id),
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_statuses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) UNIQUE,
    status     TEXT NOT NULL DEFAULT 'none',
    updated_at TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS raw_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs(id),
    title       TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    posted_date TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_scores_job    ON scores(job_id);
CREATE INDEX IF NOT EXISTS idx_scores_run    ON scores(run_id);
CREATE INDEX IF NOT EXISTS idx_cl_job        ON cover_letters(job_id);
CREATE INDEX IF NOT EXISTS idx_raw_run       ON raw_jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_url      ON jobs(url);
"""


def init_db():
    """Create all tables if they don't exist."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)


# ── timestamp helper ──────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── runs ──────────────────────────────────────────────────
def start_run(model_used: str | None = None) -> int:
    """Insert a new run row and return its ID."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, model_used) VALUES (?, 'running', ?)",
            (_now(), model_used or ""),
        )
        return cur.lastrowid


def finish_run(
    run_id: int, jobs_found: int = 0, above_threshold: int = 0, error: str | None = None
):
    """Mark a run as completed or failed."""
    status = "failed" if error else "completed"
    with get_db() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, jobs_found=?, above_threshold=?, "
            "error_message=? WHERE id=?",
            (_now(), status, jobs_found, above_threshold, error or "", run_id),
        )


def get_runs() -> list[dict]:
    """Return all runs, newest first."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


# ── jobs ──────────────────────────────────────────────────
def upsert_job(job: dict, run_id: int | None = None) -> int:
    """Insert or update a job by URL. Returns the job ID."""
    url = job.get("url", "")
    if not url:
        return 0
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()
        if existing:
            jid = existing["id"]
            conn.execute(
                "UPDATE jobs SET title=COALESCE(NULLIF(?,''),title), "
                "company=COALESCE(NULLIF(?,''),company), "
                "location=COALESCE(NULLIF(?,''),location), "
                "description=COALESCE(NULLIF(?,''),description), "
                "source=COALESCE(NULLIF(?,''),source), "
                "posted_date=COALESCE(NULLIF(?,''),posted_date) WHERE id=?",
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("description", ""),
                    job.get("source", ""),
                    job.get("posted_date", ""),
                    jid,
                ),
            )
        else:
            cur = conn.execute(
                "INSERT INTO jobs (url, title, company, location, description, "
                "source, posted_date, first_seen_run) VALUES (?,?,?,?,?,?,?,?)",
                (
                    url,
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("description", ""),
                    job.get("source", ""),
                    job.get("posted_date", ""),
                    run_id,
                ),
            )
            jid = cur.lastrowid
        return jid


def get_job_id_by_url(url: str) -> int | None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()
        return row["id"] if row else None


# ── scores ────────────────────────────────────────────────
def upsert_score(job_id: int, score_data: dict, run_id: int | None = None):
    """Insert a new score record (never updates — keeps history)."""
    if not job_id:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT INTO scores (job_id, run_id, score, verdict, work_arrangement, "
            "match_reasons, red_flags, suggested_angle, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                run_id,
                score_data.get("score", 0),
                score_data.get("verdict", "skip"),
                score_data.get("work_arrangement", ""),
                json.dumps(score_data.get("match_reasons", [])),
                json.dumps(score_data.get("red_flags", [])),
                score_data.get("suggested_angle", ""),
                _now(),
            ),
        )


def get_latest_scores() -> list[dict]:
    """Return the most recent score for each job, joined with job info."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT j.id, j.url, j.title, j.company, j.location, j.source,
                   j.posted_date,
                   s.score, s.verdict, s.work_arrangement,
                   s.match_reasons, s.red_flags, s.suggested_angle,
                   s.created_at AS scored_at
            FROM jobs j
            JOIN scores s ON s.id = (
                SELECT s2.id FROM scores s2
                WHERE s2.job_id = j.id
                ORDER BY s2.id DESC LIMIT 1
            )
            ORDER BY s.score DESC
        """).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["match_reasons"] = json.loads(d["match_reasons"])
            d["red_flags"] = json.loads(d["red_flags"])
            results.append(d)
        return results


# ── cover letters ─────────────────────────────────────────
def upsert_cover_letter(job_id: int, content: str, run_id: int | None = None):
    """Store a cover letter, replacing any existing one for this job."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM cover_letters WHERE job_id=?", (job_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE cover_letters SET content=?, created_at=?, run_id=? WHERE id=?",
                (content, _now(), run_id, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO cover_letters (job_id, run_id, content, created_at) "
                "VALUES (?,?,?,?)",
                (job_id, run_id, content, _now()),
            )


def get_cover_letter(job_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT content FROM cover_letters WHERE job_id=?", (job_id,)
        ).fetchone()
        return row["content"] if row else None


def update_cover_letter(job_id: int, content: str) -> bool:
    """Update an existing cover letter. Returns True if updated."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE cover_letters SET content=?, created_at=? WHERE job_id=?",
            (content, _now(), job_id),
        )
        return cur.rowcount > 0


# ── job statuses ──────────────────────────────────────────
def set_job_status(job_id: int, status: str, notes: str = ""):
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO job_statuses (job_id, status, updated_at, notes) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=?, updated_at=?, notes=?",
            (job_id, status, _now(), notes, status, _now(), notes),
        )


def get_job_status(job_id: int) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM job_statuses WHERE job_id=?", (job_id,)
        ).fetchone()
        return row["status"] if row else "none"


def get_all_statuses() -> dict[int, str]:
    """Return {job_id: status} for all tracked jobs."""
    with get_db() as conn:
        rows = conn.execute("SELECT job_id, status FROM job_statuses").fetchall()
        return {r["job_id"]: r["status"] for r in rows}


def get_status_counts() -> dict[str, int]:
    """Return {status: count} for funnel summary."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM job_statuses GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}


# ── raw jobs ──────────────────────────────────────────────
def insert_raw_jobs(raw_jobs: list[dict], run_id: int | None = None):
    """Bulk insert raw scraped jobs."""
    with get_db() as conn:
        for job in raw_jobs:
            conn.execute(
                "INSERT INTO raw_jobs (run_id, title, company, location, url, "
                "description, source, posted_date) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("url", ""),
                    job.get("description", ""),
                    job.get("source", ""),
                    job.get("posted_date", ""),
                ),
            )


# ── convenience: save full pipeline output ────────────────
def save_pipeline_output(scored_jobs: list[dict], run_id: int | None = None):
    """Save a list of scored job dicts (from AI analysis) into the DB."""
    for job_data in scored_jobs:
        # Upsert the job
        job_id = upsert_job(
            {
                "url": job_data.get("url", ""),
                "title": job_data.get("title", ""),
                "company": job_data.get("company", ""),
                "location": job_data.get("location", ""),
                "description": job_data.get("description", ""),
                "source": job_data.get("source", ""),
                "posted_date": job_data.get("posted_date", ""),
            },
            run_id,
        )
        # Upsert the score
        upsert_score(job_id, job_data, run_id)


def save_cover_letters(scored_jobs: list[dict], run_id: int | None = None):
    """Read cover letter files from disk and save to DB for given jobs."""
    from agent import _slug

    cl_dir = Path("output/cover_letters")
    for job_data in scored_jobs:
        company = job_data.get("company") or "unknown"
        title = job_data.get("title") or "role"
        slug = f"{_slug(company)}__{_slug(title)}"
        cl_path = cl_dir / f"{slug}.md"
        if cl_path.exists():
            job_id = get_job_id_by_url(job_data.get("url", ""))
            if job_id:
                content = cl_path.read_text(encoding="utf-8")
                upsert_cover_letter(job_id, content, run_id)


# ── API response builder ─────────────────────────────────
def get_jobs_for_api() -> list[dict]:
    """Build the full job list with scores and statuses for the frontend."""
    scores = get_latest_scores()
    statuses = get_all_statuses()
    for job in scores:
        job["status"] = statuses.get(job["id"], "none")
    return scores
