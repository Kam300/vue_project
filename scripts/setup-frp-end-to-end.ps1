[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsHost,

    [Parameter(Mandatory = $true)]
    [string]$Domain,

    [string]$VpsUser = 'root',
    [string]$IdentityFile = '',
    [int]$SshPort = 22,
    [string]$Email = '',
    [string]$Token = '',
    [int]$ServerPort = 7000,
    [int]$LocalPort = 8080,
    [string]$ProxyName = 'familyone-web',
    [switch]$InstallService,
    [switch]$StartService
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
        [string[]]$Arguments
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
        if ($null -eq $item) {
            continue
        }

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

function Normalize-Domain {
    param([string]$Value)

    $candidate = ''
    if ($null -ne $Value) {
        $candidate = [string]$Value
    }

    $candidate = $candidate.Trim()
    if (-not $candidate) {
        throw 'Domain is empty.'
    }

    $candidate = $candidate -replace '^\s*https?://', ''
    $candidate = $candidate.TrimEnd('/')
    $candidate = $candidate.Trim()

    if (-not $candidate) {
        throw 'Domain is empty after normalization.'
    }

    return $candidate
}

function ConvertTo-ShSingleQuoted {
    param([string]$Value)

    $text = ''
    if ($null -ne $Value) {
        $text = [string]$Value
    }

    return "'" + $text.Replace("'", "'""'""'") + "'"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$serverSetupScript = Join-Path $repoRoot 'infra\frp\setup-frps.sh'
$localClientSetupScript = Join-Path $PSScriptRoot 'setup-frpc.ps1'
$startServerScript = Join-Path $repoRoot 'start-server.ps1'
$runtimeDir = Join-Path $repoRoot '.runtime'
$cachedFrpcExe = Join-Path $runtimeDir 'frpc.exe'
$cachedFrpZip = Join-Path $runtimeDir 'frp_0.67.0_windows_amd64.zip'
$Domain = Normalize-Domain -Value $Domain

if (-not (Test-Path $serverSetupScript)) {
    throw "VPS setup script not found: $serverSetupScript"
}

if (-not (Test-Path $localClientSetupScript)) {
    throw "Local setup script not found: $localClientSetupScript"
}

if (-not (Test-Path $startServerScript)) {
    throw "start-server.ps1 not found: $startServerScript"
}

if (-not (Test-CommandExists 'ssh')) {
    throw "OpenSSH client not found. Install 'OpenSSH Client' in Windows and re-run."
}

if (-not (Test-CommandExists 'scp')) {
    throw "OpenSSH scp client not found. Install 'OpenSSH Client' in Windows and re-run."
}

$target = "$VpsUser@$VpsHost"
$remoteScriptPath = if ($VpsUser.ToLowerInvariant() -eq 'root') {
    '/root/codex-setup-frps.sh'
} else {
    "/home/$VpsUser/codex-setup-frps.sh"
}

$sshArgsBase = @('-o', 'ConnectTimeout=15', '-p', $SshPort)
$scpArgs = @('-P', $SshPort)
if ($IdentityFile) {
    $sshArgsBase += @('-i', $IdentityFile)
    $scpArgs += @('-i', $IdentityFile)
}

Write-Step "Uploading FRP server setup script to $target"
$scpArgs += @($serverSetupScript, "${target}:$remoteScriptPath")
$scpResult = Invoke-NativeMerged -FilePath 'scp' -Arguments $scpArgs
if ($scpResult.ExitCode -ne 0) {
    $details = $scpResult.Output
    if ($details) {
        throw "Failed to upload setup script to $target.`n$details"
    }
    throw "Failed to upload setup script to $target."
}

$remoteParts = @(
    "chmod +x $(ConvertTo-ShSingleQuoted -Value $remoteScriptPath)"
)

$runner = if ($VpsUser.ToLowerInvariant() -eq 'root') { 'bash' } else { 'sudo bash' }
$command = "$runner $(ConvertTo-ShSingleQuoted -Value $remoteScriptPath) --domain $(ConvertTo-ShSingleQuoted -Value $Domain)"

if ($Email) {
    $command += " --email $(ConvertTo-ShSingleQuoted -Value $Email)"
}

if ($Token) {
    $command += " --token $(ConvertTo-ShSingleQuoted -Value $Token)"
}

$remoteParts += $command
$remoteCommand = ($remoteParts -join ' && ')

Write-Step "Configuring FRP server on VPS $VpsHost"
$sshArgs = @()
$sshArgs += $sshArgsBase
$sshArgs += @($target, $remoteCommand)
$sshResult = Invoke-NativeMerged -FilePath 'ssh' -Arguments $sshArgs
$serverOutput = $sshResult.Output
if ($sshResult.ExitCode -ne 0) {
    $details = $serverOutput
    throw "Failed to configure FRP server on VPS.`n$details"
}

$serverText = $serverOutput
if ($serverText) {
    Write-Host $serverText
}

$resolvedToken = $Token
if (-not $resolvedToken) {
    $tokenMatch = [regex]::Match($serverText, 'FRP token:\s*(\S+)')
    if ($tokenMatch.Success) {
        $resolvedToken = $tokenMatch.Groups[1].Value.Trim()
    }
}

if (-not $resolvedToken) {
    throw 'FRP token was not found in VPS setup output.'
}

Write-Step 'Configuring local frpc'
$localSetupArgs = @{
    ServerIp   = $VpsHost
    Token      = $resolvedToken
    Domain     = $Domain
    ServerPort = $ServerPort
    LocalPort  = $LocalPort
    ProxyName  = $ProxyName
}

if (Test-Path $cachedFrpcExe) {
    Write-Step "Using cached local frpc.exe: $cachedFrpcExe"
    $localSetupArgs.FrpcExePath = $cachedFrpcExe
} elseif (Test-Path $cachedFrpZip) {
    Write-Step "Using cached local FRP ZIP: $cachedFrpZip"
    $localSetupArgs.FrpZipPath = $cachedFrpZip
}

if ($InstallService) {
    $localSetupArgs.InstallService = $true
}

if ($StartService) {
    if (-not $InstallService) {
        throw 'Use -InstallService together with -StartService.'
    }

    $localSetupArgs.StartService = $true
}

& $localClientSetupScript @localSetupArgs

Write-Step 'Starting app stack in no-tunnel mode'
& $startServerScript -NoTunnel
