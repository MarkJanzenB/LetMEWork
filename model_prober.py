"""Model health prober — discover then probe (no hardcoded model menus).

Flow:
  1. Ollama reachable → list `/api/tags`, probe each, sync into opencode.json
  2. OpenRouter API key present → list OpenRouter `/api/v1/models`, probe via OpenCode
  3. Else (no Ollama hits and no OpenRouter key) → `opencode models opencode` free list

OpenRouter / OpenCode builtins are health-checked with `opencode run`.
"""

from __future__ import annotations

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
OLLAMA_CLOUD = "https://ollama.com"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
# ponytail: cap OpenRouter / Ollama cloud probes — catalogs can be huge
OPENROUTER_PROBE_MAX = 16
OLLAMA_CLOUD_PROBE_MAX = 16


# ── Ollama via native HTTP API (local and/or ollama.com cloud key) ──


def _ollama_api_key() -> str:
    user_data.apply_env_to_process()
    keys = user_data.read_env_keys()
    return (keys.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY") or "").strip()


def _ollama_http_json(url: str, *, body: dict | None = None, timeout: float = 30) -> dict | None:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key = _ollama_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _tags_from_payload(data: dict | None) -> list[str]:
    if not data:
        return []
    names: list[str] = []
    for m in data.get("models") or []:
        name = (m.get("name") or m.get("model") or "").strip()
        if name:
            names.append(name)
    return names


def _ollama_list_models() -> list[str]:
    """Local daemon tags, plus ollama.com tags when OLLAMA_API_KEY is set."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(names: list[str]) -> None:
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)

    print(f"  Listing Ollama models ({OLLAMA_HOST})...", flush=True)
    local = _tags_from_payload(_ollama_http_json(f"{OLLAMA_HOST}/api/tags", timeout=10))
    if local:
        print(f"  Local Ollama: {len(local)} model(s)", flush=True)
        _add(local)
    else:
        print("  Local Ollama unavailable (is `ollama serve` running?)", flush=True)

    if _ollama_api_key():
        print(f"  Listing Ollama cloud models ({OLLAMA_CLOUD})…", flush=True)
        cloud = _tags_from_payload(_ollama_http_json(f"{OLLAMA_CLOUD}/api/tags", timeout=30))
        if cloud:
            # Prefer cloud-style tags; cap probe budget later
            print(f"  Ollama cloud: {len(cloud)} model(s)", flush=True)
            _add(cloud)
        else:
            print("  Ollama cloud list failed (check OLLAMA_API_KEY)", flush=True)
    else:
        print("  Skipping Ollama cloud — no API key (optional; local still used)", flush=True)

    return out


def _probe_ollama_model(name: str) -> bool:
    """Health-check one Ollama model via local host, then ollama.com if keyed."""
    body = {"model": name, "prompt": PROBE_PROMPT, "stream": False}
    for base in (OLLAMA_HOST, OLLAMA_CLOUD if _ollama_api_key() else ""):
        if not base:
            continue
        data = _ollama_http_json(
            f"{base}/api/generate",
            body=body,
            timeout=OLLAMA_PROBE_TIMEOUT,
        )
        if data and bool((data.get("response") or "").strip()):
            return True
    return False


def probe_ollama_models() -> list[str]:
    """Probe discovered Ollama tags; return healthy bare tags."""
    names = _ollama_list_models()
    if not names:
        print("  No Ollama models found", flush=True)
        return []

    # Prefer local-first order already; cap cloud-heavy lists
    if len(names) > OLLAMA_CLOUD_PROBE_MAX and _ollama_api_key():
        names = names[:OLLAMA_CLOUD_PROBE_MAX]
        print(f"  Capping Ollama probes at {OLLAMA_CLOUD_PROBE_MAX}", flush=True)

    total = len(names)
    print(f"  Probing {total} Ollama model(s)…", flush=True)
    healthy: list[str] = []
    for i, name in enumerate(names, 1):
        print(f"    [{i}/{total}] ollama/{name}...", end="", flush=True)
        ok = _probe_ollama_model(name)
        print(f" {'✓' if ok else '✗'}", flush=True)
        if ok:
            healthy.append(name)
    return healthy


def _opencode_json_path() -> Path:
    """Writable opencode.json (AppData) — seeded with job-agent for frozen runs."""
    return user_data.ensure_opencode_config()


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
    local_up = _ollama_http_json(f"{OLLAMA_HOST}/api/tags", timeout=3) is not None
    if _ollama_api_key() and not local_up:
        options["baseURL"] = f"{OLLAMA_CLOUD}/v1"
    else:
        options["baseURL"] = f"{OLLAMA_HOST}/v1"
    ollama["models"] = {name: {"name": name} for name in healthy_names}

    try:
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(
            f"  Synced {len(healthy_names)} Ollama model(s) → {path} (provider.ollama)",
            flush=True,
        )
    except OSError as e:
        print(f"  Could not write {path}: {e}", flush=True)


# ── Discovery ─────────────────────────────────────────────────


def _openrouter_api_key() -> str:
    user_data.apply_env_to_process()
    keys = user_data.read_env_keys()
    return (
        keys.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
    ).strip()


def _is_openrouter_free(entry: dict) -> bool:
    mid = str(entry.get("id") or "")
    if mid.endswith(":free") or ":free" in mid:
        return True
    pricing = entry.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt") or 0)
        completion = float(pricing.get("completion") or 0)
    except (TypeError, ValueError):
        return False
    return prompt == 0.0 and completion == 0.0


def discover_openrouter_models() -> list[str]:
    """List OpenRouter model ids (prefer free), prefixed for OpenCode."""
    key = _openrouter_api_key()
    if not key:
        return []
    print("  Discovering OpenRouter models…", flush=True)
    req = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        print(f"  OpenRouter model list failed: {e}", flush=True)
        return []

    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        print("  OpenRouter model list: unexpected response shape", flush=True)
        return []

    free: list[str] = []
    paid: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or "").strip()
        if not mid or mid.startswith("~"):
            continue
        tagged = mid if mid.startswith("openrouter/") else f"openrouter/{mid}"
        if _is_openrouter_free(entry):
            free.append(tagged)
        else:
            paid.append(tagged)

    chosen = free[:OPENROUTER_PROBE_MAX]
    if len(chosen) < OPENROUTER_PROBE_MAX:
        chosen.extend(paid[: OPENROUTER_PROBE_MAX - len(chosen)])
    print(
        f"  OpenRouter: {len(free)} free / {len(paid)} other — probing {len(chosen)}",
        flush=True,
    )
    return chosen


def discover_opencode_free_models() -> list[str]:
    """OpenCode built-in free models via `opencode models opencode`."""
    argv = user_data.opencode_argv("models", "opencode")
    if not argv:
        return []
    print("  Discovering OpenCode free models…", flush=True)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=60,
            cwd=str(user_data.user_data_dir()),
            env=user_data.opencode_run_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  OpenCode model list failed: {e}", flush=True)
        return []
    text = (proc.stdout or b"").decode("utf-8", errors="replace")
    out: list[str] = []
    for line in text.splitlines():
        mid = line.strip()
        if not mid or mid.startswith("-") or " " in mid:
            continue
        if not mid.startswith("opencode/"):
            continue
        # free tier markers used by OpenCode Zen / builtins
        if mid.endswith("-free") or mid.endswith(":free") or mid.endswith("/free"):
            out.append(mid)
    print(f"  OpenCode free: {len(out)} model(s)", flush=True)
    return out


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

    argv = user_data.opencode_argv("run", PROBE_PROMPT, "--model", model_id)
    if not argv:
        return False
    proc = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(user_data.user_data_dir()),
            env=user_data.opencode_run_env(),
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


def _probe_model_ids(model_ids: list[str]) -> list[dict]:
    healthy: list[dict] = []
    total = len(model_ids)
    if not total:
        return healthy
    print(f"  Probing {total} discovered model(s) via OpenCode…", flush=True)
    for i, model_id in enumerate(model_ids, 1):
        provider = model_id.split("/")[0]
        print(f"    [{i}/{total}] {model_id}...", end="", flush=True)
        ok = _probe_opencode_model(model_id)
        print(f" {'✓' if ok else '✗'}", flush=True)
        if ok:
            healthy.append(
                {"model": model_id, "provider": provider, "last_ok": time.time()}
            )
    return healthy


def probe_all_models() -> list[dict]:
    """Discover configured providers, then probe — no hardcoded candidate menus."""
    healthy: list[dict] = []
    now = time.time()

    ollama_ok = probe_ollama_models()
    if ollama_ok:
        sync_ollama_models_to_opencode(ollama_ok)
        for name in ollama_ok:
            healthy.append(
                {"model": f"ollama/{name}", "provider": "ollama", "last_ok": now}
            )

    has_or_key = bool(_openrouter_api_key())
    has_oc = bool(user_data.find_opencode())
    to_probe: list[str] = []

    if has_or_key:
        if has_oc:
            to_probe.extend(discover_openrouter_models())
        else:
            print(
                "  Skipping OpenRouter probes — OpenCode CLI not found "
                f"(install from {user_data.OPENCODE_INSTALL_URL}).",
                flush=True,
            )
    else:
        print("  Skipping OpenRouter — not configured", flush=True)

    # Free OpenCode builtins only when neither Ollama nor OpenRouter can supply models
    if not ollama_ok and not has_or_key:
        if has_oc:
            to_probe.extend(discover_opencode_free_models())
        else:
            print(
                "  OpenCode CLI not found — no free-model fallback.\n"
                f"  Install from {user_data.OPENCODE_INSTALL_URL} or set OPENCODE_PATH.",
                flush=True,
            )

    # de-dupe preserving order
    seen: set[str] = set()
    unique = []
    for mid in to_probe:
        if mid not in seen:
            seen.add(mid)
            unique.append(mid)

    healthy.extend(_probe_model_ids(unique))
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
    """Load cache if fresher than a week; otherwise discover + probe providers.

    If a forced/stale re-probe finds nothing, fall back to whatever is still
    on disk so a flaky probe night doesn't brick the pipeline.
    """
    stale_fallback, _ = _models_from_disk()
    if not force_probe:
        cached = load_healthy_models()
        if cached:
            print(f"  Loaded {len(cached)} healthy models from cache", flush=True)
            return cached

    print("  Discovering model providers…", flush=True)
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

    if not user_data.find_opencode() and not _openrouter_api_key():
        print(
            "  WARNING: No healthy models — configure Ollama, OpenRouter, "
            f"or install OpenCode ({user_data.OPENCODE_INSTALL_URL}).",
            flush=True,
        )
    else:
        print("  WARNING: No healthy models found!", flush=True)
    return []
