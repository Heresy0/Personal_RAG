[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ragRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ragRoot
if (-not (Test-Path -LiteralPath '.env')) { throw '请先运行setup-docker.ps1。' }
if (-not (Test-Path -LiteralPath 'config/mail.toml')) {
    Copy-Item -LiteralPath 'config/mail.example.toml' -Destination 'config/mail.toml'
}
$ragEnvPath = Join-Path $ragRoot '.env'
$ragText = [IO.File]::ReadAllText($ragEnvPath)
foreach ($ragKey in @('PERSONAL_RAG_MAIL_QQ_AUTH_CODE','PERSONAL_RAG_MAIL_163_AUTH_CODE')) {
    if ($ragText -notmatch "(?m)^$ragKey=") { $ragText += "`n$ragKey=`n" }
}
[IO.File]::WriteAllText($ragEnvPath,$ragText)
Write-Host '已准备本机config/mail.toml（默认disabled）；已有配置与授权码保留。'
Write-Host '请在本机填写邮箱地址、.env授权码后设置enabled=true。尚未连接邮箱或建立基线。'
