# Changelog

All notable changes to **Let Me Work** are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning: [SemVer](https://semver.org/) with optional `-beta.N` / `-rc.N` prerelease tags.

Repo: https://github.com/MarkJanzenB/LetMEWork

## [Unreleased]

### Added
### Changed
### Fixed
### Removed

## [0.1.0-beta.1] — 2026-08-05

First public beta of the Let Me Work (OpenCode) edition.

### Added
- OpenCode AI runtime (replaces Claude CLI) with model health probing and rotation
- SQLite job store, run history, soft-delete / restore
- First-run onboarding (keys → resume → boards) and AppData BYOK storage
- React + Vite dashboard served by FastAPI; legacy `ui/` fallback
- Windows installer (PyInstaller + Inno) with OpenCode/Node post-install retry
- Opt-in auto-update via GitHub Release `latest.json` (default: notify only)
- Firecrawl primary + backup API key failover
- Cover letters on demand; run cancel / active-run guards

### Credits
- Core scrape-and-score workflow: [Kurt Chan / AI Job Hunt Agent](https://github.com/Kurt-Chan/ai-job-scraper)
- Let Me Work edition: [Mark Janzen Bandola](https://github.com/MarkJanzenB)

[Unreleased]: https://github.com/MarkJanzenB/LetMEWork/compare/v0.1.0-beta.1...HEAD
[0.1.0-beta.1]: https://github.com/MarkJanzenB/LetMEWork/releases/tag/v0.1.0-beta.1
