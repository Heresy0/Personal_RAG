[CmdletBinding()]
param([Parameter(Position=0)][ValidateSet('enable','disable','status')][string]$Action='status')
. (Join-Path $PSScriptRoot 'openclaw-common.ps1')
if (-not $IsWindows) { throw 'Windows Task Scheduler is required.' }
$context=Get-ClawContext
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$bytes=[Text.Encoding]::UTF8.GetBytes($clawProjectRoot.ToLowerInvariant()+$identity)
$suffix=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).Substring(0,12)
$taskName="PersonalRAG-OpenClaw-$suffix"
if ($Action -eq 'disable') {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop }
    Write-Host 'Removed only this repository user-logon task. Running gateway was not stopped.'
    return
}
if ($Action -eq 'status') {
    Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Select-Object TaskName,State
    return
}
$pwsh=(Get-Command pwsh -ErrorAction Stop).Source
$entry=Join-Path $PSScriptRoot 'openclaw-startup.ps1'
$taskAction=New-ScheduledTaskAction -Execute $pwsh -Argument "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File `"$entry`"" -WorkingDirectory $clawProjectRoot
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description 'Personal_RAG Weixin bridge; original desktop session, private persisted queue' -Force | Out-Null
Write-Host "Enabled $taskName at this user's Windows logon. No password stored; no auto-login configured."
