"""Scraper tests: listing availability mapping, metadata capture, verify, and
state independence (scraper writes never touch applications)."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def dbfx(tmp_path, monkeypatch):
    """Isolated DB for scraper-flow tests."""
    import db

    (tmp_path / "data").mkdir()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "jobs.db")
    db.init_db()
    return db


class _FakeApp:
    """Minimal stand-in for the Firecrawl failover app used by extract/verify."""

    def __init__(self, doc_json=None, error=None):
        self._doc_json = doc_json or {"jobs": []}
        self._error = error

    def scrape(self, *a, **k):
        if self._error:
            raise self._error
        return SimpleNamespace(json=self._doc_json)


def _insert(db, url="https://indeed.com/viewjob?jk=abc", score=85):
    job_id = db.upsert_job(
        {
            "title": "Engineer",
            "url": url,
            "company": "Co",
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
            "verdict": "apply",
            "work_arrangement": "",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        },
    )
    return job_id


# ── listing status mapping ───────────────────────────────
def test_normalize_listing_status_mapping():
    import agent

    m = agent._normalize_listing_status
    assert m(None) == "unknown"
    assert m("") == "unknown"
    assert m("unknown") == "unknown"
    assert m("n/a") == "unknown"

    assert m("active") == "active"
    assert m("open") == "active"
    assert m("hiring") == "active"
    assert m("accepting applications") == "active"

    assert m("closed") == "closed"
    assert m("This position has been filled") == "closed"
    assert m("no longer accepting applications") == "closed"
    assert m("posting expired") == "closed"
    assert m("inactive") == "closed"
    assert m("not currently open") == "closed"

    assert m("not accepting applications") == "not_accepting"
    assert m("paused") == "not_accepting"
    assert m("on hold") == "not_accepting"

    assert m("404") == "unavailable"
    assert m("page not found") == "unavailable"
    assert m("removed") == "unavailable"
    assert m("no longer exists") == "unavailable"

    assert m("some unrelated text") == "unknown"


def test_parse_deadline_normalizes_to_iso():
    import agent

    assert agent._parse_deadline(None) is None
    assert agent._parse_deadline("") is None
    assert agent._parse_deadline("2026-08-30") == "2026-08-30T00:00:00"
    assert agent._parse_deadline("2026-08-30T23:59:00+00:00") == "2026-08-30T23:59:00+00:00"
    assert agent._parse_deadline("Aug 30, 2026") == "2026-08-30T00:00:00"
    assert agent._parse_deadline("30 August 2026") == "2026-08-30T00:00:00"
    assert agent._parse_deadline("not a date") is None


# ── extract captures listing metadata ─────────────────────
def test_extract_postings_captures_listing_metadata():
    import agent

    page = {"url": "https://www.indeed.com/jobs?q=engineer", "title": "List", "description": ""}
    app = _FakeApp(
        {
            "jobs": [
                {
                    "title": "Engineer",
                    "url": "https://www.indeed.com/viewjob?jk=abc",
                    "listing_status": "Position filled",
                    "deadline_at": "2026-08-30",
                    "source_job_id": "jk=abc",
                }
            ]
        }
    )
    postings = agent.extract_postings(app, page)

    assert postings[0]["source"] == "indeed.com"  # canonical host mapping
    assert postings[0]["listing_status"] == "closed"
    assert postings[0]["deadline_at"] == "2026-08-30T00:00:00"
    assert postings[0]["source_job_id"] == "jk=abc"


def test_extract_postings_snippet_fallback_is_unknown():
    import agent

    page = {"url": "https://indeed.com/jobs?q=x", "title": "Dev", "description": "snippet"}
    app = _FakeApp(error=Exception("scrape boom"))
    postings = agent.extract_postings(app, page)

    assert postings[0]["url"] == "https://indeed.com/jobs?q=x"
    assert postings[0]["listing_status"] == "unknown"
    assert postings[0]["deadline_at"] is None
    assert postings[0]["source_job_id"] == ""


# ── analyze output carries listing fields ─────────────────
def test_validate_job_scores_passes_listing_fields_through():
    import agent

    scored = agent._validate_job_scores(
        [
            {
                "url": "https://indeed.com/viewjob?jk=abc",
                "title": "Engineer",
                "score": 90,
                "verdict": "apply",
                "listing_status": "This position has been filled",
                "deadline_at": "Aug 30, 2026",
                "source_job_id": "jk=abc",
            }
        ]
    )
    assert scored[0]["listing_status"] == "closed"
    assert scored[0]["deadline_at"] == "2026-08-30T00:00:00"
    assert scored[0]["source_job_id"] == "jk=abc"


def test_analyze_jobs_writes_listing_fields_to_jobs_json(tmp_path, monkeypatch):
    import agent
    import config

    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text('# Experienced engineer with Python and systems work. Remote-friendly, GMT+8 timezone, seeking full-stack roles.\n')

    (out / "raw_jobs.json").write_text(
        json.dumps(
            [
                {
                    "title": "Engineer",
                    "url": "https://indeed.com/viewjob?jk=abc",
                    "company": "Co",
                    "listing_status": "active",
                    "deadline_at": "2026-08-30",
                }
            ]
        )
    )
    analyzed = [
        {
            "title": "Engineer",
            "url": "https://indeed.com/viewjob?jk=abc",
            "score": 85,
            "verdict": "apply",
            "listing_status": "closed",
            "deadline_at": "2026-08-30",
        }
    ]
    with patch.object(agent, "run_opencode_json", return_value=analyzed):
        result = agent.analyze_jobs()

    assert result[0]["listing_status"] == "closed"
    assert result[0]["deadline_at"] == "2026-08-30T00:00:00"


# ── pipeline writes listing columns ───────────────────────
def test_run_pipeline_stamps_listing_timestamps(tmp_path, monkeypatch):
    import agent
    import config
    import db

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    (tmp_path / "output").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "jobs.db")

    mock_analyzed = [
        {
            "title": "Engineer",
            "company": "Co",
            "url": "https://indeed.com/viewjob?jk=abc",
            "score": 85,
            "verdict": "apply",
            "listing_status": "active",
            "deadline_at": "2026-08-30T00:00:00",  # analyze_jobs normalizes pre-save
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]
    raw = [{"url": "https://indeed.com/viewjob?jk=abc", "title": "Engineer", "company": "Co"}]
    with (
        patch.object(agent, "extract_resume_profile", return_value={"name": "T"}),
        patch.object(agent, "build_search_config", return_value={"search_queries": ["q"]}),
        patch.object(agent, "scrape_jobs", return_value=raw),
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters"),
    ):
        agent.run_pipeline()

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, deadline_at, discovered_at, last_scraped_at, "
            "last_verified_at, source_job_id FROM jobs WHERE url=?",
            ("https://indeed.com/viewjob?jk=abc",),
        ).fetchone()
    assert row["listing_status"] == "active"
    assert row["deadline_at"] == "2026-08-30T00:00:00"
    assert row["discovered_at"] is not None  # set on insert
    assert row["last_scraped_at"] is not None  # set on every scrape write
    assert row["last_verified_at"] is not None  # confident signal → confirmed
    assert row["source_job_id"] is None  # not extractable → NULL (schema default)


def test_expired_derived_from_deadline_not_stored(tmp_path, monkeypatch):
    """A past deadline is stored as deadline_at; db derives 'expired' at read."""
    import agent
    import config
    import db

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    (tmp_path / "output").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "jobs.db")

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    mock_analyzed = [
        {
            "title": "Engineer",
            "company": "Co",
            "url": "https://indeed.com/viewjob?jk=expired",
            "score": 85,
            "verdict": "apply",
            "listing_status": "active",
            "deadline_at": past,
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]
    raw = [{"url": "https://indeed.com/viewjob?jk=expired", "title": "Engineer", "company": "Co"}]
    with (
        patch.object(agent, "extract_resume_profile", return_value={"name": "T"}),
        patch.object(agent, "build_search_config", return_value={"search_queries": ["q"]}),
        patch.object(agent, "scrape_jobs", return_value=raw),
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters"),
    ):
        agent.run_pipeline()

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, deadline_at FROM jobs WHERE url=?",
            ("https://indeed.com/viewjob?jk=expired",),
        ).fetchone()
    assert row["listing_status"] == "active"  # expired never stored
    job = {"listing_status": row["listing_status"], "deadline_at": row["deadline_at"]}
    assert db.effective_listing_status(job) == "expired"  # derived at read


# ── verify listings ───────────────────────────────────────
def test_verify_marks_closed_and_keeps_application(dbfx):
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=closed")
    dbfx.set_application_status(job_id, "applied", note="in progress")

    app = _FakeApp(
        {
            "jobs": [
                {
                    "title": "Engineer",
                    "listing_status": "This position has been filled",
                    "url": "https://indeed.com/viewjob?jk=closed",
                }
            ]
        }
    )
    result = agent.verify_listings(["https://indeed.com/viewjob?jk=closed"], app=app)

    assert result == {"checked": 1, "updated": {"https://indeed.com/viewjob?jk=closed": "closed"}}
    with dbfx.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, last_verified_at, last_scraped_at FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    assert row["listing_status"] == "closed"
    assert row["last_verified_at"] is not None
    assert row["last_scraped_at"] is not None

    # independence: the applied application row is untouched
    app_row = dbfx.get_application(job_id)
    assert app_row["status"] == "applied"
    assert app_row["note"] == "in progress"
    with dbfx.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM application_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
    assert n == 1  # only the original applied event


def test_verify_404_marks_unavailable(dbfx):
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=gone")
    err = Exception("404 Not Found")
    err.status_code = 404
    result = agent.verify_listings(["https://indeed.com/viewjob?jk=gone"], app=_FakeApp(error=err))

    assert result["updated"]["https://indeed.com/viewjob?jk=gone"] == "unavailable"
    with dbfx.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, last_verified_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["listing_status"] == "unavailable"
    assert row["last_verified_at"] is not None


def test_verify_confirms_existence_as_active(dbfx):
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=ok")
    result = agent.verify_listings(
        ["https://indeed.com/viewjob?jk=ok"],
        app=_FakeApp({"jobs": [{"title": "Engineer", "url": "https://indeed.com/viewjob?jk=ok"}]}),
    )
    assert result["updated"]["https://indeed.com/viewjob?jk=ok"] == "active"
    with dbfx.get_db() as conn:
        row = conn.execute("SELECT listing_status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["listing_status"] == "active"


def test_verify_transient_failure_changes_nothing(dbfx):
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=flaky")
    dbfx.set_listing_status(job_id, listing_status="active")
    result = agent.verify_listings(
        ["https://indeed.com/viewjob?jk=flaky"], app=_FakeApp(error=Exception("timeout"))
    )
    assert result["updated"]["https://indeed.com/viewjob?jk=flaky"] is None
    with dbfx.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, last_scraped_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["listing_status"] == "active"  # unchanged
    assert row["last_scraped_at"] is not None  # fetch attempt still recorded


def test_verify_skips_soft_deleted_never_resurrects(dbfx):
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=deleted")
    dbfx.soft_delete_job_by_url("https://indeed.com/viewjob?jk=deleted")
    result = agent.verify_listings(
        ["https://indeed.com/viewjob?jk=deleted"],
        app=_FakeApp({"jobs": [{"title": "Engineer"}]}),
    )
    assert result["checked"] == 0
    assert result["updated"] == {}
    with dbfx.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, deleted_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["listing_status"] == "unknown"
    assert row["deleted_at"] is not None  # still soft-deleted


# ── independence through the real scrape flow ─────────────
def test_scrape_flow_never_touches_application_state(dbfx):
    """What the pipeline saves (validated analyze output) must leave an existing
    application row byte-for-byte untouched, even when listing is marked closed."""
    import agent

    job_id = _insert(dbfx, url="https://indeed.com/viewjob?jk=applied")
    dbfx.set_application_status(job_id, "applied", reason="skills", note="sent")

    scored = agent._validate_job_scores(
        [
            {
                "url": "https://indeed.com/viewjob?jk=applied",
                "title": "Engineer",
                "company": "Co",
                "score": 99,
                "verdict": "apply",
                "listing_status": "closed",
                "deadline_at": "2026-08-30",
                "source_job_id": "jk=applied",
            }
        ]
    )
    agent._stamp_listing_metadata(scored)
    dbfx.save_pipeline_output(scored)

    app_row = dbfx.get_application(job_id)
    assert app_row["status"] == "applied"
    assert app_row["reason"] == "skills"
    assert app_row["note"] == "sent"
    assert app_row["last_opened_at"] is None
    with dbfx.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM application_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
    assert n == 1  # only the user's applied event

    with dbfx.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status, deadline_at, source_job_id, last_scraped_at "
            "FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    assert row["listing_status"] == "closed"
    assert row["deadline_at"] == "2026-08-30T00:00:00"
    assert row["source_job_id"] == "jk=applied"
    assert row["last_scraped_at"] is not None
