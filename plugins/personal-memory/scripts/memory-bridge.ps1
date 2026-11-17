# Host-side MCP endpoint. Requires only PowerShell 7 and Docker, no host Python/Node.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9_-]{0,63}$')][string]$Connection,
    [string]$BackendCommand = 'docker',
    [string[]]$BackendPrefixArgs = @(),
    [ValidateRange(1, 300)][int]$BackendStartupTimeoutSec = 15,
    [ValidateRange(1, 600)][int]$ToolTimeoutSec = 180
)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$policyPath = Join-Path $ProjectRoot "config/connections/$Connection.toml"
$policy = [IO.File]::ReadAllText($policyPath)
$policyHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($policy)))
# This bridge is deliberately ordinary-plugin only. The real backend enforces all
# read/write spaces and validates TOML; never advertise or forward admin tools.
if ($Connection -eq 'manager' -or $policy -match '(?m)^\s*admin\s*=\s*true\b') {
    throw '普通插件不能使用管理连接'
}
$maximum = [regex]::Match($policy, '(?m)^\s*maximum_mode\s*=\s*["''](off|read|readwrite)["'']\s*(?:#.*)?$')
if (-not $maximum.Success) { throw '连接 maximum_mode 无效' }
$catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tool-catalog.json') -Raw | ConvertFrom-Json -AsHashtable
$tools = @($catalog.tools | Where-Object { $maximum.Groups[1].Value -eq 'readwrite' -or $_.name -notin @('capture_note','append_note') })
$allowed = @($tools | ForEach-Object { $_.name })
$script:backend = $null
$script:stderrDrain = $null
$script:backendName = $null
$script:nextAttempt = [DateTime]::MinValue
$script:backendSerial = 0
$script:protocolVersion = '2025-11-25'
$instance = [guid]::NewGuid().ToString('N')
$logDirectory = Join-Path $ProjectRoot 'logs/plugin'
[void][IO.Directory]::CreateDirectory($logDirectory)
$logPath = Join-Path $logDirectory ("bridge-$instance.jsonl")

