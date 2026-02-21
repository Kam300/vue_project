[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIp,

    [Parameter(Mandatory = $true)]
    [string]$Token,

    [string]$Domain = 'totalcode.online',
    [string]$FrpVersion = '0.67.0',
    [int]$ServerPort = 7000,
    [int]$LocalPort = 8080,
    [string]$ProxyName = 'familyone-web',
    [string]$FrpDir = 'C:\frp',
    [string]$FrpcExePath = '',
    [string]$FrpZipPath = '',
    [switch]$InstallService,
    [switch]$StartService
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Yellow
}

function Write-TextUtf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Enable-Tls12 {
    try {
        $current = [System.Net.ServicePointManager]::SecurityProtocol
        $tls12 = [System.Net.SecurityProtocolType]::Tls12
        if (($current -band $tls12) -eq 0) {
            [System.Net.ServicePointManager]::SecurityProtocol = $current -bor $tls12
        }
    } catch {
        # Ignore, we still try with default protocols.
    }
}

function Test-ZipArchiveFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $false
    }

    $file = Get-Item -Path $Path -ErrorAction SilentlyContinue
    if (-not $file -or $file.Length -lt 1024) {
        return $false
    }

    $stream = $null
    $zip = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        $header = New-Object byte[] 2
        $read = $stream.Read($header, 0, 2)
        if ($read -lt 2 -or $header[0] -ne 80 -or $header[1] -ne 75) {
            return $false
        }

        $stream.Position = 0
        $zip = New-Object System.IO.Compression.ZipArchive($stream, [System.IO.Compression.ZipArchiveMode]::Read, $true)
        return ($zip.Entries.Count -gt 0)
    } catch {
        return $false
    } finally {
        if ($zip) { $zip.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}

function Download-FileWithFallback {
    param(
        [string[]]$Urls,
        [string]$OutputFile
    )

    $errors = @()

    foreach ($url in $Urls) {
        try {
            Write-Step "Download attempt (Invoke-WebRequest): $url"
            Invoke-WebRequest -Uri $url -OutFile $OutputFile -UseBasicParsing -TimeoutSec 180
            if (Test-ZipArchiveFile -Path $OutputFile) {
                return $url
            }
            $errors += "Invoke-WebRequest $url -> downloaded file is not a valid ZIP archive"
            Remove-Item -Path $OutputFile -Force -ErrorAction SilentlyContinue
        } catch {
            $errors += "Invoke-WebRequest $url -> $($_.Exception.Message)"
        }

        if (Get-Command 'curl.exe' -ErrorAction SilentlyContinue) {
            try {
                Write-Step "Download attempt (curl.exe): $url"
                & curl.exe -L --fail --connect-timeout 20 --max-time 300 -o $OutputFile $url *> $null
                if (($LASTEXITCODE -eq 0) -and (Test-ZipArchiveFile -Path $OutputFile)) {
                    return $url
                }
                if ($LASTEXITCODE -eq 0) {
                    $errors += "curl.exe $url -> downloaded file is not a valid ZIP archive"
                } else {
                    $errors += "curl.exe $url -> exit code $LASTEXITCODE"
                }
                Remove-Item -Path $OutputFile -Force -ErrorAction SilentlyContinue
            } catch {
                $errors += "curl.exe $url -> $($_.Exception.Message)"
            }
        }
    }

    throw "Unable to download FRP archive. Tried URLs:`n$($errors -join "`n")"
}

function Get-FrpcFromZipArchive {
    param(
        [string]$ZipPath,
        [string]$ExtractDir
    )

    if (-not (Test-ZipArchiveFile -Path $ZipPath)) {
        throw "Invalid FRP archive (not a ZIP): $ZipPath"
    }

    if (Test-Path $ExtractDir) {
        Remove-Item -Path $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force
    $frpcSource = Get-ChildItem -Path $ExtractDir -Recurse -Filter 'frpc.exe' -File | Select-Object -First 1
    if (-not $frpcSource) {
        throw 'frpc.exe not found in the provided ZIP archive.'
    }

    return $frpcSource.FullName
}

function Set-OrAddEnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    if (-not (Test-Path $Path)) {
        New-Item -ItemType File -Path $Path -Force | Out-Null
    }

    $lines = Get-Content -Path $Path -ErrorAction SilentlyContinue
    if ($null -eq $lines) {
        $lines = @()
    }

    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$Name\s*=") {
            $lines[$i] = "$Name=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += "$Name=$Value"
    }

    $content = ($lines -join [Environment]::NewLine)
    if ($content.Length -gt 0) {
        $content += [Environment]::NewLine
    }
    Write-TextUtf8NoBom -Path $Path -Content $content
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Test-FileUnlocked {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $true
    }

    $stream = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        return $true
    } catch {
        return $false
    } finally {
        if ($stream) {
            $stream.Dispose()
        }
    }
}

function Ensure-FrpcBinaryWritable {
    param(
        [string]$Path,
        [bool]$IsAdmin
    )

    if (-not (Test-Path $Path)) {
        return
    }

    # Stop detached/manual frpc processes first.
    $frpcProcesses = Get-Process -Name 'frpc' -ErrorAction SilentlyContinue
    if ($frpcProcesses) {
        $frpcProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    # If service exists and we're elevated, stop it too.
    $svc = Get-Service -Name 'frpc' -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Stopped' -and $IsAdmin) {
        sc.exe stop frpc | Out-Null
    }

    for ($i = 0; $i -lt 12; $i++) {
        if (Test-FileUnlocked -Path $Path) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw "Cannot overwrite $Path because it is still in use. Close frpc terminals and stop 'frpc' service, then retry."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$runtimeDir = Join-Path $repoRoot '.runtime'
$backendEnv = Join-Path $repoRoot 'backend\.env'
$backendEnvExample = Join-Path $repoRoot 'backend\.env.example'

if (-not (Test-Path $backendEnv) -and (Test-Path $backendEnvExample)) {
    Copy-Item -Path $backendEnvExample -Destination $backendEnv
}

$wwwDomain = if ($Domain.ToLowerInvariant().StartsWith('www.')) { $Domain } else { "www.$Domain" }
$publicOrigin = "https://$Domain"
$isAdminSession = Test-IsAdmin

Write-Step 'Preparing directories'
New-Item -ItemType Directory -Path $FrpDir -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

$frpcExe = Join-Path $FrpDir 'frpc.exe'
Ensure-FrpcBinaryWritable -Path $frpcExe -IsAdmin $isAdminSession
if ($FrpcExePath) {
    Write-Step "Using local frpc.exe: $FrpcExePath"
    if (-not (Test-Path $FrpcExePath)) {
        throw "Local frpc.exe not found: $FrpcExePath"
    }
    Copy-Item -Path $FrpcExePath -Destination $frpcExe -Force
} elseif ($FrpZipPath) {
    Write-Step "Using local FRP ZIP archive: $FrpZipPath"
    if (-not (Test-Path $FrpZipPath)) {
        throw "Local FRP ZIP not found: $FrpZipPath"
    }

    $tmpExtract = Join-Path $env:TEMP "frp_$FrpVersion"
    $frpcSource = Get-FrpcFromZipArchive -ZipPath $FrpZipPath -ExtractDir $tmpExtract
    Copy-Item -Path $frpcSource -Destination $frpcExe -Force
} else {
    Enable-Tls12
    Write-Step "Downloading frpc v$FrpVersion"
    $tmpZip = Join-Path $env:TEMP "frp_$FrpVersion.zip"
    $tmpExtract = Join-Path $env:TEMP "frp_$FrpVersion"
    if (Test-Path $tmpExtract) {
        Remove-Item -Path $tmpExtract -Recurse -Force -ErrorAction SilentlyContinue
    }

    $archiveUrls = @(
        "https://github.com/fatedier/frp/releases/download/v$FrpVersion/frp_${FrpVersion}_windows_amd64.zip",
        "https://ghproxy.com/https://github.com/fatedier/frp/releases/download/v$FrpVersion/frp_${FrpVersion}_windows_amd64.zip",
        "https://mirror.ghproxy.com/https://github.com/fatedier/frp/releases/download/v$FrpVersion/frp_${FrpVersion}_windows_amd64.zip"
    )

    $usedUrl = Download-FileWithFallback -Urls $archiveUrls -OutputFile $tmpZip
    Write-Host "Downloaded from: $usedUrl"

    $frpcSource = Get-FrpcFromZipArchive -ZipPath $tmpZip -ExtractDir $tmpExtract
    Copy-Item -Path $frpcSource -Destination $frpcExe -Force
}

Write-Step 'Writing frpc.toml'
$frpcConfig = Join-Path $FrpDir 'frpc.toml'
$toml = @"
serverAddr = "$ServerIp"
serverPort = $ServerPort

[auth]
method = "token"
token = "$Token"

[[proxies]]
name = "$ProxyName"
type = "http"
localIP = "127.0.0.1"
localPort = $LocalPort
customDomains = ["$Domain", "$wwwDomain"]
"@
Write-TextUtf8NoBom -Path $frpcConfig -Content $toml

Write-Step 'Updating backend/.env for no-tunnel mode'
Set-OrAddEnvValue -Path $backendEnv -Name 'PUBLIC_ORIGIN' -Value $publicOrigin
Set-OrAddEnvValue -Path $backendEnv -Name 'USE_CLOUDFLARED' -Value 'false'

if ($InstallService) {
    if (-not $isAdminSession) {
        throw 'Run PowerShell as Administrator to install startup task.'
    }

    # Remove legacy Windows service if it exists (frpc is not a native service binary).
    $legacyService = Get-Service -Name 'frpc' -ErrorAction SilentlyContinue
    if ($legacyService) {
        sc.exe stop frpc | Out-Null
        Start-Sleep -Seconds 1
        sc.exe delete frpc | Out-Null
        Start-Sleep -Seconds 1
    }

    Write-Step 'Installing frpc startup task (Task Scheduler)'
    Import-Module ScheduledTasks -ErrorAction Stop

    Unregister-ScheduledTask -TaskName 'frpc' -Confirm:$false -ErrorAction SilentlyContinue

    $taskAction = New-ScheduledTaskAction -Execute $frpcExe -Argument "-c $frpcConfig"
    $taskTrigger = New-ScheduledTaskTrigger -AtStartup
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable

    Register-ScheduledTask -TaskName 'frpc' -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Force | Out-Null

    if ($StartService) {
        Start-ScheduledTask -TaskName 'frpc'
        Start-Sleep -Seconds 1
    }
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
Write-Host "frpc binary:  $frpcExe"
Write-Host "frpc config:  $frpcConfig"
Write-Host "Public origin: $publicOrigin"
Write-Host "Proxy name:    $ProxyName"
Write-Host ''
Write-Host 'Next steps:'
Write-Host '  1) Start app stack: .\start-server.ps1 -NoTunnel'
if ($InstallService) {
    Write-Host '  2) Check task: Get-ScheduledTask -TaskName frpc'
    Write-Host '  3) Check process: tasklist | findstr /I frpc'
} else {
    Write-Host "  2) Run tunnel manually: `"$frpcExe`" -c `"$frpcConfig`""
}
