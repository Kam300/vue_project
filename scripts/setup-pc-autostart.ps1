[CmdletBinding()]
param(
    [string]$TaskName = 'familyone-stack-startup',
    [string]$WatchdogRunName = 'familyone-stack-watchdog',
    [int]$DelaySeconds = 45
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Set-RunRegistryEntry {
    param(
        [string]$Name,
        [string]$Command
    )

    $runKey = 'HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
    & reg.exe add $runKey /v $Name /t REG_SZ /d $Command /f | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to write HKCU Run entry '$Name'."
    }
}

function Start-HelperNow {
    param([string]$Arguments)

    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $Arguments -WindowStyle Hidden | Out-Null
    } catch {
        Write-Host "Could not start helper immediately: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$bootScript = Join-Path $PSScriptRoot 'start-stack-on-boot.ps1'
$watchdogScript = Join-Path $PSScriptRoot 'start-stack-if-needed.ps1'

if (-not (Test-Path $bootScript)) {
    throw "Boot script not found: $bootScript"
}
if (-not (Test-Path $watchdogScript)) {
    throw "Watchdog script not found: $watchdogScript"
}

Import-Module ScheduledTasks -ErrorAction Stop

$actionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$bootScript`" -DelaySeconds $DelaySeconds"
$watchdogArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`" -DelaySeconds 15"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if (Test-IsAdmin) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Created startup task '$TaskName' for SYSTEM (AtStartup)." -ForegroundColor Green
} else {
    try {
        $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        Write-Host "Created logon task '$TaskName' for $currentUser (AtLogOn)." -ForegroundColor Yellow
    } catch {
        Write-Host 'Task Scheduler is unavailable without admin rights. Will rely on HKCU Run watchdog after user logon.' -ForegroundColor Yellow
    }

    Write-Host 'Run PowerShell as Administrator and re-run this script if you want true boot startup before login.' -ForegroundColor Yellow
}

Set-RunRegistryEntry -Name $WatchdogRunName -Command "powershell.exe $watchdogArgs"
Write-Host "Created HKCU Run watchdog '$WatchdogRunName' for self-healing after logon." -ForegroundColor Green

Start-HelperNow -Arguments $watchdogArgs

Write-Host "Task action: powershell.exe $actionArgs"
Write-Host "Watchdog action: powershell.exe $watchdogArgs"
Write-Host "Project root: $repoRoot"