function Write-BridgeLog([string]$Event) {
    # Metadata only: never log body, tool arguments, outputs, environment or stderr.
    try {
        [IO.File]::AppendAllText($logPath, ((@{time=[DateTime]::UtcNow.ToString('o');event=$Event;generation=$script:backendSerial} | ConvertTo-Json -Compress) + "`n"))
    } catch { } # Logging failure must not corrupt or terminate the MCP stream.
}
function Send-BridgeMessage($Message) {
    [Console]::Out.WriteLine(($Message | ConvertTo-Json -Depth 100 -Compress))
    [Console]::Out.Flush()
}
function Stop-MemoryBackend {
    if ($script:backend) {
        try { $script:backend.StandardInput.Close() } catch { }
        try { if (-not $script:backend.HasExited) { $script:backend.Kill($true) } } catch { }
        $script:backend.Dispose()
        $script:backend = $null
    }
    if ($script:backendName) {
        # Only our exact per-generation one-off container. No shared services.
        try {
            $cleanup = [Diagnostics.ProcessStartInfo]::new('docker')
            $cleanup.UseShellExecute = $false; $cleanup.CreateNoWindow = $true
            $cleanup.RedirectStandardOutput = $true; $cleanup.RedirectStandardError = $true
            foreach ($arg in @('rm','-f',$script:backendName)) { $cleanup.ArgumentList.Add($arg) }
            $p = [Diagnostics.Process]::Start($cleanup)
            $out = $p.StandardOutput.ReadToEndAsync(); $err = $p.StandardError.ReadToEndAsync()
            if (-not $p.WaitForExit(3000)) { $p.Kill($true) }
            $p.Dispose()
        } catch { }
        $script:backendName = $null
    }
}
function Invoke-BackendRpc([string]$Method, $Params, [int]$TimeoutSec) {
    $id = 'bridge-' + [guid]::NewGuid().ToString('N')
    $request = @{jsonrpc='2.0';id=$id;method=$Method;params=$Params}
    $script:backend.StandardInput.WriteLine(($request | ConvertTo-Json -Depth 100 -Compress))
    $script:backend.StandardInput.Flush()
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    while ($true) {
        $remaining = [int][Math]::Max(1, ($deadline - [DateTime]::UtcNow).TotalMilliseconds)
        if ($remaining -le 1) { throw 'backend_timeout' }
        $read = $script:backend.StandardOutput.ReadLineAsync()
        if (-not $read.Wait($remaining)) { throw 'backend_timeout' }
        $line = $read.Result
        if ($null -eq $line) { throw 'backend_disconnected' }
        $response = ConvertFrom-Json -InputObject $line -AsHashtable
        if ($response.ContainsKey('id') -and $response.id -eq $id) { return $response }
        if ($response.ContainsKey('id') -and $response.ContainsKey('method')) {
            # No backend-initiated sampling/elicitation permissions are delegated.
            $reply = @{jsonrpc='2.0';id=$response.id;error=@{code=-32601;message='Backend requests are not supported'}}
            $script:backend.StandardInput.WriteLine(($reply | ConvertTo-Json -Depth 100 -Compress))
            $script:backend.StandardInput.Flush()
        }
        # Backend notifications do not change this bridge's fixed tool catalog.
    }
}
function Start-MemoryBackend {
    if ($script:backend -and -not $script:backend.HasExited) { return }
    Stop-MemoryBackend
    if ([DateTime]::UtcNow -lt $script:nextAttempt) { throw 'backend_retry_backoff' }
    $script:backendSerial++
    $psi = [Diagnostics.ProcessStartInfo]::new($BackendCommand)
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $psi.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    # MCP hosts often inherit only a minimal Windows environment. Docker uses
    # ProgramData/ProgramFiles to discover the Compose CLI plugin; without them
    # even a healthy engine can fail with "unknown flag: --project-directory".
    if ($IsWindows) {
        $folders = @{ProgramData='CommonApplicationData';ProgramFiles='ProgramFiles';'ProgramFiles(x86)'='ProgramFilesX86'}
        foreach ($key in $folders.Keys) {
            if (-not $psi.Environment[$key]) {
                $value = [Environment]::GetFolderPath($folders[$key])
                if ($value) { $psi.Environment[$key] = $value }
            }
        }
    }
    foreach ($arg in $BackendPrefixArgs) { $psi.ArgumentList.Add($arg) }
    if ($BackendCommand -eq 'docker') {
        $script:backendName = "personal-rag-plugin-$instance-$($script:backendSerial)"
        $arguments = @('compose','--project-directory',$ProjectRoot,
            '-f',(Join-Path $ProjectRoot 'compose.yaml'),'-f',(Join-Path $ProjectRoot 'compose.docker.yaml'),
            'run','--rm','--no-deps','-T','--name',$script:backendName,'mcp',
            '--connection',"/connections/$Connection.toml",'mcp')
        foreach ($arg in $arguments) { $psi.ArgumentList.Add($arg) }
    }
    $script:backend = [Diagnostics.Process]::Start($psi)
    # Drain stderr asynchronously to avoid pipe deadlock, but do not persist it.
    $script:stderrDrain = $script:backend.StandardError.ReadToEndAsync()
    $hello = Invoke-BackendRpc 'initialize' @{
        protocolVersion=$script:protocolVersion;capabilities=@{};clientInfo=@{name='personal-memory-bridge';version='0.3.2'}
    } $BackendStartupTimeoutSec
    if ($hello.error -or -not $hello.result.serverInfo) { throw 'backend_initialize_failed' }
    $script:backend.StandardInput.WriteLine('{"jsonrpc":"2.0","method":"notifications/initialized"}')
    $script:backend.StandardInput.Flush()
    $inventory = Invoke-BackendRpc 'tools/list' @{} $BackendStartupTimeoutSec
    if ($inventory.error) { throw 'backend_catalog_failed' }
    $actual = @($inventory.result.tools | ForEach-Object { $_.name })
    foreach ($name in $allowed) { if ($name -notin $actual) { throw 'backend_catalog_mismatch' } }
    Write-BridgeLog 'backend_ready'
    # Each new backend starts at the connection's initial mode; never silently
    # restore readwrite authorization after a transport failure.
}

