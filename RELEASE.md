# Release workflow — Let Me Work

**Repository:** https://github.com/MarkJanzenB/LetMEWork  

How we version, changelog, and ship. Agents follow this when you say **release**, **ship**, **cut a version**, or **publish update**. Humans can run the same steps manually.

## Dev vs release

| Mode | What you do |
|------|-------------|
| **dev** (default) | `python server.py` — iterate on code + `ui/`; note items under `CHANGELOG.md` → `[Unreleased]`. No version bump, no Setup rebuild, no GitHub Release unless you ask for a **local test build** only. |
| **release** | Batch enough `[Unreleased]` work, then bump → commit → (**ask first**) push/tag → installer → GitHub Release. |

Small day-to-day fixes stay in **dev**. Do not cut a GitHub Release for every tweak.

## Release cadence (when to ship)

Count bullet lines under `[Unreleased]` (Added / Changed / Fixed / Removed):

| Batch type | Ship when you have at least… |
|------------|------------------------------|
| Ordinary mix of fixes / polish | **10** bullets |
| Major changes (features, provider rewrites, packaging breakages, etc.) | **5** bullets |

Agents: if the user asks to release early, **report the count** and **ask** whether to wait or override. Never push/tag/`gh release` without a clear yes for that publish step.

## Version source of truth

| File | Field |
|------|--------|
| `user_data.py` | `APP_VERSION` ← **canonical** |
| `pyproject.toml` | `project.version` |
| `frontend/package.json` | `version` |
| `packaging/LetMeWork.iss` | `#define MyAppVersion` (+ `VersionInfoVersion` 4-part) |
| `CHANGELOG.md` | section heading + compare links |
| Git tag | `v` + `APP_VERSION` (e.g. `v0.1.0-beta.2`) |

Bump all of them together:

```bash
python scripts/bump_version.py 0.1.0-beta.2
```

SemVer: `MAJOR.MINOR.PATCH` plus optional `-beta.N` / `-rc.N`.

## Before every release

1. **Cadence check** — enough `[Unreleased]` bullets (see table); ask if short.
2. **CHANGELOG** — move `[Unreleased]` notes into a dated `## [x.y.z]` section; leave empty Unreleased stubs.
3. **Bump** — `python scripts/bump_version.py <version>`
4. **Format / check** — `ruff check .` (and fix); `pytest`
5. **Commit** on `clean` (or release branch) — message like `Release v0.1.0-beta.2`
6. **Ask to publish** — confirm push + GitHub Release (do not assume “release” means “push now”).
7. **Push** branch, then tag (only after yes):
   ```bash
   git tag -a v0.1.0-beta.2 -m "Let Me Work v0.1.0-beta.2"
   git push origin HEAD
   git push origin v0.1.0-beta.2
   ```
8. **Build installer** (Windows + Inno 6) — see [`packaging/README.md`](packaging/README.md)
9. **GitHub Release** — attach Setup EXE + `latest.json` (`version`, `installer_url`, `sha256`).  
   - Use **Latest** (not pre-release only) if in-app `/releases/latest/` must resolve.  
   - Or mark GitHub Pre-release for true betas and point the app at a fixed tag URL.
10. **Release notes** — paste CHANGELOG section; mention unsigned SmartScreen (**More info → Run anyway**); credit Kurt for core workflow.

## `latest.json` shape

```json
{
  "version": "0.1.0-beta.2",
  "installer_url": "https://github.com/MarkJanzenB/LetMEWork/releases/download/v0.1.0-beta.2/LetMeWork-Setup-0.1.0-beta.2.exe",
  "sha256": "<lowercase hex>"
}
```

## Agent rule

Cursor rule: [`.cursor/rules/release.mdc`](.cursor/rules/release.mdc) — applies when release language is used.

- Default to **dev** (`python server.py` + `[Unreleased]`).
- **Ask** before push, tag publish, or `gh release create`.
- Enforce the **10 / 5** batch gate (or ask for an override).
