"""SQLite database layer for the job scraper pipeline.

Provides schema creation, CRUD operations, and migration helpers.
All data previously stored in flat JSON files now lives here.

Two independent state machines, stored separately:
  - LISTING (jobs.listing_status + listing timestamps): system/scraper-controlled.
  - APPLICATION (applications row + application_events timeline): user-controlled.
Scraper writes never touch application state; user writes never touch listing state.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import config

DB_PATH = config.DB_PATH


# ── URL identity (shared with scrape dedupe) ──────────────
def _canonical_host(host: str) -> str:
    """Collapse www. and two-letter regional prefixes (in.indeed.com → indeed.com)."""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[0]) == 2:
        host = ".".join(labels[1:])
    return host


def url_dedup_key(url: str) -> str:
    """Canonical host + path + query — same identity soft-delete and scrape use."""
    p = urlparse(url)
    return f"{_canonical_host(p.netloc)}{p.path}?{p.query}"


def is_safe_http_url(url: str) -> bool:
    """Allow only http(s) URLs without credentials in the netloc."""
    if not url or not isinstance(url, str):
        return False
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc or "@" in p.netloc:
        return False
    return True


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
    step            INTEGER DEFAULT 0,
    label           TEXT DEFAULT '',
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
    first_seen_run  INTEGER REFERENCES runs(id),
    deleted_at      TEXT,
    listing_status  TEXT NOT NULL DEFAULT 'unknown',
    discovered_at   TEXT,
    last_scraped_at TEXT,
    last_verified_at TEXT,
    deadline_at     TEXT,
    source_job_id   TEXT
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

CREATE TABLE IF NOT EXISTS application_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'user',
    occurred_at TEXT NOT NULL,
    detail      TEXT
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_cl_job ON cover_letters(job_id);
CREATE INDEX IF NOT EXISTS idx_raw_run       ON raw_jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_url      ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_events_job    ON application_events(job_id);
"""

# applications is NOT in _SCHEMA: legacy DBs carry the data in job_statuses and
# must be migrated into a cleanly-shaped applications table first (see
# _migrate_legacy_statuses). Fresh DBs create it with this exact DDL.
_APPLICATIONS_DDL = """
CREATE TABLE applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(id) UNIQUE,
    status         TEXT NOT NULL DEFAULT 'not_reviewed',
    reason         TEXT,
    note           TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_opened_at TEXT,
    is_saved       INTEGER NOT NULL DEFAULT 0
)
"""

# Legacy single-enum status → new application status (idempotent UPDATEs).
# 'closed' additionally carries reason='legacy' + a note; rejected/hired/applied
# keep their names so need no remap row. 'none' and 'ignored' remap here.
_LEGACY_REMAP = [
    ("none", "not_reviewed", None, None),
    ("ignored", "skipped", None, None),
    (
        "closed",
        "skipped",
        "legacy",
        "Migrated: legacy status closed (listing closure unverified)",
    ),
    ("interviewed", "interviewing", None, None),
]

# Legacy status → timeline event_type. Statuses without a real occurrence
# (not_reviewed, skipped) get NO backfilled event — nothing happened.
_MIGRATED_STATUS_EVENT = {
    "applied": "applied",
    "interviewing": "interview",
    "offer": "offer",
    "hired": "hired",
    "rejected": "rejected",
}

# User status change → matching timeline event. not_reviewed gets none.
_STATUS_EVENT = {
    "applied": "applied",
    "interviewing": "interview",
    "offer": "offer",
    "hired": "hired",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
    "skipped": "other",
}


