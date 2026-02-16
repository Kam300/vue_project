param(
    [switch]$CheckOnly,
    [switch]$ForceReinstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$backendDir = Join-Path $repoRoot 'backend'
$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'
$cmakeBin = 'C:\Program Files\CMake\bin'

if (Test-Path (Join-Path $cmakeBin 'cmake.exe')) {
    $env:Path = "$cmakeBin;$env:Path"
}

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

function Get-DlibStatus {
    param([string]$PythonExe)

    $probeScript = @'
import json
import sys
import os

payload = {
    'python': sys.executable,
    'dlib_installed': False,
    'dlib_version': None,
    'dlib_use_cuda': False,
    'cuda_devices': 0,
    'cuda_enabled': False,
    'error': ''
}

try:
    dll_dirs = [item for item in os.environ.get('DLIB_DLL_DIRS', '').split(';') if item]
    if hasattr(os, 'add_dll_directory'):
        for dll_dir in dll_dirs:
            if os.path.isdir(dll_dir):
                os.add_dll_directory(dll_dir)

    import dlib
    payload['dlib_installed'] = True
    payload['dlib_version'] = getattr(dlib, '__version__', None)
    payload['dlib_use_cuda'] = bool(getattr(dlib, 'DLIB_USE_CUDA', False))
    try:
        payload['cuda_devices'] = int(dlib.cuda.get_num_devices())
    except Exception as exc:
        payload['error'] = f'cuda device check failed: {exc}'
        payload['cuda_devices'] = 0
    payload['cuda_enabled'] = payload['dlib_use_cuda'] and payload['cuda_devices'] > 0
except Exception as exc:
    payload['error'] = str(exc)

print(json.dumps(payload))
'@

    $raw = & $PythonExe -c $probeScript
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to run dlib probe script.'
    }
    return ($raw | ConvertFrom-Json)
}

if (-not (Test-Path $venvPython)) {
    throw "Backend venv not found: $venvPython`nRun .\start-server.ps1 first."
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host ' Dlib CUDA Installer / Verifier (Windows)' -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host ''

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Step 'Detected NVIDIA GPU:'
    & nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
} else {
    Write-Warn 'nvidia-smi not found in PATH. CUDA runtime checks may fail.'
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Warn 'cmake is not in PATH. Source build may fail.'
}

$clInPath = [bool](Get-Command cl -ErrorAction SilentlyContinue)
if (-not $clInPath) {
    Write-Warn 'cl.exe (MSVC) is not in PATH. Use "x64 Native Tools Command Prompt for VS 2022".'
}

$vswherePath = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$vsBuildToolsInstalled = $false
if (Test-Path $vswherePath) {
    $vsInstallPath = & $vswherePath -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($vsInstallPath) {
        $vsBuildToolsInstalled = $true
    }
}

if (-not $clInPath -and -not $vsBuildToolsInstalled -and -not $CheckOnly) {
    throw @"
Visual C++ Build Tools were not detected.
Install (as Administrator), then re-run:

winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget --accept-source-agreements --accept-package-agreements --override "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
"@
}

$cudaPath = $env:CUDA_PATH
if (-not $cudaPath -or -not (Test-Path $cudaPath)) {
    $cudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA'
    if (Test-Path $cudaRoot) {
        $latestCuda = Get-ChildItem $cudaRoot -Directory -Filter 'v*' | Sort-Object Name -Descending | Select-Object -First 1
        if ($latestCuda) {
            $cudaPath = $latestCuda.FullName
        }
    }
}

function Find-CudnnRoot {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not $candidate) { continue }
        if (-not (Test-Path $candidate)) { continue }

        $header = Get-ChildItem (Join-Path $candidate 'include') -Filter 'cudnn*.h' -ErrorAction SilentlyContinue | Select-Object -First 1
        $lib = Get-ChildItem (Join-Path $candidate 'lib\x64') -Filter 'cudnn*.lib' -ErrorAction SilentlyContinue | Select-Object -First 1
        $dll = Get-ChildItem (Join-Path $candidate 'bin') -Filter 'cudnn*.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $dll) {
            $dll = Get-ChildItem (Join-Path $candidate 'bin\x64') -Filter 'cudnn*.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
        }

        if ($header -and $lib -and $dll) {
            return $candidate
        }
    }

    return $null
}

