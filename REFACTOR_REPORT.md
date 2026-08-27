# Refactor Report — Two-State-Machine Job Status

Integration report for the coordinated refactor. Contract: `REFACTOR_CONTRACT.md`.

## Files changed

| File | Change |
|---|---|
| `config.py` | `LISTING_STATUSES` (stored + derived), `APPLICATION_STATUSES` (8 values), `SKIP_REASONS`, `REJECTION_REASONS`, `EVENT_TYPES`, `EVENT_SOURCES`, `VALID_STATUSES` removed |
| `db.py` | `applications` + `application_events` tables (replace `job_statuses`), `set_application_status`, `set_listing_status`, `add_event`, `mark_opened`, `effective_listing_status`, `display_label`, `get_status_counts`, `get_timeline`, `init_db` migration (idempotent) |
| `server.py` | `POST /api/status`, `/api/listing`, `/api/open` (replaces `/api/viewed`), `GET /api/timeline`, `/api/status-counts`; `/api/jobs` now returns `application_status`, `display_label`, `effective_listing_status`, `last_opened_at`; `export_csv` reads merged application status |
| `agent.py` | Scraper owns listing status/verification only; LLM signal → listing status mapping; deadline + `source_job_id` extraction; never touches application state |
| `migrate_json_to_db.py` | Upserts into `applications`/`cover_letters` by `job_id` (was calling removed `set_job_status`) |
| `ui/index.html` | Full frontend rework — see UI section |
| `test_lifecycle.py`, `test_listing.py`, `test_workflow.py`, `test_integration.py` | New backend tests |
| `test_server.py`, `test_pipeline.py`, `test_user_data.py`, `model_prober.py` | Adapted to new model |
| `README.md`, `CHANGELOG.md`, `RELEASE.md`, `.env.example`, `.cursor/rules/release.mdc` | Doc drift updated |

## Database

- `jobs` gains listing columns: `listing_status`, `discovered_at`, `last_scraped_at`, `last_verified_at`, `deadline_at`, `source_job_id`.
- New `applications` table (`job_id` PK, `status`, `reason`, `note`, `updated_at`, `created_at`, `last_opened_at`).
- New `application_events` table (`event_type`, `source`, `occurred_at`, `detail`) — timeline.
- Legacy `job_statuses` dropped after migration.

## API

- `POST /api/status {url, status, reason?, note?}` — single writer of application state + event.
- `POST /api/listing {url, listing_status}` — scraper/verification writer.
- `POST /api/open {url}` — only writer of `last_opened_at`.
- `GET /api/timeline?url=...` — event history.
- `GET /api/status-counts` — dual-axis counts (application + listing).
- `GET /api/jobs` — merged payload with both state machines.
- `POST /api/bulk-apply` — marks only `not_reviewed`; never overwrites existing state.
- `/api/viewed` **removed**.

## Migration (real DB `data/jobs.db`)

| Before | After |
|---|---|
| 614 jobs | 614 jobs, `listing_status='unknown'` for all (never fabricated) |
| 504 `job_statuses` rows | 504 `applications` rows |
| 267 closed | → `skipped` (437 total = 170 ignored + 267 closed) |
| 170 ignored | → `skipped` (no reason) |
| 59 applied | → `applied` |
| 6 rejected | → `rejected` (preserved, NOT skipped) |
| 2 none | → `not_reviewed` |
| — | 65 `application_events` backfilled (`applied`×59, `rejected`×6) at legacy `updated_at`; skipped/not_reviewed get none |

Zero legacy status values remain; `job_statuses` table dropped. Migration is idempotent and runs in `init_db` on server start. Backup: the pre-migration DB is recoverable from git history / the last pre-refactor run.

## UI

- Tabs: `not_reviewed` / `active` / `skipped` / `closed_out` (counts via `tab-count-*`).
- Funnel: per-application-status + per-listing-status groups.
- Filters: verdict, listing (`active`/`closed`/`not_accepting`/`unavailable`), source, age (via `discovered_at`), sort (`recent` = `discovered_at`, `updated`, `deadline`, score asc/desc, company).
- Cards: 8-status dropdown, listing badge, compound `display_label` badge, reason/note detail, lazy timeline, Open Listing ↗ (`POST /api/open`).
- Skip/reject → reason modal (`#reason-modal`, `openReasonModal`/`confirmReason`).
- Removed: `markJobViewed`, `nextStatus`, `TAB_OF` (replaced by `TABS`/`tabOf`).

## Tests & checks

- `pytest`: **115 passed, 0 failed** (was 63 at HEAD; `test_pipeline.py::test_run_opencode_raises_when_cli_missing` was fixed by patching the correct symbol).
- `ruff`: 75 errors at HEAD → 48 now in touched files (all remaining are pre-existing style debt in old files; the new test files are clean).
- QA (Puppeteer): t1 10/11 (one pre-existing 420px header-overflow layout check fails at HEAD too), t2 20/20, t3 8/8, t4 15/15, t5 21/21.
- `frontend/` React app is parked (README.md:68), not served — not rebuilt; it still compiles against the old status model and is out of scope.

## Known issues / deviations

- `data/jobs.db` `listing_status` is `unknown` for all jobs — correct per contract (never fabricate verification); a fresh scrape run repopulates it.
- QA header-overflow check fails — pre-existing layout issue, unrelated to the status refactor.
- `frontend/` React app still assumes the old single-status model (parked, not shipped).
