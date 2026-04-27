[CmdletBinding()]
param(
    [switch]$TestMode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\FamilyTreeAutostartTray', [ref]$createdNew)
if (-not $createdNew) {
    Write-Host 'Tray helper is already running.'
    exit 0
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$runtimeDir = Join-Path $repoRoot '.runtime'
$pidsFile = Join-Path $runtimeDir 'pids.json'
$startScript = Join-Path $repoRoot 'start-server.ps1'
$stopScript = Join-Path $repoRoot 'stop-server.ps1'
$iconCandidates = @(
    (Join-Path $repoRoot 'public\\favicon.ico'),
    (Join-Path $repoRoot 'dist\\favicon.ico')
)

function Get-ProjectIcon {
    foreach ($candidate in $iconCandidates) {
        if ((Test-Path $candidate) -and [IO.Path]::GetExtension($candidate).Equals('.ico', [System.StringComparison]::OrdinalIgnoreCase)) {
            return [System.Drawing.Icon]::new($candidate)
        }
    }

    return [System.Drawing.SystemIcons]::Application
}

function Test-ServerRunning {
    if (-not (Test-Path $pidsFile)) {
        return $false
    }

    try {
        $payload = Get-Content $pidsFile -Raw | ConvertFrom-Json
    } catch {
        return $false
    }

    foreach ($proc in @($payload.processes)) {
        if ($null -eq $proc.pid) {
            continue
        }

        if (Get-Process -Id ([int]$proc.pid) -ErrorAction SilentlyContinue) {
            return $true
        }
    }

    return $false
}

function Get-StatusText {
    if (Test-ServerRunning) {
        return 'Family Tree: server running'
    }

    return 'Family Tree: autostart enabled'
}

function Get-LaunchUrl {
    return 'http://127.0.0.1:8080'
}

function Start-HiddenPowerShell {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    $argList = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', $ScriptPath
    ) + $Arguments

    Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -WindowStyle Hidden | Out-Null
}

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = Get-ProjectIcon
$statusText = Get-StatusText
$notifyIcon.Text = $statusText.Substring(0, [Math]::Min($statusText.Length, 63))
$notifyIcon.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$openItem = $menu.Items.Add('Open web app')
$openLogsItem = $menu.Items.Add('Open logs')
$startItem = $menu.Items.Add('Start server')
$stopItem = $menu.Items.Add('Stop server')
$menu.Items.Add('-') | Out-Null
$exitItem = $menu.Items.Add('Hide icon')

$openItem.add_Click({
    Start-Process (Get-LaunchUrl) | Out-Null
})

$openLogsItem.add_Click({
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    Start-Process explorer.exe $runtimeDir | Out-Null
})

$startItem.add_Click({
    Start-HiddenPowerShell -ScriptPath $startScript -Arguments @('-NoTunnel')
})

$stopItem.add_Click({
    if (Test-Path $stopScript) {
        Start-HiddenPowerShell -ScriptPath $stopScript
    }
})

$applicationContext = New-Object System.Windows.Forms.ApplicationContext
$exitItem.add_Click({
    $applicationContext.ExitThread()
})

$notifyIcon.add_DoubleClick({
    Start-Process (Get-LaunchUrl) | Out-Null
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.add_Tick({
    $statusText = Get-StatusText
    $notifyIcon.Text = $statusText.Substring(0, [Math]::Min($statusText.Length, 63))
})
$timer.Start()

$notifyIcon.BalloonTipTitle = 'Family Tree'
$notifyIcon.BalloonTipText = 'Autostart is enabled. Tray icon has been added.'
$notifyIcon.ShowBalloonTip(4000)

if ($TestMode) {
    $timer.Stop()
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
    Write-Host 'Tray helper test completed.'
    exit 0
}

try {
    [System.Windows.Forms.Application]::Run($applicationContext)
} finally {
    $timer.Stop()
    $timer.Dispose()
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
