"""Model health prober — discovers and tests models across
OpenRouter, Ollama, and OpenCode built-in providers.

Ollama is probed via the Ollama HTTP API (not OpenCode). Healthy Ollama
models are written into opencode.json's provider.ollama.models so OpenCode
can see them. OpenRouter / OpenCode builtins are still probed via OpenCode.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import config
import user_data

HEALTH_FILE = config.DATA_DIR / "healthy_models.json"
PROBE_PROMPT = "Reply with only the word hello."
PROBE_TIMEOUT = 30  # seconds per OpenCode model probe
OLLAMA_PROBE_TIMEOUT = 60  # local/cloud Ollama generate can be slower
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


# ── OpenRouter / OpenCode candidates (still probed via OpenCode) ──


def _openrouter_candidates() -> list[str]:
    """Known free OpenRouter models to probe."""
    return [
        "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/google/gemma-4-31b-it:free",
        "openrouter/openai/gpt-oss-20b:free",
        "openrouter/cohere/north-mini-code:free",
        "openrouter/google/gemma-3-27b-it:free",
        "openrouter/meta-llama/llama-4-scout:free",
        "openrouter/mistralai/mistral-small-3.2-24b-instruct:free",
        "openrouter/qwen/qwen3-235b-a22b:free",
        "openrouter/qwen/qwen3-coder:free",
        "openrouter/deepseek/deepseek-chat-v3-0324:free",
        "openrouter/deepseek/deepseek-r1-0528:free",
    ]


def _opencode_builtin_candidates() -> list[str]:
    """Known opencode built-in free models."""
    return [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
    ]


# ── Ollama via native HTTP API ────────────────────────────────


def _ollama_list_models() -> list[str]:
    """All model tags from the local Ollama daemon."""
    try:
        print(f"  Listing Ollama models ({OLLAMA_HOST})...", flush=True)
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        names = []
        for m in data.get("models") or []:
            name = (m.get("name") or "").strip()
            if name:
                names.append(name)
        return names
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        print(f"  Ollama list failed: {e}", flush=True)
        return []


def _probe_ollama_model(name: str) -> bool:
    """Health-check one Ollama model via /api/generate (not OpenCode)."""
    body = json.dumps(
        {
            "model": name,
            "prompt": PROBE_PROMPT,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_PROBE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return bool((data.get("response") or "").strip())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def probe_ollama_models() -> list[str]:
    """Probe every model Ollama reports; return healthy bare tags."""
    names = _ollama_list_models()
    if not names:
        print("  No Ollama models found (is `ollama serve` running?)", flush=True)
        return []

    total = len(names)
    print(f"  Probing {total} Ollama model(s) via Ollama API...", flush=True)
    healthy: list[str] = []
    for i, name in enumerate(names, 1):
        print(f"    [{i}/{total}] ollama/{name}...", end="", flush=True)
        ok = _probe_ollama_model(name)
        print(f" {'✓' if ok else '✗'}", flush=True)
        if ok:
            healthy.append(name)
    return healthy


def _opencode_json_path() -> Path:
    """Project opencode.json (dev) or resource dir when packaged."""
    repo = Path(__file__).resolve().parent / "opencode.json"
    if repo.is_file() or not user_data.is_frozen():
        return repo
    return config.BASE_DIR / "opencode.json"


def sync_ollama_models_to_opencode(healthy_names: list[str]) -> None:
    """Write healthy Ollama tags into opencode.json provider.ollama.models."""
    path = _opencode_json_path()
    cfg: dict = {}
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Could not read {path}: {e} — skipping OpenCode sync", flush=True)
            return

    provider = cfg.setdefault("provider", {})
    ollama = provider.setdefault("ollama", {})
    ollama["npm"] = ollama.get("npm") or "@ai-sdk/openai-compatible"
    ollama["name"] = ollama.get("name") or "Ollama"
    options = ollama.setdefault("options", {})
    options["baseURL"] = options.get("baseURL") or f"{OLLAMA_HOST}/v1"
    ollama["models"] = {name: {"name": name} for name in healthy_names}

    try:
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(
            f"  Synced {len(healthy_names)} Ollama model(s) → {path} (provider.ollama)",
            flush=True,
        )
    except OSError as e:
        print(f"  Could not write {path}: {e}", flush=True)


# ── OpenCode probing (non-Ollama providers) ───────────────────


def _kill_probe(proc: subprocess.Popen) -> None:
    """Kill probe process tree; drain pipes so communicate can't hang."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def _probe_opencode_model(model_id: str) -> bool:
    """Test a model via `opencode run` (OpenRouter / builtins)."""
    import re

    opencode_exe = user_data.find_opencode()
    if not opencode_exe:
        return False
    proc = None
    try:
        proc = subprocess.Popen(
            [opencode_exe, "run", PROBE_PROMPT, "--model", model_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=".",
        )
        stdout_bytes, _ = proc.communicate(timeout=PROBE_TIMEOUT)
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stdout = re.sub(r"^>.*·.*\n?", "", stdout).strip()
        return bool(stdout)
    except subprocess.TimeoutExpired:
        if proc is not None:
            _kill_probe(proc)
        return False
    except Exception:
        if proc is not None:
            _kill_probe(proc)
        return False


def probe_all_models() -> list[dict]:
    """Probe Ollama natively, sync into OpenCode, then probe other providers."""
    healthy: list[dict] = []
    now = time.time()

    ollama_ok = probe_ollama_models()
    if ollama_ok:
        sync_ollama_models_to_opencode(ollama_ok)
        for name in ollama_ok:
            healthy.append(
                {"model": f"ollama/{name}", "provider": "ollama", "last_ok": now}
            )

    others = _openrouter_candidates() + _opencode_builtin_candidates()
    total = len(others)
    if total:
        print(f"  Probing {total} OpenCode/OpenRouter model(s)...", flush=True)
    for i, model_id in enumerate(others, 1):
        provider = model_id.split("/")[0]
        print(f"    [{i}/{total}] {model_id}...", end="", flush=True)
        ok = _probe_opencode_model(model_id)
        print(f" {'✓' if ok else '✗'}", flush=True)
        if ok:
            healthy.append(
                {"model": model_id, "provider": provider, "last_ok": time.time()}
            )

    return healthy


# ── persistence ────────────────────────────────────────────────


def save_healthy_models(models: list[dict]) -> None:
    """Write healthy models to disk."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "probed_at": time.time(),
        "models": models,
    }
    HEALTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved {len(models)} healthy models to {HEALTH_FILE}", flush=True)


def _models_from_disk() -> tuple[list[str], float | None]:
    """Return (model ids, probed_at) from cache file; empty if unreadable."""
    if not HEALTH_FILE.exists():
        return [], None
    try:
        data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        models = [m["model"] for m in data.get("models", []) if m.get("model")]
        return models, data.get("probed_at")
    except (json.JSONDecodeError, KeyError, OSError, TypeError):
        return [], None


def load_healthy_models(max_age_seconds: float | None = None) -> list[str]:
    """Load healthy model IDs from disk if cache is fresh.

    Older than PROBE_CACHE_TTL (default 1 week) → [] so caller re-probes.
    Missing/empty → [].
    """
    if max_age_seconds is None:
        max_age_seconds = float(config.PROBE_CACHE_TTL)
    models, probed_at = _models_from_disk()
    if not models:
        return []
    if probed_at is None:
        return models
    age = time.time() - probed_at
    if age > max_age_seconds:
        days = age / 86400
        print(
            f"  Model cache stale ({days:.1f}d old) — will re-probe",
            flush=True,
        )
        return []
    return models


def get_healthy_models(force_probe: bool = False) -> list[str]:
    """Load cache if fresher than a week; otherwise probe all providers.

    If a forced/stale re-probe finds nothing, fall back to whatever is still
    on disk so a flaky probe night doesn't brick the pipeline.
    """
    stale_fallback, _ = _models_from_disk()
    if not force_probe:
        cached = load_healthy_models()
        if cached:
            print(f"  Loaded {len(cached)} healthy models from cache", flush=True)
            return cached

    print("  Probing all model providers...", flush=True)
    healthy = probe_all_models()
    if healthy:
        save_healthy_models(healthy)
        return [m["model"] for m in healthy]

    if stale_fallback:
        print(
            f"  WARNING: Probe found no healthy models — "
            f"falling back to {len(stale_fallback)} cached model(s)",
            flush=True,
        )
        return stale_fallback

    print("  WARNING: No healthy models found!", flush=True)
    return []