function Get-CudaComputeCapability {
    param([string]$Fallback = '89')

    $override = $env:DLIB_CUDA_COMPUTE_CAPABILITY
    if ($override -and $override -match '^\d+$') {
        return $override
    }

    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return $Fallback
    }

    try {
        $raw = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
        if ($raw) {
            $normalized = $raw.Trim()
            if ($normalized -match '^\d+(\.\d+)?$') {
                return ($normalized -replace '\.', '')
            }
        }
    } catch {
        return $Fallback
    }

    return $Fallback
}

function Prepare-PatchedDlibSource {
    param(
        [string]$PythonExe,
        [string]$RepoRoot,
        [string]$ComputeCapability
    )

    $downloadDir = Join-Path $RepoRoot '.runtime\src'
    $extractRoot = 'C:\Temp\dlib-src'
    $archivePath = Join-Path $downloadDir 'dlib-20.0.0.tar.gz'
    $sourceRoot = Join-Path $extractRoot 'dlib-20.0.0'

    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

    if (-not (Test-Path $archivePath)) {
        Write-Step 'Downloading dlib source archive...'
        & $PythonExe -m pip download dlib==20.0.0 --no-binary :all: -d $downloadDir
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to download dlib source archive.'
        }
    }

    if (-not (Test-Path $sourceRoot)) {
        Write-Step 'Extracting dlib source archive...'
        & tar -xf $archivePath -C $extractRoot
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $sourceRoot)) {
            throw 'Failed to extract dlib source archive.'
        }
    }

    $testCmakeFiles = @(
        (Join-Path $sourceRoot 'dlib\cmake_utils\test_for_cuda\CMakeLists.txt'),
        (Join-Path $sourceRoot 'dlib\cmake_utils\test_for_cudnn\CMakeLists.txt')
    )

    foreach ($file in $testCmakeFiles) {
        if (-not (Test-Path $file)) {
            throw "Expected file not found: $file"
        }

        $content = Get-Content $file -Raw
        $patched = $content -replace 'sm_[0-9]+', "sm_$ComputeCapability"
        if ($patched -ne $content) {
            Set-Content -Path $file -Value $patched -Encoding UTF8 -NoNewline
        }
    }

    $mainCmakeFile = Join-Path $sourceRoot 'dlib\CMakeLists.txt'
    if (-not (Test-Path $mainCmakeFile)) {
        throw "Expected file not found: $mainCmakeFile"
    }
    $mainCmakeContent = Get-Content $mainCmakeFile -Raw
    $mainReplacement = "set(DLIB_USE_CUDA_COMPUTE_CAPABILITIES $ComputeCapability CACHE STRING `${DLIB_USE_CUDA_COMPUTE_CAPABILITIES_STR})"
    $mainCmakePatched = $mainCmakeContent -replace 'set\(DLIB_USE_CUDA_COMPUTE_CAPABILITIES 50 CACHE STRING \$\{DLIB_USE_CUDA_COMPUTE_CAPABILITIES_STR\}\)', $mainReplacement
    if ($mainCmakePatched -ne $mainCmakeContent) {
        Set-Content -Path $mainCmakeFile -Value $mainCmakePatched -Encoding UTF8 -NoNewline
    }

    $sourceBuildDir = Join-Path $sourceRoot 'build'
    if (Test-Path $sourceBuildDir) {
        Remove-Item -Path $sourceBuildDir -Recurse -Force
    }

    Write-Ok "Patched dlib CUDA test architecture to sm_$ComputeCapability"
    return $sourceRoot
}

$localCudnnRoot = Join-Path $repoRoot '.runtime\cudnn-cu13-extracted\cudnn-windows-x86_64-9.19.0.56_cuda13-archive'
$cudnnCandidates = @(
    $env:CUDNN_ROOT,
    $localCudnnRoot,
    $cudaPath
)

$cudnnRoot = Find-CudnnRoot -Candidates $cudnnCandidates
$cudaComputeCapability = Get-CudaComputeCapability -Fallback '89'

if ($cudnnRoot) {
    Write-Ok "Using cuDNN from: $cudnnRoot"
}
Write-Step "Using CUDA compute capability: sm_$cudaComputeCapability"

if (-not $cudnnRoot -and -not $CheckOnly) {
    throw @"
cuDNN was not found. dlib CUDA build requires cuDNN.

Checked locations:
- CUDNN_ROOT env: $($env:CUDNN_ROOT)
- Local extracted: $localCudnnRoot
- CUDA toolkit: $cudaPath

Install/extract cuDNN for CUDA 13 and ensure any checked location contains:
- include\cudnn*.h
- lib\x64\cudnn*.lib
- bin\cudnn*.dll (or bin\x64\cudnn*.dll)

Then re-run:
powershell -ExecutionPolicy Bypass -File scripts/enable-dlib-cuda.ps1
"@
}

