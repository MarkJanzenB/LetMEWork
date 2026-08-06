# agent.py
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from urllib.parse import urljoin, urlparse

from firecrawl import FirecrawlApp

import db
import config

config.bootstrap()

# ── free model rotation state ──────────────────────────
import model_prober

_healthy_models: list[str] = []  # Loaded from cache or probed at startup
_model_index = 0  # Rotation cursor
_model_failures: dict[str, int] = {}  # Consecutive failures per model
_pipeline_cancel = threading.Event()
_current_opencode_proc: subprocess.Popen | None = None


def request_pipeline_cancel() -> None:
    """Signal the active pipeline (and OpenCode child) to stop."""
    _pipeline_cancel.set()
    proc = _current_opencode_proc
    if proc is not None and proc.poll() is None:
        _kill_process_tree(proc)


def _check_cancelled() -> None:
    if _pipeline_cancel.is_set():
        raise RuntimeError("Run cancelled by user")


def _init_models() -> None:
    """Load healthy models from disk cache (or probe all providers)."""
    global _healthy_models
    if not _healthy_models:
        _healthy_models = model_prober.get_healthy_models()
        if _healthy_models:
            print(f"  Model pool: {len(_healthy_models)} healthy models loaded")
        else:
            raise RuntimeError(
                "No healthy models found. Check that opencode, ollama, and/or "
                "OPENROUTER_API_KEY are configured."
            )


def _next_model() -> str:
    """Round-robin through healthy models."""
    global _model_index
    if not _healthy_models:
        _init_models()
    model = _healthy_models[_model_index % len(_healthy_models)]
    _model_index += 1
    return model


def _mark_model_failed(model: str) -> None:
    """Track consecutive failures. Reset on success via _reset_model."""
    _model_failures[model] = _model_failures.get(model, 0) + 1


def _reset_model(model: str) -> None:
    """Success — reset failure count to 0."""
    _model_failures[model] = 0


def _get_healthy_model() -> str:
    """Find next model with failures < MAX_RETRIES.

    Re-probes providers at most once; then raises instead of rotating forever.
    """
    global _healthy_models
    for _ in range(max(len(_healthy_models), 1)):
        candidate = _next_model()
        if _model_failures.get(candidate, 0) < config.MAX_RETRIES:
            return candidate
    if not getattr(_get_healthy_model, "_reprobed", False):
        _get_healthy_model._reprobed = True  # type: ignore[attr-defined]
        print("  All models exhausted — re-probing providers once...")
        _model_failures.clear()
        _healthy_models = model_prober.get_healthy_models(force_probe=True)
        if not _healthy_models:
            raise RuntimeError(
                "No healthy models found after re-probe. Check opencode / providers."
            )
        print(f"  Model pool: {len(_healthy_models)} healthy models loaded")
        return _next_model()
    raise RuntimeError("All OpenCode models exhausted after re-probe")


# Where to search. config.json (same shape) overrides these defaults, so the
# job boards can be tailored without editing code or prompts.

# What Firecrawl should pull out of each scraped page.
EXTRACT_PROMPT = (
    "Extract every individual job posting on this page. For each posting capture "
    "the job title, the hiring company, the location, the direct URL to that "
    "specific posting (not this listing/search page), the date it was posted, and "
    "a short description. If the page is already a single job posting, return just "
    "that one. Ignore navigation links, ads, related searches, and other pages."
)
JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {
                        "type": "string",
                        "description": "Direct link to the individual job posting.",
                    },
                    "posted_date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["jobs"],
}


# ── search sources config ─────────────────────────────────
def load_config() -> dict:
    """Return the search-sources config (AppData / repo override of defaults)."""
    return config.load_search_config()


def _sources_context(cfg: dict) -> str:
    """Render the configured job boards as prompt context for build_queries.md."""
    boards = "\n".join(f"- {b}" for b in cfg.get("job_boards", []))
    return "\nJob boards to cover (one query each):\n" + boards


