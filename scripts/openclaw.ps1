[CmdletBinding()]
param(
    [Parameter(Position=0)][ValidateSet('login','start','stop','status')][string]$Action = 'status',
    [string]$Account,
    [ValidateRange(10,900)][int]$TimeoutSeconds = 240
)
. (Join-Path $PSScriptRoot 'openclaw-common.ps1')
if (-not $IsWindows -or $PSVersionTable.PSVersion.Major -lt 7) { throw 'Use PowerShell 7 on Windows.' }
$context = Get-ClawContext
try {
Set-ClawEnvironment $context
$pidPath = Join-Path $context.Root 'gateway.pid'

if ($Action -eq 'stop') {
    if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'No managed gateway PID recorded.'; return }
    $gatewayPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $gatewayPid"
    if (-not $process) { Write-Host 'Managed gateway is already stopped.'; return }
    if (-not (Test-ClawProcessIdentity $context $process)) { throw 'Process identity mismatch; nothing was stopped.' }
    Stop-Process -Id $gatewayPid
    Write-Host 'Stopped only this managed gateway. Login and bindings retained.'
    return
}
if ($Action -eq 'status') {
    $process = $null
    if (Test-Path -LiteralPath $pidPath) {
        $gatewayPid = [int](Get-Content -LiteralPath $pidPath -Raw)
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $gatewayPid"
    }
    $owned = Test-ClawProcessIdentity $context $process
    $ready = $false
    if ($owned) { try { $ready = (Invoke-WebRequest "http://127.0.0.1:$($context.Settings.port)/readyz" -TimeoutSec 3).StatusCode -eq 200 } catch {} }
    [pscustomobject]@{ ManagedProcess=$owned; Ready=$ready; Mode=$context.Settings.mode; Port=$context.Settings.port; Runtime=$context.Root }
    return
}
Assert-ClawStopped $context
$python = Get-ClawPython
& $python (Join-Path $clawProjectRoot 'integrations/openclaw-weixin-bindings/apply.py') --lab-root $context.Root --port $context.Settings.port --verify
if ($LASTEXITCODE -ne 0) { throw 'Adapter verification failed; run setup or inspect changed files.' }
if ($Action -eq 'login') {
    $loginArgs = @('channels','login','--channel','openclaw-weixin')
    if ($Account) { $loginArgs += @('--account',$Account) }
    Invoke-ClawCli -Context $context -Arguments $loginArgs
    $ownerArgs = @('owner')
    if ($Account) { $ownerArgs += @('--account',$Account) }
    Invoke-ClawConfig -Arguments $ownerArgs | Out-Null
    Write-Host 'Scanner configured as the owner. Next: scripts/openclaw.ps1 start.'
    return
}
# Require a known logged-in owner before accepting incoming native Codex execution.
$pluginConfig = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.config/personal-rag/plugin.json'
Invoke-ClawConfig -Arguments @('plugin','--plugin-config',$pluginConfig) | Out-Null
$config = Get-Content -LiteralPath (Join-Path $context.Root 'state/openclaw.json') -Raw | ConvertFrom-Json
if (@($config.commands.ownerAllowFrom).Count -ne 1 -or $config.commands.ownerAllowFrom[0] -notmatch '^openclaw-weixin:[A-Za-z0-9_-]+@im\.wechat$') { throw 'Run openclaw.ps1 login first.' }
$gateway = Start-Process -FilePath $context.Node -ArgumentList @(
    ('"'+$context.Entry+'"'),'--profile','personal-rag-suite','gateway','run'
) -WorkingDirectory $context.Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $context.Root 'logs/gateway.stdout.log') -RedirectStandardError (Join-Path $context.Root 'logs/gateway.stderr.log') -PassThru
[IO.File]::WriteAllText($pidPath,[string]$gateway.Id)
Write-Host "Started managed gateway PID=$($gateway.Id); waiting for readiness..."
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    if ($gateway.HasExited) { throw 'Gateway exited; inspect output/openclaw/logs/gateway.stderr.log.' }
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:$($context.Settings.port)/readyz" -TimeoutSec 2).StatusCode -eq 200) {
            if ($context.Settings.mode -eq 'desktop') { Write-Host 'Desktop queue ready. Original thread is configured locally; /wxdesk shows queue status. Desktop permissions are inherited.' }
            else { Write-Host 'Gateway ready. Send a message from your own Weixin; bind existing sessions with /codex bind.' }
            return
        }
    } catch {}
    Start-Sleep -Seconds 1
}
throw 'Readiness timed out. Process was retained; inspect status/logs before another start.'
} finally { Restore-ClawEnvironment }
