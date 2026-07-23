"""Model health prober — discovers and tests all available models across
OpenRouter, Ollama, and opencode built-in providers.

Saves working models to data/healthy_models.json so the pipeline can
rotate through known-good models without re-probing every run.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import config

HEALTH_FILE = config.DATA_DIR / "healthy_models.json"
PROBE_PROMPT = "Reply with only the word hello."
PROBE_TIMEOUT = 30  # seconds per model probe


# ── candidate models by provider ──────────────────────────────


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


def _ollama_candidates() -> list[str]:
    """Discover Ollama models — both local and cloud. Gemma 4 cloud models
    are preferred for quality."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        models = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            name = line.split()[0].strip()
            if name:
                models.append(f"ollama/{name}")
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _ollama_cloud_candidates() -> list[str]:
    """Hardcoded Ollama cloud Gemma 4 models — probe even if not pulled locally."""
    return [
        "ollama/gemma4:31b-cloud",
        "ollama/gemma4:e2b",
    ]


def _opencode_builtin_candidates() -> list[str]:
    """Known opencode built-in free models."""
    return [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
    ]


# ── probing ───────────────────────────────────────────────────


def _probe_model(model_id: str) -> bool:
    """Test a model by sending a trivial prompt. Returns True if it responds."""
    import re

    opencode_exe = shutil.which("opencode")
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
            try:
                proc.kill()
            except Exception:
                pass
        return False
    except Exception:
        return False


def probe_all_models() -> list[dict]:
    """Probe every candidate model across all providers.
    Returns a list of healthy model dicts sorted by provider then name.
    """
    candidates = (
        _ollama_cloud_candidates()  # Gemma 4 cloud first — best quality
        + _ollama_candidates()  # local ollama models
        + _openrouter_candidates()
        + _opencode_builtin_candidates()
    )

    total = len(candidates)
    print(f"  Probing {total} candidate models...")
    healthy: list[dict] = []
    for i, model_id in enumerate(candidates, 1):
        provider = model_id.split("/")[0]
        print(f"    [{i}/{total}] Probing {model_id}...", end="", flush=True)
        ok = _probe_model(model_id)
        status = "✓" if ok else "✗"
        print(f" {status}")
        if ok:
            healthy.append(
                {
                    "model": model_id,
                    "provider": provider,
                    "last_ok": time.time(),
                }
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
    print(f"  Saved {len(models)} healthy models to {HEALTH_FILE}")


def load_healthy_models(max_age_seconds: float = 3600) -> list[str]:
    """Load healthy model IDs from disk. Returns empty list if file is
    missing, stale (older than max_age_seconds), or has no models.
    """
    if not HEALTH_FILE.exists():
        return []
    try:
        data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        age = time.time() - data.get("probed_at", 0)
        if age > max_age_seconds:
            print(f"  Model cache stale ({int(age)}s old) — will re-probe")
            return []
        models = data.get("models", [])
        return [m["model"] for m in models if m.get("model")]
    except (json.JSONDecodeError, KeyError):
        return []


def get_healthy_models(force_probe: bool = False) -> list[str]:
    """Get healthy models: load from cache if fresh, otherwise probe all."""
    if not force_probe:
        cached = load_healthy_models()
        if cached:
            print(f"  Loaded {len(cached)} healthy models from cache")
            return cached

    print("  Probing all model providers...")
    healthy = probe_all_models()
    if healthy:
        save_healthy_models(healthy)
    else:
        print("  WARNING: No healthy models found!")
    return [m["model"] for m in healthy]
