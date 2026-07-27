# OpenCode + Node (official installers — not vendored)

Post-install runs `install_opencode.ps1`:

1. Install **Node.js LTS** if `npm` is missing (winget → choco → scoop → nodejs.org MSI)
2. Install **OpenCode** via documented Windows methods:

```text
npm install -g opencode-ai
scoop install opencode
choco install opencode
```

Sources: https://opencode.ai/docs/ · https://nodejs.org/

The app installer always finishes even if a step fails; users can fix PATH / re-run npm manually.
