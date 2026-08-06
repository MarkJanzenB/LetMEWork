# Let Me Work — install runtime deps via official channels only
# 1) Node.js LTS (if needed)  2) OpenCode (npm / scoop / choco)
# Docs: https://opencode.ai/docs/  https://nodejs.org/
#
# Exit codes:
#   0 = OpenCode available (already on disk, or just installed)
#   1 = install attempted and still missing
#   2 = DetectOnly: OpenCode not found (no install attempted)
#
# PATH rules: Machine/User env Path + %APPDATA%\npm — never hardcode a username.
#
# Usage:
#   install_opencode.ps1              # detect; if missing, soft-install
#   install_opencode.ps1 -DetectOnly  # detect only (exit 0/2)

param(
    [switch]$DetectOnly
)

$ErrorActionPreference = "Continue"
Write-Host ""
Write-Host "=== Let Me Work dependency setup ==="

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($chunk in @($user, $machine, $env:Path)) {
        if (-not [string]::IsNullOrWhiteSpace($chunk)) {
            foreach ($p in ($chunk -split ";")) {
                $t = $p.Trim()
                if ($t -and -not $parts.Contains($t)) { [void]$parts.Add($t) }
            }
        }
    }
    if ($env:APPDATA) {
        $npmUser = Join-Path $env:APPDATA "npm"
        if ((Test-Path $npmUser) -and -not $parts.Contains($npmUser)) {
            [void]$parts.Add($npmUser)
        }
    }
    $env:Path = ($parts -join ";")
}

function Ensure-UserNpmOnPath {
    if (-not $env:APPDATA) { return }
    $npmDir = Join-Path $env:APPDATA "npm"
    if (-not (Test-Path $npmDir)) { return }
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @()
    if ($userPath) { $entries = @($userPath -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    if ($entries -contains $npmDir) { return }
    $newPath = if ($userPath) { "$userPath;$npmDir" } else { $npmDir }
    [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Ensured %APPDATA%\npm is on the User PATH."
    Refresh-Path
}

function Test-Cmd([string]$Name) {
    Refresh-Path
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-OpenCode {
    Refresh-Path
    $cmd = Get-Command opencode -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:APPDATA) {
        [void]$candidates.Add((Join-Path $env:APPDATA "npm\opencode.exe"))
        [void]$candidates.Add((Join-Path $env:APPDATA "npm\opencode.cmd"))
    }
    if ($env:LOCALAPPDATA) {
        [void]$candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\opencode\opencode.exe"))
        [void]$candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\opencode\bin\opencode.exe"))
    }
    if ($env:USERPROFILE) {
        [void]$candidates.Add((Join-Path $env:USERPROFILE "scoop\shims\opencode.exe"))
        [void]$candidates.Add((Join-Path $env:USERPROFILE "scoop\apps\opencode\current\opencode.exe"))
    }
    if ($env:ProgramFiles) {
        [void]$candidates.Add((Join-Path $env:ProgramFiles "opencode\opencode.exe"))
    }
    # where.exe can see PATH entries Get-Command misses in some Setup contexts
    try {
        $where = & where.exe opencode 2>$null
        if ($where) {
            foreach ($line in @($where)) {
                $t = "$line".Trim()
                if ($t) { [void]$candidates.Add($t) }
            }
        }
    } catch { }

    if (Get-Command npm -ErrorAction SilentlyContinue) {
        try {
            $prefix = (& npm config get prefix 2>$null | Select-Object -Last 1)
            if ($prefix) {
                $prefix = $prefix.Trim()
                [void]$candidates.Add((Join-Path $prefix "opencode.exe"))
                [void]$candidates.Add((Join-Path $prefix "opencode.cmd"))
                [void]$candidates.Add((Join-Path $prefix "opencode"))
            }
        } catch { }
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

function Test-OpenCode {
    $path = Resolve-OpenCode
    if ($path) {
        Write-Host "OpenCode detected: $path"
        return $true
    }
    return $false
}

function Install-NodeLts {
    if (Test-Cmd "npm") {
        Write-Host "Node.js/npm already present."
        return $true
    }

    Write-Host "Node.js not found - installing LTS from official sources..."

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

    try {
        $tmp = Join-Path $env:TEMP "node-lts.msi"
        Write-Host "Downloading Node.js LTS MSI from nodejs.org..."
        $index = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -TimeoutSec 30
        $lts = $index | Where-Object { $_.lts -ne $false } | Select-Object -First 1
        if (-not $lts) { throw "Could not resolve LTS version from nodejs.org" }
        $ver = $lts.version.TrimStart("v")
        $uri = "https://nodejs.org/dist/v$ver/node-v$ver-x64.msi"
        Write-Host "URL: $uri"
        Invoke-WebRequest -Uri $uri -OutFile $tmp -UseBasicParsing
        Write-Host "Running MSI (quiet)..."
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
        Ensure-UserNpmOnPath
        Refresh-Path
        if (Test-OpenCode) { return $true }
        Write-Host "npm finished but OpenCode not resolved yet (PATH may need a new session)."
        return $false
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
if (Test-OpenCode) {
    Write-Host "=== OpenCode already on this PC - no install needed ==="
    exit 0
}

if ($DetectOnly) {
    Write-Host "OpenCode not found (detect-only)."
    exit 2
}

Write-Host "OpenCode not found - attempting soft install from official channels..."

if (-not (Test-Cmd "npm")) {
    if (Test-Cmd "scoop") {
        Write-Host "Installing OpenCode via Scoop..."
        scoop install opencode
        Refresh-Path
        if (Test-OpenCode) { exit 0 }
    }
    if (Test-Cmd "choco") {
        Write-Host "Installing OpenCode via Chocolatey..."
        choco install opencode -y
        Refresh-Path
        if (Test-OpenCode) { exit 0 }
    }
}

if (-not (Install-NodeLts)) {
    # Last chance: maybe OpenCode exists but npm/Node detection failed earlier
    if (Test-OpenCode) {
        Write-Host "=== OpenCode detected despite Node install issues - OK ==="
        exit 0
    }
    Write-Host ""
    Write-Host "Could not install Node.js automatically."
    Write-Host "Install from https://nodejs.org then run: npm install -g opencode-ai"
    exit 1
}

[void](Install-OpenCode)

# npm/scoop may error (already installed, EPERM, network) while binary is on disk
if (-not (Test-OpenCode)) {
    Write-Host ""
    Write-Host "OpenCode install reported a problem and the binary was not found."
    Write-Host "Manual fix: npm install -g opencode-ai"
    Write-Host "Then confirm: where.exe opencode"
    Write-Host "Docs: https://opencode.ai/docs/"
    exit 1
}

Write-Host "=== Dependency setup finished (OpenCode OK) ==="
exit 0
