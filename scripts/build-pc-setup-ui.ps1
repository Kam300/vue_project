[CmdletBinding()]
param(
    [string]$PythonLauncher = 'py',
    [string]$PythonVersionArg = '-3',
    [string]$OutputName = 'familyone-pc-setup-ui'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$uiScript = Join-Path $PSScriptRoot 'pc_server_setup_ui.py'
$distDir = Join-Path $repoRoot 'dist-tools'
$workDir = Join-Path $repoRoot '.runtime\pyinstaller-build'
$specDir = Join-Path $repoRoot '.runtime\pyinstaller-spec'

if (-not (Test-Path $uiScript)) {
    throw "UI script not found: $uiScript"
}

New-Item -ItemType Directory -Path $distDir -Force | Out-Null
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
New-Item -ItemType Directory -Path $specDir -Force | Out-Null

& $PythonLauncher $PythonVersionArg -m pip install --user pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install PyInstaller.'
}

& $PythonLauncher $PythonVersionArg -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --hidden-import paramiko `
    --name $OutputName `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $specDir `
    $uiScript

if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}

Write-Host ''
Write-Host 'Build complete.' -ForegroundColor Green
Write-Host "EXE: $(Join-Path $distDir ($OutputName + '.exe'))"
