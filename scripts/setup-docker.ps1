# Requires Docker Desktop / Compose and PowerShell 7; no host Python needed.
[CmdletBinding()]
param([switch]$Build, [switch]$SkipBuild, [string]$Image)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'docker-common.ps1')
$ragRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ragRoot
Initialize-RagDockerEnvironment -RagRoot $ragRoot
if ($Image) {
    if ($Image -cnotmatch '^[a-z0-9][a-z0-9./_:@-]*$') { throw '镜像名称格式无效' }
    $ragEnvPath = Join-Path $ragRoot '.env'
    $ragEnvironment = [IO.File]::ReadAllText($ragEnvPath)
    if ($ragEnvironment -match '(?m)^PERSONAL_RAG_IMAGE=') {
        $ragEnvironment = [regex]::Replace($ragEnvironment, '(?m)^PERSONAL_RAG_IMAGE=[^\r\n]*', "PERSONAL_RAG_IMAGE=$Image")
    } else {
        $ragEnvironment += "`nPERSONAL_RAG_IMAGE=$Image`n"
    }
    [IO.File]::WriteAllText($ragEnvPath, $ragEnvironment)
    $env:PERSONAL_RAG_IMAGE = $Image
}
$ragCompose = @('compose', '-f', 'compose.yaml', '-f', 'compose.docker.yaml')
if ($Build -and $SkipBuild) { throw '-Build 与 -SkipBuild 不能同时使用' }
if ($Build) {
    & docker @ragCompose build mcp
    if ($LASTEXITCODE -ne 0) { throw 'MCP 镜像构建失败' }
} elseif (-not $SkipBuild) {
    & docker @ragCompose pull mcp
    if ($LASTEXITCODE -ne 0) { throw 'MCP 镜像拉取失败，请检查网络及镜像版本' }
}
& docker @ragCompose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw '独立数据库启动失败' }
& docker @ragCompose run --rm --no-deps -T mcp init
if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败' }
$ragConfig = Join-Path $ragRoot 'knowledge_workspace/.codex/config.toml'
if (Test-Path -LiteralPath $ragConfig) {
    $ragBackup = "$ragConfig.backup-$(Get-Date -Format 'yyyyMMddHHmmssfff')"
    Copy-Item -LiteralPath $ragConfig -Destination $ragBackup
}
Write-RagDockerCodexConfig -RagRoot $ragRoot -ConnectionName 'manager' -Destination $ragConfig
Write-Host 'Docker 安装完成。请把 knowledge_workspace 添加到 Codex，并新开会话。'
