# Desktop packaging — Let Me Work

Unsigned pre-release Windows build: local app + OpenCode via **official CLI** + first-run onboarding.

## Build order

```bat
:: 1) React UI
cd frontend
npm ci
npm run build
cd ..

:: 2) Frozen EXE (bundles frontend/dist + prompts)
pip install -r requirements.txt
pip install pyinstaller
pyinstaller packaging/letmework.spec

:: 3) Compile packaging/LetMeWork.iss with Inno Setup 6
::    → dist\installer\LetMeWork-Setup-<ver>.exe
:: Post-install runs packaging/install_opencode.ps1 (retry on failure)
```

## Updates feed (GitHub Release)

Attach both assets to each release:

- `LetMeWork-Setup-<ver>.exe`
- `latest.json` — `{ "version", "installer_url", "sha256" }`

App checks `…/releases/latest/download/latest.json`. Settings: opt-in auto-update (default off) or banner + Update now.

## Dependencies the installer pulls in

Post-install script (`install_opencode.ps1`):

1. Skip if `opencode` already on PATH  
2. Else try Scoop/Choco for OpenCode directly  
3. Else install **Node.js LTS** (winget → choco → scoop → official nodejs.org MSI)  
4. Then `npm install -g opencode-ai`  
5. Exit **1** if OpenCode still missing (Inno offers Retry)

Already inside `LetMeWork.exe` (PyInstaller): Python + FastAPI + React SPA + Firecrawl client + pypdf, etc.

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