def _migrate_legacy_statuses(conn):
    """job_statuses → applications. Idempotent on fresh, legacy, and migrated DBs."""
    has_apps = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='applications'"
    ).fetchone()
    has_legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_statuses'"
    ).fetchone()

    if has_legacy and not has_apps:
        conn.execute("ALTER TABLE job_statuses RENAME TO applications_legacy")
        conn.execute(_APPLICATIONS_DDL)
        conn.execute(
            "INSERT INTO applications "
            "(job_id, status, reason, note, updated_at, created_at, last_opened_at) "
            "SELECT job_id, status, NULL, notes, updated_at, updated_at, viewed_at "
            "FROM applications_legacy"
        )
        conn.execute("DROP TABLE applications_legacy")
    elif not has_apps:
        conn.execute(_APPLICATIONS_DDL)
    else:
        # applications exists (migrated or fresh); ensure new columns if a
        # partial migration left the table short
        for col, typedef in (
            ("reason", "TEXT"),
            ("note", "TEXT"),
            ("created_at", "TEXT"),
            ("last_opened_at", "TEXT"),
            ("is_saved", "INTEGER DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists


    # Remap any surviving legacy status values (no-op once migrated / on fresh DBs)
    for old, new, reason, note in _LEGACY_REMAP:
        if reason:
            conn.execute(
                "UPDATE applications SET status=?, reason=?, note=? WHERE status=?",
                (new, reason, note, old),
            )
        else:
            conn.execute(
                "UPDATE applications SET status=? WHERE status=?", (new, old)
            )
    conn.execute(
        "UPDATE applications SET created_at=updated_at "
        "WHERE created_at IS NULL OR created_at=''"
    )

    # One timeline event per migrated application that represents an occurrence,
    # at its updated_at, only if none exists yet (idempotent backfill).
    for row in conn.execute(
        "SELECT job_id, status, updated_at FROM applications "
        "WHERE status IN ('applied','interviewing','offer','hired','rejected') "
        "AND NOT EXISTS (SELECT 1 FROM application_events e WHERE e.job_id = applications.job_id)"
    ).fetchall():
        conn.execute(
            "INSERT INTO application_events (job_id, event_type, source, occurred_at, detail) "
            "VALUES (?,?,?,?,NULL)",
            (
                row["job_id"],
                _MIGRATED_STATUS_EVENT[row["status"]],
                "system",
                row["updated_at"],
            ),
        )


def init_db():
    """Create all tables if they don't exist, and run migrations."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        _migrate_legacy_statuses(conn)
        # Migrations for existing databases
        for col, typedef, table in [
            ("step", "INTEGER DEFAULT 0", "runs"),
            ("label", "TEXT DEFAULT ''", "runs"),
            ("deleted_at", "TEXT", "jobs"),
            ("listing_status", "TEXT NOT NULL DEFAULT 'unknown'", "jobs"),
            ("discovered_at", "TEXT", "jobs"),
            ("last_scraped_at", "TEXT", "jobs"),
            ("last_verified_at", "TEXT", "jobs"),
            ("deadline_at", "TEXT", "jobs"),
            ("source_job_id", "TEXT", "jobs"),
            ("is_saved", "INTEGER DEFAULT 0", "applications"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Index after ALTER — existing DBs lack the columns until migration runs
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_deleted ON jobs(deleted_at)"
        )
        # One cover letter per job — drop dupes then enforce UNIQUE
        conn.execute(
            "DELETE FROM cover_letters WHERE id NOT IN "
            "(SELECT MAX(id) FROM cover_letters GROUP BY job_id)"
        )
        conn.execute("DROP INDEX IF EXISTS idx_cl_job")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cl_job ON cover_letters(job_id)"
        )


# ── timestamp helper ──────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    """Parse ISO timestamps; raise ValueError on empty/invalid (callers should catch)."""
    if not value or not str(value).strip():
        raise ValueError("empty timestamp")
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_waiting_signal(job: dict, now: datetime) -> bool:
    if job.get("application_status") != "applied":
        return False
    try:
        return _parse_utc(job.get("application_updated_at") or "") < now - timedelta(days=7)
    except (TypeError, ValueError):
        return False


def compute_expiring_signal(job: dict, now: datetime) -> bool:
    deadline = job.get("deadline_at")
    if not deadline:
        return False
    try:
        return _parse_utc(deadline) <= now + timedelta(days=7)
    except (TypeError, ValueError):
        return False


def compute_stale_signal(job: dict, now: datetime) -> bool:
    last = job.get("last_verified_at")
    if not last:
        return False
    try:
        return _parse_utc(last) < now - timedelta(days=14)
    except (TypeError, ValueError):
        return False


def compute_archive_candidate_signal(job: dict) -> bool:
    eff = job.get("effective_listing_status")
    return eff in ("closed", "expired") and job.get("application_status") == "not_reviewed"


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


def discard_run(run_id: int, reason: str = "cancelled before scoring") -> None:
    """Drop partial scrape data from a run that never finished scoring.

    Keeps prior jobs/applications. Removes this run's raw_jobs + scores, and
    jobs that only appeared in this run (no remaining scores).
    """
    with get_db() as conn:
        conn.execute("DELETE FROM raw_jobs WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM scores WHERE run_id=?", (run_id,))
        conn.execute(
            "DELETE FROM jobs WHERE first_seen_run=? "
            "AND id NOT IN (SELECT DISTINCT job_id FROM scores)",
            (run_id,),
        )
        conn.execute(
            "UPDATE runs SET finished_at=?, status='cancelled', "
            "jobs_found=0, above_threshold=0, error_message=? WHERE id=?",
            (_now(), reason, run_id),
        )


def get_active_run() -> dict | None:
    """Return the currently active run, or None if no run is active.
    Stale runs (older than 30 minutes) are automatically cleaned up.
    """
    with get_db() as conn:
        # Clean up stale runs older than 30 minutes
        conn.execute(
            "UPDATE runs SET status='failed', error_message='stale' "
            "WHERE status='running' AND datetime(started_at) < datetime('now', '-30 minutes')"
        )
        row = conn.execute(
            "SELECT id, step, label, status FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def update_run_step(run_id: int, step: int, label: str):
    """Update the current step of an active run."""
    with get_db() as conn:
        conn.execute(
            "UPDATE runs SET step=?, label=? WHERE id=?",
            (step, label, run_id),
        )


def get_runs() -> list[dict]:
    """Return all runs, newest first."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_last_completed_run() -> dict | None:
    """Return the most recent completed run, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, finished_at, jobs_found, above_threshold, started_at "
            "FROM runs WHERE status='completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# ── jobs ──────────────────────────────────────────────────
def upsert_job(job: dict, run_id: int | None = None, conn=None) -> int:
    """Insert or update a job by URL. Returns the job ID.

    Soft-deleted rows are left alone (still returns their id) so callers can
    decide to skip scoring — they are never undeleted by a scrape.

    Writes ONLY identity + listing fields. Never touches application state.
    """
    url = job.get("url", "")
    if not url:
        return 0
    if conn is not None:
        return _upsert_job(conn, job, run_id)
    with get_db() as c:
        return _upsert_job(c, job, run_id)


def _upsert_job(conn, job: dict, run_id: int | None = None) -> int:
    url = job.get("url", "")
    existing = conn.execute(
        "SELECT id, deleted_at FROM jobs WHERE url=?", (url,)
    ).fetchone()
    if existing:
        jid = existing["id"]
        if existing["deleted_at"]:
            return jid  # keep soft-deleted; do not refresh fields
        conn.execute(
            "UPDATE jobs SET title=COALESCE(NULLIF(?,''),title), "
            "company=COALESCE(NULLIF(?,''),company), "
            "location=COALESCE(NULLIF(?,''),location), "
            "description=COALESCE(NULLIF(?,''),description), "
            "source=COALESCE(NULLIF(?,''),source), "
            "posted_date=COALESCE(NULLIF(?,''),posted_date), "
            "listing_status=COALESCE(NULLIF(?,''),listing_status), "
            "last_scraped_at=COALESCE(?,last_scraped_at), "
            "last_verified_at=COALESCE(?,last_verified_at), "
            "deadline_at=COALESCE(?,deadline_at), "
            "source_job_id=COALESCE(?,source_job_id) WHERE id=?",
            (
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("description", ""),
                job.get("source", ""),
                job.get("posted_date", ""),
                job.get("listing_status", ""),
                job.get("last_scraped_at"),
                job.get("last_verified_at"),
                job.get("deadline_at"),
                job.get("source_job_id"),
                jid,
            ),
        )
        return jid
    cur = conn.execute(
        "INSERT INTO jobs (url, title, company, location, description, "
        "source, posted_date, first_seen_run, listing_status, discovered_at, "
        "last_scraped_at, last_verified_at, deadline_at, source_job_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            url,
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("description", ""),
            job.get("source", ""),
            job.get("posted_date", ""),
            run_id,
            job.get("listing_status", "unknown") or "unknown",
            job.get("discovered_at") or _now(),
            job.get("last_scraped_at"),
            job.get("last_verified_at"),
            job.get("deadline_at"),
            job.get("source_job_id"),
        ),
    )
    return cur.lastrowid


def soft_delete_job_by_url(url: str) -> bool:
    """Soft-delete a job so it stays hidden and is skipped on future scrapes."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET deleted_at=? WHERE url=? AND deleted_at IS NULL",
            (_now(), url),
        )
        return cur.rowcount > 0


def restore_job_by_url(url: str) -> bool:
    """Undo a soft-delete."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET deleted_at=NULL WHERE url=? AND deleted_at IS NOT NULL",
            (url,),
        )
        return cur.rowcount > 0


def is_url_soft_deleted(url: str) -> bool:
    """True if any soft-deleted job shares this URL's canonical identity."""
    if not url:
        return False
    key = url_dedup_key(url)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url FROM jobs WHERE deleted_at IS NOT NULL"
        ).fetchall()
        return any(url_dedup_key(r["url"]) == key for r in rows)


