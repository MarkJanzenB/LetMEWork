"""Workflow tests: user-driven application lifecycle over the /api/status flow.

Covers the transitions a user actually performs (manual apply, skip, reject,
interview/offer/hired/withdrawn), reason/note handling, per-transition timeline
events, and independence from listing state. Backend facts (schema, migration,
derived labels, counts) are covered by test_lifecycle.py.
"""

import importlib
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
                "SELECT event_type, source, detail FROM application_events "
                "WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ]


STATUS_EVENT = {
    "applied": "applied",
    "interviewing": "interview",
    "offer": "offer",
    "hired": "hired",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
}


# ── full user workflow, independent of listing state ─────
def test_full_transition_sequence_with_closed_listing(client, tmp_path):
    """Listing=closed + applied→interviewing→rejected: the two machines hold
    independently and the timeline records exactly those three events."""
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/listing",
        json={"url": "https://example.com/job1", "listing_status": "closed"},
    )
    assert res.status_code == 200

    for status in ("applied", "interviewing", "rejected"):
        res = client.post(
            "/api/status", json={"url": "https://example.com/job1", "status": status}
        )
        assert res.status_code == 200
        assert res.json()["application_status"] == status

    with db.get_db() as conn:
        listing = conn.execute(
            "SELECT listing_status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert listing["listing_status"] == "closed"  # listing never moved

    assert db.get_application(job_id)["status"] == "rejected"

    body = client.get(
        "/api/timeline?url=" + quote("https://example.com/job1", safe="")
    ).json()
    assert body["application_status"] == "rejected"  # current state = row, not events
    assert [e["event_type"] for e in body["events"]] == [
        "rejected", "interview", "applied",
    ]
    assert all(e["source"] == "user" for e in body["events"])


# ── one event per transition; none for not_reviewed ──────
@pytest.mark.parametrize("status,event_type", sorted(STATUS_EVENT.items()))
def test_each_transition_appends_matching_event(client, tmp_path, status, event_type):
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status", json={"url": "https://example.com/job1", "status": status}
    )
    assert res.status_code == 200
    evs = _events(db, job_id)
    assert [e["event_type"] for e in evs] == [event_type]
    assert evs[0]["source"] == "user"


def test_not_reviewed_creates_no_event(client, tmp_path):
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status", json={"url": "https://example.com/job1", "status": "not_reviewed"}
    )
    assert res.status_code == 200
    assert db.get_application_status(job_id) == "not_reviewed"
    assert _events(db, job_id) == []


# ── skip / reject with structured reason + note ──────────
def test_skip_stores_reason_and_note_and_other_event(client, tmp_path):
    import config
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status",
        json={
            "url": "https://example.com/job1",
            "status": "skipped",
            "reason": "location",
            "note": "Too far from home",
        },
    )
    assert res.status_code == 200
    app = db.get_application(job_id)
    assert app["status"] == "skipped"
    assert app["reason"] == "location"  # SKIP_REASONS canonical value round-trips
    assert app["note"] == "Too far from home"
    evs = _events(db, job_id)
    assert evs[0]["event_type"] == "other"
    assert evs[0]["detail"] == "Too far from home"  # note beats reason
    assert "location" in config.SKIP_REASONS


def test_reject_stores_rejection_reason_and_event(client, tmp_path):
    import config
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status",
        json={
            "url": "https://example.com/job1",
            "status": "rejected",
            "reason": "position_filled",
            "note": "Recruiter confirmed headcount cut",
        },
    )
    assert res.status_code == 200
    app = db.get_application(job_id)
    assert app["status"] == "rejected"
    assert app["reason"] == "position_filled"
    assert app["note"] == "Recruiter confirmed headcount cut"
    assert "position_filled" in config.REJECTION_REASONS
    assert _events(db, job_id)[0]["event_type"] == "rejected"


def test_reasons_are_free_strings_not_enum_forced(client, tmp_path):
    """Contract §1: reason/note are free strings stored as-is — the reason sets
    are the UI's canonical option list, not a backend constraint."""
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status",
        json={
            "url": "https://example.com/job1",
            "status": "skipped",
            "reason": "just not interested",
        },
    )
    assert res.status_code == 200
    assert db.get_application(job_id)["reason"] == "just not interested"


# ── notes/reasons round-trip across transitions ──────────
def test_note_preserved_across_status_transition(client, tmp_path):
    import db

    job_id = _insert_job(db)
    client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "applied",
              "note": "Follow up Friday"},
    )
    client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "interviewing"},
    )
    app = db.get_application(job_id)
    assert app["status"] == "interviewing"
    assert app["note"] == "Follow up Friday"  # status-only update must not wipe it


def test_note_explicitly_cleared(client, tmp_path):
    import db

    job_id = _insert_job(db)
    client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "applied",
              "note": "Follow up Friday"},
    )
    client.post(
        "/api/status",
        json={"url": "https://example.com/job1", "status": "interviewing", "note": ""},
    )
    assert db.get_application(job_id)["note"] == ""


# ── manual application ───────────────────────────────────
def test_manual_application_touches_only_application(client, tmp_path):
    import db

    job_id = _insert_job(db)
    res = client.post(
        "/api/status", json={"url": "https://example.com/job1", "status": "applied"}
    )
    assert res.status_code == 200
    app = db.get_application(job_id)
    assert app["status"] == "applied"
    assert app["updated_at"]
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT listing_status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["listing_status"] == "unknown"  # listing untouched
    assert [e["event_type"] for e in _events(db, job_id)] == ["applied"]
