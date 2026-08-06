import csv
import io
import json
import logging
import os
import queue
import signal
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import config
import db
import user_data

logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.bootstrap()
    db.init_db()
    # run_lock resets on process start; DB "running" rows would lie otherwise
    db.abandon_orphan_runs()
    yield


app = FastAPI(lifespan=lifespan)

run_lock = threading.Lock()


def _ui_index() -> Path:
    """Primary UI is vanilla ui/index.html (full feature dashboard)."""
    if user_data.is_frozen():
        path = config.BASE_DIR / "ui" / "index.html"
        return path if path.is_file() else Path("ui/index.html")
    for path in (Path("ui/index.html"), config.BASE_DIR / "ui" / "index.html"):
        if path.is_file():
            return path
    return Path("ui/index.html")


@app.get("/")
async def index():
    return FileResponse(_ui_index())


@app.get("/api/deps")
async def deps_status():
    st = user_data.setup_status()
    return {
        "opencode_found": st["opencode_found"],
        "opencode_path": st.get("opencode_path") or "",
        "version": st["version"],
        "has_firecrawl": st["has_firecrawl"],
        "has_resume": st["has_resume"],
    }


def _update_feed_url() -> str:
    return os.environ.get(
        "LETMEWORK_UPDATE_URL",
        "https://github.com/MarkJanzenB/LetMEWork/releases/latest/download/latest.json",
    )


