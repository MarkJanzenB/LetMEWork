# Desktop packaging — Let Me Work

Unsigned pre-release Windows build: local app + OpenCode via **official CLI** + first-run onboarding.

## Build order

```bat
pip install -r requirements.txt
pip install pyinstaller
pyinstaller packaging/letmework.spec

:: Compile packaging/LetMeWork.iss with Inno Setup 6
:: Post-install runs packaging/install_opencode.ps1
```

## Dependencies the installer pulls in

Post-install script (`install_opencode.ps1`):

1. Skip if `opencode` already on PATH  
2. Else try Scoop/Choco for OpenCode directly  
3. Else install **Node.js LTS** (winget → choco → scoop → official nodejs.org MSI)  
4. Then `npm install -g opencode-ai`

Already inside `LetMeWork.exe` (PyInstaller): Python + FastAPI + Firecrawl client + pypdf, etc.

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

**Honest limit:** without Authenticode, SmartScreen can still warn on a new publisher. Signing (see SIGNING.md) is the real fix later; these steps only lower heuristic risk.

## Runtime layout

| Path | Purpose |
|------|---------|
| `{localappdata}\LetMeWork\LetMeWork.exe` | App |
| `%APPDATA%\LetMeWork\.env` | API keys (local only) |
| `%APPDATA%\LetMeWork\resume.md` | Text for AI |
| `%APPDATA%\LetMeWork\resume.pdf` | Original uploaded PDF (optional) |
| `%APPDATA%\LetMeWork\data\jobs.db` | Job DB (frozen builds) |
