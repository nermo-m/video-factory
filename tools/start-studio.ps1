<#
.SYNOPSIS
  Start Video Factory Studio on this PC with one command, from PowerShell.

.DESCRIPTION
  Does what `make up` does, without needing make on the PATH:

  1. starts Docker Desktop when it is not running, and waits for it;
  2. creates .env from .env.example when it does not exist;
  3. builds and starts web, api, worker and db, and waits until they are healthy;
  4. in subscription mode, starts the bridge to the Claude Code and Codex command line
     tools on this PC, and says whether each tool is signed in with a plan;
  5. opens the interface in the browser.

  The mode is the one asked for with -Mode. Without -Mode it is subscription: your own
  ideas, on your own Claude and ChatGPT plans, no API key. `-Mode demo` tells the bundled
  sample story with no accounts at all. The .env file is not changed.

.EXAMPLE
  .\tools\start-studio.ps1
  .\tools\start-studio.ps1 -Mode demo
  .\tools\start-studio.ps1 -Stop
#>
param(
    [ValidateSet("subscription", "demo")]
    [string]$Mode = "subscription",
    [switch]$Stop,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-Uv {
    $onPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $installed = Get-ChildItem -Path "$env:APPDATA\Python\Python*\Scripts\uv.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($installed) { return $installed.FullName }
    return $null
}

function Test-Docker {
    # The native command writes to standard error while the engine is down. That must not
    # stop this script, so the check runs with errors as plain output.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-Bridge([string]$command) {
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host "uv was not found, so the bridge cannot be started. Install uv (https://docs.astral.sh/uv/) and run this again."
        return $false
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $uv run --env-file .env python -m tools.cli_bridge $command
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
}

if ($Stop) {
    if (Test-Docker) { docker compose down }
    Invoke-Bridge "stop" | Out-Null
    Write-Host "Video Factory Studio is stopped. Your episodes and videos are kept."
    exit 0
}

if (-not (Test-Docker)) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $desktop)) {
        Write-Host "Docker is not running and Docker Desktop was not found at $desktop. Start Docker and run this again."
        exit 1
    }
    Write-Host "Starting Docker Desktop. This takes about a minute."
    Start-Process $desktop
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-Docker)) {
        if ((Get-Date) -gt $deadline) {
            Write-Host "Docker did not start within four minutes. Open Docker Desktop, wait until it says it is running, and run this again."
            exit 1
        }
        Start-Sleep -Seconds 3
    }
}

$env:PROVIDER_MODE = $Mode
Write-Host "Starting Video Factory Studio in $Mode mode."
docker compose up --build --quiet-build --detach --wait
if ($LASTEXITCODE -ne 0) {
    Write-Host "The stack did not start. See: docker compose logs"
    exit 1
}

if ($Mode -eq "subscription") {
    if (-not (Invoke-Bridge "start")) {
        Write-Host "The bridge to Claude Code and Codex did not start, so planning and pictures will wait. See .run\cli-bridge.log"
        exit 1
    }
}

$address = "http://127.0.0.1:3000"
Write-Host ""
Write-Host "Video Factory Studio is running at $address"
if ($Mode -eq "subscription") {
    Write-Host "Choose New episode and type your own idea. Stop it with: .\tools\start-studio.ps1 -Stop"
} else {
    Write-Host "Demo mode tells the bundled sample story. Stop it with: .\tools\start-studio.ps1 -Stop"
}
if (-not $NoBrowser) { Start-Process $address }