$probeDllDirs = @()
if ($cudnnRoot) {
    $probeCudnnBin = Join-Path $cudnnRoot 'bin'
    $probeCudnnBinX64 = Join-Path $cudnnRoot 'bin\x64'
    if (Test-Path $probeCudnnBinX64) { $probeDllDirs += $probeCudnnBinX64 }
    if (Test-Path $probeCudnnBin) { $probeDllDirs += $probeCudnnBin }
}
if ($cudaPath) {
    $probeCudaBin = Join-Path $cudaPath 'bin'
    $probeCudaBinX64 = Join-Path $cudaPath 'bin\x64'
    if (Test-Path $probeCudaBinX64) { $probeDllDirs += $probeCudaBinX64 }
    if (Test-Path $probeCudaBin) { $probeDllDirs += $probeCudaBin }
}
$probeSitePackages = Join-Path $backendDir '.venv\Lib\site-packages'
$probeCublasVenvBin = Join-Path $probeSitePackages 'nvidia\cu13\bin\x86_64'
if (Test-Path $probeCublasVenvBin) { $probeDllDirs += $probeCublasVenvBin }

if ($probeDllDirs.Count -gt 0) {
    $env:DLIB_DLL_DIRS = ($probeDllDirs | Select-Object -Unique) -join ';'
}

$before = Get-DlibStatus -PythonExe $venvPython
Write-Host ''
Write-Host "Current status:" -ForegroundColor Cyan
Write-Host "  Python:         $($before.python)"
Write-Host "  dlib installed: $($before.dlib_installed)"
Write-Host "  dlib version:   $($before.dlib_version)"
Write-Host "  DLIB_USE_CUDA:  $($before.dlib_use_cuda)"
Write-Host "  CUDA devices:   $($before.cuda_devices)"
Write-Host "  CUDA enabled:   $($before.cuda_enabled)"
if ($before.error) {
    Write-Host "  Error:          $($before.error)" -ForegroundColor DarkYellow
}

if ($CheckOnly) {
    if ($before.cuda_enabled) {
        Write-Ok 'CUDA already enabled in dlib.'
        exit 0
    }
    Write-Warn 'CUDA is not enabled in current dlib build.'
    exit 1
}

if ($before.cuda_enabled -and -not $ForceReinstall) {
    Write-Ok 'CUDA already enabled in dlib. Use -ForceReinstall to rebuild.'
    exit 0
}

Write-Host ''
Write-Step 'Upgrading build tools in venv (pip/setuptools=65.5.0/wheel/ninja)...'
& $venvPython -m pip install --upgrade pip wheel ninja setuptools==65.5.0
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to upgrade build tools.'
}

Write-Step 'Removing CPU dlib wheels if present...'
& $venvPython -m pip uninstall -y dlib dlib-bin | Out-Null

$dlibSourcePath = Prepare-PatchedDlibSource -PythonExe $venvPython -RepoRoot $repoRoot -ComputeCapability $cudaComputeCapability

$oldCmakeArgs = $env:CMAKE_ARGS
$oldCmakeGenerator = $env:CMAKE_GENERATOR
$oldCmakeGeneratorPlatform = $env:CMAKE_GENERATOR_PLATFORM
$oldCmakePrefixPath = $env:CMAKE_PREFIX_PATH
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$buildTempRoot = 'C:\Temp\pip-dlib'
New-Item -ItemType Directory -Force -Path $buildTempRoot | Out-Null
$env:TEMP = $buildTempRoot
$env:TMP = $buildTempRoot
$env:CMAKE_ARGS = "-DDLIB_USE_CUDA=1 -DDLIB_USE_CUDA_COMPUTE_CAPABILITIES=$cudaComputeCapability -DUSE_AVX_INSTRUCTIONS=1 -DCMAKE_BUILD_TYPE=Release"
$env:CMAKE_GENERATOR = 'Visual Studio 17 2022'
$env:CMAKE_GENERATOR_PLATFORM = 'x64'

if ($cudnnRoot) {
    if ($oldCmakePrefixPath) {
        $env:CMAKE_PREFIX_PATH = "$cudnnRoot;$oldCmakePrefixPath"
    } else {
        $env:CMAKE_PREFIX_PATH = $cudnnRoot
    }
}

