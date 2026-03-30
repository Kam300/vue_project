[CmdletBinding()]
param(
    [string]$TaskName = 'familyone-stack-startup',
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

    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name $Name -Value $Command
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$bootScript = Join-Path $PSScriptRoot 'start-stack-on-boot.ps1'

if (-not (Test-Path $bootScript)) {
    throw "Boot script not found: $bootScript"
}

Import-Module ScheduledTasks -ErrorAction Stop

$actionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$bootScript`" -DelaySeconds $DelaySeconds"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if (Test-IsAdmin) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Created startup task '$TaskName' for SYSTEM (AtStartup)." -ForegroundColor Green
} else {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    try {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        Write-Host "Created logon task '$TaskName' for $currentUser (AtLogOn)." -ForegroundColor Yellow
    } catch {
        $command = "powershell.exe $actionArgs"
        Set-RunRegistryEntry -Name $TaskName -Command $command
        Write-Host "Task Scheduler is unavailable without admin rights. Created HKCU Run autostart '$TaskName' instead." -ForegroundColor Yellow
        Write-Host "It will start after user logon: $currentUser" -ForegroundColor Yellow
    }

    Write-Host 'Run PowerShell as Administrator and re-run this script if you want true boot startup before login.' -ForegroundColor Yellow
}

Write-Host "Task action: powershell.exe $actionArgs"
Write-Host "Project root: $repoRoot"
