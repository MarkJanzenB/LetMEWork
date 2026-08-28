import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest


def test_discover_pages_interleaves_results_across_queries():
    import agent

    results = {
        "q1": [
            SimpleNamespace(url=f"https://www.indeed.com/viewjob?jk={i}", title="", description="")
            for i in range(3)
        ],
        "q2": [
            SimpleNamespace(url=f"https://www.linkedin.com/jobs/view/{i}", title="", description="")
            for i in range(2)
        ],
        "q3": [],
    }
    fake_app = SimpleNamespace(search=lambda q, limit: SimpleNamespace(web=results[q]))

    pages = agent.discover_pages(fake_app, ["q1", "q2", "q3"])

    assert [p["url"] for p in pages] == [
        "https://www.indeed.com/viewjob?jk=0",
        "https://www.linkedin.com/jobs/view/0",
        "https://www.indeed.com/viewjob?jk=1",
        "https://www.linkedin.com/jobs/view/1",
        "https://www.indeed.com/viewjob?jk=2",
    ]


def test_discover_pages_dedupes_regional_subdomains():
    import agent

    results = {
        "q1": [
            SimpleNamespace(url="https://www.indeed.com/viewjob?jk=abc", title="", description="")
        ],
        "q2": [
            SimpleNamespace(url="https://in.indeed.com/viewjob?jk=abc", title="", description=""),
            SimpleNamespace(url="https://uk.linkedin.com/jobs/view/123", title="", description=""),
        ],
        "q3": [
            SimpleNamespace(url="https://www.linkedin.com/jobs/view/123", title="", description="")
        ],
    }
    fake_app = SimpleNamespace(search=lambda q, limit: SimpleNamespace(web=results[q]))

    pages = agent.discover_pages(fake_app, ["q1", "q2", "q3"])

    assert [p["url"] for p in pages] == [
        "https://www.indeed.com/viewjob?jk=abc",
        "https://uk.linkedin.com/jobs/view/123",
    ]


def test_canonical_host_leaves_regular_domains_alone():
    import agent

    assert agent._canonical_host("www.indeed.com") == "indeed.com"
    assert agent._canonical_host("ng.indeed.com") == "indeed.com"
    assert agent._canonical_host("ph.jobstreet.com") == "jobstreet.com"
    assert agent._canonical_host("onlinejobs.ph") == "onlinejobs.ph"
    assert agent._canonical_host("glassdoor.co.uk") == "glassdoor.co.uk"
    assert agent._canonical_host("reddit.com") == "reddit.com"


