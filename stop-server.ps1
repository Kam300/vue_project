<#
.SYNOPSIS
    Остановка всех сервисов «Семейное Древо»
#>

$repoRoot = $PSScriptRoot
if (-not $repoRoot) { $repoRoot = (Get-Location).ToString().Replace('\scripts', '') }

# Попробовать найти pids.json в нескольких местах
$pidsFile = Join-Path $repoRoot '.runtime\pids.json'
if (-not (Test-Path $pidsFile)) {
    $pidsFile = Join-Path (Join-Path $repoRoot '..') '.runtime\pids.json'
}

Write-Host ''
Write-Host '  Остановка сервисов...' -ForegroundColor Yellow

if (Test-Path $pidsFile) {
    $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
    foreach ($proc in $pids.processes) {
        try {
            $p = Get-Process -Id $proc.pid -ErrorAction SilentlyContinue
            if ($p) {
                Stop-Process -Id $proc.pid -Force
                Write-Host "  ✓ Остановлен $($proc.name) (PID $($proc.pid))" -ForegroundColor Green
            } else {
                Write-Host "  - $($proc.name) (PID $($proc.pid)) уже остановлен" -ForegroundColor Gray
            }
        } catch {
            Write-Host "  ⚠ Не удалось остановить $($proc.name) (PID $($proc.pid))" -ForegroundColor DarkYellow
        }
    }
    Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host '  ✓ Все сервисы остановлены' -ForegroundColor Green
} else {
    Write-Host '  Нет запущенных сервисов (pids.json не найден)' -ForegroundColor Gray
}
Write-Host ''
