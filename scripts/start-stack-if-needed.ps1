[CmdletBinding()]
param(
    [int]$DelaySeconds = 15
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$runtimeDir = Join-Path $repoRoot '.runtime'
$watchdogLog = Join-Path $runtimeDir 'autostart-watchdog.log'
$startScript = Join-Path $repoRoot 'start-server.ps1'
$trayScript = Join-Path $repoRoot 'scripts\show-autostart-tray.ps1'

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Write-WatchdogLog {
    param([string]$Message)

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $watchdogLog -Value "[$timestamp] $Message"
}

function Test-LocalUrl {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Start-TrayHelper {
    if (-not (Test-Path $trayScript)) {
        return
    }

    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden',
            '-File', $trayScript
        ) -WindowStyle Hidden | Out-Null
        Write-WatchdogLog 'Tray helper launch requested.'
    } catch {
        Write-WatchdogLog "Tray helper launch failed: $($_.Exception.Message)"
    }
}

function Start-RuntimeProcesses {
    # Lightweight restart: launch processes directly without reinstalling dependencies.
    # Used as fallback when start-server.ps1 fails (e.g. pip install error).
    $backendDir   = Join-Path $repoRoot 'backend'
    $venvPython   = Join-Path $backendDir '.venv\Scripts\python.exe'
    $apiBat       = Join-Path $backendDir 'run-api.bat'
    $caddyConfig  = Join-Path $repoRoot 'infra\Caddyfile'
    $frpcExe      = 'C:\frp\frpc.exe'
    $frpcConfig   = 'C:\frp\frpc.toml'

    # Require venv to exist
    if (-not (Test-Path $venvPython)) {
        throw 'Python venv not found. Full setup required.'
    }

    # Kill stale processes
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*telegram_service*" -or $_.CommandLine -like "*backend*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name 'caddy' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Start Flask API
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', $apiBat) `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput (Join-Path $runtimeDir 'api.out.log') `
        -RedirectStandardError  (Join-Path $runtimeDir 'api.err.log') `
        -WindowStyle Hidden | Out-Null

    Start-Sleep -Seconds 3

    # Start Caddy
    $env:CADDY_ADMIN = '127.0.0.1:0'
    Start-Process -FilePath 'caddy' `
        -ArgumentList @('run', '--config', $caddyConfig, '--adapter', 'caddyfile') `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput (Join-Path $runtimeDir 'caddy.out.log') `
        -RedirectStandardError  (Join-Path $runtimeDir 'caddy.err.log') `
        -WindowStyle Hidden | Out-Null
    Remove-Item Env:\CADDY_ADMIN -ErrorAction SilentlyContinue

    # Start frpc if configured
    if ((Test-Path $frpcExe) -and (Test-Path $frpcConfig)) {
        $existingFrpc = Get-Process -Name 'frpc' -ErrorAction SilentlyContinue
        if (-not $existingFrpc) {
            Start-Process -FilePath $frpcExe `
                -ArgumentList @('-c', $frpcConfig) `
                -WorkingDirectory (Split-Path $frpcExe -Parent) `
                -RedirectStandardOutput (Join-Path $runtimeDir 'frpc.out.log') `
                -RedirectStandardError  (Join-Path $runtimeDir 'frpc.err.log') `
                -WindowStyle Hidden | Out-Null
        }
    }

    Start-Sleep -Seconds 5

    $ok = (Test-LocalUrl 'http://127.0.0.1:8080/api/health') -or (Test-LocalUrl 'http://127.0.0.1:5000/health')
    if (-not $ok) {
        throw 'Lightweight restart: health check failed after starting processes.'
    }
}

try {
    Write-WatchdogLog "Watchdog triggered. DelaySeconds=$DelaySeconds"

    if ($DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
    }

    Start-TrayHelper

    $healthy = (Test-LocalUrl 'http://127.0.0.1:8080/api/health') -or (Test-LocalUrl 'http://127.0.0.1:5000/health')
    if ($healthy) {
        Write-WatchdogLog 'Stack is already healthy. Nothing to do.'
        exit 0
    }

    Write-WatchdogLog 'Local stack is down. Launching preferred restart path.'

    # Try lightweight restart first (fast, no pip install)
    try {
        Write-WatchdogLog 'Trying lightweight runtime restart.'
        Start-RuntimeProcesses
        Write-WatchdogLog 'Watchdog completed successfully.'
        exit 0
    } catch {
        Write-WatchdogLog "Lightweight restart failed: $($_.Exception.Message). Falling back to full start-server.ps1."
    }

    # Fallback: full setup (installs dependencies)
    Write-WatchdogLog 'Launching start-server.ps1 -NoTunnel (full setup).'
    & $startScript -NoTunnel
    Write-WatchdogLog 'Watchdog completed successfully.'
} catch {
    Write-WatchdogLog "Watchdog failed: $($_.Exception.Message)"
    throw
}