# ── step 0: build search config from resume ───────────────
def build_search_config(profile: dict | None = None) -> dict:
    """Ask opencode to extract search config from the resume."""
    resume = config.RESUME_FILE.read_text(encoding="utf-8")
    profile_json = json.dumps(profile, indent=2) if profile else ""
    context = (
        _sources_context(load_config())
        + f"\n\n=== STRUCTURED PROFILE ===\n{profile_json}\n=== END PROFILE ==="
        + f"\n\n=== RAW RESUME ===\n{resume}\n=== END RESUME ==="
    )
    result = run_opencode_json("prompts/build_queries.md", context=context)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUT_DIR / "search_config.json").write_text(json.dumps(result, indent=2))
    print(f"  Roles: {result.get('target_roles')}")
    print(f"  Skills: {result.get('key_skills')}")
    print(f"  Queries ({len(result.get('search_queries', []))}): ready")
    return result


# ── step 0a: extract structured resume profile ────────────
def _resume_profile_path() -> Path:
    return config.OUTPUT_DIR / "resume_profile.json"


def invalidate_resume_profile_cache() -> None:
    """Drop cached profile so the next run re-extracts after resume edits."""
    path = _resume_profile_path()
    if path.exists():
        path.unlink()
        print(f"  Cleared resume profile cache ({path})")


def extract_resume_profile() -> dict:
    """Extract a structured profile from the resume once, cache to disk."""
    profile_path = _resume_profile_path()
    if profile_path.exists():
        print("  Using cached resume profile")
        return json.loads(profile_path.read_text(encoding="utf-8"))

    resume = config.RESUME_FILE.read_text(encoding="utf-8")
    context = f"=== RESUME ===\n{resume}\n=== END RESUME ==="
    print("  Extracting resume profile...")
    profile = run_opencode_json("prompts/extract_profile.md", context=context)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(
        f"  Profile: {profile.get('name', '?')} — {profile.get('experience_years', '?')} years experience"
    )
    return profile


# ── url canonicalization (db.url_dedup_key is source of truth) ──
def _canonical_host(host: str) -> str:
    return db._canonical_host(host)


def _dedup_key(url: str) -> str:
    return db.url_dedup_key(url)


# ── step 1a: discover candidate pages via search ─────────
def discover_pages(app: "FirecrawlApp", search_queries: list[str]) -> list[dict]:
    """Run each search query and return unique candidate pages.

    A page may be a single posting OR a listing/category page that contains
    many postings — stage 1b sorts that out by scraping.

    Results are interleaved round-robin across queries (first hit of each
    query, then second of each, ...) so the MAX_PAGES_TO_SCRAPE cap doesn't
    starve sources whose queries run later in the list.
    """
    seen_urls: set[str] = set()
    results_per_query: list[list[dict]] = []

    for query in search_queries:
        print(f"  Searching: {query[:70]}...")
        hits: list[dict] = []
        try:
            response = app.search(query, limit=10)
            for r in response.web or []:
                url = r.url
                if not url or not db.is_safe_http_url(url) or _dedup_key(url) in seen_urls:
                    continue
                seen_urls.add(_dedup_key(url))
                hits.append(
                    {
                        "url": url,
                        "title": r.title or "",
                        "description": r.description or "",
                    }
                )
        except Exception as e:
            print(f"  Query failed: {e}")
        print(f"    {len(hits)} new result(s)")
        results_per_query.append(hits)

    return [page for group in zip_longest(*results_per_query) for page in group if page]