Write-BridgeLog 'bridge_ready'
try {
    while ($null -ne ($line = [Console]::In.ReadLine())) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $request = ConvertFrom-Json -InputObject $line -AsHashtable } catch {
            Send-BridgeMessage @{jsonrpc='2.0';id=$null;error=@{code=-32700;message='Parse error'}}
            continue
        }
        if ($request -isnot [System.Collections.IDictionary] -or $request.jsonrpc -ne '2.0' -or $request.method -isnot [string]) {
            Send-BridgeMessage @{jsonrpc='2.0';id=$null;error=@{code=-32600;message='Invalid request'}}
            continue
        }
        if (-not $request.ContainsKey('id')) { continue }
        $id = $request.id
        $result = $null; $rpcError = $null
        switch ($request.method) {
            'initialize' {
                if ($request.params.protocolVersion -in @('2024-11-05','2025-03-26','2025-06-18','2025-11-25')) {
                    $script:protocolVersion = $request.params.protocolVersion
                }
                $result = @{protocolVersion=$script:protocolVersion;capabilities=@{tools=@{listChanged=$false}};
                    serverInfo=@{name='Personal Knowledge Memory Bridge';version='0.3.2'};
                    instructions=($catalog.instructions + ' This host bridge keeps tools available while Docker is offline. Backend errors do not mean the tool is missing. After backend reconnection, check memory_status and explicitly re-enable the required mode. Never blindly replay an interrupted write.')}
            }
            'ping' { $result = @{} }
            'tools/list' { $result = @{tools=$tools} }
            'tools/call' {
                if ($request.params.name -notin $allowed) {
                    $rpcError = @{code=-32602;message='Tool not available in this connection'}
                    break
                }
                try {
                    $nowPolicy = [IO.File]::ReadAllText($policyPath)
                    $nowHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($nowPolicy)))
                    if ($nowHash -ne $policyHash) { throw 'policy_changed' }
                    Start-MemoryBackend
                    $response = Invoke-BackendRpc 'tools/call' $request.params $ToolTimeoutSec
                    if ($response.ContainsKey('error')) { $rpcError = $response.error } else { $result = $response.result }
                } catch {
                    $reason = $_.Exception.Message
                    if ($reason -notin @('backend_timeout','backend_disconnected','backend_retry_backoff','backend_initialize_failed','backend_catalog_failed','backend_catalog_mismatch','policy_changed')) {
                        $reason = 'backend_unavailable_or_interrupted'
                    }
                    Write-BridgeLog $reason
                    Stop-MemoryBackend
                    $script:nextAttempt = [DateTime]::UtcNow.AddSeconds(1)
                    $result = @{isError=$true;content=@(@{type='text';text=(
                        '知识库后端暂不可用或连接中断，未确认本次操作成功。工具连接仍保留；确认 Docker 和数据库就绪后可再次请求，无需切换插件。' +
                        '后端重建会恢复启动配置的初始模式，请先 memory_status 并按需 set_memory_mode。' +
                        '写入可能已执行，不会自动重放；capture_note 重试须沿用原 request_id 和参数，append_note 须先读取核对版本。' +
                        '若修改过连接权限，请刷新插件加载新配置。')})}
                }
            }
            default { $rpcError = @{code=-32601;message='Method not found'} }
        }
        if ($null -ne $rpcError) { Send-BridgeMessage @{jsonrpc='2.0';id=$id;error=$rpcError} }
        else { Send-BridgeMessage @{jsonrpc='2.0';id=$id;result=$result} }
    }
} finally {
    Stop-MemoryBackend
    Write-BridgeLog 'bridge_closed'
}
