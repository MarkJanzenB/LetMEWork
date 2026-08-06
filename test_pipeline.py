import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest


def test_discover_pages_interleaves_results_across_queries():
    import agent

    results = {
        "q1": [
            SimpleNamespace(url=f"https://a.com/{i}", title="", description="") for i in range(3)
        ],
        "q2": [
            SimpleNamespace(url=f"https://b.com/{i}", title="", description="") for i in range(2)
        ],
        "q3": [],
    }
    fake_app = SimpleNamespace(search=lambda q, limit: SimpleNamespace(web=results[q]))

    pages = agent.discover_pages(fake_app, ["q1", "q2", "q3"])

    assert [p["url"] for p in pages] == [
        "https://a.com/0",
        "https://b.com/0",
        "https://a.com/1",
        "https://b.com/1",
        "https://a.com/2",
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

    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.md").write_text("# Resume")
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
    assert result == {"total": 1, "above_threshold": 1}


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

    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.md").write_text("# Resume")
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
    monkeypatch.setattr(config, "GENERATE_COVER_LETTERS_IN_PIPELINE", False)
    (tmp_path / "resume.md").write_text("# Resume")
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
    with patch.object(agent.shutil, "which", return_value=None):
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
    (tmp_path / "resume.md").write_text("I build things.")

    raw_jobs = [{"title": "Dev", "url": "https://example.com", "company": "Test"}]
    (out / "raw_jobs.json").write_text(json.dumps(raw_jobs))

    analyzed = [{"title": "Dev", "url": "https://example.com", "score": 85, "verdict": "apply"}]
    with patch.object(agent, "run_opencode_json", return_value=analyzed):
        result = agent.analyze_jobs()

    assert len(result) == 1
    assert result[0]["title"] == "Dev"
    assert result[0]["url"] == "https://example.com"
    assert json.loads((out / "jobs.json").read_text()) == result


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