# ── step 1b: scrape each page and extract individual postings ─
def extract_postings(app: "FirecrawlApp", page: dict) -> list[dict]:
    """Scrape one page and extract the individual job postings it contains.

    Falls back to the search snippet (treated as a single posting) if the
    scrape fails or the page yields no structured postings, so we never lose
    a result that was already an individual posting.
    """
    listing_url = page["url"]
    source = db._canonical_host(urlparse(listing_url).netloc)

    def _snippet_fallback() -> list[dict]:
        return [
            {
                "title": page["title"],
                "company": "",
                "location": "Remote",
                "url": listing_url,
                "description": page["description"],
                "posted_date": "",
                "source": source,
            }
        ]

    try:
        doc = app.scrape(
            listing_url,
            formats=[{"type": "json", "prompt": EXTRACT_PROMPT, "schema": JOB_EXTRACT_SCHEMA}],
            only_main_content=True,
            timeout=config.SCRAPE_TIMEOUT_MS,
        )
    except Exception as e:
        print(f"    Scrape failed ({source}): {e} — keeping search snippet")
        return _snippet_fallback()

    data = doc.json if isinstance(doc.json, dict) else {}
    raw_postings = data.get("jobs") or []
    if not raw_postings:
        return _snippet_fallback()

    postings: list[dict] = []
    for p in raw_postings:
        if not isinstance(p, dict) or not (p.get("title") or "").strip():
            continue
        # Resolve the posting URL relative to the page; fall back to the page URL.
        posting_url = (p.get("url") or "").strip()
        posting_url = urljoin(listing_url, posting_url) if posting_url else listing_url
        if not db.is_safe_http_url(posting_url):
            continue
        # Skip if the extracted URL is the same as the source (search results page)
        if _dedup_key(posting_url) == _dedup_key(listing_url):
            continue
        postings.append(
            {
                "title": p.get("title", "").strip(),
                "company": (p.get("company") or "").strip(),
                "location": (p.get("location") or "Remote").strip() or "Remote",
                "url": posting_url,
                "description": (p.get("description") or "").strip(),
                "posted_date": (p.get("posted_date") or "").strip(),
                "source": source,
            }
        )
    return postings or _snippet_fallback()


# ── step 1: search → scrape → individual postings ─────────
def _is_firecrawl_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "payment required",
            "insufficient",
            "credit",
            "quota",
            "rate limit",
            "rate_limit",
            "too many requests",
            "402",
            "429",
            "exhausted",
            "upgrade your plan",
        )
    )


class _FirecrawlFailover:
    """Primary key first; on quota/payment errors, retry with backup once."""

    def __init__(self, keys: list[str]):
        if not keys:
            raise RuntimeError(
                "No Firecrawl API key set — add FIRECRAWL_API_KEY (and optional "
                "FIRECRAWL_API_KEY_BACKUP) in Settings or .env."
            )
        self._keys = keys
        self._i = 0
        self._app = FirecrawlApp(api_key=keys[0])

    def _call(self, method: str, *args, **kwargs):
        try:
            return getattr(self._app, method)(*args, **kwargs)
        except Exception as e:
            if self._i + 1 < len(self._keys) and _is_firecrawl_quota_error(e):
                self._i += 1
                print(
                    f"  Firecrawl primary key exhausted — switching to backup "
                    f"({self._i + 1}/{len(self._keys)})"
                )
                self._app = FirecrawlApp(api_key=self._keys[self._i])
                return getattr(self._app, method)(*args, **kwargs)
            raise

    def search(self, *args, **kwargs):
        return self._call("search", *args, **kwargs)

    def scrape(self, *args, **kwargs):
        return self._call("scrape", *args, **kwargs)


def scrape_jobs(search_queries: list[str]) -> list[dict]:
    import user_data

    app = _FirecrawlFailover(user_data.firecrawl_api_keys())

    pages = discover_pages(app, search_queries)
    print(
        f"  Discovered {len(pages)} candidate pages; scraping up to {config.MAX_PAGES_TO_SCRAPE}..."
    )

    # Seed with soft-deleted URLs so ignored/rejected removals stay gone
    deleted_keys = {_dedup_key(u) for u in db.get_soft_deleted_urls()}
    seen_urls: set[str] = set(deleted_keys)
    skipped_deleted = 0
    jobs: list[dict] = []
    for page in pages[: config.MAX_PAGES_TO_SCRAPE]:
        print(f"  Scraping: {page['url'][:70]}...")
        for job in extract_postings(app, page):
            url = job["url"]
            if not url:
                continue
            key = _dedup_key(url)
            if key in seen_urls:
                if key in deleted_keys:
                    skipped_deleted += 1
                continue
            seen_urls.add(key)
            jobs.append(job)

    if skipped_deleted:
        print(f"  Skipped {skipped_deleted} soft-deleted posting(s)")
    return jobs


