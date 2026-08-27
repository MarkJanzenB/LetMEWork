"""Self-check for local key storage helpers."""

from io import BytesIO


def test_write_env_keys_local_only(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")

    user_data.write_env_keys(firecrawl_key="fc-test-secret", openrouter_key="")
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "FIRECRAWL_API_KEY=fc-test-secret" in text
    assert "OPENROUTER_API_KEY" not in text
    assert "never uploaded" in text.lower() or "ONLY on this PC" in text

    status = user_data.setup_status()
    assert status["has_firecrawl"] is True
    assert status["keys_local_only"] is True
    assert "fc-t" in status["firecrawl_masked"] or status["firecrawl_masked"].startswith("fc-")
    assert "test-secret" not in status["firecrawl_masked"]


def test_firecrawl_backup_key(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")

    user_data.write_env_keys(
        firecrawl_key="fc-primary-aaaa",
        firecrawl_backup_key="fc-backup-bbbb",
    )
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "FIRECRAWL_API_KEY=fc-primary-aaaa" in text
    assert "FIRECRAWL_API_KEY_BACKUP=fc-backup-bbbb" in text
    keys = user_data.firecrawl_api_keys()
    assert keys == ["fc-primary-aaaa", "fc-backup-bbbb"]
    status = user_data.setup_status()
    assert status["has_firecrawl_backup"] is True
    assert status["firecrawl_backup_masked"].startswith("fc-b")
    assert "backup-bbbb" not in status["firecrawl_backup_masked"]


def test_firecrawl_failover_swaps_on_quota(monkeypatch):
    import agent

    class FakeApp:
        def __init__(self, api_key):
            self.key = api_key

        def search(self, query, limit=10):
            if self.key == "primary":
                raise RuntimeError("402 Payment Required — insufficient credits")
            return type("R", (), {"web": []})()

    monkeypatch.setattr(agent, "FirecrawlApp", FakeApp)
    app = agent._FirecrawlFailover(["primary", "backup"])
    app.search("test")
    assert app._i == 1
    assert app._app.key == "backup"


def test_ensure_opencode_config_seeds_job_agent(tmp_path, monkeypatch):
    import json

    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    path = user_data.ensure_opencode_config()
    assert path == tmp_path / "opencode.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert "job-agent" in cfg["agent"]
    # Re-run keeps existing provider block if present
    cfg["provider"] = {"ollama": {"models": {"x": {"name": "x"}}}}
    path.write_text(json.dumps(cfg), encoding="utf-8")
    user_data.ensure_opencode_config()
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["provider"]["ollama"]["models"]["x"]["name"] == "x"
    assert "job-agent" in again["agent"]


def test_opencode_argv_wraps_cmd(monkeypatch, tmp_path):
    import user_data

    cmd = tmp_path / "opencode.cmd"
    cmd.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(user_data, "find_opencode", lambda: str(cmd))
    argv = user_data.opencode_argv("run", "hi")
    assert argv[:3] == ["cmd.exe", "/c", str(cmd)]
    assert argv[3:] == ["run", "hi"]


def test_soft_install_opencode_skips_when_present(monkeypatch, tmp_path):
    import user_data

    monkeypatch.setattr(user_data, "find_opencode", lambda: str(tmp_path / "opencode.exe"))
    out = user_data.soft_install_opencode()
    assert out["ok"] is True
    assert out["already_present"] is True
    assert "opencode.exe" in out["path"]


def test_parse_and_pick_opencode_free_models():
    import model_prober

    text = (
        "opencode/big-pickle\n"
        "opencode/claude-opus-5\n"
        "opencode/deepseek-v4-flash-free\n"
        "  opencode/laguna-s-2.1-free  free  $0\n"
        "\x1b[32mopencode/mimo-v2.5-free\x1b[0m\n"
        "openrouter/other/x\n"
    )
    ids = model_prober._parse_opencode_model_ids(text)
    assert "opencode/big-pickle" in ids
    assert "opencode/deepseek-v4-flash-free" in ids
    assert "opencode/laguna-s-2.1-free" in ids
    assert "opencode/mimo-v2.5-free" in ids
    picked = model_prober._pick_opencode_free_candidates(ids)
    assert "opencode/big-pickle" in picked
    assert "opencode/deepseek-v4-flash-free" in picked
    assert "opencode/claude-opus-5" not in picked


def test_pick_opencode_falls_back_to_cheap_hints():
    import model_prober

    listed = [
        "opencode/claude-opus-5",
        "opencode/gpt-5-nano",
        "opencode/gemini-3-flash",
    ]
    picked = model_prober._pick_opencode_free_candidates(listed)
    assert picked[0] in ("opencode/gpt-5-nano", "opencode/gemini-3-flash")
    assert "opencode/claude-opus-5" not in picked


def test_probe_skips_openrouter_without_key(tmp_path, monkeypatch):
    import io

    import model_prober

    monkeypatch.setattr(model_prober.user_data, "apply_env_to_process", lambda: None)
    monkeypatch.setattr(model_prober.user_data, "read_env_keys", lambda: {})
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(model_prober, "probe_ollama_models", lambda: [])
    monkeypatch.setattr(model_prober.user_data, "find_opencode", lambda: None)
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    healthy = model_prober.probe_all_models()
    assert healthy == []
    assert "Skipping OpenRouter — not configured" in buf.getvalue()


def test_discover_openrouter_prefers_free(monkeypatch):
    import io
    import json

    import model_prober

    payload = {
        "data": [
            {"id": "vendor/paid-model", "pricing": {"prompt": "1", "completion": "1"}},
            {"id": "vendor/free-a:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "~alias/skip", "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }

    class CM:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(model_prober, "_openrouter_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_prober.urllib.request, "urlopen", lambda *a, **k: CM()
    )
    monkeypatch.setattr("sys.stdout", io.StringIO())
    ids = model_prober.discover_openrouter_models()
    assert ids[0] == "openrouter/vendor/free-a:free"
    assert "openrouter/vendor/paid-model" in ids
    assert all(not x.startswith("openrouter/~") for x in ids)


def test_ollama_probe_and_opencode_sync(tmp_path, monkeypatch):
    import io
    import json

    import model_prober

    tags = {"models": [{"name": "gemma4:e4b"}, {"name": "dead:model"}]}

    class CM:
        def __init__(self, data: bytes):
            self._buf = io.BytesIO(data)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._buf.read()

    def urlopen_smart(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        assert "ollama.com" in str(url)
        if str(url).endswith("/api/tags"):
            return CM(json.dumps(tags).encode())
        data = getattr(req, "data", b"") or b""
        if b"dead:model" in data:
            return CM(json.dumps({"response": ""}).encode())
        return CM(json.dumps({"response": "hello"}).encode())

    oc_path = tmp_path / "opencode.json"
    oc_path.write_text('{"$schema": "x", "agent": {"job-agent": {}}}', encoding="utf-8")
    monkeypatch.setattr(model_prober, "_opencode_json_path", lambda: oc_path)
    monkeypatch.setattr(model_prober, "_ollama_api_key", lambda: "test-key")
    monkeypatch.setattr(model_prober.urllib.request, "urlopen", urlopen_smart)

    healthy = model_prober.probe_ollama_models()
    assert healthy == ["gemma4:e4b"]
    model_prober.sync_ollama_models_to_opencode(healthy)
    cfg = json.loads(oc_path.read_text(encoding="utf-8"))
    assert "gemma4:e4b" in cfg["provider"]["ollama"]["models"]
    assert cfg["provider"]["ollama"]["options"]["baseURL"] == "https://ollama.com/v1"
    assert cfg["agent"]["job-agent"] == {}


def test_ollama_skipped_without_key(monkeypatch):
    import io

    import model_prober

    monkeypatch.setattr(model_prober, "_ollama_api_key", lambda: "")
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    assert model_prober.probe_ollama_models() == []
    assert "Skipping Ollama Cloud" in buf.getvalue()


def test_save_resume(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    path = user_data.save_resume_text("# Me\n\nDeveloper")
    assert path.exists()
    assert "Developer" in path.read_text(encoding="utf-8")


def _minimal_text_pdf(text: str) -> bytes:
    """Tiny PDF with a text stream (no OCR)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    stream = content.encode("latin-1")
    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("latin-1")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref = out.tell()
    out.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.write(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return out.getvalue()


def test_save_resume_pdf_keeps_original_and_extracts_text(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    monkeypatch.setattr(user_data, "resume_pdf_path", lambda: tmp_path / "resume.pdf")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")

    data = _minimal_text_pdf("HelloResumePDF")
    result = user_data.save_resume_pdf(data, original_name="Mark_CV.pdf")
    assert (tmp_path / "resume.pdf").exists()
    assert (tmp_path / "resume.pdf").read_bytes().startswith(b"%PDF")
    assert "HelloResumePDF" in result["content"]
    assert "HelloResumePDF" in (tmp_path / "resume.md").read_text(encoding="utf-8")
    assert result["original_name"] == "Mark_CV.pdf"


def test_resume_is_usable_rejects_stub_and_short():
    import user_data

    assert user_data.resume_is_usable("") is False
    assert user_data.resume_is_usable("# New Resume\nUpdated") is False
    assert user_data.resume_is_usable("# New Resume\n" + ("x" * 50)) is False
    assert user_data.resume_is_usable(
        "# Mark Bandola\n\nSoftware developer with Python, React, and embedded "
        "experience. Based in Cebu (GMT+8). Seeking remote AI / full-stack roles.\n"
    ) is True


def test_resume_usable_in_setup_status(tmp_path, monkeypatch):
    import user_data

    monkeypatch.setattr(user_data, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(user_data, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(user_data, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(user_data, "resume_path", lambda: tmp_path / "resume.md")
    monkeypatch.setattr(user_data, "resource_dir", lambda: tmp_path / "missing-repo")
    monkeypatch.setattr(user_data, "find_opencode", lambda: None)
    (tmp_path / "resume.md").write_text("# New Resume\nUpdated\n", encoding="utf-8")
    status = user_data.setup_status()
    assert status["has_resume"] is True
    assert status["resume_usable"] is False
    assert status["ready"] is False
