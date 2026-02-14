$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$runtimeDir = Join-Path $repoRoot '.runtime'
$pidsFile = Join-Path $runtimeDir 'pids.json'

if (-not (Test-Path $pidsFile)) {
    Write-Host 'No managed processes found (.runtime/pids.json is missing).'
    exit 0
}

try {
    $payload = Get-Content -Path $pidsFile -Raw | ConvertFrom-Json
} catch {
    throw "Failed to parse PID file: $pidsFile"
}

$processes = @($payload.processes)
if ($processes.Count -eq 0) {
    Remove-Item -Path $pidsFile -Force -ErrorAction SilentlyContinue
    Write-Host 'PID file was empty. Nothing to stop.'
    exit 0
}

foreach ($processInfo in $processes) {
    $name = [string]$processInfo.name
    $processId = [int]$processInfo.pid

    if ($processId -le 0) {
        continue
    }

    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Write-Host "$name (PID $processId) is not running."
        continue
    }

    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped $name (PID $processId)."
    } catch {
        Write-Warning "Failed to stop $name (PID $processId): $($_.Exception.Message)"
    }
}

Remove-Item -Path $pidsFile -Force -ErrorAction SilentlyContinue
Write-Host 'Done. PID file removed.'
