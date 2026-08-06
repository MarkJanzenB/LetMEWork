# Architecture Blueprint — Host-Owned AI Pipeline

A portable description of the idea behind this repo: what it is, how a run executes, what you need to rebuild it elsewhere, and where the working design still cuts corners.

Use this when transplanting the **workflow**, not the job-hunting domain.

## Provenance

The **host-owned pipeline** pattern (local orchestrator + disposable AI CLI + Firecrawl acquisition + prompt contracts) comes from [Kurt Chan’s AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper).

**Let Me Work** ([MarkJanzenB/LetMEWork](https://github.com/MarkJanzenB/LetMEWork)) is Mark Janzen Bandola’s edition of that workflow: OpenCode instead of Claude CLI, SQLite, React UI, Windows packaging, onboarding, and reliability layers. See [`NOTICE`](NOTICE) and the README credits table.

---

## 1. The Idea

**One local process owns the workflow. An external AI CLI is a disposable worker that only returns text.**

| Principle | Meaning |
|---|---|
| Host owns side effects | Python (or equivalent) writes files, DB rows, and API responses. The AI never “saves results.” |
| Prompts are contracts | Each step is a markdown prompt that demands a fixed stdout shape (usually JSON). |
| Context is inlined | Resume, profile, jobs, and source lists are pasted into the prompt. The worker should not need file tools. |
| Acquisition is separate | Web search/scrape is an API adapter (here: Firecrawl), not the LLM browsing the open web ad hoc. |
| Flaky compute is expected | Free/unreliable models → health probe, rotate, dual timeouts, kill hung processes, tolerant JSON parse. |
| UI is a thin shell | Local HTTP + Server-Sent Events for long runs; REST for state. Single-user, localhost. |
| Secrets stay local | API keys and personal docs live in a user data dir / `.env`, not in the domain database. |

**System style:** orchestrated pipeline (batch ETL + AI evaluation) inside a modular monolith — not microservices, not a formal hexagonal layout.

**Domain in this repo (replaceable):** resume → search queries → scrape postings → score → optional cover letters → dashboard. The reusable spine is the host/worker/pipeline/SSE pattern above.

---

## 2. How It Gets Executed

### 2.1 Entry points

| Mode | Start | What happens |
|---|---|---|
| Dashboard | `python server.py` | Bootstrap → SQLite init → serve `ui/index.html` on `127.0.0.1:8000` |
| Headless | `python agent.py` | Bootstrap → validate → run full pipeline once |
| Packaged | frozen EXE | Same; opens browser; writable state under AppData |

### 2.2 Bootstrap (every process)

1. Merge env files (repo / install / AppData; later wins).
2. Ensure writable `data/` and `output/` (or AppData equivalents when frozen).
3. Resolve resume path and search-config path.
4. On server start: create SQLite schema + light migrations.

### 2.3 Full pipeline (the working workflow)

```
resume.md (or PDF → text → resume.md)
    │
    ▼
[0] Extract structured profile          AI → JSON
    cache: output/resume_profile.json   (skip AI if file exists)
    │
    ▼
[1] Build search config                 AI → JSON { target_roles, key_skills, search_queries }
    inject: configured job boards
    │
    ▼
[2] Acquire entities
    for each query: search API → candidate pages
    interleave results across queries (fairness under a page cap)
    for each page (up to MAX_PAGES): scrape + schema extract → items
    fallback: keep search snippet if scrape/extract fails
    dedupe by canonical URL; skip soft-deleted URLs
    write: output/raw_jobs.json + raw_jobs rows
    │
    ▼
[3] Evaluate in batches (e.g. 30 items)
    AI → JSON array of scores/verdicts
    validate/clamp fields; merge batches
    write: output/jobs.json + jobs + append-only scores
    │
    ▼
[4] Synthesize artifacts (optional / on-demand)
    cover letters for high-score "apply" items
    default in this repo: OFF in pipeline; generate from UI per job
    │
    ▼
finish run ledger (counts or error)
```

Progress: `on_progress(step, label, status)` updates the DB run row and, from the UI path, pushes SSE events.

### 2.4 One AI call (the reliability loop)

```
load prompt file + append context
resolve AI CLI binary
pick next healthy model
  spawn: cli run "<prompt>" --agent <readonly-agent> --model <id>
  stream stdout/stderr
  kill if: hard time cap OR silence with no output
  success → reset that model's failure count → return text
  fail/stall → mark failure → next model
  if every model exhausted → re-probe providers → continue
parse JSON tolerantly (strip fences / find first `{` or `[`)
```

### 2.5 UI run path

```
Browser GET /api/run (EventSource)
  → gate: keys + resume + CLI present
  → acquire single-flight lock (else SSE "busy")
  → background thread:
       tee stdout/stderr into event queue
       run_pipeline(on_progress → queue)
  → async SSE loop drains queue → client
  → release lock
```

State after a run is pulled via REST (`/api/jobs`, statuses, cover letters, export).

### 2.6 Persistence model (why it looks like this)

| Concept | Shape |
|---|---|
| Run ledger | `running` → `completed` / `failed`; live `step` + `label`; stale runs cleaned after ~30m |
| Entities | upsert by unique URL |
| Evaluations | append-only score rows; API shows latest per entity |
| Tombstones | soft-delete timestamp; re-scrape must not resurrect |
| User tracking | status enum on the entity (applied, ignored, …) |
| Artifacts | cover letter upsert per entity |

JSON under `output/` is a convenience / backward path; SQLite is source of truth for the dashboard.

---

## 3. Requirements

### 3.1 To run *this* project

| Requirement | Notes |
|---|---|
| Python 3.10+ | Runtime |
| `pip install -r requirements.txt` | FastAPI, uvicorn, firecrawl-py, pypdf, … |
| Firecrawl API key | Search + structured scrape |
| OpenCode CLI installed + on PATH (not bundled in the installer) | AI worker |
| At least one working free model provider | OpenRouter and/or Ollama and/or OpenCode builtins |
| `resume.md` (or upload PDF in UI) | Domain input; gitignored |
| Optional: `config.json` | Job boards |

### 3.2 To rebuild the *architecture* in another domain

You need equivalents of:

| Building block | Responsibility | Minimum contract |
|---|---|---|
| **Orchestrator** | Ordered steps + progress callback + run id | `run_pipeline(on_progress) -> summary` |
| **Agent runner** | Spawn CLI/LLM, stream, dual timeouts, rotate models | `run(prompt, context) -> str` / `…_json()` |
| **Model health pool** | Probe, TTL cache, skip after N failures, re-probe | `get_healthy_models() -> [id]` |
| **Prompt pack** | One file per step; stdout-only schema | Human-readable contract the host validates |
| **Acquisition adapter** | Search + extract structured items | Swap vendor; keep normalize/dedupe |
| **Repository** | Run ledger, entities, evaluations, tombstones | SQLite is enough for local single-user |
| **API shell** | REST for state; SSE for long task | Single-flight lock |
| **Trust vault** | Keys + personal docs outside domain DB | Onboarding gate before run |
| **Config** | Thresholds, timeouts, batch size, source lists | Code defaults + optional JSON override |

### 3.3 Non-requirements (intentionally absent)

- Microservices, message bus, DI container
- Multi-tenant auth
- AI writing files directly
- Always-on paid model (this design assumes flaky free compute)

---

## 4. Known Flaws (working, but imperfect)

Honest ceilings of the current design — keep or fix when you transplant:

| Flaw | Effect | Upgrade path |
|---|---|---|
| God-module orchestrator (`agent.py`) | Scrape + AI runner + pipeline in one file | Split `runner` / `acquire` / `pipeline` only when it hurts |
| Infinite outer retry on AI calls | Can spin a long time if models return empty/junk but “succeed” enough to stay in pool | Cap total attempts per step |
| Prompt drift toward one biography | `analyze.md` can hardcode education/domain; breaks “any profession” | Derive scoring rules only from extracted profile |
| Agent config not committed (`opencode.json` gitignored) | Clones may lack the read-only agent definition | Ship a sample or generate on first run |
| Prober vs runner resolve CLI differently | Probe may miss a binary the pipeline finds (or vice versa) | One `find_cli()` shared |
| Profile cache = file exists | Stale profile after resume edit until manual delete | Hash resume or bust cache on save |
| Soft quality of snippet fallback | Failed scrapes still enter the pool as thin rows | Score them lower or mark `partial` |
| Single global run lock | Fine for one user; no queue | Queue if you ever need concurrent runs |
| Scraped text → prompt | Prompt-injection surface into the model | Sanitize/limit description length; never trust model for auth |
| No in-repo CI | Regressions depend on local `pytest` | Add a minimal test workflow when the team grows |
| Cover letters off by default | Correct for cost; easy to forget and think letters are “broken” | Document clearly; bulk generate in UI |

`ponytail:` several of these are deliberate shortcuts (cost, single-user, free models). Fix when the ceiling is hit, not before.

---

## 5. Minimal Mental Model

```
┌─────────────┐     REST / SSE      ┌─────────────┐
│  Local UI   │◄───────────────────►│  API shell  │
└─────────────┘                     └──────┬──────┘
                                           │
                                    ┌──────▼──────┐
                                    │ Orchestrator│
                                    └──────┬──────┘
                         ┌─────────────────┼─────────────────┐
                         ▼                 ▼                 ▼
                   Agent CLI          Acquire API         Repository
                   (stdout)           (search/scrape)     (SQLite)
```

**Invariant to preserve when copying:** the host is the system of record; the model is a function `context → text` behind retries.

---

## 6. Transplant Checklist

- [ ] Define domain steps and stdout contracts (prompts)
- [ ] Implement agent runner with dual timeouts + process-tree kill
- [ ] Implement model pool (or a single paid model and delete the pool)
- [ ] Implement acquire → normalize → dedupe → tombstone skip
- [ ] Implement run ledger + append-only evaluations + latest projection
- [ ] Wire SSE long-task + single-flight lock
- [ ] Keep secrets out of the domain DB
- [ ] Add one validation layer on AI JSON (don’t trust the model)
- [ ] Decide which known flaws you accept on day one
```

---

Skipped: the 15-phase encyclopedia, new abstractions, fixing the listed flaws.

Add when: you want this renamed, or a second file that maps each blueprint box to exact functions in this repo.