$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

$runtimeDir = Join-Path $repoRoot '.runtime'
$pidsFile = Join-Path $runtimeDir 'pids.json'
$cloudflaredConfig = Join-Path $repoRoot 'infra\cloudflared\config.yml'
$backendEnvFile = Join-Path $repoRoot 'backend\.env'
$backendEnvExample = Join-Path $repoRoot 'backend\.env.example'
$isWindowsPlatform = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Ensure-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command '$Name' was not found in PATH."
    }
}

function Add-DirectoryToPath {
    param([string]$DirPath)

    if (-not (Test-Path $DirPath)) {
        return
    }

    $pathParts = $env:Path -split ';'
    if ($pathParts -contains $DirPath) {
        return
    }

    $env:Path = "$DirPath;$env:Path"
}

function Ensure-CommandWithCandidates {
    param(
        [string]$Name,
        [string[]]$CandidateExecutables
    )

    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return
    }

    foreach ($candidate in $CandidateExecutables) {
        if (Test-Path $candidate) {
            Add-DirectoryToPath -DirPath (Split-Path $candidate -Parent)
        }
    }

    Ensure-Command -Name $Name
}

function Run-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host "==> $Name"
    & $Action
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$Attempts = 40,
        [int]$DelaySeconds = 1
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        } catch {
            # keep retrying
        }
        Start-Sleep -Seconds $DelaySeconds
    }

    return $false
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdOut,
        [string]$StdErr
    )

    Write-Host "Starting $Name..."
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr -PassThru -WindowStyle Hidden

    Start-Sleep -Milliseconds 400
    if (-not $process -or $process.HasExited) {
        throw "Failed to start process '$Name'. Check logs: $StdErr"
    }

    return $process
}

function Resolve-PythonLauncher {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            & python --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    Command = 'python'
                    Prefix = @()
                }
            }
        } catch {
            # fall through to py launcher
        }
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3 --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    Command = 'py'
                    Prefix = @('-3')
                }
            }
        } catch {
            # no working python launcher
        }
    }

    throw "No working Python launcher found. Install Python and ensure 'python' or 'py -3' is available."
}

Run-Step -Name 'Checking required commands' -Action {
    $caddyCandidates = @(
        'C:\Program Files\Caddy\caddy.exe'
    )

    $wingetCaddy = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -Filter 'CaddyServer.Caddy_*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($wingetCaddy) {
        $wingetCaddyExe = Get-ChildItem -Path $wingetCaddy.FullName -Filter 'caddy.exe' -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($wingetCaddyExe) {
            $caddyCandidates += $wingetCaddyExe.FullName
        }
    }

    Ensure-CommandWithCandidates -Name 'node' -CandidateExecutables @('C:\Program Files\nodejs\node.exe', "$env:LOCALAPPDATA\Programs\nodejs\node.exe")
    Ensure-CommandWithCandidates -Name 'npm' -CandidateExecutables @('C:\Program Files\nodejs\npm.cmd', "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd")
    Ensure-CommandWithCandidates -Name 'caddy' -CandidateExecutables $caddyCandidates
    Ensure-Command -Name 'cloudflared'
}

$pythonLauncher = Resolve-PythonLauncher
$pythonCommand = [string]$pythonLauncher.Command
$pythonPrefix = @($pythonLauncher.Prefix)
Write-Host "Using Python launcher: $pythonCommand $($pythonPrefix -join ' ')"

if (-not (Test-Path $cloudflaredConfig)) {
    throw "Missing $cloudflaredConfig. Create it from infra/cloudflared/config.yml.example first."
}

if (-not (Test-Path $backendEnvFile)) {
    Copy-Item -Path $backendEnvExample -Destination $backendEnvFile
    Write-Host 'Created backend/.env from .env.example'
}

$stopScript = Join-Path $repoRoot 'scripts\stop-all.ps1'
if (Test-Path $stopScript) {
    Write-Host 'Stopping previous managed processes (if any)...'
    & $stopScript | Out-Null
}

Run-Step -Name 'Installing frontend dependencies' -Action {
    npm install
    if ($LASTEXITCODE -ne 0) {
        throw 'npm install failed.'
    }
}

Run-Step -Name 'Building frontend' -Action {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw 'npm run build failed.'
    }
}

$venvDir = Join-Path $repoRoot 'backend\.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Run-Step -Name 'Creating backend virtual environment' -Action {
        & $pythonCommand @pythonPrefix -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            throw 'python venv creation failed.'
        }
    }
}

