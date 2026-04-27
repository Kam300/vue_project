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

    Write-WatchdogLog 'Local stack is down. Launching start-server.ps1 -NoTunnel.'
    & $startScript -NoTunnel
    Write-WatchdogLog 'Watchdog completed successfully.'
} catch {
    Write-WatchdogLog "Watchdog failed: $($_.Exception.Message)"
    throw
}
