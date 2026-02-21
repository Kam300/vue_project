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

function Remove-BrokenPipDistributions {
    param([string]$VenvRoot)

    $sitePackages = Join-Path $VenvRoot 'Lib\site-packages'
    if (-not (Test-Path $sitePackages)) {
        return
    }

    $brokenEntries = Get-ChildItem -Path $sitePackages -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^~' }

    if (-not $brokenEntries) {
        return
    }

    $removed = @()
    foreach ($entry in $brokenEntries) {
        Remove-Item -Path $entry.FullName -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $entry.FullName)) {
            $removed += $entry.Name
        }
    }

    if ($removed.Count -gt 0) {
        Write-Host "Removed broken pip artifacts: $($removed -join ', ')"
    }
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

function Get-DlibCudaState {
    param([string]$PythonExe)

    $fallback = [pscustomobject]@{
        has_dlib = $false
        use_cuda = $false
        cuda_devices = 0
        cuda_enabled = $false
        error = ''
    }

    if (-not (Test-Path $PythonExe)) {
        return $fallback
    }

    $probeScript = @'
import json
import os

payload = {
    "has_dlib": False,
    "use_cuda": False,
    "cuda_devices": 0,
    "cuda_enabled": False,
    "error": ""
}

try:
    dll_dirs = [item for item in os.environ.get("DLIB_DLL_DIRS", "").split(";") if item]
    if hasattr(os, "add_dll_directory"):
        for dll_dir in dll_dirs:
            if os.path.isdir(dll_dir):
                os.add_dll_directory(dll_dir)

    import dlib
    payload["has_dlib"] = True
    payload["use_cuda"] = bool(getattr(dlib, "DLIB_USE_CUDA", False))
    try:
        payload["cuda_devices"] = int(dlib.cuda.get_num_devices())
    except Exception:
        payload["cuda_devices"] = 0
    payload["cuda_enabled"] = payload["use_cuda"] and payload["cuda_devices"] > 0
except Exception as exc:
    payload["error"] = str(exc)

print(json.dumps(payload))
'@

    try {
        $raw = $probeScript | & $PythonExe -
        if ($LASTEXITCODE -eq 0 -and $raw) {
            return ($raw | ConvertFrom-Json)
        }
    } catch {
        return $fallback
    }

    return $fallback
}

function Set-DlibProbeDllDirs {
    param(
        [string]$RepoRoot,
        [string]$VenvPython
    )

    $dirs = @()
    $runtimeCudnn = Join-Path $RepoRoot '.runtime\cudnn-cu13-extracted\cudnn-windows-x86_64-9.19.0.56_cuda13-archive'
    $dirs += (Join-Path $runtimeCudnn 'bin\x64')
    $dirs += (Join-Path $runtimeCudnn 'bin')

    if ($env:CUDA_PATH) {
        $dirs += (Join-Path $env:CUDA_PATH 'bin\x64')
        $dirs += (Join-Path $env:CUDA_PATH 'bin')
    }

    $cudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA'
    if (Test-Path $cudaRoot) {
        $latestCuda = Get-ChildItem -Path $cudaRoot -Directory -Filter 'v*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($latestCuda) {
            $dirs += (Join-Path $latestCuda.FullName 'bin\x64')
            $dirs += (Join-Path $latestCuda.FullName 'bin')
        }
    }

    try {
        $venvScriptsDir = Split-Path $VenvPython -Parent
        $venvRoot = Split-Path $venvScriptsDir -Parent
        $sitePackages = Join-Path $venvRoot 'Lib\site-packages'
        $dirs += (Join-Path $sitePackages 'nvidia\cu13\bin\x86_64')
        $dirs += (Join-Path $sitePackages 'nvidia\cudnn\bin')
        $dirs += (Join-Path $sitePackages 'nvidia\cudnn\bin\x64')
    } catch {
        # keep defaults only
    }

    $validDirs = $dirs | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    if ($validDirs.Count -gt 0) {
        $env:DLIB_DLL_DIRS = $validDirs -join ';'
    }
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