def get_soft_deleted_urls() -> list[str]:
    """URLs that must be treated as seen during scrape dedupe."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url FROM jobs WHERE deleted_at IS NOT NULL"
        ).fetchall()
        return [r["url"] for r in rows]


def abandon_orphan_runs(reason: str = "server restarted") -> int:
    """Mark leftover status=running rows failed (lock is process-local)."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE runs SET finished_at=?, status='failed', error_message=? "
            "WHERE status='running'",
            (_now(), reason),
        )
        return cur.rowcount


def get_job_id_by_url(url: str) -> int | None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()
        return row["id"] if row else None


# ── listing state (system/scraper-controlled) ─────────────
def set_listing_status(
    job_id: int,
    listing_status: str | None = None,
    deadline_at: str | None = None,
    last_verified_at: str | None = None,
    last_scraped_at: str | None = None,
    source_job_id: str | None = None,
):
    """Update ONLY listing fields on jobs. Never touches application state.
    Pass None to leave a field unchanged.
    """
    if listing_status is not None and listing_status not in config.LISTING_STATUSES:
        raise ValueError(
            f"Invalid listing_status: {listing_status}. "
            f"Must be one of {config.LISTING_STATUSES}"
        )
    sets = []
    params = []
    for col, val in (
        ("listing_status", listing_status),
        ("deadline_at", deadline_at),
        ("last_verified_at", last_verified_at),
        ("last_scraped_at", last_scraped_at),
        ("source_job_id", source_job_id),
    ):
        if val is not None:
            sets.append(f"{col}=?")
            params.append(val)
    if not sets:
        return
    params.append(job_id)
    with get_db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", params)


