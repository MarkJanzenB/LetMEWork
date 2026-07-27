import csv
import io
import json
import logging
import queue
import signal
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import db

logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)

run_lock = threading.Lock()


@app.get("/")
async def index():
    return FileResponse("ui/index.html")


@app.get("/api/jobs")
async def get_jobs():
    db.init_db()
    jobs = db.get_jobs_for_api()
    return JSONResponse(jobs)


class StatusUpdate(BaseModel):
    url: str
    status: str


@app.post("/api/status")
async def update_status(body: StatusUpdate):
    db.init_db()
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
    db.init_db()
    db.mark_viewed(body.url)
    return {"ok": True}


@app.get("/api/run-status")
async def get_run_status():
    db.init_db()
    run = db.get_active_run()
    if run:
        return JSONResponse(
            {
                "active": True,
                "step": run.get("step", 0),
                "label": run.get("label", ""),
                "status": run.get("status", "running"),
            }
        )
    return JSONResponse({"active": False})


@app.post("/api/bulk-apply")
async def bulk_apply(
    min_score: int | None = Query(default=None),
    max_score: int | None = Query(default=None),
):
    """Mark filtered jobs as applied and return their URLs."""
    db.init_db()
    jobs = db.get_jobs_for_api()
    urls = []
    for job in jobs:
        url = job.get("url", "")
        score = job.get("score", 0)
        if not url:
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
    db.init_db()
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
    db.init_db()
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
    db.init_db()
    counts = db.get_status_counts()
    # Ensure all statuses are present
    for status in ["none", "applied", "ignored", "interviewed", "rejected", "hired"]:
        if status not in counts:
            counts[status] = 0
    return counts


@app.get("/api/runs")
async def get_runs():
    db.init_db()
    runs = db.get_runs()
    return runs


@app.get("/api/export/csv")
async def export_csv(
    min_score: int | None = Query(default=None),
    max_score: int | None = Query(default=None),
    status: str | None = Query(default=None),
):
    db.init_db()
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
    db.init_db()
    job_id = db.get_job_id_by_url(body.url)
    if not job_id:
        raise HTTPException(status_code=404, detail="Job not found")
    db.upsert_cover_letter(job_id, body.content)
    return {"ok": True}


@app.get("/api/run")
async def run_agent():
    if not run_lock.acquire(blocking=False):

        async def _busy():
            yield f"data: {json.dumps({'step': 'busy'})}\n\n"

        return StreamingResponse(_busy(), media_type="text/event-stream")

    q: queue.Queue = queue.Queue()

    def _on_progress(step: int, label: str, status: str) -> None:
        q.put({"step": step, "label": label, "status": status})

    def _pipeline_thread() -> None:
        try:
            from agent import run_pipeline

            result = run_pipeline(on_progress=_on_progress)
            q.put({"step": "complete", **result})
        except Exception as exc:
            q.put({"step": "error", "message": str(exc)})
        finally:
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


if __name__ == "__main__":

    def _shutdown(sig, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    print("  Server running at http://127.0.0.1:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
