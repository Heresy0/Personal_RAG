[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{0,63}$')][string]$Connection = 'plugin-memory',
    [string[]]$Spaces = @('general', 'inbox', 'learning', 'work', 'life'),
    [switch]$ReadOnly,
    [string]$ConfigPath,
    [string]$CodexPath,
    [switch]$SkipRegistration
)
$ErrorActionPreference = 'Stop'
$ragRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $ragRoot '.env'))) {
    throw '先运行 scripts/setup-docker.ps1 初始化本机知识库。'
}
if ($Connection -eq 'manager') { throw '普通会话插件不能使用管理连接' }
if (-not $Spaces.Count) { throw '至少选择一个资料空间' }
foreach ($ragSpace in $Spaces) {
    if ($ragSpace -cnotmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { throw '资料空间名称无效' }
}
$ragPolicyPath = Join-Path $ragRoot "config/connections/$Connection.toml"
if (-not (Test-Path -LiteralPath $ragPolicyPath)) {
    $ragMode = if ($ReadOnly) { 'read' } else { 'readwrite' }
    $ragSpacesJson = ConvertTo-Json -InputObject @($Spaces | Select-Object -Unique) -Compress
    $ragPolicy = "name = `"$Connection`"`nspaces = $ragSpacesJson`nmaximum_mode = `"$ragMode`"`ninitial_mode = `"off`"`nadmin = false`n"
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $ragPolicyPath))
    [IO.File]::WriteAllText($ragPolicyPath, $ragPolicy)
} else {
    $ragExisting = Get-Content -LiteralPath $ragPolicyPath -Raw
    if ($ragExisting -match '(?m)^\s*admin\s*=\s*true') { throw '插件连接不能具有管理权限' }
    Write-Host '保留已有连接范围与读写权限；修改范围请编辑本机连接配置。'
}
if (-not $ConfigPath) {
    $ragUserProfile = [Environment]::GetFolderPath('UserProfile')
    $ConfigPath = Join-Path $ragUserProfile '.config/personal-rag/plugin.json'
}
$ragLocalConfiguration = @{ projectRoot = $ragRoot; connection = $Connection } | ConvertTo-Json
[void][IO.Directory]::CreateDirectory((Split-Path -Parent ([IO.Path]::GetFullPath($ConfigPath))))
if (Test-Path -LiteralPath $ConfigPath) {
    Copy-Item -LiteralPath $ConfigPath -Destination "$ConfigPath.backup-$(Get-Date -Format 'yyyyMMddHHmmssfff')"
}
[IO.File]::WriteAllText(([IO.Path]::GetFullPath($ConfigPath)), $ragLocalConfiguration)
if (-not $SkipRegistration) {
    if (-not $CodexPath) {
        $ragCodexCommand = Get-Command codex -ErrorAction SilentlyContinue
        if ($ragCodexCommand) { $CodexPath = $ragCodexCommand.Source }
    }
    if (-not $CodexPath -and $env:LOCALAPPDATA) {
        $ragBundledDirectory = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
        if (Test-Path -LiteralPath $ragBundledDirectory) {
            $ragBundledCommand = Get-ChildItem -LiteralPath $ragBundledDirectory -Filter codex.exe -Recurse -File |
                Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
            if ($ragBundledCommand) { $CodexPath = $ragBundledCommand.FullName }
        }
    }
    if (-not $CodexPath) { throw '未找到 codex CLI。可用 -CodexPath 指定，或先用 -SkipRegistration 配置后在桌面插件目录注册仓库源。' }
    & $CodexPath plugin marketplace add $ragRoot --json
    if ($LASTEXITCODE -ne 0) { throw '插件源注册失败' }
    & $CodexPath plugin add 'personal-memory@personal-rag' --json
    if ($LASTEXITCODE -ne 0) { throw '插件安装失败' }
}
Write-Host '个人知识库插件已配置。重启Codex或新开会话，在＋号/插件选择器中搜索“个人知识库”。'
Write-Host "本机配置：$ConfigPath；连接范围：$ragPolicyPath"