def effective_listing_status(job: dict, now: datetime | None = None) -> str:
    """Stored listing status + derived freshness. Derived only when stored is 'active'.

    Precedence: expired > expiring > stale > stored value. Non-active stored
    statuses (closed/not_accepting/unavailable/unknown) are returned as-is —
    never re-derived, so a verified closure can't decay into 'stale'.
    """
    now = now or datetime.now(timezone.utc)
    stored = job.get("listing_status") or "unknown"
    if stored != "active":
        return stored
    deadline = job.get("deadline_at")
    if deadline:
        try:
            dl = _parse_utc(deadline)
            if dl <= now:
                return "expired"
            if dl <= now + timedelta(days=config.LISTING_EXPIRING_BEFORE_DAYS):
                return "expiring"
        except ValueError:
            pass
    last = job.get("last_verified_at")
    if last:
        try:
            lv = _parse_utc(last)
            if lv < now - timedelta(days=config.LISTING_STALE_AFTER_DAYS):
                return "stale"
        except ValueError:
            pass
    return stored


def display_label(application_status: str, effective_listing_status: str) -> str:
    """Derived overall display label — the only third view, never stored.

    Terminal application states (rejected/hired/withdrawn) win outright.
    In-progress states combine with a closed listing. Not-started states show
    the listing state.
    """
    app = application_status or "not_reviewed"
    eff = effective_listing_status or "unknown"
    if app in ("rejected", "hired", "withdrawn"):
        return config.APPLICATION_LABELS[app]
    if app in ("applied", "interviewing", "offer"):
        label = config.APPLICATION_LABELS[app]
        if eff in ("closed", "unavailable", "expired"):
            return f"{label} · Listing Closed"
        return label
    if app == "skipped":
        return "Skipped"
    return config.LISTING_LABELS.get(eff, "Not Reviewed")


