# Optional Windows bridge; does not start Docker, overwrite global Codex config, or restart any gateway.
[CmdletBinding()]
param([switch]$InitOnly)
. (Join-Path $PSScriptRoot 'openclaw-common.ps1')
if (-not $IsWindows -or $PSVersionTable.PSVersion.Major -lt 7) { throw 'Use PowerShell 7 on Windows.' }
$initialized = Invoke-ClawConfig -Arguments @('init')
if ($initialized.created -or $InitOnly) {
    Write-Host 'Edit config/openclaw.local.json: fill model; codexPath may be empty for automatic discovery.'
    Write-Host 'Then run scripts/setup-openclaw.ps1 again. Existing settings were preserved.'
    return
}
$settings = Invoke-ClawConfig -Arguments @('settings')
$context = @{Root=$settings.runtime; Settings=$settings}
Assert-ClawStopped $context
if (-not (Test-Path -LiteralPath (Join-Path $clawProjectRoot '.env'))) { throw 'Run setup-docker.ps1 first.' }
$pluginConfig = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.config/personal-rag/plugin.json'
Invoke-ClawConfig -Arguments @('plugin','--plugin-config',$pluginConfig) | Out-Null
$databaseContainer = & docker compose --project-directory $clawProjectRoot -f (Join-Path $clawProjectRoot 'compose.yaml') ps --status running -q postgres
if ($LASTEXITCODE -ne 0 -or -not $databaseContainer) { throw 'Knowledge database is not running; deploy Docker first.' }
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) { throw 'Install Node.js 24+ and reopen PowerShell.' }
$nodePath = $nodeCommand.Source
$nodeVersion = & $nodePath --version
if ($LASTEXITCODE -ne 0 -or [int]($nodeVersion.TrimStart('v').Split('.')[0]) -lt 24) { throw 'Node.js 24+ is required.' }
$codexPath = $settings.codexPath
if (-not $codexPath) {
    $codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
    if ($codexCommand) { $codexPath = $codexCommand.Source }
    elseif ($env:LOCALAPPDATA) {
        $bundledRoot = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
        if (Test-Path -LiteralPath $bundledRoot) {
            $found = Get-ChildItem -LiteralPath $bundledRoot -Filter codex.exe -Recurse -File | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
            if ($found) { $codexPath = $found.FullName }
        }
    }
}
if (-not $codexPath -or -not (Test-Path -LiteralPath $codexPath -PathType Leaf)) { throw 'Set codexPath to your codex.exe full path.' }
& $codexPath login status *> $null
if ($LASTEXITCODE -ne 0) { throw 'Log in to your own Codex first; this script never copies credentials.' }
$prepareArgs = @('prepare','--codex-path',$codexPath,'--node-path',$nodePath)
if (-not (Test-Path -LiteralPath (Join-Path $settings.runtime 'codex-install-receipt.json'))) { $prepareArgs += '--bootstrap' }
Invoke-ClawConfig -Arguments $prepareArgs | Out-Null
$context = Get-ClawContext
try {
Set-ClawEnvironment $context
$npm = Get-Command npm.cmd -ErrorAction Stop
$dependenciesReceipt = Join-Path $context.Root 'dependencies-ready.json'
if (-not (Test-Path -LiteralPath $dependenciesReceipt)) {
    if (Test-Path -LiteralPath (Join-Path $context.Root 'bindings-patch.json')) { throw 'Missing dependency receipt for a patched runtime; inspect before reinstalling.' }
    $installCommand = if (Test-Path -LiteralPath (Join-Path $context.Root 'runtime/package-lock.json')) { 'ci' } else { 'install' }
    & $npm.Source $installCommand --prefix (Join-Path $context.Root 'runtime') --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; rerun setup after fixing the network.' }
    # Rebuild only the packages needed by the pinned runtime, never enable all dependency scripts.
    & $npm.Source rebuild --prefix (Join-Path $context.Root 'runtime') openclaw esbuild protobufjs '@google/genai' --ignore-scripts=false
    if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency build failed; inspect npm output.' }
}
foreach ($package in @(@('openclaw','2026.11.3'), @('@tencent-weixin/openclaw-weixin','2.4.10'))) {
    $manifest = Get-Content -LiteralPath (Join-Path $context.Root "runtime/node_modules/$($package[0])/package.json") -Raw | ConvertFrom-Json
    if ($manifest.version -ne $package[1]) { throw 'Unexpected installed dependency version; refusing to overwrite it.' }
}
[IO.File]::WriteAllText($dependenciesReceipt,'{"openclaw":"2026.11.3","weixin":"2.4.10"}')
$receiptPath = Join-Path $context.Root 'codex-install-receipt.json'
if (-not (Test-Path -LiteralPath $receiptPath)) {
    Invoke-ClawCli -Context $context -Arguments @('plugins','install','@openclaw/codex@2026.11.3','--pin','--accept-capabilities')
    [IO.File]::WriteAllText($receiptPath,'{"version":"2026.11.3"}')
} elseif ((Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json).version -ne '2026.11.3') {
    throw 'Unexpected Codex plugin version receipt.'
}
Invoke-ClawConfig -Arguments @('prepare','--codex-path',$codexPath,'--node-path',$nodePath) | Out-Null
$python = Get-ClawPython
$patch = Join-Path $clawProjectRoot 'integrations/openclaw-weixin-bindings/apply.py'
$patchArgs = @('--lab-root',$context.Root,'--port',[string]$context.Settings.port)
if (Test-Path -LiteralPath (Join-Path $context.Root 'bindings-patch.json')) {
    & $python $patch @patchArgs --verify
} else { & $python $patch @patchArgs --apply }
if ($LASTEXITCODE -ne 0) { throw 'Adapter verification or application failed.' }
Invoke-ClawCli -Context $context -Arguments @('plugins','registry','--refresh','--json')
Write-Host 'Setup complete. Next: scripts/openclaw.ps1 login, then scripts/openclaw.ps1 start.'
} finally { Restore-ClawEnvironment }
