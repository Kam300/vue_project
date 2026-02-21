<#
.SYNOPSIS
    Full server launch for "Family Tree" on any Windows PC.
    Auto-installs all dependencies and starts all services.

.USAGE
    1. Copy the project folder to another PC
    2. Open PowerShell as Administrator (first run only, for installing tools)
    3. Run:
         Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
         .\start-server.ps1
    4. Subsequent runs do NOT require admin rights
#>

param(
    [switch]$NoTunnel
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ========================================
# CONFIGURATION
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
$frpcExePath        = 'C:\frp\frpc.exe'
$frpcConfigPath     = 'C:\frp\frpc.toml'

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

Write-Host ''
Write-Host '========================================================' -ForegroundColor Cyan
Write-Host '        Family Tree Server - Auto Setup & Launch         ' -ForegroundColor Cyan
Write-Host '========================================================' -ForegroundColor Cyan
Write-Host ''

# ========================================
# UTILITIES
# ========================================

function Write-Step {
    param([string]$Message)
    Write-Host "  > $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK: $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  WARN: $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  FAIL: $Message" -ForegroundColor Red
}

function Write-Section {
    param([string]$Title)
    Write-Host ''
    Write-Host "--- $Title ---" -ForegroundColor Magenta
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
        Write-Fail "winget not found. Install $FriendlyName manually and re-run."
        throw "Cannot install $FriendlyName - winget unavailable."
    }

    Write-Step "Installing $FriendlyName via winget..."
    winget install --id $PackageId --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install $FriendlyName. Install manually."
    }

    # Refresh PATH for current session
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path    = "$machinePath;$userPath"

    Write-Ok "$FriendlyName installed"
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

function Get-EnvValue {
    param(
        [string]$FilePath,
        [string]$Name,
        [string]$DefaultValue = ''
    )

    if (-not (Test-Path $FilePath)) {
        return $DefaultValue
    }

    $raw = Get-Content $FilePath -ErrorAction SilentlyContinue
    foreach ($line in $raw) {
        if (-not $line) { continue }
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('#')) { continue }
        if ($trimmed -notmatch '=') { continue }

        $pair = $trimmed.Split('=', 2)
        $key = $pair[0].Trim()
        if ($key -ne $Name) { continue }

        $value = $pair[1].Trim().Trim('"').Trim("'")
        if ($value) { return $value }
    }

    return $DefaultValue
}

function Normalize-Origin {
    param([string]$Value, [string]$DefaultValue)
    $candidate = ''
    if ($null -ne $Value) {
        $candidate = [string]$Value
    }
    $candidate = $candidate.Trim()
    if (-not $candidate) { $candidate = $DefaultValue }
    return $candidate.TrimEnd('/')
}

function Get-OriginHost {
    param([string]$Origin, [string]$FallbackHost)
    try {
        $uri = [uri]$Origin
        if ($uri.Host) { return $uri.Host }
    } catch {}
    return $FallbackHost
}

function Convert-EnvBoolean {
    param([string]$Value)
    if (-not $Value) { return $null }

    $normalized = $Value.Trim().ToLowerInvariant()
    switch ($normalized) {
        '1' { return $true }
        'true' { return $true }
        'yes' { return $true }
        'y' { return $true }
        'on' { return $true }
        '0' { return $false }
        'false' { return $false }
        'no' { return $false }
        'n' { return $false }
        'off' { return $false }
        default { return $null }
    }
}

