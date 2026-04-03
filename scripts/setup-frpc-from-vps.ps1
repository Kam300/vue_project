[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsHost,

    [Parameter(Mandatory = $true)]
    [string]$Domain,

    [string]$VpsUser = 'root',
    [string]$ServerIp = '',
    [string]$Token = '',
    [string]$IdentityFile = '',
    [int]$SshPort = 22,
    [int]$ServerPort = 7000,
    [int]$LocalPort = 8080,
    [string]$ProxyName = 'familyone-web',
    [bool]$RunServer = $true,
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

function Get-FrpTokenFromVps {
    param(
        [string]$RemoteHost,
        [string]$User,
        [int]$Port,
        [string]$IdentityFile = ''
    )

    if (-not (Test-CommandExists 'ssh')) {
        throw "OpenSSH client not found. Install 'OpenSSH Client' in Windows and re-run."
    }

    $target = "$User@$RemoteHost"
    $runner = if ($User.ToLowerInvariant() -eq 'root') { 'sh' } else { 'sudo sh' }
    $remoteCommand = @"
$runner -lc '
config_path=""
for candidate in \
  /etc/frp/frps.toml \
  /etc/frps.toml \
  /usr/local/etc/frp/frps.toml \
  /etc/frp/frps.ini \
  /etc/frps.ini \
  /usr/local/etc/frp/frps.ini
do
  if [ -f "`$candidate" ]; then
    config_path="`$candidate"
    break
  fi
done

if [ -z "`$config_path" ]; then
  config_path=`$(systemctl show -p ExecStart frps 2>/dev/null | sed -n "s/.* -c \([^ ;\"]*\).*/\1/p" | head -n 1)
fi

if [ -z "`$config_path" ] || [ ! -f "`$config_path" ]; then
  config_path=`$(find /etc /usr/local/etc /opt /root -maxdepth 4 -type f \( -name frps.toml -o -name frps.ini \) 2>/dev/null | head -n 1)
fi

if [ -z "`$config_path" ] || [ ! -f "`$config_path" ]; then
  echo "__FRPS_MISSING__"
  exit 0
fi

token_value=`$(awk '
/^[[:space:]]*(auth\.)?token[[:space:]]*=/ {
  line=`$0
  sub(/^[[:space:]]*(auth\.)?token[[:space:]]*=[[:space:]]*/, "", line)
  sub(/[[:space:]]*[#;].*$/, "", line)
  gsub(/^"/, "", line)
  gsub(/"$/, "", line)
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
  print line
  exit
}
' "`$config_path")
if [ -z "`$token_value" ]; then
  echo "__TOKEN_MISSING__"
else
  echo "`$token_value"
fi
'
"@

    Write-Step "Connecting to $target to read FRP token"
    $sshArgs = @('-o', 'ConnectTimeout=12', '-p', $Port)
    if ($IdentityFile) {
        $sshArgs += @('-i', $IdentityFile)
    }
    $sshArgs += @($target, $remoteCommand)

    $output = & ssh @sshArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = ($output | Out-String).Trim()
        if ($details -match 'Connection timed out') {
            throw "SSH could not reach $target on port $Port. Check VPS IP, SSH port, firewall/security group, or run again with -SshPort <port>.`n$details"
        }
        if ($details -match 'Permission denied') {
            throw "SSH denied access to $target. Check login/password, try another user (often ubuntu/debian), or use -IdentityFile C:\path\key.pem.`n$details"
        }
        throw "SSH failed while reading token from VPS.`n$details"
    }

    $value = (($output | Out-String).Trim() -split "`r?`n" | Select-Object -Last 1).Trim()
    if (-not $value) {
        throw "SSH succeeded, but token output was empty."
    }

    if ($value -eq '__FRPS_MISSING__') {
        throw "FRPS config was not found on VPS. Run FRP server setup there first."
    }

    if ($value -eq '__TOKEN_MISSING__') {
        throw "Token entry was not found in the FRPS config on VPS."
    }

    return $value
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$setupFrpcScript = Join-Path $PSScriptRoot 'setup-frpc.ps1'
$startServerScript = Join-Path $repoRoot 'start-server.ps1'
$Domain = Normalize-Domain -Value $Domain

if (-not (Test-Path $setupFrpcScript)) {
    throw "setup-frpc.ps1 not found: $setupFrpcScript"
}

if (-not $ServerIp) {
    $ServerIp = $VpsHost
}

if (-not $Token) {
    $Token = Get-FrpTokenFromVps -RemoteHost $VpsHost -User $VpsUser -Port $SshPort -IdentityFile $IdentityFile
    Write-Step 'FRP token received from VPS'
}

$setupArgs = @{
    ServerIp   = $ServerIp
    Token      = $Token
    Domain     = $Domain
    ServerPort = $ServerPort
    LocalPort  = $LocalPort
    ProxyName  = $ProxyName
}

if ($InstallService) {
    $setupArgs.InstallService = $true
}

if ($StartService) {
    if (-not $InstallService) {
        throw 'Use -InstallService together with -StartService.'
    }
    $setupArgs.StartService = $true
}

Write-Step 'Configuring local frpc and backend/.env'
& $setupFrpcScript @setupArgs

if ($RunServer) {
    if (-not (Test-Path $startServerScript)) {
        throw "start-server.ps1 not found: $startServerScript"
    }

    Write-Step 'Starting app stack in no-tunnel mode'
    & $startServerScript -NoTunnel
}
