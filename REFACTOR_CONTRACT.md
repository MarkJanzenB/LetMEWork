# REFACTOR CONTRACT — Domain · Database · Backend

Authoritative data contract for the two-state-machine refactor (Let Me Work job
scraper). Agents 2–4 implement against THIS file only. Backend = `config.py`,
`db.py`, `server.py` (Agent 1). UI (`ui/index.html`, `frontend/`) and scraper
(`agent.py`) are NOT covered here except where the API surface touches them.

---

## 1. Enums (exact, lowercase)

Source of truth: `config.py`.

| Enum | Values |
|---|---|
| `LISTING_STATUSES` (stored, system/scraper-controlled) | `active`, `closed`, `not_accepting`, `unavailable`, `unknown` |
| `APPLICATION_STATUSES` (stored, user-controlled) | `not_reviewed`, `skipped`, `applied`, `interviewing`, `offer`, `hired`, `rejected`, `withdrawn` |
| `SKIP_REASONS` (UI option list for skipped) | `location`, `experience`, `skills`, `compensation`, `employment_type`, `schedule`, `company`, `duplicate`, `low_match`, `other` |
| `REJECTION_REASONS` (UI option list for rejected) | `experience`, `skills`, `location`, `compensation`, `position_filled`, `candidate_pool`, `internal_candidate`, `other`, `unknown` |
| `EVENT_TYPES` (application_events.event_type) | `applied`, `follow_up`, `recruiter_contact`, `assessment`, `interview`, `offer`, `hired`, `withdrawn`, `rejected`, `other` |
| `EVENT_SOURCES` (application_events.source) | `user`, `system`, `ai` |

- `reason`/`note` fields are free strings (stored as-is). The SKIP/REJECTION
  reason sets are the UI's canonical options; `legacy` is a migration-only
  reason value (see §3).
- Freshness thresholds: `LISTING_STALE_AFTER_DAYS=7`,
  `LISTING_EXPIRING_BEFORE_DAYS=2`, `LISTING_EXPIRED_AFTER_DAYS=0`.
- Display labels: `APPLICATION_LABELS`, `LISTING_LABELS` in config.py.

## 2. Tables and columns

SQLite. Legacy `job_statuses` table is destroyed on migration (see §3).

### jobs — IDENTITY + LISTING only (never application fields)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| url | TEXT UNIQUE NOT NULL | |
| title, company, location, description, source | TEXT NOT NULL DEFAULT '' | identity |
| posted_date | TEXT NOT NULL DEFAULT '' | posting date when extractable (kept name; contract `posted_at` maps here) |
| first_seen_run | INTEGER → runs(id) | |
| deleted_at | TEXT NULL | soft delete; preserved exactly as before |
| listing_status | TEXT NOT NULL DEFAULT 'unknown' | `LISTING_STATUSES` |
| discovered_at | TEXT NULL | set to now on insert |
| last_scraped_at | TEXT NULL | scraper writes on every scrape |
| last_verified_at | TEXT NULL | last time listing existence was confirmed |
| deadline_at | TEXT NULL | application deadline (drives expiring/expired) |
| source_job_id | TEXT NULL | source-specific id when extractable |

### applications — user-controlled (replaces job_statuses)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| job_id | INTEGER NOT NULL UNIQUE → jobs(id) | one per job |
| status | TEXT NOT NULL DEFAULT 'not_reviewed' | `APPLICATION_STATUSES` |
| reason | TEXT NULL | |
| note | TEXT NOT NULL DEFAULT '' | '' = empty |
| updated_at | TEXT NOT NULL | UTC ISO-8601 (`_now()`) |
| created_at | TEXT NOT NULL | |
| last_opened_at | TEXT NULL | set ONLY by POST /api/open |

### application_events — timeline (belongs to the application; no separate activity log)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| job_id | INTEGER NOT NULL → jobs(id) | indexed |
| event_type | TEXT NOT NULL | `EVENT_TYPES` |
| source | TEXT NOT NULL DEFAULT 'user' | `EVENT_SOURCES` |
| occurred_at | TEXT NOT NULL | UTC ISO-8601 |
| detail | TEXT NULL | e.g. skip reason for `other` events |