Run-Step -Name 'Installing backend dependencies' -Action {
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw 'pip upgrade failed.'
    }

    & $venvPython -m pip install -r (Join-Path $repoRoot 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw 'pip install -r backend/requirements.txt failed.'
    }

    # On Windows we avoid building dlib from source by installing face-recognition without deps.
    if ($isWindowsPlatform) {
        & $venvPython -m pip install --no-deps face-recognition==1.3.0
        if ($LASTEXITCODE -ne 0) {
            throw 'pip install face-recognition==1.3.0 --no-deps failed.'
        }
    }

    & $venvPython -c "import face_recognition, dlib; print('face stack ok')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Face recognition runtime import check failed.'
    }
}

$apiOut = Join-Path $runtimeDir 'api.out.log'
$apiErr = Join-Path $runtimeDir 'api.err.log'
$caddyOut = Join-Path $runtimeDir 'caddy.out.log'
$caddyErr = Join-Path $runtimeDir 'caddy.err.log'
$cloudOut = Join-Path $runtimeDir 'cloudflared.out.log'
$cloudErr = Join-Path $runtimeDir 'cloudflared.err.log'

$apiProcess = Start-ManagedProcess -Name 'API' -FilePath $venvPython -Arguments @('telegram_service.py') -WorkingDirectory (Join-Path $repoRoot 'backend') -StdOut $apiOut -StdErr $apiErr
$caddyProcess = Start-ManagedProcess -Name 'Caddy' -FilePath 'caddy' -Arguments @('run', '--config', (Join-Path $repoRoot 'infra\Caddyfile'), '--adapter', 'caddyfile') -WorkingDirectory $repoRoot -StdOut $caddyOut -StdErr $caddyErr
$cloudflaredProcess = Start-ManagedProcess -Name 'Cloudflared' -FilePath 'cloudflared' -Arguments @('tunnel', '--protocol', 'http2', '--config', $cloudflaredConfig, 'run') -WorkingDirectory $repoRoot -StdOut $cloudOut -StdErr $cloudErr

$pidPayload = [ordered]@{
    started_at = (Get-Date).ToString('o')
    processes = @(
        [ordered]@{ name = 'api'; pid = $apiProcess.Id; stdout = $apiOut; stderr = $apiErr }
        [ordered]@{ name = 'caddy'; pid = $caddyProcess.Id; stdout = $caddyOut; stderr = $caddyErr }
        [ordered]@{ name = 'cloudflared'; pid = $cloudflaredProcess.Id; stdout = $cloudOut; stderr = $cloudErr }
    )
}
$pidPayload | ConvertTo-Json -Depth 6 | Set-Content -Path $pidsFile -Encoding UTF8

Run-Step -Name 'Health checks (local)' -Action {
    if (-not (Wait-HttpOk -Url 'http://127.0.0.1:5000/health' -Attempts 50 -DelaySeconds 1)) {
        throw 'API health check failed: http://127.0.0.1:5000/health'
    }

    if (-not (Wait-HttpOk -Url 'http://127.0.0.1:8080/' -Attempts 30 -DelaySeconds 1)) {
        throw 'Caddy frontend check failed: http://127.0.0.1:8080/'
    }

    if (-not (Wait-HttpOk -Url 'http://127.0.0.1:8080/api/health' -Attempts 30 -DelaySeconds 1)) {
        throw 'Caddy API check failed: http://127.0.0.1:8080/api/health'
    }

    if (-not (Wait-HttpOk -Url 'http://127.0.0.1:8080/health' -Attempts 30 -DelaySeconds 1)) {
        throw 'Caddy legacy API check failed: http://127.0.0.1:8080/health'
    }
}

Write-Host '==> Health checks (external)'
$externalChecks = @(
    'https://totalcode.indevs.in/',
    'https://totalcode.indevs.in/api/health',
    'https://totalcode.indevs.in/health'
)

foreach ($url in $externalChecks) {
    if (Wait-HttpOk -Url $url -Attempts 5 -DelaySeconds 2) {
        Write-Host "  OK  $url"
    } else {
        Write-Warning "  FAIL $url (check Cloudflare DNS/tunnel readiness)"
    }
}

Write-Host ''
Write-Host 'Services started successfully.'
Write-Host "API PID:         $($apiProcess.Id)"
Write-Host "Caddy PID:       $($caddyProcess.Id)"
Write-Host "Cloudflared PID: $($cloudflaredProcess.Id)"
Write-Host "PID file:        $pidsFile"
Write-Host "Logs:            $runtimeDir"
