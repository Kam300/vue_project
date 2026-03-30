[CmdletBinding()]
param(
    [int]$DelaySeconds = 45
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$runtimeDir = Join-Path $repoRoot '.runtime'
$bootLog = Join-Path $runtimeDir 'boot-start.log'
$startScript = Join-Path $repoRoot 'start-server.ps1'

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Write-BootLog {
    param([string]$Message)

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $bootLog -Value "[$timestamp] $Message"
}

try {
    Write-BootLog "Startup task triggered. DelaySeconds=$DelaySeconds"
    if ($DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
    }

    Write-BootLog 'Launching start-server.ps1 -NoTunnel'
    & $startScript -NoTunnel
    Write-BootLog 'Startup task completed successfully'
} catch {
    Write-BootLog "Startup task failed: $($_.Exception.Message)"
    throw
}
