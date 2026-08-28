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
    assert "html" in res.text.lower()
    assert ("UI" in res.text) or ('id="root"' in res.text) or ("Let Me Work" in res.text)


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
    db.set_application_status(job_id, "applied")

    res = client.get("/api/jobs")
    data = res.json()
    assert len(data) == 1
    assert data[0]["status"] == "applied"
    assert data[0]["application_status"] == "applied"


def test_get_jobs_application_status_defaults_to_not_reviewed(client, tmp_path):
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
    assert data[0]["status"] == "not_reviewed"
    assert data[0]["application_status"] == "not_reviewed"


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
    status = db.get_application_status(job_id)
    assert status == "applied"


def test_post_status_rejects_legacy_none(client, tmp_path):
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
    db.set_application_status(job_id, "applied")

    # 'none' is a legacy value — must be rejected, not silently accepted
    res = client.post("/api/status", json={"url": "https://example.com", "status": "none"})
    assert res.status_code == 400

    # Verify application state unchanged
    status = db.get_application_status(job_id)
    assert status == "applied"


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


def test_jobs_include_has_cover_letter_flag(client):
    import db

    with_cl = _insert_job(db, url="https://example.com/with-cl", score=80)
    db.upsert_cover_letter(with_cl, "Dear Hiring Manager,")
    _insert_job(db, url="https://example.com/no-cl", score=70)

    jobs = {j["url"]: j for j in client.get("/api/jobs").json()}
    assert jobs["https://example.com/with-cl"]["has_cover_letter"] is True
    assert jobs["https://example.com/no-cl"]["has_cover_letter"] is False


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["db"] == "ok"


def test_is_safe_http_url():
    import db

    assert db.is_safe_http_url("https://example.com/job")
    assert db.is_safe_http_url("http://example.com/job")
    assert not db.is_safe_http_url("javascript:alert(1)")
    assert not db.is_safe_http_url("data:text/html,hi")
    assert not db.is_safe_http_url("https://user:pass@evil.com/")
    assert not db.is_safe_http_url("")


def test_validate_job_scores_rejects_bad_schemes():
    import agent

    out = agent._validate_job_scores(
        [
            {"url": "javascript:alert(1)", "title": "Bad", "score": 90, "verdict": "apply"},
            {
                "url": "https://ok.example/job",
                "title": "Good",
                "score": 80,
                "verdict": "apply",
                "match_reasons": [],
                "red_flags": [],
            },
        ]
    )
    assert len(out) == 1
    assert out[0]["url"].startswith("https://")


def test_run_status_includes_last_run(client):
    import db

    db.init_db()
    run_id = db.start_run()
    db.finish_run(run_id, jobs_found=3, above_threshold=1)

    res = client.get("/api/run-status")
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is False
    assert data["last_run"]["jobs_found"] == 3
    assert data["last_run"]["above_threshold"] == 1
    assert data["last_run"]["finished_at"]


def test_soft_delete_hides_job_and_blocks_pipeline_resurrect(client):
    import db

    job_id = _insert_job(db, url="https://example.com/gone", score=88)
    assert db.soft_delete_job_by_url("https://example.com/gone")

    jobs = client.get("/api/jobs").json()
    assert all(j["url"] != "https://example.com/gone" for j in jobs)

    # re-scrape path must not resurrect
    db.save_pipeline_output(
        [
            {
                "url": "https://example.com/gone",
                "title": "Gone",
                "company": "X",
                "score": 99,
                "verdict": "apply",
                "match_reasons": [],
                "red_flags": [],
                "suggested_angle": "",
            }
        ]
    )
    jobs = client.get("/api/jobs").json()
    assert all(j["url"] != "https://example.com/gone" for j in jobs)

    # undo
    res = client.post("/api/restore", json={"url": "https://example.com/gone"})
    assert res.status_code == 200
    jobs = {j["url"]: j for j in client.get("/api/jobs").json()}
    assert "https://example.com/gone" in jobs
    assert jobs["https://example.com/gone"]["id"] == job_id


def test_get_jobs_include_signals_and_saved(client):
    import db
    job_id = _insert_job(db, url="https://example.com/signals", score=80)
    
    # Set some state to trigger signals
    with db.get_db() as conn:
        # signal_waiting: applied and updated > 7 days ago
        # signal_expiring: deadline within 7 days
        # signal_stale: verified > 14 days ago
        conn.execute(
            "UPDATE jobs SET deadline_at=?, last_verified_at=? WHERE id=?",
            (db._now(), "2000-01-01T00:00:00Z", job_id)
        )
        conn.execute(
            "INSERT INTO applications (job_id, status, updated_at, created_at, is_saved) "
            "VALUES (?, 'applied', '2000-01-01T00:00:00Z', '2000-01-01T00:00:00Z', 1)",
            (job_id,)
        )

    res = client.get("/api/jobs")
    job = res.json()[0]
    assert "is_saved" in job
    assert job["is_saved"] is True
    assert "signal_waiting" in job
    assert "signal_expiring" in job
    assert "signal_stale" in job
    assert "signal_archive" in job


