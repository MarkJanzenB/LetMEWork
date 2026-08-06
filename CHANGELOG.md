# Changelog

All notable changes to **Let Me Work** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning: [SemVer](https://semver.org/) with optional `-beta.N` / `-rc.N` prerelease tags.

Repo: https://github.com/MarkJanzenB/LetMEWork

## [Unreleased]

### Added
- Ollama Cloud API key (`OLLAMA_API_KEY`) in onboarding/Settings under **Model providers** (alongside OpenRouter); local `ollama serve` still needs no key
### Changed
### Fixed
- Packaged EXE: bundle firecrawl package data so version lookup no longer fails under `_MEI`
- Packaged EXE: seed `%APPDATA%\LetMeWork\opencode.json` with `job-agent`; run OpenCode with `OPENCODE_CONFIG` + AppData cwd (fixes agent-not-found on launch)
- Refresh User/Machine PATH + wrap `opencode.cmd` via `cmd.exe` so GUI-launched EXE finds npm OpenCode
- Clearer console warning when OpenCode CLI is missing vs models merely unhealthy
- Model discovery: no hardcoded OpenRouter/OpenCode menus — list from Ollama / OpenRouter API / `opencode models`; skip OpenRouter when not configured
- Settings / onboarding: show **Not configured** instead of fake `fc-…` / `sk-or-…` placeholders when keys are empty
- Dashboard warns when Firecrawl key or resume is missing (even after onboarding)

### Removed

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

[Unreleased]: https://github.com/MarkJanzenB/LetMEWork/compare/v0.1.0-beta.3...HEAD
[0.1.0-beta.3]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.3
[0.1.0-beta.2]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.2
[0.1.0-beta.1]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.1
