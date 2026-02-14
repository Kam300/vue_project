<#
.SYNOPSIS
    Stop all Family Tree services
#>

$repoRoot = $PSScriptRoot
if (-not $repoRoot) { $repoRoot = Get-Location }

$pidsFile = Join-Path $repoRoot '.runtime\pids.json'

Write-Host ''
Write-Host '  Stopping services...' -ForegroundColor Yellow

if (Test-Path $pidsFile) {
    $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
    foreach ($proc in $pids.processes) {
        try {
            $p = Get-Process -Id $proc.pid -ErrorAction SilentlyContinue
            if ($p) {
                Stop-Process -Id $proc.pid -Force
                Write-Host "  OK: Stopped $($proc.name) (PID $($proc.pid))" -ForegroundColor Green
            } else {
                Write-Host "  -  $($proc.name) (PID $($proc.pid)) already stopped" -ForegroundColor Gray
            }
        } catch {
            Write-Host "  WARN: Could not stop $($proc.name) (PID $($proc.pid))" -ForegroundColor DarkYellow
        }
    }
    Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host '  All services stopped.' -ForegroundColor Green
} else {
    Write-Host '  No running services found (pids.json not found)' -ForegroundColor Gray
}
Write-Host ''