def test_post_save_job(client):
    import db
    url = "https://example.com/save-me"
    job_id = _insert_job(db, url=url)
    # Must have a score to appear in /api/jobs
    db.upsert_score(
        job_id,
        {
            "score": 80,
            "verdict": "review",
            "work_arrangement": "",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        },
    )
    
    # Save it
    res = client.post("/api/jobs/save", json={"url": url, "saved": True})
    assert res.status_code == 200
    
    # Verify in /api/jobs
    job = next(j for j in client.get("/api/jobs").json() if j["url"] == url)
    assert job["is_saved"] is True
    
    # Unsave it
    client.post("/api/jobs/save", json={"url": url, "saved": False})
    job = next(j for j in client.get("/api/jobs").json() if j["url"] == url)
    assert job["is_saved"] is False

    # Not found
    res = client.post("/api/jobs/save", json={"url": "https://nowhere.com", "saved": True})
    assert res.status_code == 404


def test_status_counts_match_live_jobs_not_orphans(client):
    """Funnel counts must use the same universe as /api/jobs (exclude soft-deleted)."""
    import db

    live = _insert_job(db, url="https://example.com/live", score=80)
    gone = _insert_job(db, url="https://example.com/gone-count", score=40)
    db.set_application_status(live, "applied")
    db.set_application_status(gone, "skipped")
    db.soft_delete_job_by_url("https://example.com/gone-count")

    res = client.get("/api/status-counts")
    assert res.status_code == 200
    counts = res.json()
    assert counts["application"]["applied"] == 1
    assert counts["application"]["skipped"] == 0  # soft-deleted must not inflate funnel
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert sum(counts["application"].values()) == len(jobs)


def test_scrape_seeds_soft_deleted_urls():
    import agent
    import db
    from types import SimpleNamespace
    from unittest.mock import patch

    deleted = ["https://www.indeed.com/viewjob?jk=gone"]
    pages = [{"url": "https://listing.example/page", "title": "", "description": ""}]
    posting = {
        "title": "Old job",
        "company": "Co",
        "location": "Remote",
        "url": "https://in.indeed.com/viewjob?jk=gone",  # regional = same dedup key
        "description": "",
        "posted_date": "",
        "source": "indeed.com",
    }

    with (
        patch.object(db, "get_soft_deleted_urls", return_value=deleted),
        patch.object(agent, "discover_pages", return_value=pages),
        patch.object(agent, "extract_postings", return_value=[posting]),
        patch.object(agent, "FirecrawlApp", return_value=SimpleNamespace()),
        patch.dict("os.environ", {"FIRECRAWL_API_KEY": "test"}),
    ):
        jobs = agent.scrape_jobs(["q"])

    assert jobs == []


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