## 3. Migration (idempotent; runs in `db.init_db()`)

Applied to legacy DBs where `job_statuses` exists. Fresh DBs skip straight to
the clean schema.

| Legacy status | applications.status | reason | note | listing_status |
|---|---|---|---|---|
| none | not_reviewed | NULL | NULL | unknown |
| ignored | skipped | NULL | NULL | unknown |
| closed | skipped | `legacy` | "Migrated: legacy status closed (listing closure unverified)" | unknown |
| applied | applied | NULL | NULL | unknown |
| interviewed | interviewing | NULL | NULL | unknown |
| rejected | rejected | NULL | NULL | unknown |
| hired | hired | NULL | NULL | unknown |

- jobs.listing_status is ALWAYS `unknown` after migration — verification is
  never fabricated.
- `job_statuses.notes` → `applications.note`; `job_statuses.viewed_at` →
  `applications.last_opened_at`; `applications.created_at` = legacy
  `updated_at`.
- Timeline backfill: ONE `application_events` row per migrated application with
  status in {applied, interviewing, offer, hired, rejected}, at its
  `updated_at`, event_type from {applied→`applied`, interviewing→`interview`,
  offer→`offer`, hired→`hired`, rejected→`rejected`}, source=`system`.
  skipped/not_reviewed get NO event (nothing occurred — an event would
  fabricate history). Backfill is guarded by `NOT EXISTS (event for job)` so
  re-running init_db never duplicates.

## 4. API

All under `/api`. Errors: `404 {detail}` job not found, `400 {detail}` invalid
status/listing value. Unchanged endpoints (not re-listed): `/`, `/api/deps`,
`/api/update/*`, `/api/run*`, `/api/health`, `/api/delete`, `/api/restore`,
`/api/cover-letter`, `/api/generate-cover-letter`, `/api/setup/*`, `/api/export/csv`,
`/api/runs`.

### GET /api/jobs → JSON array
Each job (scored, not soft-deleted), newest score first. Score keys unchanged
(`id, url, title, company, location, source, posted_date, score, verdict,
work_arrangement, match_reasons, red_flags, suggested_angle, scored_at,
has_cover_letter`). Added:
```json
{
  "listing_status": "active",
  "effective_listing_status": "stale",
  "listing_derived": "stale",
  "discovered_at": "…|null",
  "last_scraped_at": "…|null",
  "last_verified_at": "…|null",
  "deadline_at": "…|null",
  "source_job_id": "…|null",
  "status": "applied",
  "application_status": "applied",
  "application_reason": "skills|null",
  "application_note": "…|null",
  "application_updated_at": "…|null",
  "application_created_at": "…|null",
  "last_opened_at": "…|null",
  "display_label": "Applied · Listing Closed"
}
```
- `status` is a legacy alias equal to `application_status` (old UI reads it).
- `effective_listing_status` = stored listing_status, EXCEPT derived
  stale/expiring/expired (§5). `listing_derived` = the derived value or null.
- `application_status` defaults to `not_reviewed` when no application row.
- `display_label` = derived overall label (§6). Do not re-derive client-side.

### POST /api/status — application state update (extends old /api/status)
Request:
```json
{ "url": "…", "status": "applied", "reason": "skills|null", "note": "…|null" }
```
`status` MUST be an `APPLICATION_STATUSES` value. Legacy values (`none`,
`ignored`, `interviewed`, `closed`) → 400. Writes the application row AND
appends a timeline event. NEVER touches listing fields.
Response: `{"ok": true, "application_status": "applied"}`.

Status → timeline event_type: applied→`applied`, interviewing→`interview`,
offer→`offer`, hired→`hired`, rejected→`rejected`, withdrawn→`withdrawn`,
skipped→`other` (event `detail` = note, else reason). not_reviewed → no event.
Event `source` = `user`.

