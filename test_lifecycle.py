"""Lifecycle tests for the dual state machines (listing vs application).

Covers: state independence, reasons, timeline events, source metadata,
last_opened_at rules, bulk-apply safety, status counts, derived listing
statuses, display labels, and migration fidelity of the legacy single enum.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<html><body>UI</body></html>")
    (tmp_path / "data").mkdir()
    (tmp_path / "output").mkdir()
    import importlib

    import db
    import server

    importlib.reload(server)
    db.DB_PATH = tmp_path / "data" / "jobs.db"
    db.init_db()
    return TestClient(server.app)


def _insert_job(db, url="https://example.com/job1", score=85):
    job_id = db.upsert_job(
        {
            "title": "Frontend Engineer",
            "url": url,
            "company": "Tech Holding",
            "location": "Remote",
            "description": "",
            "source": "indeed.com",
            "posted_date": "",
        }
    )
    db.upsert_score(
        job_id,
        {
            "score": score,
            "verdict": "review",
            "work_arrangement": "",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        },
    )
    return job_id


def _events(db, job_id):
    with db.get_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, event_type, source, occurred_at, detail "
                "FROM application_events WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ]


# ── config enums ─────────────────────────────────────────
def test_config_enums():
    import config

    assert config.LISTING_STATUSES == (
        "active", "closed", "not_accepting", "unavailable", "unknown",
    )
    assert set(config.APPLICATION_STATUSES) == {
        "not_reviewed", "skipped", "applied", "interviewing",
        "offer", "hired", "rejected", "withdrawn",
    }
    assert "none" not in config.APPLICATION_STATUSES
    assert "ignored" not in config.APPLICATION_STATUSES
    assert "interviewed" not in config.APPLICATION_STATUSES
    assert "closed" not in config.APPLICATION_STATUSES
    assert "location" in config.SKIP_REASONS
    assert "position_filled" in config.REJECTION_REASONS
    assert set(config.EVENT_TYPES) >= {
        "applied", "interview", "offer", "hired", "rejected", "other",
    }
    assert config.LISTING_STALE_AFTER_DAYS > 0
    assert config.LISTING_EXPIRING_BEFORE_DAYS > 0


# ── application state ────────────────────────────────────
def test_application_update_writes_status_reason_note_and_event(client, tmp_path):
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "applied",
              "reason": "skills", "note": "Sent custom intro"},
    )
    assert res.status_code == 200
    assert res.json()["application_status"] == "applied"

    app = db.get_application(job_id)
    assert app["status"] == "applied"
    assert app["reason"] == "skills"
    assert app["note"] == "Sent custom intro"
    assert app["updated_at"]

    evs = _events(db, job_id)
    assert len(evs) == 1
    assert evs[0]["event_type"] == "applied"
    assert evs[0]["source"] == "user"


def test_status_rejects_invalid_application_status(client):
    client.post("/api/status", json={"url": "https://example.com/job1", "status": "maybe"})
    _insert_job(__import__("db"))
    res = client.post("/api/status", json={"url": "https://example.com/job1", "status": "maybe"})
    assert res.status_code == 400
    res = client.post("/api/status", json={"url": "https://example.com/job1", "status": "none"})
    assert res.status_code == 400
    res = client.post("/api/status", json={"url": "https://example.com/job1", "status": "ignored"})
    assert res.status_code == 400


def test_skipped_appends_other_event_with_reason(client, tmp_path):
    import db

    job_id = _insert_job(db)
    client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "skipped", "reason": "location"},
    )
    app = db.get_application(job_id)
    assert app["status"] == "skipped"
    assert app["reason"] == "location"
    evs = _events(db, job_id)
    assert evs[0]["event_type"] == "other"
    assert evs[0]["detail"] == "location"


# ── listing state ────────────────────────────────────────
def test_listing_update_sets_listing_fields_only(client, tmp_path):
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/listing",
        json={"url": "https://example.com/job1", "listing_status": "closed",
              "deadline_at": "2026-08-01T00:00:00+00:00"},
    )
    assert res.status_code == 200
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, deadline_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["listing_status"] == "closed"
    assert row["deadline_at"] == "2026-08-01T00:00:00+00:00"
    # no application row was created or touched
    assert db.get_application(job_id) is None
    assert _events(db, job_id) == []


def test_listing_rejects_invalid_listing_status(client):
    _insert_job(__import__("db"))
    res = client.post(
        "/api/listing",
        json={"url": "https://example.com/job1", "listing_status": "gone"},
    )
    assert res.status_code == 400


# ── state independence ───────────────────────────────────
def test_listing_close_does_not_change_application(client, tmp_path):
    import db

    job_id = _insert_job(db)
    db.set_application_status(job_id, "applied", note="in progress")

    client.post(
        "/api/listing",
        json={"url": "https://example.com/job1", "listing_status": "closed"},
    )

    app = db.get_application(job_id)
    assert app["status"] == "applied"
    assert app["note"] == "in progress"
    assert len(_events(db, job_id)) == 1  # only the applied event

    # and the reverse: application update never touches listing
    db.set_application_status(job_id, "rejected")
    with db.get_db() as conn:
        row = conn.execute("SELECT listing_status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["listing_status"] == "closed"


def test_scraper_upsert_keeps_application_state(client, tmp_path):
    import db

    job_id = _insert_job(db)
    db.set_application_status(job_id, "applied", reason="skills")

    db.save_pipeline_output(
        [
            {
                "url": "https://example.com/job1",
                "title": "Frontend Engineer",
                "company": "Tech Holding",
                "score": 99,
                "verdict": "apply",
                "listing_status": "closed",
                "last_scraped_at": "2026-08-13T10:00:00+00:00",
                "match_reasons": [],
                "red_flags": [],
            }
        ]
    )

    app = db.get_application(job_id)
    assert app["status"] == "applied"
    assert app["reason"] == "skills"
    assert len(_events(db, job_id)) == 1
    with db.get_db() as conn:
        row = conn.execute("SELECT listing_status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["listing_status"] == "closed"


def test_scraper_never_sets_last_opened_at(client, tmp_path):
    import db

    job_id = _insert_job(db, url="https://example.com/scraped")
    db.save_pipeline_output(
        [{"url": "https://example.com/scraped", "title": "T", "score": 90, "verdict": "apply"}]
    )
    db.set_listing_status(job_id, listing_status="closed")
    client.post("/api/bulk-apply")
    assert db.get_application(job_id)["last_opened_at"] is None


# ── last_opened_at (user-open only) ──────────────────────
def test_mark_open_sets_last_opened_at_only(client, tmp_path):
    import db

    job_id = _insert_job(db)
    res = client.post("/api/open", json={"url": "https://example.com/job1"})
    assert res.status_code == 200
    ts = res.json()["last_opened_at"]
    assert ts

    app = db.get_application(job_id)
    assert app["last_opened_at"] == ts
    assert app["status"] == "not_reviewed"  # open must not change status
    assert _events(db, job_id) == []        # and must not create timeline noise
    with db.get_db() as conn:
        row = conn.execute("SELECT listing_status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["listing_status"] == "unknown"  # listing untouched


def test_mark_open_does_not_reset_application_state(client, tmp_path):
    import db

    job_id = _insert_job(db)
    db.set_application_status(job_id, "interviewing")
    client.post("/api/open", json={"url": "https://example.com/job1"})
    assert db.get_application_status(job_id) == "interviewing"


def test_mark_open_unknown_job_returns_404(client):
    res = client.post("/api/open", json={"url": "https://nowhere.example"})
    assert res.status_code == 404


# ── timeline ─────────────────────────────────────────────
def test_timeline_endpoint_orders_newest_first(client, tmp_path):
    import db

    job_id = _insert_job(db)
    db.set_application_status(job_id, "applied")
    db.set_application_status(job_id, "interviewing")

    res = client.get("/api/timeline?url=https%3A%2F%2Fexample.com%2Fjob1")
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == job_id
    assert body["application_status"] == "interviewing"
    assert [e["event_type"] for e in body["events"]] == ["interview", "applied"]
    assert all(e["source"] == "user" for e in body["events"])


def test_timeline_unknown_job_returns_404(client):
    res = client.get("/api/timeline?url=" + quote("https://nowhere.example", safe=""))
    assert res.status_code == 404


# ── bulk-apply safety ────────────────────────────────────
def test_bulk_apply_never_overwrites_existing_application_state(client, tmp_path):
    import db

    fresh = _insert_job(db, url="https://example.com/a", score=95)
    applied = _insert_job(db, url="https://example.com/b", score=95)
    interviewing = _insert_job(db, url="https://example.com/c", score=95)
    skipped = _insert_job(db, url="https://example.com/d", score=95)
    rejected = _insert_job(db, url="https://example.com/e", score=95)
    db.set_application_status(applied, "applied")
    db.set_application_status(interviewing, "interviewing")
    db.set_application_status(skipped, "skipped", reason="location")
    db.set_application_status(rejected, "rejected")

    res = client.post("/api/bulk-apply")
    assert res.status_code == 200
    assert res.json()["urls"] == ["https://example.com/a"]

    assert db.get_application_status(applied) == "applied"
    assert db.get_application_status(interviewing) == "interviewing"
    assert db.get_application_status(skipped) == "skipped"
    assert db.get_application_status(rejected) == "rejected"
    assert db.get_application_status(fresh) == "applied"


# ── status counts ────────────────────────────────────────
def test_status_counts_structure(client, tmp_path):
    import config
    import db

    live = _insert_job(db, url="https://example.com/live", score=80)
    db.set_application_status(live, "applied")
    db.set_listing_status(live, listing_status="closed")

    counts = client.get("/api/status-counts").json()
    assert set(counts["application"]) == set(config.APPLICATION_STATUSES)
    assert set(counts["listing"]) == set(config.LISTING_STATUSES)
    assert counts["application"]["applied"] == 1
    assert counts["listing"]["closed"] == 1
    assert counts["listing"]["active"] == 0


# ── /api/jobs payload ────────────────────────────────────
def test_jobs_payload_includes_dual_state_and_display_label(client, tmp_path):
    import db

    job_id = _insert_job(db)
    db.set_application_status(job_id, "applied", reason="skills", note="sent")
    client.post("/api/open", json={"url": "https://example.com/job1"})
    client.post(
        "/api/listing",
        json={"url": "https://example.com/job1", "listing_status": "closed"},
    )

    job = client.get("/api/jobs").json()[0]
    assert job["application_status"] == "applied"
    assert job["status"] == "applied"
    assert job["application_reason"] == "skills"
    assert job["application_note"] == "sent"
    assert job["last_opened_at"]
    assert job["application_updated_at"]
    assert job["listing_status"] == "closed"
    assert job["effective_listing_status"] == "closed"
    assert job["listing_derived"] is None
    assert job["display_label"] == "Applied · Listing Closed"
    assert "deadline_at" in job and "last_verified_at" in job and "source_job_id" in job


def test_jobs_payload_reports_derived_listing(client, tmp_path):
    import db

    job_id = _insert_job(db)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.set_listing_status(job_id, listing_status="active", deadline_at=past)

    job = client.get("/api/jobs").json()[0]
    assert job["effective_listing_status"] == "expired"
    assert job["listing_derived"] == "expired"
    assert job["display_label"] == "Expired"  # not_reviewed + expired


# ── derived listing statuses ─────────────────────────────
def test_effective_listing_status_derivation():
    import db

    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    day = timedelta(days=1)

    def job(listing_status="active", deadline_at=None, last_verified_at=None):
        return {"listing_status": listing_status, "deadline_at": deadline_at,
                "last_verified_at": last_verified_at}

    assert db.effective_listing_status(job(deadline_at=(now - day).isoformat()), now) == "expired"
    assert db.effective_listing_status(job(deadline_at=(now + day).isoformat()), now) == "expiring"
    assert db.effective_listing_status(
        job(last_verified_at=(now - timedelta(days=8)).isoformat()), now
    ) == "stale"
    assert db.effective_listing_status(
        job(last_verified_at=(now - day).isoformat()), now
    ) == "active"
    # non-active stored statuses are never re-derived
    assert db.effective_listing_status(
        job("closed", deadline_at=(now - day).isoformat()), now
    ) == "closed"
    assert db.effective_listing_status(
        job("unknown", last_verified_at=(now - timedelta(days=30)).isoformat()), now
    ) == "unknown"


def test_display_label_rules():
    import db

    assert db.display_label("not_reviewed", "active") == "Not Reviewed"
    assert db.display_label("not_reviewed", "unknown") == "Not Reviewed"
    assert db.display_label("not_reviewed", "expired") == "Expired"
    assert db.display_label("not_reviewed", "expiring") == "Expiring Soon"
    assert db.display_label("not_reviewed", "closed") == "Listing Closed"
    assert db.display_label("skipped", "active") == "Skipped"
    assert db.display_label("applied", "closed") == "Applied · Listing Closed"
    assert db.display_label("applied", "active") == "Applied"
    assert db.display_label("interviewing", "expired") == "Interviewing · Listing Closed"
    assert db.display_label("offer", "active") == "Offer"
    assert db.display_label("rejected", "closed") == "Rejected"
    assert db.display_label("hired", "expired") == "Hired"
    assert db.display_label("withdrawn", "active") == "Withdrawn"


# ── migration fidelity ───────────────────────────────────
def _make_legacy_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
            step INTEGER DEFAULT 0, label TEXT DEFAULT '',
            jobs_found INTEGER DEFAULT 0, above_threshold INTEGER DEFAULT 0,
            model_used TEXT, error_message TEXT);
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL DEFAULT '', company TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '', posted_date TEXT NOT NULL DEFAULT '',
            first_seen_run INTEGER REFERENCES runs(id), deleted_at TEXT);
        CREATE TABLE job_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES jobs(id) UNIQUE,
            status TEXT NOT NULL DEFAULT 'none', updated_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', viewed_at TEXT);
        """
    )
    for url, status, updated_at, viewed_at in rows:
        cur = conn.execute(
            "INSERT INTO jobs (url, title, company) VALUES (?,?,?)", (url, "T", "C")
        )
        conn.execute(
            "INSERT INTO job_statuses (job_id, status, updated_at, viewed_at) VALUES (?,?,?,?)",
            (cur.lastrowid, status, updated_at, viewed_at),
        )
    conn.commit()
    conn.close()


