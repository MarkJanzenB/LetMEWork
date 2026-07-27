import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<html><body>UI</body></html>")
    (tmp_path / "data").mkdir()
    (tmp_path / "output").mkdir()
    import importlib, server, db

    importlib.reload(server)
    # Initialize and clear database
    db.DB_PATH = tmp_path / "data" / "jobs.db"
    db.init_db()
    return TestClient(server.app)


def test_index_returns_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "UI" in res.text


def test_get_jobs_empty_when_no_file(client):
    res = client.get("/api/jobs")
    assert res.status_code == 200
    assert res.json() == []


def test_get_jobs_merges_status(client, tmp_path):
    import db

    db.init_db()

    # Insert a job
    job_id = db.upsert_job(
        {
            "title": "Dev",
            "company": "Co",
            "url": "https://example.com",
            "location": "Remote",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )

    # Insert a score
    db.upsert_score(
        job_id,
        {
            "score": 85,
            "verdict": "apply",
            "work_arrangement": "",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        },
    )

    # Set status
    db.set_job_status(job_id, "applied")

    res = client.get("/api/jobs")
    data = res.json()
    assert len(data) == 1
    assert data[0]["status"] == "applied"


def test_get_jobs_status_defaults_to_none(client, tmp_path):
    import db

    db.init_db()

    # Insert a job
    job_id = db.upsert_job(
        {
            "title": "Dev",
            "url": "https://example.com",
            "company": "",
            "location": "",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )

    # Insert a score
    db.upsert_score(
        job_id,
        {
            "score": 85,
            "verdict": "apply",
            "work_arrangement": "",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        },
    )

    res = client.get("/api/jobs")
    data = res.json()
    assert len(data) == 1
    assert data[0]["status"] == "none"


def test_post_status_saves_applied(client, tmp_path):
    import db

    db.init_db()

    # Insert a job first
    job_id = db.upsert_job(
        {
            "title": "Dev",
            "url": "https://example.com",
            "company": "",
            "location": "",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )

    res = client.post("/api/status", json={"url": "https://example.com", "status": "applied"})
    assert res.status_code == 200

    # Verify in database
    status = db.get_job_status(job_id)
    assert status == "applied"


def test_post_status_none_removes_entry(client, tmp_path):
    import db

    db.init_db()

    # Insert a job first
    job_id = db.upsert_job(
        {
            "title": "Dev",
            "url": "https://example.com",
            "company": "",
            "location": "",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )

    # Set to applied first
    db.set_job_status(job_id, "applied")

    # Now set to none
    client.post("/api/status", json={"url": "https://example.com", "status": "none"})

    # Verify in database
    status = db.get_job_status(job_id)
    assert status == "none"


def test_post_status_rejects_invalid_value(client, tmp_path):
    import db

    db.init_db()

    # Insert a job first
    job_id = db.upsert_job(
        {
            "title": "Dev",
            "url": "https://example.com",
            "company": "",
            "location": "",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )

    res = client.post("/api/status", json={"url": "https://example.com", "status": "maybe"})
    assert res.status_code == 400


def _insert_job(db, url="https://example.com/job1", score=None):
    job_id = db.upsert_job(
        {
            "title": "Frontend Engineer",
            "url": url,
            "company": "Tech Holding",
            "location": "Remote",
            "description": "",
            "source": "",
            "posted_date": "",
        }
    )
    if score is not None:
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


def test_cover_letter_found(client):
    import db

    job_id = _insert_job(db)
    db.upsert_cover_letter(job_id, "Dear hiring manager,")

    res = client.get("/api/cover-letter?url=https%3A%2F%2Fexample.com%2Fjob1")
    assert res.status_code == 200
    assert "Dear hiring manager" in res.json()["content"]


def test_cover_letter_not_found(client):
    res = client.get("/api/cover-letter?url=https%3A%2F%2Fnowhere.example")
    assert res.status_code == 404


def test_cover_letter_missing_for_existing_job(client):
    import db

    _insert_job(db)
    res = client.get("/api/cover-letter?url=https%3A%2F%2Fexample.com%2Fjob1")
    assert res.status_code == 404


def test_put_cover_letter_saves_edit(client):
    import db

    job_id = _insert_job(db)
    res = client.put(
        "/api/cover-letter",
        json={"url": "https://example.com/job1", "content": "Edited letter"},
    )
    assert res.status_code == 200
    assert db.get_cover_letter(job_id) == "Edited letter"


def test_generate_cover_letter_on_demand(client):
    import db
    from unittest.mock import patch

    job_id = _insert_job(db, score=65)

    with (
        patch("agent.generate_cover_letter", return_value="Generated letter"),
        patch("agent.load_cached_profile", return_value=None),
    ):
        res = client.post(
            "/api/generate-cover-letter", json={"url": "https://example.com/job1"}
        )

    assert res.status_code == 200
    assert res.json()["content"] == "Generated letter"
    assert db.get_cover_letter(job_id) == "Generated letter"


def test_generate_cover_letter_unknown_job(client):
    res = client.post("/api/generate-cover-letter", json={"url": "https://nowhere.example"})
    assert res.status_code == 404
