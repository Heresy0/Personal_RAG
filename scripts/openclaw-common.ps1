$ErrorActionPreference = 'Stop'
$clawProjectRoot = Split-Path -Parent $PSScriptRoot

function Get-ClawPython {
    $candidate = Join-Path $clawProjectRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Install Python 3.12+; the knowledge base itself still runs in Docker.' }
    & $command.Source -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
    return $command.Source
}

function Invoke-ClawConfig {
    param([string[]]$Arguments)
    $python = Get-ClawPython
    $result = & $python (Join-Path $clawProjectRoot 'scripts/openclaw_config.py') @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'OpenClaw configuration check failed; see the error above.' }
    return ($result | ConvertFrom-Json)
}

function Get-ClawContext {
    $settings = Invoke-ClawConfig -Arguments @('settings')
    $markerPath = Join-Path $settings.runtime 'personal-rag-openclaw.json'
    if (-not (Test-Path -LiteralPath $markerPath)) { throw 'Run scripts/setup-openclaw.ps1 first.' }
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ([IO.Path]::GetFullPath($marker.projectRoot) -ne [IO.Path]::GetFullPath($clawProjectRoot)) { throw 'Runtime belongs to another repository.' }
    if ($marker.port -ne $settings.port) { throw 'Port changed; stop with the old configuration before running setup again.' }
    return @{ Settings=$settings; Root=$settings.runtime; Node=$marker.nodePath; Entry=(Join-Path $settings.runtime 'runtime/node_modules/openclaw/openclaw.mjs') }
}

function Set-ClawEnvironment {
    param($Context)
    $script:clawPreviousEnvironment = @{}
    foreach ($name in @('OPENCLAW_STATE_DIR','OPENCLAW_CONFIG_PATH','OPENCLAW_NO_RESPAWN','npm_config_cache','PATH')) {
        $script:clawPreviousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
    }
    $env:OPENCLAW_STATE_DIR = Join-Path $Context.Root 'state'
    $env:OPENCLAW_CONFIG_PATH = Join-Path $Context.Root 'state/openclaw.json'
    $env:OPENCLAW_NO_RESPAWN = '1'
    $env:npm_config_cache = Join-Path $Context.Root 'npm-cache'
    $env:PATH = (Split-Path -Parent $Context.Node) + [IO.Path]::PathSeparator + $env:PATH
}

function Restore-ClawEnvironment {
    if ($null -ne $script:clawPreviousEnvironment) {
        foreach ($name in $script:clawPreviousEnvironment.Keys) {
            if ($null -eq $script:clawPreviousEnvironment[$name]) {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            } else {
                [Environment]::SetEnvironmentVariable($name,$script:clawPreviousEnvironment[$name],'Process')
            }
        }
    }
}

function Assert-ClawStopped {
    param($Context)
    if (-not $IsWindows) { throw 'These lifecycle scripts currently support Windows PowerShell 7 only.' }
    $pidPath = Join-Path $Context.Root 'gateway.pid'
    if (Test-Path -LiteralPath $pidPath) {
        $recorded = [int](Get-Content -LiteralPath $pidPath -Raw)
        if (Get-Process -Id $recorded -ErrorAction SilentlyContinue) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $recorded"
            $identityContext = $Context
            if (-not $Context.Node) {
                $markerPath = Join-Path $Context.Root 'personal-rag-openclaw.json'
                if (Test-Path -LiteralPath $markerPath) {
                    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
                    $identityContext = @{Node=$marker.nodePath;Entry=(Join-Path $Context.Root 'runtime/node_modules/openclaw/openclaw.mjs')}
                }
            }
            if ($identityContext.Node -and (Test-ClawProcessIdentity $identityContext $process)) { throw 'This managed gateway is still running; stop it before maintenance.' }
            Write-Warning 'Recorded PID was reused by a different process. It will be left unchanged; checking the configured port.'
        }
    }
    if (Get-NetTCPConnection -LocalPort $Context.Settings.port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $($Context.Settings.port) is occupied; no process was stopped."
    }
}

function Invoke-ClawCli {
    param($Context, [string[]]$Arguments)
    & $Context.Node $Context.Entry --profile personal-rag-suite @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'OpenClaw command failed; inspect its output. No policies were bypassed.' }
}

function Test-ClawProcessIdentity {
    param($Context, $Process)
    return ($null -ne $Process -and $Process.ExecutablePath -eq $Context.Node -and
        $Process.CommandLine.Contains($Context.Entry) -and
        $Process.CommandLine.Contains('--profile personal-rag-suite') -and
        $Process.CommandLine -match '(?:^|\s)gateway\s+run(?:\s|$)')
}
