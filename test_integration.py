"""End-to-end integration: search/open -> status -> export -> re-read.

Ties the real modules together (server API + db + status machine + CSV export)
over the full lifecycle the user performs, instead of unit-testing each piece
in isolation. Network steps are already mocked at their source in
test_pipeline.py; here the shared DB is the medium the flow travels through.
"""

import csv
import importlib
import io
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


def _insert_job(db, url="https://example.com/job1"):
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
            "score": 85,
            "verdict": "review",
            "work_arrangement": "",
            "match_reasons": ["react"],
            "red_flags": [],
            "suggested_angle": "",
        },
    )
    return job_id


def _csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.text)))


def test_search_open_status_export_reread(client):
    """Search+open seeds not_reviewed; a UI status change lands in the DB, then
    the CSV export, and re-reading the DB matches what the CSV said."""
    import db

    job_id = _insert_job(db)

    # browser controller: user opens the listing
    res = client.post("/api/open", json={"url": "https://example.com/job1"})
    assert res.status_code == 200

    # the open recorded status not_reviewed, no event yet
    assert db.get_application_status(job_id) == "not_reviewed"

    # UI status change to applied
    res = client.post(
        "/api/status", json={"url": "https://example.com/job1", "status": "applied"}
    )
    assert res.status_code == 200
    assert res.json()["application_status"] == "applied"

    # CSV export reflects the new status
    rows = _csv_rows(client.get("/api/export/csv"))
    assert rows, "export produced rows"
    row = next(r for r in rows if r["URL"] == "https://example.com/job1")
    assert row["Status"] == "applied"
    assert row["Title"] == "Frontend Engineer"
    assert row["Score"] == "85"

    # re-read through the API: status + event agree with the CSV
    body = client.get("/api/timeline?url=" + quote("https://example.com/job1", safe="")).json()
    assert body["application_status"] == "applied"
    assert [e["event_type"] for e in body["events"]] == ["applied"]
    assert all(e["source"] == "user" for e in body["events"])
    assert db.get_application(job_id)["status"] == "applied"
