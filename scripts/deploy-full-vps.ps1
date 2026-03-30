[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsHost,

    [string]$VpsUser = 'root',
    [string]$IdentityFile = '',
    [int]$SshPort = 22,
    [string]$AppDir = '/opt/familyone-vps',
    [string]$SiteAddress = ':8081',
    [string]$PublicOrigin = '',
    [int]$ApiPort = 5001,
    [string]$ServiceName = 'familyone-backend-vps',
    [string]$Email = '',
    [int]$SwapMb = 4096
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Yellow
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-NativeMerged {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rawOutput = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $lines = @()
    foreach ($item in @($rawOutput)) {
        if ($null -eq $item) { continue }

        if ($item -is [System.Management.Automation.ErrorRecord]) {
            $lines += $item.ToString()
            continue
        }

        $lines += [string]$item
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = ($lines -join [Environment]::NewLine).Trim()
    }
}

function ConvertTo-ShSingleQuoted {
    param([string]$Value)

    $text = ''
    if ($null -ne $Value) {
        $text = [string]$Value
    }

    return "'" + $text.Replace("'", "'""'""'") + "'"
}

function New-TarArchive {
    param(
        [string]$RepoRoot,
        [string]$ArchivePath
    )

    $excludeArgs = @(
        '--exclude=.git',
        '--exclude=node_modules',
        '--exclude=.runtime',
        '--exclude=dist',
        '--exclude=backend/.venv',
        '--exclude=backend/__pycache__',
        '--exclude=backend/backup_storage',
        '--exclude=backend/reference_photos',
        '--exclude=backend/uploaded_photos',
        '--exclude=backend/temp_pdf',
        '--exclude=familyone-vps-*.tar',
        '--exclude=familyone-vps-*.tgz'
    )

    $tarArgs = @('-czf', $ArchivePath)
    $tarArgs += $excludeArgs
    $tarArgs += @('.')

    Push-Location $RepoRoot
    try {
        $tarResult = Invoke-NativeMerged -FilePath 'tar.exe' -Arguments $tarArgs
        if ($tarResult.ExitCode -ne 0) {
            throw "Failed to create deployment archive.`n$($tarResult.Output)"
        }
    } finally {
        Pop-Location
    }
}

if (-not $PublicOrigin) {
    if ($SiteAddress -match '^:(\d+)$') {
        $PublicOrigin = "http://${VpsHost}:$($Matches[1])"
    }
}

if (-not $PublicOrigin) {
    $firstHost = ($SiteAddress -split ',')[0].Trim()
    if ($firstHost) {
        $PublicOrigin = "https://$firstHost"
    }
}

if (-not (Test-CommandExists 'ssh')) {
    throw "OpenSSH client not found. Install 'OpenSSH Client' in Windows and re-run."
}

if (-not (Test-CommandExists 'scp')) {
    throw "OpenSSH scp client not found. Install 'OpenSSH Client' in Windows and re-run."
}

if (-not (Test-CommandExists 'tar.exe')) {
    throw "tar.exe not found. It is required to package the project before upload."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$remoteArchive = '/tmp/familyone-vps-deploy.tgz'
$target = "$VpsUser@$VpsHost"
$archivePath = Join-Path $env:TEMP 'familyone-vps-deploy.tgz'
$sshArgsBase = @('-o', 'ConnectTimeout=15', '-p', $SshPort)
$scpArgs = @('-P', $SshPort)

if ($IdentityFile) {
    $sshArgsBase += @('-i', $IdentityFile)
    $scpArgs += @('-i', $IdentityFile)
}

Write-Step 'Creating deployment archive'
New-TarArchive -RepoRoot $repoRoot -ArchivePath $archivePath

Write-Step "Uploading archive to $target"
$scpArgs += @($archivePath, "${target}:$remoteArchive")
$scpResult = Invoke-NativeMerged -FilePath 'scp' -Arguments $scpArgs
if ($scpResult.ExitCode -ne 0) {
    throw "Upload failed.`n$($scpResult.Output)"
}

$runner = if ($VpsUser.ToLowerInvariant() -eq 'root') { 'bash' } else { 'sudo bash' }
$emailArg = ''
if ($Email) {
    $emailArg = " --email $(ConvertTo-ShSingleQuoted -Value $Email)"
}

$remoteParts = @(
    "set -e",
    "if systemctl list-unit-files | grep -q '^$ServiceName\.service'; then systemctl stop $ServiceName || true; fi",
    "rm -rf $(ConvertTo-ShSingleQuoted -Value $AppDir)",
    "mkdir -p $(ConvertTo-ShSingleQuoted -Value $AppDir)",
    "tar -xzf $(ConvertTo-ShSingleQuoted -Value $remoteArchive) -C $(ConvertTo-ShSingleQuoted -Value $AppDir)",
    "$runner $(ConvertTo-ShSingleQuoted -Value "$AppDir/infra/vps/setup-full-vps.sh") --app-dir $(ConvertTo-ShSingleQuoted -Value $AppDir) --site-address $(ConvertTo-ShSingleQuoted -Value $SiteAddress) --public-origin $(ConvertTo-ShSingleQuoted -Value $PublicOrigin) --api-port $(ConvertTo-ShSingleQuoted -Value ([string]$ApiPort)) --service-name $(ConvertTo-ShSingleQuoted -Value $ServiceName) --swap-mb $(ConvertTo-ShSingleQuoted -Value ([string]$SwapMb))$emailArg",
    "rm -f $(ConvertTo-ShSingleQuoted -Value $remoteArchive)"
)
$remoteCommand = ($remoteParts -join ' && ')

Write-Step "Deploying full VPS stack to $VpsHost"
$sshArgs = @()
$sshArgs += $sshArgsBase
$sshArgs += @($target, $remoteCommand)
$sshResult = Invoke-NativeMerged -FilePath 'ssh' -Arguments $sshArgs
if ($sshResult.ExitCode -ne 0) {
    throw "Remote deployment failed.`n$($sshResult.Output)"
}

if ($sshResult.Output) {
    Write-Host $sshResult.Output
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
Write-Host "Test URL: $PublicOrigin" -ForegroundColor Cyan