def test_setup_keys_endpoint(client, tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    monkeypatch.setattr(user_data, "find_opencode", lambda: str(tmp_path / "opencode.exe"))
    (tmp_path / "opencode.exe").write_bytes(b"fake")

    res = client.get("/api/setup/status")
    assert res.status_code == 200
    assert res.json()["keys_local_only"] is True

    res = client.post("/api/setup/keys", json={"firecrawl_key": "fc-abc12345xyz"})
    assert res.status_code == 200
    assert res.json()["has_firecrawl"] is True
    assert (tmp_path / ".env").exists()

    client.post("/api/setup/resume", json={"content": "# Resume\n\nHello"})
    res = client.post("/api/setup/complete", json={})
    assert res.status_code == 200
    assert res.json()["onboarding_complete"] is True


def test_run_blocked_without_firecrawl(client, monkeypatch):
    import user_data

    monkeypatch.setattr(
        user_data,
        "setup_status",
        lambda: {
            "has_firecrawl": False,
            "opencode_found": True,
            "has_resume": True,
        },
    )

    with client.stream("GET", "/api/run") as res:
        body = b"".join(res.iter_bytes()).decode()
    assert "Firecrawl" in body
    assert "error" in body


def test_sources_get_and_save(client, tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config.user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "writable_config_path", lambda: tmp_path / "config.json")

    res = client.get("/api/setup/sources")
    assert res.status_code == 200
    data = res.json()
    assert any(b["id"] == "indeed.com" for b in data["boards"])
    assert any(b["id"] == "onlinejobs.ph" for b in data["boards"])
    assert any(b.get("host") == "linkedin.com" for b in data["boards"])
    assert "work_arrangements" in data
    assert {a["id"] for a in data["work_arrangements"]} >= {"remote", "hybrid", "onsite"}
    # default: OnlineJobs off
    oj = next(b for b in data["boards"] if b["id"] == "onlinejobs.ph")
    assert oj["enabled"] is False

    res = client.post(
        "/api/setup/sources",
        json={
            "job_boards": ["indeed.com", "jobstreet.com"],
            "work_arrangements": ["remote", "hybrid"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_boards"] == ["indeed.com", "jobstreet.com"]
    assert body["enabled_work_arrangements"] == ["remote", "hybrid"]
    assert (tmp_path / "config.json").exists()

    res = client.post("/api/setup/sources", json={"job_boards": []})
    assert res.status_code == 400

    res = client.post(
        "/api/setup/sources",
        json={"job_boards": ["indeed.com"], "work_arrangements": []},
    )
    assert res.status_code == 400


def test_upload_resume_pdf_endpoint(client, tmp_path, monkeypatch):
    import user_data
    from test_user_data import _minimal_text_pdf

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    monkeypatch.setattr(user_data, "resume_pdf_path", lambda: tmp_path / "resume.pdf")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")

    pdf = _minimal_text_pdf("EndpointPDFText")
    res = client.post(
        "/api/setup/resume-pdf",
        files={"file": ("cv.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "EndpointPDFText" in body["content"]
    assert (tmp_path / "resume.pdf").exists()
    assert (tmp_path / "resume.md").exists()


def test_bulk_apply_only_marks_not_reviewed(client):
    import db

    fresh_id = _insert_job(db, url="https://example.com/fresh", score=85)
    skipped_id = _insert_job(db, url="https://example.com/skipped", score=90)
    hired_id = _insert_job(db, url="https://example.com/hired", score=95)
    db.set_application_status(skipped_id, "skipped")
    db.set_application_status(hired_id, "hired")

    res = client.post("/api/bulk-apply?min_score=80")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["urls"] == ["https://example.com/fresh"]
    assert db.get_application_status(fresh_id) == "applied"
    assert db.get_application_status(skipped_id) == "skipped"
    assert db.get_application_status(hired_id) == "hired"


def test_soft_delete_blocks_canonical_url_variants(client):
    import db

    job_id = _insert_job(db, url="https://www.indeed.com/viewjob?jk=abc", score=80)
    assert db.soft_delete_job_by_url("https://www.indeed.com/viewjob?jk=abc")

    db.save_pipeline_output(
        [
            {
                "url": "https://in.indeed.com/viewjob?jk=abc",
                "title": "Resurrect?",
                "company": "X",
                "score": 99,
                "verdict": "apply",
                "match_reasons": [],
                "red_flags": [],
                "suggested_angle": "",
            }
        ]
    )
    jobs = client.get("/api/jobs").json()
    assert all("jk=abc" not in j["url"] for j in jobs)
    assert db.is_url_soft_deleted("https://indeed.com/viewjob?jk=abc")
    assert job_id  # original row still exists as soft-deleted


def test_resume_save_clears_profile_cache(client, tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output").mkdir(exist_ok=True)
    cache = tmp_path / "output" / "resume_profile.json"
    cache.write_text('{"name":"Stale"}', encoding="utf-8")

    res = client.post("/api/setup/resume", json={"content": "# New Resume\nUpdated"})
    assert res.status_code == 200
    assert not cache.exists()


def test_installer_filename_from_github_url():
    import server

    url = "https://github.com/MarkJanzenB/LetMEWork/releases/download/v0.1.0-beta.4/LetMeWork-Setup-0.1.0-beta.4.exe"
    assert server._installer_filename(url) == "LetMeWork-Setup-0.1.0-beta.4.exe"
    assert server._installer_filename("https://example.com/nope") == "LetMeWork-Setup.exe"


def test_version_newer_detects_mismatch():
    import server

    assert server._version_newer("0.1.0-beta.4", "0.1.0-beta.3") is True
    assert server._version_newer("0.1.0-beta.4", "0.1.0-beta.4") is False


def test_pending_update_roundtrip(tmp_path, monkeypatch):
    import server
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(server.config, "APP_VERSION", "0.1.0-beta.3")
    setup = tmp_path / "LetMeWork-Setup.exe"
    setup.write_bytes(b"fake")
    server._save_pending_update("0.1.0-beta.4", setup, "abc")
    pending = server._load_pending_update()
    assert pending["version"] == "0.1.0-beta.4"
    assert pending["path"] == str(setup)

    monkeypatch.setattr(server.config, "APP_VERSION", "0.1.0-beta.4")
    assert server._load_pending_update() is None
    assert not user_data.pending_update_path().exists()


def test_update_install_requires_download(client, tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    res = client.post("/api/update/install")
    assert res.status_code == 400


def test_abandon_orphan_runs_on_lifespan(tmp_path, monkeypatch):
    import importlib
    import db
    import server

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<html></html>")
    (tmp_path / "data").mkdir()
    db.DB_PATH = tmp_path / "data" / "jobs.db"
    db.init_db()
    orphan = db.start_run()
    assert db.get_active_run() is not None

    n = db.abandon_orphan_runs("test restart")
    assert n == 1
    assert db.get_active_run() is None
    # finished as failed
    with db.get_db() as conn:
        row = conn.execute("SELECT status, error_message FROM runs WHERE id=?", (orphan,)).fetchone()
        assert row["status"] == "failed"
        assert "restart" in row["error_message"]