### POST /api/listing — listing state update (scraper/system)
Request (all optional — omit to leave unchanged):
```json
{ "url": "…", "listing_status": "closed", "deadline_at": "…|null",
  "last_verified_at": "…|null", "last_scraped_at": "…|null",
  "source_job_id": "…|null" }
```
`listing_status` MUST be a `LISTING_STATUSES` value. Updates ONLY jobs listing
columns. NEVER creates/touches an application row or event.
Response: `{"ok": true}`.
The pipeline's `db.upsert_job`/`db.save_pipeline_output` accept the same fields
(`listing_status, deadline_at, last_scraped_at, last_verified_at,
source_job_id`) on scrape writes.

### POST /api/open — explicit user "Open Listing" (replaces /api/viewed)
Request: `{"url": "…"}`. Sets `last_opened_at` ONLY. Creates the application
row (status `not_reviewed`) if none exists. MUST be called only from the
explicit Open Listing click — scraper fetches, listing updates, and bulk
actions never call it. No timeline event. `/api/viewed` is REMOVED.
Response: `{"ok": true, "last_opened_at": "…"}`.

### GET /api/timeline?url=… → application timeline
Response:
```json
{ "job_id": 1, "application_status": "applied",
  "events": [ { "id": 1, "event_type": "interview", "source": "user",
                "occurred_at": "…", "detail": null } ] }
```
Events newest first (`occurred_at DESC, id DESC`).

### GET /api/status-counts → dual-axis counts
Response: `{"application": {"not_reviewed": n, "skipped": n, "applied": n,
"interviewing": n, "offer": n, "hired": n, "rejected": n, "withdrawn": n},
"listing": {"active": n, "closed": n, "not_accepting": n, "unavailable": n,
"unknown": n}}`. Universe = same as /api/jobs (scored, not soft-deleted).

### POST /api/bulk-apply?min_score=&max_score=
Marks as `applied` ONLY jobs whose `application_status == "not_reviewed"`
(within score band). Never overwrites existing application state. Each writes
its application row + `applied` event. Response:
`{"urls": ["…"], "count": n}`.

## 5. Derived listing status — `db.effective_listing_status(job, now)`

Derived at read time ONLY, never stored. `now` = current UTC.

1. stored != `active` → return stored as-is (closed/not_accepting/unavailable/
   unknown are authoritative and never decay).
2. stored == `active`:
   - deadline_at set and deadline_at <= now → `expired`
   - deadline_at set and deadline_at <= now + 2 days → `expiring`
   - last_verified_at set and last_verified_at < now − 7 days → `stale`
   - else → `active`

`db.effective_listing_status` / `db.display_label` are the shared functions;
the UI must not re-derive.

## 6. Derived overall display label — `db.display_label(app_status, eff_listing)`

Exact table:
| application_status | effective_listing_status | display_label |
|---|---|---|
| rejected / hired / withdrawn | any | Rejected / Hired / Withdrawn |
| applied / interviewing / offer | closed / unavailable / expired | `{label} · Listing Closed` |
| applied / interviewing / offer | any other | Applied / Interviewing / Offer |
| skipped | any | Skipped |
| not_reviewed | active / unknown / stale | Not Reviewed |
| not_reviewed | expiring | Expiring Soon |
| not_reviewed | expired | Expired |
| not_reviewed | closed / unavailable | Listing Closed |
| not_reviewed | not_accepting | Not Accepting |

There is NO third stored "overall status" — the label above is always derived.

## 7. Invariants (hard)

1. State independence: listing writes (upsert_job, save_pipeline_output,
   set_listing_status, POST /api/listing) NEVER write application rows,
   application status, reasons, notes, or last_opened_at. Application writes
   (POST /api/status, POST /api/open, set_application_status, mark_opened)
   NEVER write listing_status or listing timestamps. The pair
   {listing=closed, application=applied} is fully representable.
2. last_opened_at is set ONLY by POST /api/open. Scraper fetches, pipeline
   saves, listing updates, and bulk-apply never set it.
3. User status changes append a timeline event; listing updates append none.
4. Soft delete (`jobs.deleted_at`) semantics unchanged: soft-deleted jobs are
   hidden, skipped by scrape dedupe, never resurrected by upsert.
5. Status updates validate against the exact enums; unknown values → 400.
6. `reason='legacy'` on applications means "migrated from legacy 'closed'" —
   not a user skip.