def _fetch_latest_manifest() -> dict:
    import urllib.request

    with urllib.request.urlopen(_update_feed_url(), timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _version_newer(latest: str, current: str) -> bool:
    """True if latest looks different/newer than current (string compare is enough for tagged betas)."""
    return bool(latest) and latest.strip() != current.strip()


@app.get("/api/update/check")
async def update_check():
    """Compare APP_VERSION to latest.json on GitHub Releases (best-effort)."""
    import urllib.error

    current = config.APP_VERSION
    try:
        data = _fetch_latest_manifest()
        latest = str(data.get("version") or "")
        return {
            "update_available": _version_newer(latest, current),
            "current": current,
            "latest": latest or None,
            "installer_url": data.get("installer_url"),
            "sha256": data.get("sha256"),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {
            "update_available": False,
            "current": current,
            "error": str(e),
        }


@app.post("/api/update/apply")
async def update_apply():
    """Download Setup, verify sha256, launch installer, then quit this process."""
    import hashlib
    import subprocess
    import tempfile
    import urllib.error
    import urllib.request

    try:
        data = _fetch_latest_manifest()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch update manifest: {e}")

    url = data.get("installer_url")
    expected = (data.get("sha256") or "").strip().lower()
    if not url or not expected:
        raise HTTPException(status_code=400, detail="Manifest missing installer_url or sha256")

    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            blob = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    digest = hashlib.sha256(blob).hexdigest()
    if digest != expected:
        raise HTTPException(status_code=400, detail="Installer checksum mismatch — aborted")

    dest = Path(tempfile.gettempdir()) / (Path(str(url)).name or "LetMeWork-Setup.exe")
    dest.write_bytes(blob)
    subprocess.Popen([str(dest)], shell=False)

    def _quit():
        import time

        time.sleep(1.5)
        os._exit(0)

    threading.Thread(target=_quit, daemon=True).start()
    return {"ok": True, "path": str(dest)}


@app.get("/api/jobs")
async def get_jobs():
    jobs = db.get_jobs_for_api()
    return JSONResponse(jobs)


class StatusUpdate(BaseModel):
    url: str
    status: str


@app.post("/api/status")
async def update_status(body: StatusUpdate):
    job_id = db.get_job_id_by_url(body.url)
    if not job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        db.set_job_status(job_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/api/viewed")
async def mark_viewed(body: StatusUpdate):
    db.mark_viewed(body.url)
    return {"ok": True}


class UrlBody(BaseModel):
    url: str


@app.post("/api/delete")
async def soft_delete(body: UrlBody):
    """Soft-delete a job. Future scrapes skip this URL (dedupe)."""
    if not db.get_job_id_by_url(body.url):
        raise HTTPException(status_code=404, detail="Job not found")
    db.soft_delete_job_by_url(body.url)
    return {"ok": True}


@app.post("/api/restore")
async def restore_job(body: UrlBody):
    """Undo a soft-delete."""
    if not db.restore_job_by_url(body.url):
        raise HTTPException(status_code=404, detail="Deleted job not found")
    return {"ok": True}


@app.get("/api/run-status")
async def get_run_status():
    # Truth = in-process lock OR a live DB run (post-restart orphans cleaned at boot)
    locked = run_lock.locked()
    run = db.get_active_run()
    last = db.get_last_completed_run()
    last_payload = (
        {
            "finished_at": last.get("finished_at"),
            "jobs_found": last.get("jobs_found", 0),
            "above_threshold": last.get("above_threshold", 0),
        }
        if last
        else None
    )
    if locked or run:
        return JSONResponse(
            {
                "active": True,
                "locked": locked,
                "step": (run or {}).get("step", 0),
                "label": (run or {}).get("label", "") or ("Running…" if locked else ""),
                "status": (run or {}).get("status", "running"),
                "last_run": last_payload,
            }
        )
    return JSONResponse({"active": False, "last_run": last_payload})


@app.get("/api/health")
async def health():
    """Liveness + DB + last completed run — used when the UI suspects connection loss."""
    try:
        with db.get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        last = db.get_last_completed_run()
        return {
            "ok": True,
            "db": "ok",
            "version": config.APP_VERSION,
            "last_run": (
                {
                    "finished_at": last.get("finished_at"),
                    "jobs_found": last.get("jobs_found", 0),
                    "above_threshold": last.get("above_threshold", 0),
                }
                if last
                else None
            ),
        }
    except Exception:
        return {"ok": False, "db": "error", "version": config.APP_VERSION}


# ── setup / onboarding (keys stay on this PC only) ───────


class KeysBody(BaseModel):
    firecrawl_key: str | None = None
    firecrawl_backup_key: str | None = None
    openrouter_key: str | None = None


class ResumeBody(BaseModel):
    content: str


class SettingsBody(BaseModel):
    onboarding_complete: bool | None = None
    auto_update: bool | None = None


@app.get("/api/setup/status")
async def setup_status():
    return user_data.setup_status()


@app.post("/api/setup/keys")
async def setup_keys(body: KeysBody):
    """Save API keys to AppData .env only — never to the job database."""
    user_data.write_env_keys(
        firecrawl_key=body.firecrawl_key,
        firecrawl_backup_key=body.firecrawl_backup_key,
        openrouter_key=body.openrouter_key,
    )
    return user_data.setup_status()


@app.get("/api/setup/resume")
async def get_resume():
    status = user_data.setup_status()
    path = Path(status["resume_path"])
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        "content": content,
        "path": str(path),
        "has_resume_pdf": status.get("has_resume_pdf", False),
        "resume_pdf_path": status.get("resume_pdf_path", ""),
        "resume_pdf_name": status.get("resume_pdf_name", ""),
    }


@app.post("/api/setup/resume")
async def save_resume(body: ResumeBody):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Resume cannot be empty")
    path = user_data.save_resume_text(body.content)
    config.bootstrap()
    from agent import invalidate_resume_profile_cache

    invalidate_resume_profile_cache()
    return {"ok": True, "path": str(path)}


@app.post("/api/setup/resume-pdf")
async def upload_resume_pdf(file: UploadFile = File(...)):
    """Keep the original PDF on disk; extract text into resume.md for the AI."""
    name = file.filename or "resume.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")
    data = await file.read()
    try:
        result = user_data.save_resume_pdf(data, original_name=name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}")
    config.bootstrap()
    from agent import invalidate_resume_profile_cache

    invalidate_resume_profile_cache()
    return {"ok": True, **result}


class SourcesBody(BaseModel):
    job_boards: list[str]


@app.get("/api/setup/sources")
async def get_sources():
    return config.sources_payload()


@app.post("/api/setup/sources")
async def save_sources(body: SourcesBody):
    try:
        config.save_job_boards(body.job_boards)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return config.sources_payload()


@app.post("/api/setup/complete")
async def setup_complete(body: SettingsBody = SettingsBody()):
    status = user_data.setup_status()
    if not status["has_firecrawl"]:
        raise HTTPException(
            status_code=400,
            detail="Firecrawl API key is required before finishing setup",
        )
    if not status["has_resume"]:
        raise HTTPException(status_code=400, detail="Add your resume before finishing setup")
    if not status["opencode_found"]:
        raise HTTPException(
            status_code=400,
            detail="OpenCode not found — reinstall the app or install OpenCode",
        )
    boards = config.load_search_config().get("job_boards") or []
    if not boards:
        raise HTTPException(status_code=400, detail="Select at least one job board before finishing setup")
    updates = {"onboarding_complete": True}
    user_data.save_settings(updates)
    return user_data.setup_status()


@app.post("/api/setup/settings")
async def setup_settings(body: SettingsBody):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        user_data.save_settings(updates)
    return user_data.setup_status()


def _require_ready_to_scrape() -> None:
    status = user_data.setup_status()
    if not status["has_firecrawl"]:
        raise HTTPException(
            status_code=400,
            detail="Add your Firecrawl API key in Settings before running the agent.",
        )
    if not status["opencode_found"]:
        raise HTTPException(
            status_code=400,
            detail="OpenCode not found. Reinstall Let Me Work or install OpenCode.",
        )
    if not status["has_resume"]:
        raise HTTPException(
            status_code=400,
            detail="Add your resume in Settings before running the agent.",
        )


@app.post("/api/bulk-apply")
async def bulk_apply(
    min_score: int | None = Query(default=None),
    max_score: int | None = Query(default=None),
):
    """Mark Not Started jobs in the score band as applied; never overwrite other statuses."""
    jobs = db.get_jobs_for_api()
    urls = []
    for job in jobs:
        url = job.get("url", "")
        score = job.get("score", 0)
        if not url:
            continue
        if (job.get("status") or "none") != "none":
            continue
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        job_id = job.get("id")
        if job_id:
            db.set_job_status(job_id, "applied")
            urls.append(url)
    return JSONResponse({"urls": urls, "count": len(urls)})


@app.get("/api/cover-letter")
async def get_cover_letter(url: str = Query(...)):
    job_id = db.get_job_id_by_url(url)
    if not job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    content = db.get_cover_letter(job_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Cover letter not found")
    return {"content": content}


class CoverLetterBody(BaseModel):
    url: str
    content: str = ""


@app.post("/api/generate-cover-letter")
def generate_cover_letter_endpoint(body: CoverLetterBody):
    """Generate a cover letter on demand for one job.

    Sync def on purpose: FastAPI runs it in a threadpool, so the minutes-long
    model call doesn't block the event loop.
    """
    job_id = db.get_job_id_by_url(body.url)
    if not job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    job = next((j for j in db.get_jobs_for_api() if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job has no score data yet")

    import agent

    try:
        content = agent.generate_cover_letter(job, agent.load_cached_profile())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}")
    db.upsert_cover_letter(job_id, content)
    return {"content": content}


@app.get("/api/status-counts")
async def get_status_counts():
    counts = db.get_status_counts()
    # Ensure all statuses are present
    for status in ["none", "applied", "ignored", "interviewed", "rejected", "hired", "closed"]:
        if status not in counts:
            counts[status] = 0
    return counts


@app.get("/api/runs")
async def get_runs():
    runs = db.get_runs()
    return runs


@app.get("/api/export/csv")
async def export_csv(
    min_score: int | None = Query(default=None),
    max_score: int | None = Query(default=None),
    status: str | None = Query(default=None),
):
    jobs = db.get_jobs_for_api()

    # Apply filters
    filtered_jobs = []
    for job in jobs:
        score = job.get("score", 0)
        job_status = job.get("status", "none")

        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        if status and job_status != status:
            continue
        filtered_jobs.append(job)

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "Score",
            "Verdict",
            "Status",
            "Title",
            "Company",
            "Location",
            "Work Arrangement",
            "URL",
            "Match Reasons",
            "Red Flags",
            "Suggested Angle",
        ]
    )

    # Data rows
    for job in filtered_jobs:
        writer.writerow(
            [
                job.get("score", ""),
                job.get("verdict", ""),
                job.get("status", "none"),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("work_arrangement", ""),
                job.get("url", ""),
                "; ".join(job.get("match_reasons", [])),
                "; ".join(job.get("red_flags", [])),
                job.get("suggested_angle", ""),
            ]
        )

    # Return as downloadable CSV
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs_export.csv"},
    )