def test_migration_fidelity(tmp_path):
    """Legacy single-enum data must migrate losslessly; rejected/hired/
    interviewed must NOT collapse into skipped; nothing fabricated."""
    import db

    p = tmp_path / "data" / "jobs.db"
    (tmp_path / "data").mkdir()
    _make_legacy_db(
        p,
        [
            ("https://a.example", "rejected", "2026-07-01T10:00:00+00:00", None),
            ("https://b.example", "hired", "2026-07-02T10:00:00+00:00", None),
            ("https://c.example", "interviewed", "2026-07-03T10:00:00+00:00", None),
            ("https://d.example", "applied", "2026-07-04T10:00:00+00:00",
             "2026-07-05T10:00:00+00:00"),
            ("https://e.example", "ignored", "2026-07-06T10:00:00+00:00", None),
            ("https://f.example", "closed", "2026-07-07T10:00:00+00:00", None),
            ("https://g.example", "none", "2026-07-08T10:00:00+00:00", None),
        ],
    )
    db.DB_PATH = p
    db.init_db()

    with db.get_db() as conn:
        apps = {
            r["url"]: dict(r)
            for r in conn.execute(
                "SELECT j.url, a.* FROM applications a JOIN jobs j ON j.id = a.job_id"
            )
        }
        evs = {
            r["url"]: dict(r)
            for r in conn.execute(
                "SELECT j.url, e.* FROM application_events e JOIN jobs j ON j.id = e.job_id"
            )
        }
        listing = {
            r["url"]: r["listing_status"]
            for r in conn.execute("SELECT url, listing_status FROM jobs")
        }

    assert apps["https://a.example"]["status"] == "rejected"
    assert apps["https://b.example"]["status"] == "hired"
    assert apps["https://c.example"]["status"] == "interviewing"
    assert apps["https://d.example"]["status"] == "applied"
    assert apps["https://e.example"]["status"] == "skipped"
    assert apps["https://e.example"]["reason"] is None
    assert apps["https://f.example"]["status"] == "skipped"
    assert apps["https://f.example"]["reason"] == "legacy"
    assert "closed" in (apps["https://f.example"]["note"] or "").lower()
    assert apps["https://g.example"]["status"] == "not_reviewed"

    # listing_status unknown for every legacy job — never a fabricated claim
    assert set(listing.values()) == {"unknown"}

    # one event per real occurrence, at the original updated_at, source=system
    assert evs["https://a.example"]["event_type"] == "rejected"
    assert evs["https://a.example"]["occurred_at"] == "2026-07-01T10:00:00+00:00"
    assert evs["https://b.example"]["event_type"] == "hired"
    assert evs["https://c.example"]["event_type"] == "interview"
    assert evs["https://d.example"]["event_type"] == "applied"
    # skipped / not_reviewed produce no event — nothing occurred
    for url in ("https://e.example", "https://f.example", "https://g.example"):
        assert url not in evs
    assert all(e["source"] == "system" for e in evs.values())

    # viewed_at → last_opened_at; created_at backfilled from updated_at
    assert apps["https://d.example"]["last_opened_at"] == "2026-07-05T10:00:00+00:00"
    assert apps["https://a.example"]["created_at"] == "2026-07-01T10:00:00+00:00"

    # idempotent: re-running init_db must not remap or duplicate events
    db.init_db()
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM application_events").fetchone()[0]
        n_apps = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    assert n == 4
    assert n_apps == 7


def test_migration_fresh_db_has_no_legacy_tables(tmp_path):
    import db

    p = tmp_path / "data" / "jobs.db"
    db.DB_PATH = p
    db.init_db()
    with db.get_db() as conn:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "job_statuses" not in tables
    assert "applications" in tables
    assert "application_events" in tables
