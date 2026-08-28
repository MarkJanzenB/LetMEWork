# Changelog

All notable changes to **Let Me Work** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning: [SemVer](https://semver.org/) with optional `-beta.N` / `-rc.N` prerelease tags.

Repo: https://github.com/MarkJanzenB/LetMEWork

## [Unreleased]

### Added
- Resume stub guard: refuse Run Agent when resume is empty/placeholder (`# New Resume`); setup status exposes `resume_usable`
- Reuse last `search_config.json` when the model returns zero search queries
- Cancel policy: discard scrape before scoring; keep jobs if cancel happens after scores are saved
- Run-complete modal with new / updated / above-threshold counts (+ chime, respects reduced motion)
- Parallel analyze (same pinned model, up to 3 workers); skip already-scored URLs on re-runs
### Changed
- Calm dashboard — left sidebar nav/filters, cut metric funnel, leaner header
- Higher-contrast text tokens so secondary labels stay readable on dark chrome
- Settings: work-type checkboxes (Remote / Hybrid / On-site); scrape limited to selected boards + location
- Sidebar source filter lists supported websites (not only discovered hosts)
- Ollama provider is **Cloud-only** (`OLLAMA_API_KEY` → ollama.com); local `ollama serve` is no longer probed
### Fixed
- Job-board selection is enforced in queries and scrape results (not prompt-only)
- Foreign onsite/hybrid listings filtered out early when resume location is local (e.g. Philippines)
- In-app update: download while you work, Restart now / Later, then silent Setup + relaunch
### Removed
- Local Ollama daemon discovery/probing (`127.0.0.1:11434`)

## [0.1.0-beta.4] — 2026-08-06

### Added
- Ollama Cloud API key (`OLLAMA_API_KEY`) in onboarding/Settings under **Model providers** (alongside OpenRouter); local `ollama serve` still needs no key
- Installer: Tasks opt-in for OpenCode; detect-first; soft-install only if missing; recover when install errors but binary is present; quieter silent Setup
- Onboarding/Settings **Install OpenCode** soft-install via `/api/setup/install-opencode`

### Fixed
- OpenCode free-model discovery: parse verbose/ANSI lists, include `big-pickle` + `*-free`, fall back to cheap-looking ids; clearer WARNING when nothing is healthy
- Packaged EXE: bundle firecrawl package data so version lookup no longer fails under `_MEI`
- Packaged EXE: seed `%APPDATA%\LetMeWork\opencode.json` with `job-agent`; run OpenCode with `OPENCODE_CONFIG` + AppData cwd (fixes agent-not-found on launch)
- Refresh User/Machine PATH + wrap `opencode.cmd` via `cmd.exe` so GUI-launched EXE finds npm OpenCode
- Clearer console warning when OpenCode CLI is missing vs models merely unhealthy
- Model discovery: no hardcoded OpenRouter/OpenCode menus — list from Ollama / OpenRouter API / `opencode models`; skip OpenRouter when not configured
- Settings / onboarding: show **Not configured** instead of fake `fc-…` / `sk-or-…` placeholders when keys are empty
- Dashboard warns (banner + toast) when Firecrawl key, resume, or OpenCode is missing after onboarding

### Credits
- Core scrape-and-score workflow: [Kurt Chan / AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper)
- Let Me Work edition: [Mark Janzen Bandola](https://github.com/MarkJanzenB)

## [0.1.0-beta.3] — 2026-08-06

### Changed
- Primary dashboard is vanilla `ui/index.html` again (React SPA not served / not bundled)
- Resume PDF upload: confirm + toast that scanned/image PDFs are not supported yet
- OpenCode post-install PATH: prefer User PATH, ensure `%APPDATA%\npm`, resolve via env vars only (no hardcoded username)

### Fixed
- Packaged app resolves OpenCode under per-user npm / scoop locations when PATH is stale
- Update check + banner runs on first launch even while onboarding wizard is open

## [0.1.0-beta.2] — 2026-08-06

Coherent public beta: React-era app tagged and published under **LetMEWork**.

### Added
- React + Vite dashboard (onboarding, jobs, cover letters, Settings) served by FastAPI
- Opt-in auto-update (`latest.json`) with notify-only default; Check for updates in Settings
- Release workflow docs (`CHANGELOG`, `RELEASE.md`, `scripts/bump_version.py`, Cursor release rule)
- README **About** + **Models & providers** (Ollama probe → sync into OpenCode → `opencode run`)

### Changed
- Repo identity / update feed → `MarkJanzenB/LetMEWork`
- Inno post-install surfaces OpenCode install failures with retry
- Dual copyright NOTICE; clearer provenance vs Kurt’s core workflow

### Fixed
- Tag/source mismatch vs first Setup (beta.1 tag predated React commit)

## [0.1.0-beta.1] — 2026-08-05

First public beta of the Let Me Work (OpenCode) edition.

### Added
- OpenCode AI runtime (replaces Claude CLI) with model health probing and rotation
- SQLite job store, run history, soft-delete / restore
- First-run onboarding (keys → resume → boards) and AppData BYOK storage
- Windows installer (PyInstaller + Inno) with OpenCode/Node post-install
- Firecrawl primary + backup API key failover
- Cover letters on demand; run cancel / active-run guards

### Credits
- Core scrape-and-score workflow: [Kurt Chan / AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper)
- Let Me Work edition: [Mark Janzen Bandola](https://github.com/MarkJanzenB)

[Unreleased]: https://github.com/MarkJanzenB/LetMEWork/compare/v0.1.0-beta.4...HEAD
[0.1.0-beta.4]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.4
[0.1.0-beta.3]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.3
[0.1.0-beta.2]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.2
[0.1.0-beta.1]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.1