# ── opencode runner ───────────────────────────────────────
def _strip_status_line(text: str) -> str:
    """Remove the UI status line that opencode run prints (e.g. '> build · model-name')."""
    return re.sub(r"^>.*·.*\n?", "", text).strip()


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a subprocess and all its children to prevent zombie processes.

    On Windows, uses taskkill /F /T to kill the entire process tree.
    On other platforms, uses os.kill with process group.
    """
    import os
    import signal

    try:
        if os.name == "nt":  # Windows
            # Use taskkill to kill the process tree
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:  # Unix-like
            # Send SIGTERM to the process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Wait a bit, then force kill
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_opencode(prompt_file: str, context: str = "", model: str = None) -> str:
    """Run a prompt file via opencode with live output streaming and stall detection.

    Streams stdout line-by-line so we can see what the model is doing.
    Rotates through healthy models with a hard attempt ceiling
    (config.MAX_OPENCODE_ATTEMPTS). Each model gets up to MAX_RETRIES
    consecutive failures before being skipped. A success resets that
    model's failure count. Pool may re-probe once, then fails.

    Two timeout mechanisms:
      - STALL_TIMEOUT: hard cap on total runtime per attempt
      - STALL_SILENCE_TIMEOUT: if no new output for this long, it's stuck
    """
    import queue
    import threading
    import time

    prompt = config.resolve_prompt(prompt_file).read_text(encoding="utf-8")
    if context:
        prompt = prompt + "\n" + context
    import user_data

    if not user_data.find_opencode():
        raise RuntimeError(
            "opencode CLI not found — install from https://opencode.ai "
            "or reinstall Let Me Work after installing OpenCode on PATH."
        )

    if not model:
        _init_models()
    _get_healthy_model._reprobed = False  # type: ignore[attr-defined]

    selected_model = model or _next_model()
    last_error = None
    total_attempts = 0
    oc_env = user_data.opencode_run_env()
    oc_cwd = str(user_data.user_data_dir())

    while total_attempts < config.MAX_OPENCODE_ATTEMPTS:
        total_attempts += 1
        # Skip unhealthy models if not manually specified
        if not model and _model_failures.get(selected_model, 0) >= config.MAX_RETRIES:
            print(f"  Skipping {selected_model} (failed {_model_failures[selected_model]}x)")
            selected_model = _get_healthy_model()

        print(f"  [Attempt {total_attempts}/{config.MAX_OPENCODE_ATTEMPTS}] Using model: {selected_model}")
        global _current_opencode_proc
        argv = user_data.opencode_argv(
            "run", prompt, "--agent", "job-agent", "--model", selected_model
        )
        if not argv:
            raise RuntimeError(
                "opencode CLI not found — install from https://opencode.ai "
                "or reinstall Let Me Work after installing OpenCode on PATH."
            )
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=oc_cwd,
            env=oc_env,
        )
        _current_opencode_proc = proc

        stdout_chunks: list[str] = []
        start_time = time.monotonic()
        last_output_time = start_time
        last_heartbeat = start_time
        output_queue: queue.Queue[tuple[bytes, str] | None] = queue.Queue()

        def _reader(stream, tag: str):
            """Read lines from a stream and put (bytes, tag) tuples in the queue."""
            try:
                for line in iter(stream.readline, b""):
                    output_queue.put((line, tag))
            finally:
                output_queue.put(None)
                stream.close()

        stdout_thread = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        stderr_lines: list[str] = []

        try:
            while True:
                _check_cancelled()
                elapsed = time.monotonic() - start_time
                silence = time.monotonic() - last_output_time

                # Hard timeout
                if elapsed > config.STALL_TIMEOUT:
                    raise subprocess.TimeoutExpired(proc, config.STALL_TIMEOUT)

                # Silent stall — no stdout and no stderr activity
                total_output = len(stdout_chunks) + len(stderr_lines)
                if silence > config.STALL_SILENCE_TIMEOUT and total_output == 0:
                    raise subprocess.TimeoutExpired(proc, config.STALL_SILENCE_TIMEOUT)

                # Heartbeat every 30s
                now = time.monotonic()
                if now - last_heartbeat >= 30:
                    preview = (
                        "".join(stdout_chunks)[-80:].replace("\n", " ").strip()
                        if stdout_chunks
                        else "(no output yet)"
                    )
                    print(
                        f"    ⏳ {int(elapsed)}s elapsed, {int(silence)}s since output — {preview}"
                    )
                    last_heartbeat = now

                # Drain queue (non-blocking)
                try:
                    while True:
                        item = output_queue.get_nowait()
                        if item is None:
                            # One reader thread finished — check if proc exited
                            if proc.poll() is not None:
                                break
                            continue
                        chunk_bytes, tag = item
                        text = chunk_bytes.decode("utf-8", errors="replace")
                        if tag == "stdout":
                            stdout_chunks.append(text)
                        else:
                            stderr_lines.append(text)
                        last_output_time = time.monotonic()
                        stripped = text.rstrip()
                        if stripped:
                            print(f"    → {stripped[:120]}")
                except queue.Empty:
                    pass

                # Check if process exited
                if proc.poll() is not None:
                    # Drain remaining items from queue
                    try:
                        while True:
                            item = output_queue.get_nowait()
                            if item is None:
                                continue
                            chunk_bytes, tag = item
                            text = chunk_bytes.decode("utf-8", errors="replace")
                            if tag == "stdout":
                                stdout_chunks.append(text)
                            else:
                                stderr_lines.append(text)
                            last_output_time = time.monotonic()
                    except queue.Empty:
                        pass
                    break

                time.sleep(0.3)  # Don't busy-wait

            # Process finished
            stdout = "".join(stdout_chunks)
            stderr = "".join(stderr_lines)
            # Also grab any remaining stderr
            try:
                remaining_stderr = proc.stderr.read()
                if remaining_stderr:
                    stderr += remaining_stderr.decode("utf-8", errors="replace")
            except Exception:
                pass
            elapsed = time.monotonic() - start_time

            if proc.returncode != 0:
                _mark_model_failed(selected_model)
                last_error = stderr[:500]
                print(
                    f"  ✗ Model {selected_model} failed (rc={proc.returncode}, {int(elapsed)}s): {last_error}"
                )
                selected_model = _get_healthy_model()
                continue

            _reset_model(selected_model)
            output_len = len(stdout)
            print(f"  ✓ Model {selected_model} returned {output_len} chars in {int(elapsed)}s")
            return _strip_status_line(stdout)

        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            _mark_model_failed(selected_model)
            elapsed = time.monotonic() - start_time
            chunks_so_far = "".join(stdout_chunks)
            print(
                f"  ✗ STALLED: {selected_model} after {int(elapsed)}s ({len(chunks_so_far)} chars received) — rotating"
            )
            if chunks_so_far:
                print(f"    Partial output: {chunks_so_far[-200:]}")
            selected_model = _get_healthy_model()
            last_error = f"Timed out after {int(elapsed)}s"
        except RuntimeError:
            _kill_process_tree(proc)
            raise
        finally:
            if _current_opencode_proc is proc:
                _current_opencode_proc = None

    raise RuntimeError(
        f"OpenCode failed after {config.MAX_OPENCODE_ATTEMPTS} attempts"
        + (f": {last_error}" if last_error else "")
    )


def _parse_json_output(raw: str):
    """Parse the AI output as JSON, tolerating markdown fences and prose
    around the JSON payload (the model sometimes adds them despite instructions)."""
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*\n", "", raw)
        raw = re.sub(r"\n```\s*$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back to the first parseable JSON value embedded in the text.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in "[{":
            try:
                value, _ = decoder.raw_decode(raw, i)
                return value
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("no JSON value found in output", raw, 0)


def _validate_job_scores(data: list[dict]) -> list[dict]:
    """Validate and clean job scores from AI output.

    Ensures each job has required fields and valid values.
    Returns only valid jobs, discarding malformed entries.
    """
    if not isinstance(data, list):
        raise ValueError("AI output must be a list of jobs")

    valid_jobs = []
    for job in data:
        if not isinstance(job, dict):
            continue

        # Required fields — http(s) only (blocks javascript: / data: XSS sinks)
        url = job.get("url", "")
        title = job.get("title", "")
        if not url or not title or not db.is_safe_http_url(url):
            continue

        # Validate and clamp score
        score = job.get("score", 0)
        if not isinstance(score, (int, float)):
            score = 0
        score = max(0, min(100, int(score)))

        # Validate verdict
        verdict = job.get("verdict", "skip")
        if verdict not in ("apply", "review", "skip"):
            verdict = "skip"

        # Ensure lists are actually lists
        match_reasons = job.get("match_reasons", [])
        if not isinstance(match_reasons, list):
            match_reasons = []

        red_flags = job.get("red_flags", [])
        if not isinstance(red_flags, list):
            red_flags = []

        # Build clean job
        clean_job = {
            "url": url,
            "title": title,
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "description": job.get("description", ""),
            "source": job.get("source", ""),
            "posted_date": job.get("posted_date", ""),
            "score": score,
            "verdict": verdict,
            "work_arrangement": job.get("work_arrangement", ""),
            "match_reasons": match_reasons,
            "red_flags": red_flags,
            "suggested_angle": job.get("suggested_angle", ""),
        }
        valid_jobs.append(clean_job)

    if not valid_jobs:
        raise ValueError("No valid jobs found in AI output")

    return valid_jobs


def run_opencode_json(prompt_file: str, context: str = ""):
    """Run an opencode prompt that must return JSON, and parse it."""
    raw = run_opencode(prompt_file, context)
    if not raw:
        raise RuntimeError(f"OpenCode returned empty output for {prompt_file}")
    try:
        return _parse_json_output(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"OpenCode returned invalid JSON for {prompt_file}: {e}\n---\n{raw[:300]}"
        )


# ── step 2: analyze scraped jobs via opencode ─────────────
ANALYZE_BATCH_SIZE = 30  # jobs per model call — keeps context small enough for free models


def analyze_jobs(profile: dict | None = None) -> list[dict]:
    """Run opencode analysis on raw_jobs.json in batches, then merge."""
    raw_jobs = json.loads((config.OUTPUT_DIR / "raw_jobs.json").read_text(encoding="utf-8"))
    resume = config.RESUME_FILE.read_text(encoding="utf-8")
    profile_json = json.dumps(profile, indent=2) if profile else ""
    today = datetime.now().strftime("%Y-%m-%d")
    all_scored: list[dict] = []

    batches = [
        raw_jobs[i : i + ANALYZE_BATCH_SIZE] for i in range(0, len(raw_jobs), ANALYZE_BATCH_SIZE)
    ]
    print(
        f"  Analyzing {len(raw_jobs)} jobs in {len(batches)} batch(es) of ≤{ANALYZE_BATCH_SIZE}..."
    )

    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} jobs)...")
        context = (
            f"Today's date is {today}.\n"
            f"\n=== STRUCTURED PROFILE ===\n{profile_json}\n=== END PROFILE ===\n"
            f"\n=== RAW RESUME ===\n{resume}\n=== END RESUME ===\n"
            f"\n=== JOBS (batch {idx} of {len(batches)}) ===\n"
            f"{json.dumps(batch, indent=2)}\n=== END JOBS ==="
        )
        try:
            scored = run_opencode_json("prompts/analyze.md", context=context)
            all_scored.extend(scored)
            print(f"    → {len(scored)} jobs scored from batch {idx}")
        except Exception as e:
            print(f"    → Batch {idx} failed: {e} — skipping")

    all_scored = _validate_job_scores(all_scored)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUT_DIR / "jobs.json").write_text(json.dumps(all_scored, indent=2))
    return all_scored


# ── cover letters ─────────────────────────────────────────
def _slug(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len]


def generate_cover_letter(job: dict, profile: dict | None = None) -> str:
    """Generate one cover letter for a job dict. Returns the letter text."""
    resume = config.RESUME_FILE.read_text(encoding="utf-8")
    profile_json = json.dumps(profile, indent=2) if profile else ""
    context = (
        f"=== STRUCTURED PROFILE ===\n{profile_json}\n=== END PROFILE ===\n"
        f"\n=== RAW RESUME ===\n{resume}\n=== END RESUME ===\n"
        f"\n---JOB---\n{json.dumps(job, indent=2)}"
    )
    return run_opencode("prompts/cover_letter.md", context=context)


def load_cached_profile() -> dict | None:
    """Return the cached resume profile, or None if it hasn't been extracted yet."""
    profile_path = _resume_profile_path()
    if profile_path.exists():
        return json.loads(profile_path.read_text(encoding="utf-8"))
    return None