# ── scores ────────────────────────────────────────────────
def upsert_score(job_id: int, score_data: dict, run_id: int | None = None, conn=None):
    """Insert a new score record (never updates — keeps history)."""
    if not job_id:
        return
    if conn is not None:
        _upsert_score(conn, job_id, score_data, run_id)
        return
    with get_db() as c:
        _upsert_score(c, job_id, score_data, run_id)


def _upsert_score(conn, job_id: int, score_data: dict, run_id: int | None = None):
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
    """Return the most recent score for each job, joined with listing + application info."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT j.id, j.url, j.title, j.company, j.location, j.source,
                   j.description, j.posted_date,
                   COALESCE(j.listing_status, 'unknown') AS listing_status,
                   j.discovered_at, j.last_scraped_at, j.last_verified_at,
                   j.deadline_at, j.source_job_id,
                   a.status AS application_status,
                   a.reason AS application_reason,
                   a.note AS application_note,
                   a.updated_at AS application_updated_at,
                   a.created_at AS application_created_at,
                   a.last_opened_at,
                   a.is_saved,
                   s.score, s.verdict, s.work_arrangement,
                   s.match_reasons, s.red_flags, s.suggested_angle,
                   s.created_at AS scored_at,
                   EXISTS(SELECT 1 FROM cover_letters cl WHERE cl.job_id = j.id)
                     AS has_cover_letter
            FROM jobs j
            JOIN scores s ON s.id = (
                SELECT s2.id FROM scores s2
                WHERE s2.job_id = j.id
                ORDER BY s2.id DESC LIMIT 1
            )
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE j.deleted_at IS NULL
            ORDER BY s.score DESC
        """).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["match_reasons"] = json.loads(d["match_reasons"])
            d["red_flags"] = json.loads(d["red_flags"])
            d["has_cover_letter"] = bool(d["has_cover_letter"])
            results.append(d)
        return results


# ── cover letters ─────────────────────────────────────────
def upsert_cover_letter(job_id: int, content: str, run_id: int | None = None):
    """Store a cover letter, replacing any existing one for this job."""
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM cover_letters WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE cover_letters SET content=?, created_at=?, run_id=? WHERE id=?",
                (content, _now(), run_id, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO cover_letters (job_id, run_id, content, created_at) VALUES (?,?,?,?)",
                (job_id, run_id, content, _now()),
            )


