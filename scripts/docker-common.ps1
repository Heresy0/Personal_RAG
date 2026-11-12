$ErrorActionPreference = 'Stop'

function Initialize-RagDockerEnvironment {
    param([string]$RagRoot)
    $ragEnvPath = Join-Path $RagRoot '.env'
    if (-not (Test-Path -LiteralPath $ragEnvPath)) {
        $ragBytes = [byte[]]::new(24)
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($ragBytes)
        $ragPassword = [Convert]::ToHexString($ragBytes).ToLowerInvariant()
        $ragTemplate = Get-Content -LiteralPath (Join-Path $RagRoot '.env.example') -Raw
        $ragTemplate = $ragTemplate.Replace('REPLACE_ME', $ragPassword)
        $ragTemplate += "`nPERSONAL_RAG_DB_PASSWORD=$ragPassword`n"
        [IO.File]::WriteAllText($ragEnvPath, $ragTemplate)
    }
    foreach ($ragRelative in @('knowledge_workspace/vault', 'config/connections', 'connections')) {
        [void][IO.Directory]::CreateDirectory((Join-Path $RagRoot $ragRelative))
    }
}

function Write-RagDockerCodexConfig {
    param([string]$RagRoot, [string]$ConnectionName, [string]$Destination)
    if ($ConnectionName -notmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { throw '连接名称无效' }
    $ragArguments = @('compose', '--project-directory', $RagRoot,
        '-f', (Join-Path $RagRoot 'compose.yaml'), '-f', (Join-Path $RagRoot 'compose.docker.yaml'),
        'run', '--rm', '--no-deps', '-T', 'mcp', '--connection', "/connections/$ConnectionName.toml", 'mcp')
    $ragArgsJson = ConvertTo-Json -InputObject $ragArguments -Compress
    $ragContent = "[mcp_servers.personal_memory]`ncommand = `"docker`"`nargs = $ragArgsJson`nenabled = true`nstartup_timeout_sec = 60`ntool_timeout_sec = 120`n"
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Destination))
    [IO.File]::WriteAllText($Destination, $ragContent)
}