function Test-PythonModule {
    param(
        [string]$PythonExe,
        [string]$ModuleName
    )

    try {
        & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Start-BackgroundProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkDir,
        [string]$LogOut,
        [string]$LogErr,
        [int]$WaitMs = 1000
    )

    Write-Step "Starting $Name..."
    $process = Start-Process -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkDir `
        -RedirectStandardOutput $LogOut `
        -RedirectStandardError $LogErr `
        -PassThru -WindowStyle Hidden

    Start-Sleep -Milliseconds $WaitMs
    if (-not $process -or $process.HasExited) {
        Write-Fail "$Name failed to start!"
        Write-Host ''
        Write-Host '  --- ERROR LOG ---' -ForegroundColor Red
        if (Test-Path $LogErr) {
            $errContent = Get-Content $LogErr -Raw -ErrorAction SilentlyContinue
            if ($errContent) {
                Write-Host $errContent -ForegroundColor Gray
            }
        }
        if (Test-Path $LogOut) {
            $outContent = Get-Content $LogOut -Raw -ErrorAction SilentlyContinue
            if ($outContent) {
                Write-Host $outContent -ForegroundColor Gray
            }
        }
        Write-Host '  --- END LOG ---' -ForegroundColor Red
        Write-Host ''
        throw "$Name failed to start."
    }

    Write-Ok "$Name running (PID: $($process.Id))"
    return $process
}

$defaultPublicOrigin = 'https://totalcode.indevs.in'
$publicOrigin = Normalize-Origin (Get-EnvValue -FilePath $backendEnvFile -Name 'PUBLIC_ORIGIN' -DefaultValue $defaultPublicOrigin) $defaultPublicOrigin
$publicHost = Get-OriginHost -Origin $publicOrigin -FallbackHost 'totalcode.indevs.in'
$useCloudflaredRaw = Get-EnvValue -FilePath $backendEnvFile -Name 'USE_CLOUDFLARED' -DefaultValue ''
$useCloudflared = Convert-EnvBoolean -Value $useCloudflaredRaw
if ($NoTunnel) {
    $useCloudflared = $false
}
$requestedTunnel = ($useCloudflared -eq $true)
$requestedNoTunnel = ($useCloudflared -eq $false)
$externalRootUrl = "$publicOrigin/"
$externalApiHealthUrl = "$publicOrigin/api/health"

# ========================================
# STEP 1: STOP PREVIOUS PROCESSES
# ========================================

Write-Section 'Step 1/7 - Stopping previous processes'

if (Test-Path $pidsFile) {
    try {
        $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
        foreach ($proc in $pids.processes) {
            try {
                $p = Get-Process -Id $proc.pid -ErrorAction SilentlyContinue
                if ($p) {
                    Stop-Process -Id $proc.pid -Force -ErrorAction SilentlyContinue
                    Write-Ok "Stopped $($proc.name) (PID $($proc.pid))"
                }
            } catch {}
        }
        Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Warn 'Could not read pids.json, skipping'
    }
} else {
    Write-Ok 'No previous processes found'
}

# Убиваем все оставшиеся Python-процессы (чтобы не было зомби со старым кодом)
$pythonProcs = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcs) {
    $pythonProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "Stopped $(@($pythonProcs).Count) stale Python process(es)"
    Start-Sleep -Seconds 2
}

# Stop orphaned Caddy processes that can keep admin port 2019 busy.
$caddyProcs = Get-Process caddy -ErrorAction SilentlyContinue
if ($caddyProcs) {
    $caddyProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "Stopped $(@($caddyProcs).Count) stale Caddy process(es)"
    Start-Sleep -Seconds 1
}

# Stop stale frpc instances to avoid duplicate proxy registration errors.
$frpcProcs = Get-Process frpc -ErrorAction SilentlyContinue
if ($frpcProcs) {
    $frpcProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "Stopped $(@($frpcProcs).Count) stale frpc process(es)"
    Start-Sleep -Seconds 1
}

# ========================================
# STEP 2: CHECK & INSTALL DEPENDENCIES
# ========================================

Write-Section 'Step 2/7 - Checking dependencies'

# -- Node.js --
$nodeFound = Find-AndAddToPath 'node' @(
    'C:\Program Files\nodejs\node.exe',
    "$env:LOCALAPPDATA\Programs\nodejs\node.exe"
)
if (-not $nodeFound) {
    Write-Warn 'Node.js not found, installing...'
    Install-ViaWinget 'OpenJS.NodeJS.LTS' 'Node.js'
    if (-not (Test-CommandExists 'node')) {
        throw 'Node.js not found after install. Restart terminal and re-run.'
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
    throw 'npm not found. Reinstall Node.js.'
}
Write-Ok 'npm found'

# -- Python --
$pythonCmd = Resolve-PythonCommand
if (-not $pythonCmd) {
    Write-Warn 'Python not found, installing...'
    Install-ViaWinget 'Python.Python.3.11' 'Python 3.11'
    $pythonCmd = Resolve-PythonCommand
    if (-not $pythonCmd) {
        throw 'Python not found after install. Restart terminal and re-run.'
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
    Write-Warn 'Caddy not found, installing...'
    Install-ViaWinget 'CaddyServer.Caddy' 'Caddy Server'
    if (-not (Test-CommandExists 'caddy')) {
        throw 'Caddy not found after install. Restart terminal and re-run.'
    }
}
Write-Ok 'Caddy found'

# -- cloudflared --
if ($requestedNoTunnel) {
    Write-Ok 'cloudflared skipped (disabled by -NoTunnel or USE_CLOUDFLARED=false)'
} else {
    if (-not (Test-CommandExists 'cloudflared')) {
        Write-Warn 'cloudflared not found, installing...'
        Install-ViaWinget 'Cloudflare.cloudflared' 'Cloudflare Tunnel'
        if (-not (Test-CommandExists 'cloudflared')) {
            throw 'cloudflared not found after install. Restart terminal and re-run.'
        }
    }
    Write-Ok 'cloudflared found'
}

# ========================================
# STEP 3: CLOUDFLARE TUNNEL CONFIG
# ========================================

Write-Section 'Step 3/7 - Cloudflare Tunnel config'

if ($requestedNoTunnel) {
    $noTunnel = $true
    Write-Ok 'Cloudflare Tunnel disabled explicitly'
} elseif (-not (Test-Path $cloudflaredConfig)) {
    if ($requestedTunnel) {
        Write-Fail "Cloudflare Tunnel requested but config missing: $cloudflaredConfig"
        Write-Host ''
        Write-Host '  To set up the tunnel, run these commands in a SEPARATE terminal:' -ForegroundColor Cyan
        Write-Host ''
        Write-Host '    cloudflared tunnel login' -ForegroundColor White
        Write-Host '    cloudflared tunnel create family-tree-server' -ForegroundColor White
        Write-Host "    cloudflared tunnel route dns family-tree-server $publicHost" -ForegroundColor White
        Write-Host ''
        Write-Host "  Then copy: $cloudflaredExample" -ForegroundColor Gray
        Write-Host "  to:        $cloudflaredConfig" -ForegroundColor Gray
        Write-Host '  and fill in tunnel ID + credentials path.' -ForegroundColor Gray
        Write-Host ''
        throw 'Cloudflare Tunnel is enabled but config file is missing.'
    }

    $noTunnel = $true
    Write-Warn "Cloudflare config not found, starting without tunnel: $cloudflaredConfig"
} else {
    $noTunnel = $false
    Write-Ok "Config found: $cloudflaredConfig"
}

# ========================================
# STEP 4: PYTHON VENV + DEPENDENCIES
# ========================================

Write-Section 'Step 4/7 - Python dependencies'

if (-not (Test-Path $backendEnvFile)) {
    if (Test-Path $backendEnvExample) {
        Copy-Item -Path $backendEnvExample -Destination $backendEnvFile
        Write-Ok 'Created backend/.env from .env.example'
    }
}

$pyPrefix = if ($pythonCmd -eq 'py') { @('-3') } else { @() }

if (-not (Test-Path $venvPython)) {
    Write-Step 'Creating Python virtual environment...'
    & $pythonCmd @pyPrefix -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create venv.' }
    Write-Ok 'venv created'
}

Write-Step 'Upgrading pip...'
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }

Write-Step 'Installing Python packages...'
& $venvPython -m pip install -r (Join-Path $backendDir 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

# face-recognition on Windows (pre-built dlib + models)
$isWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)

# Install dlib first
if ($isWindows) {
    Write-Step 'Installing dlib-bin...'
    try {
        & $venvPython -m pip install dlib-bin --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "dlib-bin install returned code $LASTEXITCODE. Continuing anyway."
        }
    } catch {
        Write-Warn "dlib-bin install warning: $($_.Exception.Message)"
    }
}

# Check if face_recognition_models is installed
$modelsInstalled = Test-PythonModule -PythonExe $venvPython -ModuleName 'face_recognition_models'
if (-not $modelsInstalled) {
    Write-Step 'face_recognition_models NOT installed. Installing from git...'
    & $venvPython -m pip install --force-reinstall "git+https://github.com/ageitgey/face_recognition_models" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'git install failed. Trying without --force-reinstall...'
        & $venvPython -m pip install "git+https://github.com/ageitgey/face_recognition_models" 2>&1
    }
    # Verify it installed
    $modelsInstalled = Test-PythonModule -PythonExe $venvPython -ModuleName 'face_recognition_models'
    if (-not $modelsInstalled) {
        Write-Fail 'face_recognition_models still not installed!'
        Write-Host '  Run this manually:' -ForegroundColor Gray
        Write-Host "  $venvPython -m pip install git+https://github.com/ageitgey/face_recognition_models" -ForegroundColor White
    } else {
        Write-Ok 'face_recognition_models installed'
    }
} else {
    Write-Ok 'face_recognition_models already installed'
}

# Install face_recognition itself
Write-Step 'Installing face_recognition...'
& $venvPython -m pip install --no-deps face-recognition==1.3.0 --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warn "face_recognition install returned code $LASTEXITCODE."
}

# Deep check: actually trigger models loading
Write-Step 'Checking full import chain...'
& $venvPython -c "from face_recognition.api import face_encodings; print('    ALL OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Fail 'face_recognition deep check failed!'
    Write-Host '  Diagnostics:' -ForegroundColor Gray
    $hasModels = Test-PythonModule -PythonExe $venvPython -ModuleName 'face_recognition_models'
    $hasFace = Test-PythonModule -PythonExe $venvPython -ModuleName 'face_recognition'
    $hasDlib = Test-PythonModule -PythonExe $venvPython -ModuleName 'dlib'
    Write-Host "    face_recognition_models: $hasModels" -ForegroundColor Gray
    Write-Host "    face_recognition:        $hasFace" -ForegroundColor Gray
    Write-Host "    dlib:                    $hasDlib" -ForegroundColor Gray
    Write-Host ''
    Write-Host '  Server will try to start but may fail.' -ForegroundColor DarkYellow
} else {
    Write-Ok 'face_recognition fully working'
}
Write-Ok 'Backend dependencies ready'

# ========================================
# STEP 5: FRONTEND BUILD
# ========================================

Write-Section 'Step 5/7 - Building frontend'

Write-Step 'npm install...'
npm install --silent 2>$null
if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
Write-Ok 'npm packages installed'

Write-Step 'npm run build...'
npm run build 2>$null
if ($LASTEXITCODE -ne 0) { throw 'npm run build failed.' }
Write-Ok 'Frontend built -> dist/'

# ========================================
# STEP 6: START SERVICES
# ========================================

Write-Section 'Step 6/7 - Starting services'

$apiOut   = Join-Path $runtimeDir 'api.out.log'
$apiErr   = Join-Path $runtimeDir 'api.err.log'
$caddyOut = Join-Path $runtimeDir 'caddy.out.log'
$caddyErr = Join-Path $runtimeDir 'caddy.err.log'
$frpcOut  = Join-Path $runtimeDir 'frpc.out.log'
$frpcErr  = Join-Path $runtimeDir 'frpc.err.log'
$cloudOut = Join-Path $runtimeDir 'cloudflared.out.log'
$cloudErr = Join-Path $runtimeDir 'cloudflared.err.log'

# API (use batch wrapper to activate venv properly)
$apiBat = Join-Path $backendDir 'run-api.bat'
$apiProcess = Start-BackgroundProcess -Name 'Flask API' `
    -FilePath 'cmd.exe' `
    -Arguments @('/c', $apiBat) `
    -WorkDir $backendDir `
    -LogOut $apiOut -LogErr $apiErr `
    -WaitMs 3000

# Caddy
$caddyConfigPath = Join-Path $repoRoot 'infra\Caddyfile'
$hadCaddyAdminEnv = Test-Path Env:\CADDY_ADMIN
$prevCaddyAdminEnv = $null
if ($hadCaddyAdminEnv) {
    $prevCaddyAdminEnv = $env:CADDY_ADMIN
}
# Some Caddy builds on Windows don't accept "off" from env var and fail with
# "lookup off: no such host". Use an ephemeral localhost admin listener instead.
$env:CADDY_ADMIN = '127.0.0.1:0'
try {
    $caddyProcess = Start-BackgroundProcess -Name 'Caddy' `
        -FilePath 'caddy' `
        -Arguments @('run', '--config', $caddyConfigPath, '--adapter', 'caddyfile') `
        -WorkDir $repoRoot `
        -LogOut $caddyOut -LogErr $caddyErr
} finally {
    if ($hadCaddyAdminEnv) {
        $env:CADDY_ADMIN = $prevCaddyAdminEnv
    } else {
        Remove-Item Env:\CADDY_ADMIN -ErrorAction SilentlyContinue
    }
}

# FRP client for no-tunnel mode (public domain via VPS frps)
$frpcProcess = $null
if ($noTunnel) {
    if ((Test-Path $frpcExePath) -and (Test-Path $frpcConfigPath)) {
        $existingFrpc = Get-Process frpc -ErrorAction SilentlyContinue
        if ($existingFrpc) {
            $existingCount = @($existingFrpc).Count
            $selected = @($existingFrpc)[0]
            if ($existingCount -gt 1) {
                Write-Warn "Detected $existingCount running frpc processes; using existing PID $($selected.Id)"
            } else {
                Write-Ok "frpc already running (PID: $($selected.Id)), skipping extra start"
            }
            $frpcProcess = $selected
        } else {
            $frpcProcess = Start-BackgroundProcess -Name 'frpc' `
                -FilePath $frpcExePath `
                -Arguments @('-c', $frpcConfigPath) `
                -WorkDir (Split-Path $frpcExePath -Parent) `
                -LogOut $frpcOut -LogErr $frpcErr
        }
    } else {
        Write-Warn "frpc is not configured. Expected files: $frpcExePath and $frpcConfigPath"
        Write-Warn "Run scripts/setup-frpc.ps1 to enable public domain via FRP."
    }
}

# Cloudflared (if configured)
$cloudflaredProcess = $null
if (-not $noTunnel) {
    $cloudflaredProcess = Start-BackgroundProcess -Name 'Cloudflare Tunnel' `
        -FilePath 'cloudflared' `
        -Arguments @('tunnel', '--protocol', 'http2', '--config', $cloudflaredConfig, 'run') `
        -WorkDir $repoRoot `
        -LogOut $cloudOut -LogErr $cloudErr
}

# Save PIDs
$processes = @(
    [ordered]@{ name = 'api'; pid = $apiProcess.Id; stdout = $apiOut; stderr = $apiErr }
    [ordered]@{ name = 'caddy'; pid = $caddyProcess.Id; stdout = $caddyOut; stderr = $caddyErr }
)
if ($frpcProcess) {
    $processes += [ordered]@{ name = 'frpc'; pid = $frpcProcess.Id; stdout = $frpcOut; stderr = $frpcErr }
}
if ($cloudflaredProcess) {
    $processes += [ordered]@{ name = 'cloudflared'; pid = $cloudflaredProcess.Id; stdout = $cloudOut; stderr = $cloudErr }
}
$pidPayload = [ordered]@{
    started_at = (Get-Date).ToString('o')
    processes = $processes
}
$pidPayload | ConvertTo-Json -Depth 6 | Set-Content -Path $pidsFile -Encoding UTF8

# ========================================
# STEP 7: HEALTH CHECKS
# ========================================

Write-Section 'Step 7/7 - Health checks'

Write-Step 'Waiting for API server...'
if (-not (Wait-ForHttp 'http://127.0.0.1:5000/health' 50 1)) {
    Write-Fail 'API server not responding!'
    Write-Host "  Logs: $apiErr" -ForegroundColor Gray
    throw 'API health check failed.'
}
Write-Ok 'API server - OK'

Write-Step 'Waiting for Caddy...'
if (-not (Wait-ForHttp 'http://127.0.0.1:8080/' 30 1)) {
    Write-Fail 'Caddy not responding!'
    throw 'Caddy check failed.'
}
Write-Ok 'Caddy - OK'

Write-Step 'Checking API routing through Caddy...'
if (-not (Wait-ForHttp 'http://127.0.0.1:8080/api/health' 20 1)) {
    Write-Fail 'API routing through Caddy not working!'
    throw 'Caddy API routing check failed.'
}
Write-Ok 'API routing - OK'

if ($frpcProcess) {
    Write-Step 'Checking frpc connection...'
    $frpcConnected = $false
    for ($i = 1; $i -le 12; $i++) {
        $conn = Get-NetTCPConnection -OwningProcess $frpcProcess.Id -State Established -ErrorAction SilentlyContinue |
            Where-Object { $_.RemotePort -eq 7000 } |
            Select-Object -First 1
        if ($conn) {
            $frpcConnected = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if ($frpcConnected) {
        Write-Ok 'frpc connected to FRP server'
    } else {
        Write-Warn 'frpc started but did not establish connection to FRP server yet'
        Write-Warn "Check log: $frpcErr"
    }
}

Write-Step 'Health checks (external)'
if ($noTunnel) {
    Write-Warn 'Running without Cloudflare Tunnel; external checks depend on DNS + router/NAT forwarding'
}
$externalUrls = @(
    $externalRootUrl,
    $externalApiHealthUrl
)
foreach ($url in $externalUrls) {
    if (Wait-ForHttp $url 5 2) {
        Write-Ok $url
    } else {
        Write-Warn "$url - may need more time"
    }
}

# ========================================
# DONE!
# ========================================

Write-Host ''
Write-Host '========================================================' -ForegroundColor Green
Write-Host '          SERVER STARTED SUCCESSFULLY!                   ' -ForegroundColor Green
Write-Host '========================================================' -ForegroundColor Green
Write-Host ''
Write-Host "  Local site:    http://127.0.0.1:8080" -ForegroundColor White
Write-Host "  Local API:     http://127.0.0.1:5000/health" -ForegroundColor White
Write-Host "  External:      $publicOrigin" -ForegroundColor Cyan
Write-Host "  External API:  $externalApiHealthUrl" -ForegroundColor Cyan
if ($noTunnel) {
    Write-Host '  Tunnel mode:   disabled' -ForegroundColor DarkYellow
} else {
    Write-Host '  Tunnel mode:   cloudflared' -ForegroundColor DarkYellow
}
Write-Host ''
Write-Host "  PID file:      $pidsFile" -ForegroundColor Gray
Write-Host "  Logs:          $runtimeDir" -ForegroundColor Gray
Write-Host ''
Write-Host "  API:           PID $($apiProcess.Id)" -ForegroundColor Gray
Write-Host "  Caddy:         PID $($caddyProcess.Id)" -ForegroundColor Gray
if ($frpcProcess) {
    Write-Host "  frpc:          PID $($frpcProcess.Id)" -ForegroundColor Gray
}
if ($cloudflaredProcess) {
    Write-Host "  Cloudflared:   PID $($cloudflaredProcess.Id)" -ForegroundColor Gray
}
Write-Host ''
Write-Host '  To stop: .\stop-server.ps1' -ForegroundColor DarkGray
Write-Host ''