$runtimeDllDirs = @()
if ($cudnnRoot) {
    $cudnnBin = Join-Path $cudnnRoot 'bin'
    $cudnnBinX64 = Join-Path $cudnnRoot 'bin\x64'
    if (Test-Path $cudnnBinX64) { $runtimeDllDirs += $cudnnBinX64 }
    if (Test-Path $cudnnBin) { $runtimeDllDirs += $cudnnBin }
}
if ($cudaPath) {
    $cudaBin = Join-Path $cudaPath 'bin'
    $cudaBinX64 = Join-Path $cudaPath 'bin\x64'
    if (Test-Path $cudaBinX64) { $runtimeDllDirs += $cudaBinX64 }
    if (Test-Path $cudaBin) { $runtimeDllDirs += $cudaBin }
}
$venvSitePackages = Join-Path $backendDir '.venv\Lib\site-packages'
$cublasVenvBin = Join-Path $venvSitePackages 'nvidia\cu13\bin\x86_64'
if (Test-Path $cublasVenvBin) { $runtimeDllDirs += $cublasVenvBin }

$runtimeDllDirs = $runtimeDllDirs | Select-Object -Unique
if ($runtimeDllDirs.Count -gt 0) {
    $env:DLIB_DLL_DIRS = $runtimeDllDirs -join ';'
    $env:Path = ($runtimeDllDirs -join ';') + ';' + $env:Path
}

$installArgs = @('install', '--no-cache-dir', '--no-build-isolation', '--verbose', $dlibSourcePath)
$installed = $false
try {
    Write-Step "Trying: pip $($installArgs -join ' ')"
    & $venvPython -m pip @installArgs
    if ($LASTEXITCODE -eq 0) {
        $installed = $true
    } else {
        Write-Warn 'dlib build/install command failed.'
    }
} finally {
    $env:CMAKE_ARGS = $oldCmakeArgs
    $env:CMAKE_GENERATOR = $oldCmakeGenerator
    $env:CMAKE_GENERATOR_PLATFORM = $oldCmakeGeneratorPlatform
    $env:CMAKE_PREFIX_PATH = $oldCmakePrefixPath
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
}

if (-not $installed) {
    Write-Warn 'Restoring CPU fallback package dlib-bin...'
    & $venvPython -m pip install --force-reinstall dlib-bin==20.0.0
    throw 'Could not install CUDA-enabled dlib from source.'
}

Write-Step 'Reinstalling face-recognition packages...'
& $venvPython -m pip install --force-reinstall --no-deps face-recognition==1.3.0
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to reinstall face-recognition.'
}

& $venvPython -m pip install --force-reinstall face-recognition-models==0.3.0
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to reinstall face-recognition-models.'
}

Write-Step 'Import verification...'
$verifyScript = @'
import os

dll_dirs = [item for item in os.environ.get("DLIB_DLL_DIRS", "").split(";") if item]
if hasattr(os, "add_dll_directory"):
    for dll_dir in dll_dirs:
        if os.path.isdir(dll_dir):
            os.add_dll_directory(dll_dir)

import face_recognition
import dlib

print("face stack ok")
print(f"dlib cuda: use_cuda={dlib.DLIB_USE_CUDA}, devices={dlib.cuda.get_num_devices()}")
'@
& $venvPython -c $verifyScript
if ($LASTEXITCODE -ne 0) {
    throw 'Face stack import verification failed.'
}

$after = Get-DlibStatus -PythonExe $venvPython
Write-Host ''
Write-Host "New status:" -ForegroundColor Cyan
Write-Host "  dlib version:   $($after.dlib_version)"
Write-Host "  DLIB_USE_CUDA:  $($after.dlib_use_cuda)"
Write-Host "  CUDA devices:   $($after.cuda_devices)"
Write-Host "  CUDA enabled:   $($after.cuda_enabled)"
if ($after.error) {
    Write-Host "  Error:          $($after.error)" -ForegroundColor DarkYellow
}

if (-not $after.cuda_enabled) {
    throw "CUDA still disabled in dlib. Start from VS Native Tools shell and re-run scripts/enable-dlib-cuda.ps1."
}

Write-Host ''
Write-Ok 'CUDA-enabled dlib is active.'
Write-Host 'Restart backend to apply (start-server.ps1 or scripts/deploy-and-run.ps1).' -ForegroundColor Cyan
