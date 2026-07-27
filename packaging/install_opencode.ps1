# Let Me Work — install runtime deps via official channels only
# 1) Node.js LTS (if needed)  2) OpenCode (npm / scoop / choco)
# Docs: https://opencode.ai/docs/  https://nodejs.org/

$ErrorActionPreference = "Continue"
Write-Host ""
Write-Host "=== Let Me Work dependency setup ==="

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-OpenCode {
    Refresh-Path
    $cmd = Get-Command opencode -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host "OpenCode ready: $($cmd.Source)"
        return $true
    }
    return $false
}

function Install-NodeLts {
    if (Test-Cmd "npm") {
        Write-Host "Node.js/npm already present."
        return $true
    }

    Write-Host "Node.js not found — installing LTS from official sources…"

    if (Test-Cmd "winget") {
        Write-Host "Trying: winget install OpenJS.NodeJS.LTS (user scope)"
        winget install -e --id OpenJS.NodeJS.LTS --scope user --accept-package-agreements --accept-source-agreements
        Refresh-Path
        if (Test-Cmd "npm") { return $true }

        Write-Host "Trying: winget install OpenJS.NodeJS.LTS (default scope)"
        winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
        Refresh-Path
        if (Test-Cmd "npm") { return $true }
    }

    if (Test-Cmd "choco") {
        Write-Host "Trying: choco install nodejs-lts -y"
        choco install nodejs-lts -y
        Refresh-Path
        if (Test-Cmd "npm") { return $true }
    }

    if (Test-Cmd "scoop") {
        Write-Host "Trying: scoop install nodejs-lts"
        scoop install nodejs-lts
        Refresh-Path
        if (Test-Cmd "npm") { return $true }
    }

    # Last resort: official Node MSI (may prompt UAC)
    try {
        $tmp = Join-Path $env:TEMP "node-lts.msi"
        Write-Host "Downloading Node.js LTS MSI from nodejs.org…"
        $index = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -TimeoutSec 30
        $lts = $index | Where-Object { $_.lts -ne $false } | Select-Object -First 1
        if (-not $lts) { throw "Could not resolve LTS version from nodejs.org" }
        $ver = $lts.version.TrimStart("v")
        $uri = "https://nodejs.org/dist/v$ver/node-v$ver-x64.msi"
        Write-Host "URL: $uri"
        Invoke-WebRequest -Uri $uri -OutFile $tmp -UseBasicParsing
        Write-Host "Running MSI (quiet)…"
        Start-Process msiexec.exe -ArgumentList "/i `"$tmp`" /qn /norestart" -Wait -NoNewWindow
        Refresh-Path
        Remove-Item $tmp -ErrorAction SilentlyContinue
        if (Test-Cmd "npm") { return $true }
    } catch {
        Write-Host "MSI install failed: $_"
    }

    return $false
}

function Install-OpenCode {
    if (Test-OpenCode) { return $true }

    if (Test-Cmd "npm") {
        Write-Host "Installing OpenCode: npm install -g opencode-ai"
        npm install -g opencode-ai
        Refresh-Path
        if (Test-OpenCode) { return $true }
        Write-Host "npm finished; open a new terminal if 'opencode' is not on PATH yet."
        return $true  # package likely installed; PATH refresh is the usual issue
    }

    if (Test-Cmd "scoop") {
        Write-Host "Installing OpenCode: scoop install opencode"
        scoop install opencode
        Refresh-Path
        return (Test-OpenCode)
    }

    if (Test-Cmd "choco") {
        Write-Host "Installing OpenCode: choco install opencode -y"
        choco install opencode -y
        Refresh-Path
        return (Test-OpenCode)
    }

    return $false
}

# --- main ---
if (Test-OpenCode) { exit 0 }

# Direct OpenCode via scoop/choco if npm missing but those exist
if (-not (Test-Cmd "npm")) {
    if (Test-Cmd "scoop") {
        Write-Host "Installing OpenCode via Scoop…"
        scoop install opencode
        Refresh-Path
        if (Test-OpenCode) { exit 0 }
    }
    if (Test-Cmd "choco") {
        Write-Host "Installing OpenCode via Chocolatey…"
        choco install opencode -y
        Refresh-Path
        if (Test-OpenCode) { exit 0 }
    }
}

if (-not (Install-NodeLts)) {
    Write-Host ""
    Write-Host "Could not install Node.js automatically."
    Write-Host "Install from https://nodejs.org then re-run:"
    Write-Host "  npm install -g opencode-ai"
    Write-Host "Let Me Work is still installed; finish OpenCode before running the agent."
    exit 0
}

[void](Install-OpenCode)

if (-not (Test-OpenCode)) {
    Write-Host ""
    Write-Host "OpenCode may need a new terminal for PATH. Verify with: opencode --version"
    Write-Host "Manual fix: npm install -g opencode-ai"
    Write-Host "Docs: https://opencode.ai/docs/"
}

Write-Host "=== Dependency setup finished ==="
exit 0
