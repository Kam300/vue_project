<#
.SYNOPSIS
    Полный запуск сервера «Семейное Древо» на любом Windows ПК.
    Скрипт автоматически установит все зависимости и запустит все сервисы.

.DESCRIPTION
    Что делает скрипт:
    1. Проверяет и устанавливает: Node.js, Python, Caddy, Cloudflared (через winget)
    2. Устанавливает npm и pip зависимости
    3. Собирает Vue.js фронтенд
    4. Запускает Flask API (порт 5000)
    5. Запускает Caddy (порт 8080)
    6. Запускает Cloudflare Tunnel (totalcode.indevs.in)
    7. Проверяет работу всех сервисов

.USAGE
    1. Скопируйте папку проекта на другой ПК
    2. Откройте PowerShell от имени администратора (при первом запуске для установки)
    3. Выполните:
         Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
         .\start-server.ps1
    4. При повторном запуске права администратора НЕ нужны
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ========================================
# КОНФИГУРАЦИЯ
# ========================================
$repoRoot = $PSScriptRoot
if (-not $repoRoot) { $repoRoot = Get-Location }
Set-Location $repoRoot

$runtimeDir        = Join-Path $repoRoot '.runtime'
$pidsFile           = Join-Path $runtimeDir 'pids.json'
$cloudflaredConfig  = Join-Path $repoRoot 'infra\cloudflared\config.yml'
$cloudflaredExample = Join-Path $repoRoot 'infra\cloudflared\config.yml.example'
$backendDir         = Join-Path $repoRoot 'backend'
$backendEnvFile     = Join-Path $backendDir '.env'
$backendEnvExample  = Join-Path $backendDir '.env.example'
$venvDir            = Join-Path $backendDir '.venv'
$venvPython         = Join-Path $venvDir 'Scripts\python.exe'

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '║        Семейное Древо — FamilyOne Server         ║' -ForegroundColor Cyan
Write-Host '║          Автоматическая установка и запуск        ║' -ForegroundColor Cyan
Write-Host '╚══════════════════════════════════════════════════╝' -ForegroundColor Cyan
Write-Host ''

# ========================================
# УТИЛИТЫ
# ========================================

function Write-Step {
    param([string]$Message)
    Write-Host "  ▸ $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ⚠ $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  ✗ $Message" -ForegroundColor Red
}

function Write-Section {
    param([string]$Title)
    Write-Host ''
    Write-Host "━━━ $Title ━━━" -ForegroundColor Magenta
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-ToPath {
    param([string]$DirPath)
    if (-not (Test-Path $DirPath)) { return }
    $parts = $env:Path -split ';'
    if ($parts -contains $DirPath) { return }
    $env:Path = "$DirPath;$env:Path"
}

function Install-ViaWinget {
    param(
        [string]$PackageId,
        [string]$FriendlyName
    )

    if (-not (Test-CommandExists 'winget')) {
        Write-Fail "winget не найден. Установите $FriendlyName вручную и перезапустите скрипт."
        Write-Host "    Скачать: https://winget.run/$PackageId" -ForegroundColor Gray
        throw "Не удалось установить $FriendlyName — winget недоступен."
    }

    Write-Step "Устанавливаем $FriendlyName через winget..."
    winget install --id $PackageId --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Ошибка установки $FriendlyName. Установите вручную."
    }

    # Обновляем PATH для текущей сессии
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path    = "$machinePath;$userPath"

    Write-Ok "$FriendlyName установлен"
}

function Find-AndAddToPath {
    param(
        [string]$Name,
        [string[]]$CandidatePaths
    )

    if (Test-CommandExists $Name) { return $true }

    foreach ($candidate in $CandidatePaths) {
        if (Test-Path $candidate) {
            Add-ToPath (Split-Path $candidate -Parent)
            if (Test-CommandExists $Name) { return $true }
        }
    }

    return $false
}

function Resolve-PythonCommand {
    if (Test-CommandExists 'python') {
        try {
            & python --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return 'python'
            }
        } catch {}
    }

    if (Test-CommandExists 'py') {
        try {
            & py -3 --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return 'py'
            }
        } catch {}
    }

    return $null
}

