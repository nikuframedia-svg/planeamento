param(
 [Parameter(Mandatory=$true)][ValidateSet('cpis','original')][string]$Source,
 [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference='Stop'
$start=Join-Path $PSScriptRoot 'start.ps1'
$name='RAW Importacao '+$Source
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$start`" -Source $Source -Python `"$Python`" -Watch"
$trigger=New-ScheduledTaskTrigger -AtLogOn
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1)) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $name