$defaultPublicOrigin = 'https://totalcode.indevs.in'
$publicOrigin = Normalize-Origin (Get-EnvValue -FilePath $backendEnvFile -Name 'PUBLIC_ORIGIN' -DefaultValue $defaultPublicOrigin) $defaultPublicOrigin
$externalChecks = @(
    "$publicOrigin/",
    "$publicOrigin/api/health",
    "$publicOrigin/health"
)

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
    $requirementsPath = Join-Path $repoRoot 'backend\requirements.txt'
    $requirementsToInstall = $requirementsPath
    $usedCpuFallback = $false
    $faceStackProbe = @'
import os

dll_dirs = [item for item in os.environ.get("DLIB_DLL_DIRS", "").split(";") if item]
if hasattr(os, "add_dll_directory"):
    for dll_dir in dll_dirs:
        if os.path.isdir(dll_dir):
            os.add_dll_directory(dll_dir)

import face_recognition
import dlib

print("face stack ok")
print(f"dlib cuda: use_cuda={bool(getattr(dlib, 'DLIB_USE_CUDA', False))}, devices={int(dlib.cuda.get_num_devices())}")
'@

    if ($isWindowsPlatform) {
        Remove-BrokenPipDistributions -VenvRoot $venvDir
    }

    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw 'pip upgrade failed.'
    }

    # On Windows we install requirements without dlib-bin first to avoid overwriting CUDA-enabled dlib.
    if ($isWindowsPlatform) {
        Set-DlibProbeDllDirs -RepoRoot $repoRoot -VenvPython $venvPython
        $pipFreeze = & $venvPython -m pip list --format=freeze
        $hasDlibBin = $pipFreeze -match '^dlib-bin=='
        if ($hasDlibBin) {
            $previousErrorAction = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & $venvPython -m pip uninstall -y dlib-bin *> $null
            } finally {
                $ErrorActionPreference = $previousErrorAction
            }
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "pip uninstall dlib-bin exited with code $LASTEXITCODE. Continuing."
            }
        }
        $requirementsToInstall = Join-Path $runtimeDir 'requirements.no-dlib-bin.txt'
        (Get-Content $requirementsPath) |
            Where-Object { $_ -notmatch '^\s*dlib-bin\b' } |
            Set-Content -Path $requirementsToInstall -Encoding UTF8
    }

    & $venvPython -m pip install -r $requirementsToInstall
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

    $faceStackOk = $true
    $faceStackProbe | & $venvPython -
    if ($LASTEXITCODE -ne 0) {
        $faceStackOk = $false
    }

    if (-not $faceStackOk -and $isWindowsPlatform) {
        Write-Warning 'Face recognition runtime import failed with current dlib. Falling back to CPU dlib-bin.'
        $usedCpuFallback = $true

        & $venvPython -m pip install --force-reinstall dlib-bin==20.0.0
        if ($LASTEXITCODE -ne 0) {
            throw 'pip install dlib-bin==20.0.0 fallback failed.'
        }

        & $venvPython -m pip install --no-deps --force-reinstall face-recognition==1.3.0
        if ($LASTEXITCODE -ne 0) {
            throw 'pip reinstall face-recognition==1.3.0 --no-deps failed.'
        }

        $faceStackProbe | & $venvPython -
        if ($LASTEXITCODE -ne 0) {
            throw 'Face recognition runtime import check failed after CPU fallback.'
        }
    } elseif (-not $faceStackOk) {
        throw 'Face recognition runtime import check failed.'
    }

    if ($isWindowsPlatform) {
        Set-DlibProbeDllDirs -RepoRoot $repoRoot -VenvPython $venvPython
        $dlibState = Get-DlibCudaState -PythonExe $venvPython
        Write-Host "dlib runtime state: cuda_enabled=$($dlibState.cuda_enabled), use_cuda=$($dlibState.use_cuda), devices=$($dlibState.cuda_devices)"

        $statePath = Join-Path $runtimeDir 'dlib-deploy-state.json'
        [ordered]@{
            timestamp = (Get-Date).ToString('o')
            requirements_file = $requirementsToInstall
            used_cpu_fallback = $usedCpuFallback
            dlib = $dlibState
        } | ConvertTo-Json -Depth 4 | Set-Content -Path $statePath -Encoding UTF8
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
