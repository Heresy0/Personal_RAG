[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9][a-z0-9_-]{0,55}$')][string]$Name,
    [switch]$Write
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'docker-common.ps1')
$ragRoot = Split-Path -Parent $PSScriptRoot
$ragPolicy = Join-Path $ragRoot "config/connections/$Name.toml"
if (Test-Path -LiteralPath $ragPolicy) { throw '该连接已存在，未覆盖' }
$ragMode = if ($Write) { 'readwrite' } else { 'read' }
$ragReadSpaces = "[`"general`", `"project-$Name`"]"
$ragWriteSpaces = if ($Write) { $ragReadSpaces } else { '[]' }
$ragContent = "name = `"$Name`"`nread_spaces = $ragReadSpaces`nwrite_spaces = $ragWriteSpaces`nmaximum_mode = `"$ragMode`"`ninitial_mode = `"off`"`nadmin = false`n"
[void][IO.Directory]::CreateDirectory((Split-Path -Parent $ragPolicy))
[IO.File]::WriteAllText($ragPolicy, $ragContent)
$ragSnippet = Join-Path $ragRoot "connections/$Name.codex.toml"
Write-RagDockerCodexConfig -RagRoot $ragRoot -ConnectionName $Name -Destination $ragSnippet
Write-Host "已生成 $ragSnippet；合并到目标项目的 .codex/config.toml。默认关闭。"