def generate_cover_letters(
    jobs: list[dict], profile: dict | None = None, run_id: int | None = None
):
    """Generate cover letters for many jobs; save each to DB (by URL) and disk."""
    out_dir = config.OUTPUT_DIR / "cover_letters"
    out_dir.mkdir(parents=True, exist_ok=True)

    for job in jobs:
        company = job.get("company") or "unknown"
        title = job.get("title") or "role"
        slug = f"{_slug(company)}__{_slug(title)}"

        print(f"  Writing cover letter: {company} — {title[:50]}...")
        try:
            letter = generate_cover_letter(job, profile)
            (out_dir / f"{slug}.md").write_text(letter, encoding="utf-8")
            job_id = db.get_job_id_by_url(job.get("url", ""))
            if job_id:
                db.upsert_cover_letter(job_id, letter, run_id)
        except Exception as e:
            print(f"  Failed for {slug}: {e}")


# ── pipeline orchestrator ──────────────────────────────────
def run_pipeline(on_progress=None) -> dict:
    """Run the full 4-step pipeline.

    Calls on_progress(step, label, status) at each stage where:
      step   — int 1-4
      label  — human-readable step name
      status — "running" or "done"

    Returns {"total": int, "above_threshold": int}.
    Raises RuntimeError on any failure.
    """

    def emit(step, label, status):
        if on_progress:
            on_progress(step, label, status)
        db.update_run_step(run_id, step, label)

    _pipeline_cancel.clear()
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()

    if not config.RESUME_FILE.exists():
        raise RuntimeError(f"Missing {config.RESUME_FILE} — add your resume before running.")

    run_id = db.start_run()

    try:
        _check_cancelled()
        emit(0, "Extracting resume profile", "running")
        profile = extract_resume_profile()
        emit(0, "Extracting resume profile", "done")

        _check_cancelled()
        emit(1, "Building search config", "running")
        search_config = build_search_config(profile)
        search_queries = search_config.get("search_queries", [])
        if not search_queries:
            raise RuntimeError("No search queries generated — check prompts/build_queries.md")
        emit(1, "Building search config", "done")

        _check_cancelled()
        emit(2, "Scraping jobs", "running")
        jobs = scrape_jobs(search_queries)
        if not jobs:
            raise RuntimeError("No jobs found — check your FIRECRAWL_API_KEY or search queries.")
        (config.OUTPUT_DIR / "raw_jobs.json").write_text(json.dumps(jobs, indent=2))
        db.insert_raw_jobs(jobs, run_id)
        emit(2, "Scraping jobs", "done")

        _check_cancelled()
        emit(3, "Analyzing & scoring", "running")
        all_jobs = analyze_jobs(profile)
        db.save_pipeline_output(all_jobs, run_id)
        emit(3, "Analyzing & scoring", "done")

        good_jobs = [j for j in all_jobs if j.get("score", 0) >= config.THRESHOLD]
        emit(4, "Cover letters (on demand)", "running")
        if config.GENERATE_COVER_LETTERS_IN_PIPELINE:
            apply_jobs = [j for j in good_jobs if j.get("verdict") == "apply"]
            if apply_jobs:
                generate_cover_letters(apply_jobs, profile, run_id)
        emit(4, "Cover letters (on demand)", "done")

        db.finish_run(run_id, jobs_found=len(all_jobs), above_threshold=len(good_jobs))
        return {"total": len(all_jobs), "above_threshold": len(good_jobs)}

    except Exception as e:
        db.finish_run(run_id, error=str(e))
        raise
    finally:
        global _current_opencode_proc
        _pipeline_cancel.clear()
        _current_opencode_proc = None


# ── main pipeline ─────────────────────────────────────────
def run():
    def print_progress(step, label, status):
        if status == "running":
            print(f"\nStep {step}: {label}...")

    try:
        config.validate_config()
        result = run_pipeline(on_progress=print_progress)
        print(
            f"\nDone! {result['above_threshold']} of {result['total']} jobs above threshold ({config.THRESHOLD})"
        )
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    run()