@app.put("/api/cover-letter")
async def update_cover_letter(body: CoverLetterBody):
    job_id = db.get_job_id_by_url(body.url)
    if not job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    db.upsert_cover_letter(job_id, body.content)
    return {"ok": True}


@app.get("/api/run")
async def run_agent():
    try:
        _require_ready_to_scrape()
    except HTTPException as exc:
        detail = exc.detail

        async def _blocked():
            yield f"data: {json.dumps({'step': 'error', 'message': detail})}\n\n"

        return StreamingResponse(_blocked(), media_type="text/event-stream")

    if not run_lock.acquire(blocking=False):

        async def _busy():
            yield f"data: {json.dumps({'step': 'busy'})}\n\n"

        return StreamingResponse(_busy(), media_type="text/event-stream")

    q: queue.Queue = queue.Queue()

    def _on_progress(step: int, label: str, status: str) -> None:
        q.put({"step": step, "label": label, "status": status})

    class _LogTee:
        """Mirror stdout/stderr to the SSE queue (and still print to the console)."""

        _REDACT = __import__("re").compile(
            r"(api[_-]?key\s*[:=]\s*\S+|sk-[a-zA-Z0-9]{8,}|"
            r"Bearer\s+\S+|FIRECRAWL_API_KEY(_BACKUP)?|OPENROUTER_API_KEY|"
            r"=== (RESUME|STRUCTURED PROFILE) ===)",
            __import__("re").I,
        )

        def __init__(self, real):
            self._real = real
            self._buf = ""

        def write(self, s):
            if not isinstance(s, str):
                s = str(s)
            self._real.write(s)
            self._real.flush()
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.rstrip()
                if not line:
                    continue
                if self._REDACT.search(line):
                    line = "[redacted sensitive log line]"
                elif len(line) > 400:
                    line = line[:200] + "…"
                q.put({"step": "log", "line": line})

        def flush(self):
            self._real.flush()

        def isatty(self):
            return False

    def _pipeline_thread() -> None:
        old_out, old_err = sys.stdout, sys.stderr
        tee = _LogTee(old_out)
        sys.stdout = tee
        sys.stderr = _LogTee(old_err)
        try:
            from agent import run_pipeline

            result = run_pipeline(on_progress=_on_progress)
            q.put({"step": "complete", **result})
        except Exception as exc:
            q.put({"step": "error", "message": str(exc)})
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            run_lock.release()
            q.put(None)

    threading.Thread(target=_pipeline_thread, daemon=True).start()

    async def _event_stream():
        import asyncio

        loop = asyncio.get_running_loop()
        while True:
            event = await loop.run_in_executor(None, q.get)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.post("/api/run/cancel")
async def cancel_run():
    """Stop the in-flight pipeline if any (human in control)."""
    if not run_lock.locked():
        return JSONResponse({"ok": True, "cancelled": False, "message": "No active run"})
    from agent import request_pipeline_cancel

    request_pipeline_cancel()
    return JSONResponse({"ok": True, "cancelled": True})


if __name__ == "__main__":

    def _shutdown(sig, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    config.bootstrap()
    host, port = "127.0.0.1", int(os.environ.get("PORT", "8000"))
    url = f"http://{host}:{port}"
    print(f"  Let Me Work {config.APP_VERSION}")
    print(f"  Server running at {url}\n")
    if user_data.is_frozen() or "--open" in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="error")
