# Installed plugin cache location is unrelated to the user's knowledge directory.
[CmdletBinding()]
param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
try {
    if (-not $ConfigPath) { $ConfigPath = $env:PERSONAL_RAG_PLUGIN_CONFIG }
    if (-not $ConfigPath) {
        $ragUserProfile = [Environment]::GetFolderPath('UserProfile')
        $ConfigPath = Join-Path $ragUserProfile '.config/personal-rag/plugin.json'
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw '请先在 Personal_RAG 目录运行 scripts/install-plugin.ps1，配置本机知识库。'
    }
    $ragConfiguration = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    $ragProjectRoot = [IO.Path]::GetFullPath([string]$ragConfiguration.projectRoot)
    $ragConnectionName = [string]$ragConfiguration.connection
    if ($ragConnectionName -cnotmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { throw '插件连接名称无效' }
    foreach ($ragRequired in @('compose.yaml', 'compose.docker.yaml', '.env', "config/connections/$ragConnectionName.toml")) {
        if (-not (Test-Path -LiteralPath (Join-Path $ragProjectRoot $ragRequired) -PathType Leaf)) {
            throw '本机知识库配置不完整，请先运行 setup-docker.ps1。'
        }
    }
    # Keep the host-side MCP transport alive independently of Docker.
    & (Join-Path $PSScriptRoot 'memory-bridge.ps1') -ProjectRoot $ragProjectRoot -Connection $ragConnectionName
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
