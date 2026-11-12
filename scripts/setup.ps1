$ErrorActionPreference = 'Stop'
$ragRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ragRoot
if (-not (Test-Path -LiteralPath '.env')) {
    $ragBytes = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($ragBytes)
    $ragPassword = [Convert]::ToHexString($ragBytes).ToLowerInvariant()
    $ragTemplate = Get-Content -LiteralPath '.env.example' -Raw
    $ragTemplate = $ragTemplate.Replace('REPLACE_ME', $ragPassword)
    $ragTemplate += "`nPERSONAL_RAG_DB_PASSWORD=$ragPassword`n"
    [IO.File]::WriteAllText((Join-Path $ragRoot '.env'), $ragTemplate)
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv 创建失败' }
}
& .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw '锁定依赖安装失败' }
& .venv/Scripts/python.exe -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
docker compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw '独立 PostgreSQL 启动失败' }
& .venv/Scripts/python.exe -m personal_rag.cli init
if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败' }
if (-not (Test-Path -LiteralPath 'knowledge_workspace/.codex/config.toml')) {
    & .venv/Scripts/python.exe -m personal_rag.cli manager-config
    if ($LASTEXITCODE -ne 0) { throw '管理项目配置失败' }
}
Write-Host '完成。请在 Codex 中打开 knowledge_workspace 为独立项目。'
