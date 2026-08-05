# Release workflow — Let Me Work

**Repository:** https://github.com/MarkJanzenB/LetMEWork  

How we version, changelog, and ship. Agents follow this when you say **release**, **ship**, **cut a version**, or **publish update**. Humans can run the same steps manually.

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

1. **CHANGELOG** — move `[Unreleased]` notes into a dated `## [x.y.z]` section; leave empty Unreleased stubs.
2. **Bump** — `python scripts/bump_version.py <version>`
3. **Format / check** — `ruff check .` (and fix); `pytest`; if UI changed: `cd frontend && npm run build`
4. **Commit** on `clean` (or release branch) — message like `Release v0.1.0-beta.2`
5. **Push** branch, then tag:
   ```bash
   git tag -a v0.1.0-beta.2 -m "Let Me Work v0.1.0-beta.2"
   git push origin HEAD
   git push origin v0.1.0-beta.2
   ```
6. **Build installer** (Windows + Inno 6) — see [`packaging/README.md`](packaging/README.md)
7. **GitHub Release** — attach Setup EXE + `latest.json` (`version`, `installer_url`, `sha256`).  
   - Use **Latest** (not pre-release only) if in-app `/releases/latest/` must resolve.  
   - Or mark GitHub Pre-release for true betas and point the app at a fixed tag URL.
8. **Release notes** — paste CHANGELOG section; mention unsigned SmartScreen (**More info → Run anyway**); credit Kurt for core workflow.

## `latest.json` shape

```json
{
  "version": "0.1.0-beta.2",
  "installer_url": "https://github.com/MarkJanzenB/LetMEWork/releases/download/v0.1.0-beta.2/LetMeWork-Setup-0.1.0-beta.2.exe",
  "sha256": "<lowercase hex>"
}
```

## Agent rule

Cursor rule: [`.cursor/rules/release.mdc`](.cursor/rules/release.mdc) — auto-applies when release language is used. Do **not** push or create a GitHub Release unless the user explicitly asked.
