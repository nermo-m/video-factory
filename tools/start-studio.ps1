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
  5. starts ComfyUI, the program that makes moving clips on the graphics card, when the
     COMFYUI_DIR environment variable says where it is installed (docs/gpu-setup.md).
     Without it the studio works as before and a clip scene shows its still picture;
  6. opens the interface in the browser.

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

$comfyAddress = "http://127.0.0.1:8188"
$comfyPidFile = Join-Path $root ".run\comfyui.pid"

function Test-Comfy {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "$comfyAddress/system_stats" | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-Comfy {
    if (Test-Comfy) {
        Write-Host "ComfyUI is already running, so clips can be made on the graphics card."
        return
    }
    $folder = $env:COMFYUI_DIR
    if (-not $folder) {
        Write-Host "ComfyUI is not set up (COMFYUI_DIR is not set), so clip scenes show their still picture. See docs\gpu-setup.md."
        return
    }
    $python = Join-Path $folder ".venv\Scripts\python.exe"
    if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $folder "main.py"))) {
        Write-Host "COMFYUI_DIR is $folder, but ComfyUI and its .venv were not found there. See docs\gpu-setup.md."
        return
    }
    New-Item -ItemType Directory -Force (Join-Path $root ".run") | Out-Null
    # It listens on this PC only. The containers reach it through host.docker.internal.
    $started = Start-Process -FilePath $python `
        -ArgumentList "main.py", "--listen", "127.0.0.1", "--port", "8188" `
        -WorkingDirectory $folder -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $root ".run\comfyui.out.log") `
        -RedirectStandardError (Join-Path $root ".run\comfyui.log")
    Set-Content -Path $comfyPidFile -Value $started.Id -Encoding ascii
    Write-Host "ComfyUI is starting. It takes about a minute, and the GPU dot in the studio turns green when it is ready."
}

function Stop-Comfy {
    if (-not (Test-Path $comfyPidFile)) { return }
    $id = [int](Get-Content $comfyPidFile -TotalCount 1)
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    # Only the ComfyUI this script started, and only while that number still is a Python.
    if ($process -and $process.ProcessName -like "python*") {
        Stop-Process -Id $id -Force -Confirm:$false
    }
    Remove-Item $comfyPidFile -Force -Confirm:$false
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example."
}

if ($Stop) {
    if (Test-Docker) { docker compose down }
    Invoke-Bridge "stop" | Out-Null
    Stop-Comfy
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
    Start-Comfy
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