def get_cover_letter(job_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT content FROM cover_letters WHERE job_id=?", (job_id,)).fetchone()
        return row["content"] if row else None


def set_job_saved(url: str, saved: bool) -> bool:
    """Toggle the is_saved flag for a job by URL."""
    job_id = get_job_id_by_url(url)
    if not job_id:
        return False
    with get_db() as conn:
        conn.execute(
            "INSERT INTO applications (job_id, status, updated_at, created_at, is_saved) "
            "VALUES (?, 'not_reviewed', ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET is_saved=?",
            (job_id, _now(), _now(), int(saved), int(saved)),
        )
        return True

# ── applications (user-controlled) ────────────────────────
def set_application_status(
    job_id: int,
    status: str,
    reason: str | None = None,
    note: str | None = None,
    source: str = "user",
):
    """Upsert the application row AND append a matching timeline event.

    None reason/note leaves the stored value unchanged (pass "" to clear) so a
    status-only update never silently wipes a saved note/reason.
    Never touches jobs.listing_status or listing timestamps.
    """
    if status not in config.APPLICATION_STATUSES:
        raise ValueError(
            f"Invalid application status: {status}. "
            f"Must be one of {config.APPLICATION_STATUSES}"
        )
    if source not in config.EVENT_SOURCES:
        raise ValueError(f"Invalid event source: {source}")
    raw_reason, raw_note = reason, note
    with get_db() as conn:
        now = _now()
        existing = conn.execute(
            "SELECT reason, note FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
        if existing:
            reason = existing["reason"] if reason is None else (reason or None)
            note = existing["note"] if note is None else (note or "")
        else:
            reason = reason or None
            note = note or ""
        conn.execute(
            "INSERT INTO applications "
            "(job_id, status, reason, note, updated_at, created_at, last_opened_at) "
            "VALUES (?,?,?,?,?,?,NULL) "
            "ON CONFLICT(job_id) DO UPDATE SET status=?, reason=?, note=?, updated_at=?",
            (
                job_id, status, reason, note, now, now,
                status, reason, note, now,
            ),
        )
        event_type = _STATUS_EVENT.get(status)
        if event_type:
            # event detail reflects THIS action's own inputs, not preserved
            # fields, so an old note can't leak into a skip event's detail
            detail = raw_note or (raw_reason if status == "skipped" else None)
            add_event(job_id, event_type, source=source, detail=detail, conn=conn, occurred_at=now)


def add_event(
    job_id: int,
    event_type: str,
    source: str = "user",
    detail: str | None = None,
    occurred_at: str | None = None,
    conn=None,
):
    """Append one row to application_events."""
    if event_type not in config.EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}. Must be one of {config.EVENT_TYPES}")
    if source not in config.EVENT_SOURCES:
        raise ValueError(f"Invalid event source: {source}")

    def _insert(c):
        c.execute(
            "INSERT INTO application_events (job_id, event_type, source, occurred_at, detail) "
            "VALUES (?,?,?,?,?)",
            (job_id, event_type, source, occurred_at or _now(), detail),
        )

    if conn is not None:
        _insert(conn)
    else:
        with get_db() as c:
            _insert(c)


def mark_opened(job_url: str) -> str | None:
    """User clicked Open Listing. Sets last_opened_at ONLY.

    Ensures an application row exists (default not_reviewed). Never touches
    listing_status and never appends a timeline event.
    """
    with get_db() as conn:
        job = conn.execute("SELECT id FROM jobs WHERE url=?", (job_url,)).fetchone()
        if not job:
            return None
        now = _now()
        conn.execute(
            "INSERT INTO applications (job_id, status, updated_at, created_at, last_opened_at) "
            "VALUES (?, 'not_reviewed', ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET last_opened_at=?",
            (job["id"], now, now, now, now),
        )
        return now


def get_application(job_id: int) -> dict | None:
    """Full application row, or None if the user never touched this job."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT job_id, status, reason, note, updated_at, created_at, last_opened_at "
            "FROM applications WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None


def get_application_status(job_id: int) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
        return row["status"] if row else "not_reviewed"


def get_timeline(job_id: int) -> dict:
    """Application row + events, newest first, for the timeline UI."""
    with get_db() as conn:
        app = conn.execute(
            "SELECT status FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
        rows = conn.execute(
            "SELECT id, event_type, source, occurred_at, detail FROM application_events "
            "WHERE job_id=? ORDER BY occurred_at DESC, id DESC",
            (job_id,),
        ).fetchall()
        return {
            "job_id": job_id,
            "application_status": app["status"] if app else "not_reviewed",
            "events": [dict(r) for r in rows],
        }


def get_status_counts() -> dict:
    """Counts by application and listing status over the /api/jobs universe
    (scored, not soft-deleted)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(a.status, 'not_reviewed') AS app_status,
                   COALESCE(j.listing_status, 'unknown') AS listing_status,
                   COUNT(*) AS cnt
            FROM jobs j
            JOIN scores s ON s.id = (
                SELECT s2.id FROM scores s2
                WHERE s2.job_id = j.id
                ORDER BY s2.id DESC LIMIT 1
            )
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE j.deleted_at IS NULL
            GROUP BY app_status, listing_status
            """
        ).fetchall()
    app_counts = dict.fromkeys(config.APPLICATION_STATUSES, 0)
    listing_counts = dict.fromkeys(config.LISTING_STATUSES, 0)
    for r in rows:
        app_counts[r["app_status"]] = app_counts.get(r["app_status"], 0) + r["cnt"]
        listing_counts[r["listing_status"]] = (
            listing_counts.get(r["listing_status"], 0) + r["cnt"]
        )
    return {"application": app_counts, "listing": listing_counts}


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
def save_pipeline_output(scored_jobs: list[dict], run_id: int | None = None) -> dict:
    """Save a list of scored job dicts (from AI analysis) into the DB.

    Soft-deleted URLs are skipped so a re-scrape never resurrects them.
    One transaction for the whole batch. Writes only jobs + scores — never
    application state. Returns {"new": int, "updated": int}.
    """
    deleted = {url_dedup_key(u) for u in get_soft_deleted_urls()}
    new_count = updated_count = 0
    with get_db() as conn:
        for job_data in scored_jobs:
            url = job_data.get("url", "")
            if not url or url_dedup_key(url) in deleted:
                continue
            existing = conn.execute(
                "SELECT id, deleted_at FROM jobs WHERE url=?", (url,)
            ).fetchone()
            if existing and existing["deleted_at"]:
                continue
            is_new = existing is None
            job_id = upsert_job(
                {
                    "url": url,
                    "title": job_data.get("title", ""),
                    "company": job_data.get("company", ""),
                    "location": job_data.get("location", ""),
                    "description": job_data.get("description", ""),
                    "source": job_data.get("source", ""),
                    "posted_date": job_data.get("posted_date", ""),
                    "listing_status": job_data.get("listing_status"),
                    "deadline_at": job_data.get("deadline_at"),
                    "last_scraped_at": job_data.get("last_scraped_at"),
                    "last_verified_at": job_data.get("last_verified_at"),
                    "source_job_id": job_data.get("source_job_id"),
                },
                run_id,
                conn=conn,
            )
            upsert_score(job_id, job_data, run_id, conn=conn)
            if is_new:
                new_count += 1
            else:
                updated_count += 1
    return {"new": new_count, "updated": updated_count}


# ── API response builder ─────────────────────────────────
def get_jobs_for_api() -> list[dict]:
    """Build the full job list with scores, listing state, application state,
    and the derived overall display label for the frontend."""
    scores = get_latest_scores()
    for job in scores:
        app_status = job.get("application_status") or "not_reviewed"
        job["application_status"] = app_status
        job["status"] = app_status
        eff = effective_listing_status(job)
        job["effective_listing_status"] = eff
        job["listing_derived"] = (
            eff if eff in ("stale", "expiring", "expired") else None
        )
        job["display_label"] = display_label(app_status, eff)
        
        now = datetime.now(timezone.utc)
        job["signal_waiting"] = compute_waiting_signal(job, now)
        job["signal_expiring"] = compute_expiring_signal(job, now)
        job["signal_stale"] = compute_stale_signal(job, now)
        job["signal_archive"] = compute_archive_candidate_signal(job)
        job["is_saved"] = bool(job.get("is_saved"))
    return scores