function Wait-ForHttp {
    param(
        [string]$Url,
        [int]$MaxAttempts = 40,
        [int]$DelaySeconds = 1
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        } catch {}
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Start-BackgroundProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkDir,
        [string]$LogOut,
        [string]$LogErr
    )

    Write-Step "Запускаем $Name..."
    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkDir `
        -RedirectStandardOutput $LogOut `
        -RedirectStandardError $LogErr `
        -PassThru -WindowStyle Hidden

    Start-Sleep -Milliseconds 500
    if (-not $process -or $process.HasExited) {
        Write-Fail "$Name не запустился! Проверьте логи: $LogErr"
        throw "$Name failed to start."
    }

    Write-Ok "$Name запущен (PID: $($process.Id))"
    return $process
}

# ========================================
# ШАГ 1: ОСТАНОВКА ПРЕДЫДУЩИХ ПРОЦЕССОВ
# ========================================

Write-Section 'Шаг 1/7 — Остановка предыдущих процессов'

$stopScript = Join-Path $repoRoot 'scripts\stop-all.ps1'
if (Test-Path $pidsFile) {
    try {
        $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
        foreach ($proc in $pids.processes) {
            try {
                $p = Get-Process -Id $proc.pid -ErrorAction SilentlyContinue
                if ($p) {
                    Stop-Process -Id $proc.pid -Force -ErrorAction SilentlyContinue
                    Write-Ok "Остановлен $($proc.name) (PID $($proc.pid))"
                }
            } catch {}
        }
        Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Warn 'Не удалось прочитать pids.json, пропускаем'
    }
} else {
    Write-Ok 'Нет запущенных процессов'
}

# ========================================
# ШАГ 2: ПРОВЕРКА И УСТАНОВКА ЗАВИСИМОСТЕЙ
# ========================================

Write-Section 'Шаг 2/7 — Проверка зависимостей'

# -- Node.js --
$nodeFound = Find-AndAddToPath 'node' @(
    'C:\Program Files\nodejs\node.exe',
    "$env:LOCALAPPDATA\Programs\nodejs\node.exe"
)
if (-not $nodeFound) {
    Write-Warn 'Node.js не найден, устанавливаем...'
    Install-ViaWinget 'OpenJS.NodeJS.LTS' 'Node.js'
    if (-not (Test-CommandExists 'node')) {
        throw 'Node.js не найден после установки. Перезапустите терминал и скрипт.'
    }
}
$nodeVersion = & node --version
Write-Ok "Node.js $nodeVersion"

# -- npm --
Find-AndAddToPath 'npm' @(
    'C:\Program Files\nodejs\npm.cmd',
    "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd"
) | Out-Null
if (-not (Test-CommandExists 'npm')) {
    throw 'npm не найден. Переустановите Node.js.'
}
Write-Ok "npm найден"

# -- Python --
$pythonCmd = Resolve-PythonCommand
if (-not $pythonCmd) {
    Write-Warn 'Python не найден, устанавливаем...'
    Install-ViaWinget 'Python.Python.3.11' 'Python 3.11'
    $pythonCmd = Resolve-PythonCommand
    if (-not $pythonCmd) {
        throw 'Python не найден после установки. Перезапустите терминал и скрипт.'
    }
}
$pyVersionArgs = if ($pythonCmd -eq 'py') { @('-3', '--version') } else { @('--version') }
$pyVersion = & $pythonCmd @pyVersionArgs 2>&1
Write-Ok "$pyVersion"

# -- Caddy --
$caddyPaths = @('C:\Program Files\Caddy\caddy.exe')
$wingetCaddy = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -Filter 'CaddyServer.Caddy_*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($wingetCaddy) {
    $wingetCaddyExe = Get-ChildItem -Path $wingetCaddy.FullName -Filter 'caddy.exe' -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($wingetCaddyExe) { $caddyPaths += $wingetCaddyExe.FullName }
}
$caddyFound = Find-AndAddToPath 'caddy' $caddyPaths
if (-not $caddyFound) {
    Write-Warn 'Caddy не найден, устанавливаем...'
    Install-ViaWinget 'CaddyServer.Caddy' 'Caddy Server'
    if (-not (Test-CommandExists 'caddy')) {
        throw 'Caddy не найден после установки. Перезапустите терминал и скрипт.'
    }
}
Write-Ok 'Caddy найден'

# -- cloudflared --
if (-not (Test-CommandExists 'cloudflared')) {
    Write-Warn 'cloudflared не найден, устанавливаем...'
    Install-ViaWinget 'Cloudflare.cloudflared' 'Cloudflare Tunnel'
    if (-not (Test-CommandExists 'cloudflared')) {
        throw 'cloudflared не найден после установки. Перезапустите терминал и скрипт.'
    }
}
Write-Ok 'cloudflared найден'

# ========================================
# ШАГ 3: НАСТРОЙКА CLOUDFLARE TUNNEL
# ========================================

Write-Section 'Шаг 3/7 — Настройка Cloudflare Tunnel'

if (-not (Test-Path $cloudflaredConfig)) {
    Write-Warn "Конфигурация Cloudflare Tunnel не найдена."
    Write-Host ''
    Write-Host '  Для настройки выполните эти команды в ОТДЕЛЬНОМ терминале:' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '    cloudflared tunnel login' -ForegroundColor White
    Write-Host '    cloudflared tunnel create family-tree-server' -ForegroundColor White
    Write-Host '    cloudflared tunnel route dns family-tree-server totalcode.indevs.in' -ForegroundColor White
    Write-Host ''
    Write-Host "  Затем скопируйте $cloudflaredExample" -ForegroundColor Gray
    Write-Host "  в $cloudflaredConfig" -ForegroundColor Gray
    Write-Host '  и заполните tunnel ID и путь к credentials.' -ForegroundColor Gray
    Write-Host ''

    $skipTunnel = Read-Host '  Запустить сервер БЕЗ Cloudflare Tunnel? (y/n)'
    if ($skipTunnel -ne 'y' -and $skipTunnel -ne 'Y') {
        throw 'Настройте Cloudflare Tunnel и перезапустите скрипт.'
    }
    $noTunnel = $true
} else {
    $noTunnel = $false
    Write-Ok "Конфигурация найдена: $cloudflaredConfig"
}

# ========================================
# ШАГ 4: BACKEND — PYTHON VENV + ЗАВИСИМОСТИ
# ========================================

Write-Section 'Шаг 4/7 — Установка Python зависимостей'

if (-not (Test-Path $backendEnvFile)) {
    Copy-Item -Path $backendEnvExample -Destination $backendEnvFile
    Write-Ok 'Создан backend/.env из .env.example'
}

$pyPrefix = if ($pythonCmd -eq 'py') { @('-3') } else { @() }

if (-not (Test-Path $venvPython)) {
    Write-Step 'Создаём виртуальное окружение Python...'
    & $pythonCmd @pyPrefix -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка создания venv.' }
    Write-Ok 'venv создан'
}

Write-Step 'Обновляем pip...'
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw 'Ошибка обновления pip.' }

Write-Step 'Устанавливаем Python зависимости...'
& $venvPython -m pip install -r (Join-Path $backendDir 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'Ошибка pip install.' }

# Установка face-recognition на Windows без сборки dlib из исходников
$isWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)
if ($isWindows) {
    & $venvPython -m pip install --no-deps face-recognition==1.3.0 --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки face-recognition.' }
}

Write-Step 'Проверяем face_recognition...'
& $venvPython -c "import face_recognition, dlib; print('  face_recognition + dlib OK')"
if ($LASTEXITCODE -ne 0) { throw 'Не удалось импортировать face_recognition/dlib.' }
Write-Ok 'Backend зависимости установлены'

# ========================================
# ШАГ 5: FRONTEND — NPM + BUILD
# ========================================

Write-Section 'Шаг 5/7 — Сборка фронтенда'

Write-Step 'Устанавливаем npm зависимости...'
npm install --silent 2>$null
if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
Write-Ok 'npm зависимости установлены'

Write-Step 'Собираем фронтенд (npm run build)...'
npm run build 2>$null
if ($LASTEXITCODE -ne 0) { throw 'npm run build failed.' }
Write-Ok 'Фронтенд собран → dist/'

# ========================================
# ШАГ 6: ЗАПУСК СЕРВИСОВ
# ========================================

Write-Section 'Шаг 6/7 — Запуск сервисов'

$apiOut   = Join-Path $runtimeDir 'api.out.log'
$apiErr   = Join-Path $runtimeDir 'api.err.log'
$caddyOut = Join-Path $runtimeDir 'caddy.out.log'
$caddyErr = Join-Path $runtimeDir 'caddy.err.log'
$cloudOut = Join-Path $runtimeDir 'cloudflared.out.log'
$cloudErr = Join-Path $runtimeDir 'cloudflared.err.log'

# API
$apiProcess = Start-BackgroundProcess -Name 'Flask API' `
    -FilePath $venvPython `
    -Arguments @('telegram_service.py') `
    -WorkDir $backendDir `
    -LogOut $apiOut -LogErr $apiErr

# Caddy
$caddyConfigPath = Join-Path $repoRoot 'infra\Caddyfile'
$caddyProcess = Start-BackgroundProcess -Name 'Caddy' `
    -FilePath 'caddy' `
    -Arguments @('run', '--config', $caddyConfigPath, '--adapter', 'caddyfile') `
    -WorkDir $repoRoot `
    -LogOut $caddyOut -LogErr $caddyErr

# Cloudflared (если настроен)
$cloudflaredProcess = $null
if (-not $noTunnel) {
    $cloudflaredProcess = Start-BackgroundProcess -Name 'Cloudflare Tunnel' `
        -FilePath 'cloudflared' `
        -Arguments @('tunnel', '--protocol', 'http2', '--config', $cloudflaredConfig, 'run') `
        -WorkDir $repoRoot `
        -LogOut $cloudOut -LogErr $cloudErr
}

# Сохраняем PID-ы
$processes = @(
    [ordered]@{ name = 'api'; pid = $apiProcess.Id; stdout = $apiOut; stderr = $apiErr }
    [ordered]@{ name = 'caddy'; pid = $caddyProcess.Id; stdout = $caddyOut; stderr = $caddyErr }
)
if ($cloudflaredProcess) {
    $processes += [ordered]@{ name = 'cloudflared'; pid = $cloudflaredProcess.Id; stdout = $cloudOut; stderr = $cloudErr }
}
$pidPayload = [ordered]@{
    started_at = (Get-Date).ToString('o')
    processes = $processes
}
$pidPayload | ConvertTo-Json -Depth 6 | Set-Content -Path $pidsFile -Encoding UTF8

# ========================================
# ШАГ 7: ПРОВЕРКА РАБОТЫ
# ========================================

Write-Section 'Шаг 7/7 — Проверка работы'

Write-Step 'Ожидаем API сервер...'
if (-not (Wait-ForHttp 'http://127.0.0.1:5000/health' 50 1)) {
    Write-Fail 'API сервер не отвечает!'
    Write-Host "  Логи: $apiErr" -ForegroundColor Gray
    throw 'API health check failed.'
}
Write-Ok 'API сервер — OK'

Write-Step 'Ожидаем Caddy...'
if (-not (Wait-ForHttp 'http://127.0.0.1:8080/' 30 1)) {
    Write-Fail 'Caddy не отвечает!'
    throw 'Caddy check failed.'
}
Write-Ok 'Caddy — OK'

Write-Step 'Проверяем маршрутизацию API...'
if (-not (Wait-ForHttp 'http://127.0.0.1:8080/api/health' 20 1)) {
    Write-Fail 'API маршрутизация через Caddy не работает!'
    throw 'Caddy API routing check failed.'
}
Write-Ok 'API маршрутизация — OK'

if (-not $noTunnel) {
    Write-Step 'Проверяем Cloudflare Tunnel...'
    $externalUrls = @(
        'https://totalcode.indevs.in/',
        'https://totalcode.indevs.in/api/health'
    )
    foreach ($url in $externalUrls) {
        if (Wait-ForHttp $url 5 2) {
            Write-Ok $url
        } else {
            Write-Warn "$url — не отвечает (может потребоваться время)"
        }
    }
}

# ========================================
# ГОТОВО!
# ========================================

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '║             ✓ Сервер запущен успешно!            ║' -ForegroundColor Green
Write-Host '╚══════════════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
Write-Host "  Локальный сайт:    http://127.0.0.1:8080" -ForegroundColor White
Write-Host "  Локальный API:     http://127.0.0.1:5000/health" -ForegroundColor White
if (-not $noTunnel) {
    Write-Host "  Внешний сайт:      https://totalcode.indevs.in" -ForegroundColor Cyan
    Write-Host "  Внешний API:       https://totalcode.indevs.in/api/health" -ForegroundColor Cyan
}
Write-Host ''
Write-Host "  PID файл:          $pidsFile" -ForegroundColor Gray
Write-Host "  Логи:              $runtimeDir" -ForegroundColor Gray
Write-Host ''
Write-Host "  API:          PID $($apiProcess.Id)" -ForegroundColor Gray
Write-Host "  Caddy:        PID $($caddyProcess.Id)" -ForegroundColor Gray
if ($cloudflaredProcess) {
    Write-Host "  Cloudflared:  PID $($cloudflaredProcess.Id)" -ForegroundColor Gray
}
Write-Host ''
Write-Host '  Для остановки: .\scripts\stop-all.ps1' -ForegroundColor DarkGray
Write-Host '  Или просто закройте терминал.' -ForegroundColor DarkGray
Write-Host ''
