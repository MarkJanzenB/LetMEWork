# Desktop packaging — Let Me Work

Unsigned public-beta Windows build for [MarkJanzenB/LetMEWork](https://github.com/MarkJanzenB/LetMEWork): local app + OpenCode via **official CLI** + first-run onboarding.

Core scrape-and-score workflow: Kurt Chan’s AI Job Hunt Agent. This packaging layer is part of Mark Janzen Bandola’s Let Me Work edition (see repo `NOTICE`).

## Build order

```bat
:: 1) Frozen EXE (bundles ui/ + prompts)
pip install -r requirements.txt
pip install pyinstaller
pyinstaller packaging/letmework.spec

:: 2) Compile packaging/LetMeWork.iss with Inno Setup 6
::    → dist\installer\LetMeWork-Setup-<ver>.exe
:: Post-install runs packaging/install_opencode.ps1 (retry on failure)
```

## Updates feed (GitHub Release)

Attach both assets to each release:

- `LetMeWork-Setup-<ver>.exe`
- `latest.json` — `{ "version", "installer_url", "sha256" }`

App checks `https://github.com/MarkJanzenB/LetMEWork/releases/latest/download/latest.json`. Settings: opt-in auto-update (default off) or banner + Update now. Use a non-prerelease GitHub Release so `/latest/` resolves.

## Dependencies the installer pulls in

Post-install script (`install_opencode.ps1`):

1. **Wizard Tasks** — “Install OpenCode CLI if missing” (checked by default)  
2. **Detect** (`-DetectOnly`) — PATH, `%APPDATA%\npm`, Scoop, `where.exe`, npm prefix  
3. If found → skip download (tell the user; quiet when silent)  
4. If missing + task opted in → confirm (interactive) then soft-install  
5. Soft install: Scoop/Choco OpenCode, else Node LTS then `npm install -g opencode-ai`  
6. If the installer tool errors but OpenCode is still detected → treat as **success**  
7. Exit **1** only when still missing (Inno offers Retry); exit **2** = detect-only miss  

**Important:** recompile `LetMeWork.iss` after changing this script — an old Setup EXE still runs the old post-install behavior.

Already inside `LetMeWork.exe` (PyInstaller): Python + FastAPI + vanilla UI + Firecrawl client (source + rthook so `__init__.py` exists under `_MEI`) + `opencode.json` template + `install_opencode.ps1` + pypdf, etc.

Not installed (BYOK): Firecrawl / OpenRouter API keys.

## Practices that reduce false positives (no cert yet)

| Practice | Why |
|----------|-----|
| No bundled `opencode.exe` | Shipping unknown binaries inside Setup is a common AV trigger |
| Official package managers only | Reputation comes from npm/Scoop/Choco, not a random exe |
| No UPX on PyInstaller | UPX-packed EXEs are heavily fingerprinted by AV |
| Per-user install (`PrivilegesRequired=lowest`) | Avoids unnecessary admin elevation |
| Clear publisher + VersionInfo* | Helps Windows identify the software |
| Honest InfoBefore text | User consent for OpenCode network install |
| SetupLogging | Easier support / audit |
| Stable AppId | Later Setups upgrade in place |

**Honest limit:** without Authenticode, SmartScreen can still warn on a new publisher. Signing (see SIGNING.md) is the real fix later; these steps only lower heuristic risk.

## Runtime layout

| Path | Purpose |
|------|---------|
| `{localappdata}\LetMeWork\LetMeWork.exe` | App |
| `%APPDATA%\LetMeWork\.env` | API keys (local only) |
| `%APPDATA%\LetMeWork\resume.md` | Text for AI |
| `%APPDATA%\LetMeWork\resume.pdf` | Original uploaded PDF (optional) |
| `%APPDATA%\LetMeWork\data\jobs.db` | Job DB (frozen builds) |
| `%APPDATA%\LetMeWork\settings.json` | Onboarding + `auto_update` |
| `%APPDATA%\LetMeWork\opencode.json` | OpenCode `job-agent` + synced providers (seeded from `packaging/opencode.json`) |