def test_run_pipeline_emits_all_step_events(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    (tmp_path / "output").mkdir()

    mock_config = {"search_queries": ["frontend dev remote"]}
    mock_raw_jobs = [
        {
            "title": "Dev",
            "company": "Co",
            "location": "Remote",
            "url": "https://example.com",
            "description": "",
            "posted_date": "",
            "source": "example.com",
        }
    ]
    mock_analyzed = [
        {
            "title": "Dev",
            "company": "Co",
            "url": "https://example.com",
            "score": 85,
            "verdict": "apply",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]

    events = []

    mock_profile = {"name": "Test", "experience_years": 2}

    with (
        patch.object(agent, "extract_resume_profile", return_value=mock_profile),
        patch.object(agent, "build_search_config", return_value=mock_config),
        patch.object(agent, "scrape_jobs", return_value=mock_raw_jobs),
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters"),
    ):
        result = agent.run_pipeline(on_progress=lambda s, l, st: events.append((s, st)))

    step_statuses = {(s, st) for s, st in events}
    assert (0, "running") in step_statuses
    assert (0, "done") in step_statuses
    assert (1, "running") in step_statuses
    assert (1, "done") in step_statuses
    assert (2, "running") in step_statuses
    assert (2, "done") in step_statuses
    assert (3, "running") in step_statuses
    assert (3, "done") in step_statuses
    assert (4, "running") in step_statuses
    assert (4, "done") in step_statuses
    assert result["total"] == 1
    assert result["above_threshold"] == 1
    assert "new" in result and "updated" in result


def test_run_pipeline_raises_when_resume_missing(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.chdir(tmp_path)
    # Override RESUME_FILE to point to the temp directory
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    with pytest.raises(RuntimeError, match="Missing"):
        agent.run_pipeline()


def test_run_pipeline_works_without_callback(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    (tmp_path / "output").mkdir()

    mock_config = {"search_queries": ["q"]}
    mock_raw_jobs = [
        {
            "title": "Dev",
            "company": "Co",
            "location": "Remote",
            "url": "https://example.com",
            "description": "",
            "posted_date": "",
            "source": "example.com",
        }
    ]
    mock_analyzed = [
        {
            "title": "Dev",
            "url": "https://example.com",
            "score": 50,
            "verdict": "skip",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]

    with (
        patch.object(agent, "extract_resume_profile", return_value={"name": "Test"}),
        patch.object(agent, "build_search_config", return_value=mock_config),
        patch.object(agent, "scrape_jobs", return_value=mock_raw_jobs),
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters"),
    ):
        result = agent.run_pipeline()

    assert result["total"] == 1
    assert result["above_threshold"] == 0


def test_run_pipeline_skips_cover_letters_by_default(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    monkeypatch.setattr(config, "GENERATE_COVER_LETTERS_IN_PIPELINE", False)
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    (tmp_path / "output").mkdir()

    mock_analyzed = [
        {
            "title": "Dev",
            "company": "Co",
            "url": "https://example.com",
            "score": 85,
            "verdict": "apply",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]

    with (
        patch.object(agent, "extract_resume_profile", return_value={"name": "Test"}),
        patch.object(agent, "build_search_config", return_value={"search_queries": ["q"]}),
        patch.object(
            agent,
            "scrape_jobs",
            return_value=[
                {
                    "title": "Dev",
                    "company": "Co",
                    "location": "Remote",
                    "url": "https://example.com",
                    "description": "",
                    "posted_date": "",
                    "source": "example.com",
                }
            ],
        ),
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters") as mock_gen,
    ):
        agent.run_pipeline()

    mock_gen.assert_not_called()


def test_run_pipeline_reuses_prev_queries_when_build_returns_empty(tmp_path, monkeypatch):
    import agent
    import config
    import json
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    out = tmp_path / "output"
    out.mkdir()
    (out / "search_config.json").write_text(
        json.dumps({"search_queries": ["site:indeed.com old query"]})
    )

    mock_raw_jobs = [
        {
            "title": "Dev",
            "company": "Co",
            "location": "Remote",
            "url": "https://example.com",
            "description": "",
            "posted_date": "",
            "source": "example.com",
        }
    ]
    mock_analyzed = [
        {
            "title": "Dev",
            "company": "Co",
            "url": "https://example.com",
            "score": 85,
            "verdict": "apply",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]

    with (
        patch.object(agent, "extract_resume_profile", return_value={"name": "Test"}),
        patch.object(agent, "build_search_config", return_value={"search_queries": []}),
        patch.object(agent, "scrape_jobs", return_value=mock_raw_jobs) as mock_scrape,
        patch.object(agent, "analyze_jobs", return_value=mock_analyzed),
        patch.object(agent, "generate_cover_letters"),
    ):
        result = agent.run_pipeline()

    assert result["total"] == 1
    mock_scrape.assert_called_once_with(["site:indeed.com old query"], {"name": "Test"})


def test_run_opencode_json_strips_markdown_fences():
    import agent

    fenced = '```json\n{"target_roles": ["Virtual Assistant"]}\n```'
    with patch.object(agent, "run_opencode", return_value=fenced):
        assert agent.run_opencode_json("prompts/x.md") == {"target_roles": ["Virtual Assistant"]}


def test_run_opencode_json_passes_plain_json_through():
    import agent

    with patch.object(agent, "run_opencode", return_value='[{"score": 88}]'):
        assert agent.run_opencode_json("prompts/x.md") == [{"score": 88}]


def test_run_opencode_json_extracts_json_from_surrounding_prose():
    import agent

    chatty = (
        "I don't have write permission for `output/jobs.json`. Per the task "
        'instructions, here is the raw JSON array:\n\n[{"title": "Support Rep", '
        '"score": 72}]\n\nLet me know if you need anything else.'
    )
    with patch.object(agent, "run_opencode", return_value=chatty):
        assert agent.run_opencode_json("prompts/x.md") == [{"title": "Support Rep", "score": 72}]


def test_run_opencode_json_still_fails_loudly_on_no_json():
    import agent

    with patch.object(agent, "run_opencode", return_value="Sorry, I cannot do that."):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            agent.run_opencode_json("prompts/x.md")


def test_load_config_returns_defaults_without_file(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.setattr(config, "writable_config_path", lambda: tmp_path / "nope.json")
    monkeypatch.setattr(config, "_REPO_CONFIG", tmp_path / "nope2.json")
    cfg = agent.load_config()
    assert "linkedin.com/jobs" in cfg["job_boards"]
    assert "onlinejobs.ph" not in cfg["job_boards"]
    assert "reddit_groups" not in cfg


def test_load_config_overrides_from_file(tmp_path, monkeypatch):
    import agent
    import config

    (tmp_path / "config.json").write_text(
        json.dumps({"job_boards": ["indeed.com"], "reddit_groups": [{"name": "x", "subreddits": ["y"]}]})
    )
    monkeypatch.setattr(config, "writable_config_path", lambda: tmp_path / "config.json")
    cfg = agent.load_config()
    assert cfg["job_boards"] == ["indeed.com"]
    assert "reddit_groups" not in cfg


def test_sources_context_lists_boards_only():
    import agent

    ctx = agent._sources_context(
        {
            "job_boards": ["remoteok.com", "weworkremotely.com"],
            "reddit_groups": [
                {
                    "name": "Dev",
                    "subreddits": ["webdev", "cscareers"],
                    "extra_terms": "hiring",
                },
            ],
        }
    )
    assert "- remoteok.com" in ctx
    assert "- weworkremotely.com" in ctx
    assert "reddit" not in ctx.lower()
    assert "webdev" not in ctx


def test_run_opencode_raises_when_cli_missing(tmp_path, monkeypatch):
    import agent

    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompt.md").write_text("hello")
    with patch("user_data.find_opencode", return_value=None):
        with pytest.raises(RuntimeError, match="opencode CLI not found"):
            agent.run_opencode("prompt.md")


def test_run_opencode_uses_resolved_executable(tmp_path, monkeypatch):
    import agent
    import user_data
    from io import BytesIO

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    (tmp_path / "prompt.md").write_text("hello")
    fake_stdout = BytesIO(b"ok\n")
    fake_stderr = BytesIO(b"")
    fake_proc = SimpleNamespace(
        returncode=0,
        pid=12345,
        stdout=fake_stdout,
        stderr=fake_stderr,
        poll=lambda: 0,
    )
    with (
        patch("user_data.find_opencode", return_value="/usr/local/bin/opencode"),
        patch("user_data.opencode_argv", side_effect=lambda *a: ["/usr/local/bin/opencode", *a]),
        patch("user_data.opencode_run_env", return_value={"OPENCODE_CONFIG": str(tmp_path / "opencode.json")}),
        patch.object(agent.subprocess, "Popen", return_value=fake_proc) as mock_popen,
        patch.object(agent, "_init_models"),
        patch.object(agent, "_healthy_models", ["fake/model"]),
    ):
        out = agent.run_opencode("prompt.md")
    assert out == "ok"
    assert mock_popen.call_args[0][0][0] == "/usr/local/bin/opencode"
    assert mock_popen.call_args.kwargs.get("cwd") == str(tmp_path)
    assert mock_popen.call_args.kwargs.get("env", {}).get("OPENCODE_CONFIG")


def test_analyze_jobs_writes_jobs_json(tmp_path, monkeypatch):
    import agent
    import config

    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text('# Experienced engineer with Python and systems work. Remote-friendly, GMT+8 timezone, seeking full-stack roles.\n')

    raw_jobs = [{"title": "Dev", "url": "https://example.com", "company": "Test"}]
    (out / "raw_jobs.json").write_text(json.dumps(raw_jobs))

    analyzed = [{"title": "Dev", "url": "https://example.com", "score": 85, "verdict": "apply"}]
    with (
        patch.object(agent, "run_opencode_json", return_value=analyzed) as mock_json,
        patch.object(agent, "_prior_scores_by_url", return_value={}),
        patch.object(agent, "_init_models"),
        patch.object(agent, "_next_model", return_value="test/model"),
    ):
        result = agent.analyze_jobs()

    assert len(result) == 1
    assert result[0]["title"] == "Dev"
    assert result[0]["url"] == "https://example.com"
    assert json.loads((out / "jobs.json").read_text()) == result
    assert mock_json.call_args.kwargs.get("model") == "test/model"


def test_run_opencode_respects_attempt_budget(tmp_path, monkeypatch):
    import agent
    import config
    from io import BytesIO
    from types import SimpleNamespace
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompt.md").write_text("hello")
    monkeypatch.setattr(config, "MAX_OPENCODE_ATTEMPTS", 3)
    monkeypatch.setattr(config, "MAX_RETRIES", 99)

    def _failing(*_a, **_k):
        return SimpleNamespace(
            returncode=1,
            pid=1,
            stdout=BytesIO(b""),
            stderr=BytesIO(b"fail"),
            poll=lambda: 1,
        )

    with (
        patch.object(agent, "_init_models"),
        patch.object(agent, "_healthy_models", ["m1", "m2"]),
        patch.object(agent, "_model_failures", {}),
        patch.object(agent, "_model_index", 0),
        patch("user_data.find_opencode", return_value="/fake/opencode"),
        patch.object(agent.subprocess, "Popen", side_effect=_failing),
        patch.object(agent, "_kill_process_tree"),
    ):
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            agent.run_opencode("prompt.md")


def test_invalidate_resume_profile_cache(tmp_path, monkeypatch):
    import agent
    import config

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    cache = tmp_path / "resume_profile.json"
    cache.write_text("{}", encoding="utf-8")
    agent.invalidate_resume_profile_cache()
    assert not cache.exists()
    agent.invalidate_resume_profile_cache()  # idempotent


def test_url_matches_enabled_boards():
    import config

    boards = ["indeed.com", "linkedin.com/jobs"]
    assert config.url_matches_enabled_boards("https://ph.indeed.com/viewjob?jk=1", boards)
    assert config.url_matches_enabled_boards("https://www.linkedin.com/jobs/view/123", boards)
    assert not config.url_matches_enabled_boards("https://wellfound.com/jobs/1", boards)


def test_filter_queries_to_boards():
    import agent

    boards = ["indeed.com", "jobstreet.com"]
    qs = agent.filter_queries_to_boards(
        [
            'site:indeed.com Python Philippines',
            'site:glassdoor.com Python USA',
            'Python remote',  # no site:
        ],
        boards,
    )
    assert qs == ['site:indeed.com Python Philippines']


def test_filter_jobs_by_prefs_drops_foreign_onsite():
    import agent

    profile = {"location": "Cebu City, Philippines", "timezone": "GMT+8"}
    jobs = [
        {"title": "Dev", "location": "Manila, Philippines", "url": "https://a"},
        {"title": "Dev", "location": "Remote", "url": "https://b"},
        {"title": "Dev", "location": "Bangalore, India", "url": "https://c"},
        {"title": "Dev", "location": "New York, United States", "url": "https://d"},
    ]
    kept = agent.filter_jobs_by_prefs(jobs, profile, ["remote", "hybrid", "onsite"])
    locs = {j["location"] for j in kept}
    assert "Manila, Philippines" in locs
    assert "Remote" in locs
    assert "Bangalore, India" not in locs
    assert "New York, United States" not in locs


def test_filter_jobs_by_prefs_drops_foreign_hybrid():
    import agent

    profile = {"location": "Cebu City, Philippines", "timezone": "GMT+8"}
    jobs = [
        {"title": "Dev", "location": "Makati, Philippines", "work_arrangement": "hybrid"},
        {"title": "Dev", "location": "London, United Kingdom", "work_arrangement": "hybrid"},
        {"title": "Dev", "location": "Hybrid Remote — New York, United States", "work_arrangement": "hybrid"},
        {"title": "Dev", "location": "Remote — Worldwide", "work_arrangement": "remote"},
        {"title": "Dev", "location": "United States", "work_arrangement": "remote"},
    ]
    kept = agent.filter_jobs_by_prefs(jobs, profile, ["remote", "hybrid", "onsite"])
    assert len(kept) == 3
    locs = {j["location"] for j in kept}
    assert "Makati, Philippines" in locs
    assert "Remote — Worldwide" in locs
    assert "United States" in locs  # pure remote abroad still OK
    assert not any("London" in (j["location"] or "") for j in kept)
    assert not any("New York" in (j["location"] or "") for j in kept)


def test_filter_jobs_by_prefs_respects_remote_off():
    import agent

    profile = {"location": "Philippines"}
    jobs = [
        {"title": "Dev", "location": "Remote — Worldwide", "work_arrangement": "remote"},
        {"title": "Dev", "location": "Cebu, Philippines", "work_arrangement": "onsite"},
    ]
    kept = agent.filter_jobs_by_prefs(jobs, profile, ["onsite"])
    assert len(kept) == 1
    assert kept[0]["work_arrangement"] == "onsite"


def test_discard_run_removes_raw_and_orphans(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    db.init_db()
    run_id = db.start_run()
    db.insert_raw_jobs(
        [{"title": "T", "url": "https://ex.com/a", "company": "C", "source": "ex.com"}],
        run_id,
    )
    # Job only from this run, no score yet
    db.upsert_job({"url": "https://ex.com/a", "title": "T", "company": "C"}, run_id)
    db.discard_run(run_id)
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM raw_jobs").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"] == 0
        row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        assert row["status"] == "cancelled"


def test_analyze_jobs_skips_already_scored(tmp_path, monkeypatch):
    import agent
    import config
    from unittest.mock import patch

    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    (tmp_path / "resume.md").write_text(
        "# Experienced engineer with Python and systems work. "
        "Remote-friendly, GMT+8 timezone, seeking full-stack roles.\n"
    )
    (out / "raw_jobs.json").write_text(
        json.dumps(
            [
                {
                    "title": "Old",
                    "url": "https://ex.com/old",
                    "company": "A",
                    "listing_status": "closed",
                },
                {"title": "New", "url": "https://ex.com/new", "company": "B"},
            ]
        )
    )
    prior = {
        agent._dedup_key("https://ex.com/old"): {
            "url": "https://ex.com/old",
            "title": "Old",
            "company": "A",
            "score": 70,
            "verdict": "review",
            "match_reasons": ["x"],
            "red_flags": [],
            "suggested_angle": "",
            "work_arrangement": "remote",
        }
    }
    analyzed = [
        {
            "title": "New",
            "url": "https://ex.com/new",
            "score": 90,
            "verdict": "apply",
            "match_reasons": [],
            "red_flags": [],
            "suggested_angle": "",
        }
    ]
    with (
        patch.object(agent, "_prior_scores_by_url", return_value=prior),
        patch.object(agent, "run_opencode_json", return_value=analyzed) as mock_json,
        patch.object(agent, "_init_models"),
        patch.object(agent, "_next_model", return_value="test/model"),
    ):
        result = agent.analyze_jobs()

    urls = {j["url"] for j in result}
    assert urls == {"https://ex.com/old", "https://ex.com/new"}
    old = next(j for j in result if j["url"].endswith("/old"))
    assert old["score"] == 70
    assert old["listing_status"] == "closed"  # refreshed from scrape
    # Only the fresh job was sent to the model
    assert mock_json.call_count == 1
    sent = mock_json.call_args.kwargs.get("context") or mock_json.call_args[1].get("context", "")
    if not sent and mock_json.call_args[0]:
        # context is keyword-only in our call — also check args
        pass
    ctx = mock_json.call_args.kwargs["context"]
    assert "https://ex.com/new" in ctx
    assert "https://ex.com/old" not in ctx


def test_analyze_jobs_runs_batches_in_parallel(tmp_path, monkeypatch):
    import agent
    import config
    import time
    from unittest.mock import patch

    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    monkeypatch.setattr(agent, "ANALYZE_BATCH_SIZE", 1)
    monkeypatch.setattr(agent, "ANALYZE_WORKERS", 3)
    (tmp_path / "resume.md").write_text(
        "# Experienced engineer with Python and systems work. "
        "Remote-friendly, GMT+8 timezone, seeking full-stack roles.\n"
    )
    raw = [
        {"title": f"J{i}", "url": f"https://ex.com/{i}", "company": "C"} for i in range(3)
    ]
    (out / "raw_jobs.json").write_text(json.dumps(raw))

    active = {"n": 0, "peak": 0}
    lock = __import__("threading").Lock()

    def _slow_json(*_a, **_k):
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        time.sleep(0.15)
        url = "https://ex.com/0"
        # return one job matching whatever; validator needs score fields
        # Extract from context which url
        ctx = _k.get("context", "")
        for i in range(3):
            if f"https://ex.com/{i}" in ctx:
                url = f"https://ex.com/{i}"
                break
        with lock:
            active["n"] -= 1
        return [
            {
                "title": "J",
                "url": url,
                "score": 80,
                "verdict": "apply",
                "match_reasons": [],
                "red_flags": [],
                "suggested_angle": "",
            }
        ]

    with (
        patch.object(agent, "_prior_scores_by_url", return_value={}),
        patch.object(agent, "run_opencode_json", side_effect=_slow_json),
        patch.object(agent, "_init_models"),
        patch.object(agent, "_next_model", return_value="test/model"),
    ):
        result = agent.analyze_jobs()

    assert len(result) == 3
    assert active["peak"] >= 2  # overlapped workers


def test_run_pipeline_cancel_before_score_discards(tmp_path, monkeypatch):
    import agent
    import config
    import db

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "RESUME_FILE", tmp_path / "resume.md")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    (tmp_path / "output").mkdir()
    (tmp_path / "resume.md").write_text(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    )
    db.init_db()

    def _cancel_on_analyze(*_a, **_k):
        raise RuntimeError("Run cancelled by user")

    with (
        patch.object(agent, "extract_resume_profile", return_value={}),
        patch.object(agent, "build_search_config", return_value={"search_queries": ["q"]}),
        patch.object(
            agent,
            "scrape_jobs",
            return_value=[{"title": "Dev", "url": "https://ex.com/1", "company": "C"}],
        ),
        patch.object(agent, "analyze_jobs", side_effect=_cancel_on_analyze),
    ):
        with pytest.raises(RuntimeError, match="cancelled"):
            agent.run_pipeline()

    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM raw_jobs").fetchone()["c"] == 0
        row = conn.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert row["status"] == "cancelled"
