# Invoked at user logon. Never starts the shared Docker engine or touches enterprise services.
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'openclaw-common.ps1')
$context=Get-ClawContext
$log=Join-Path $context.Root 'logs/startup.log'
try {
    $state=& (Join-Path $PSScriptRoot 'openclaw.ps1') status
    if (-not $state.ManagedProcess) { & (Join-Path $PSScriptRoot 'openclaw.ps1') start *>> $log }
    # The desktop worker keeps newly received messages on disk while PostgreSQL is unavailable.
    for ($attempt=0;$attempt -lt 30;$attempt++) {
        & docker info --format '{{.ServerVersion}}' *> $null
        if ($LASTEXITCODE -eq 0) {
            & docker compose --project-directory $clawProjectRoot -f (Join-Path $clawProjectRoot 'compose.yaml') up -d postgres *>> $log
            if ($LASTEXITCODE -ne 0) { throw 'Personal_RAG PostgreSQL startup failed.' }
            Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Personal_RAG database requested; desktop worker checks health."
            return
        }
        Start-Sleep -Seconds 10
    }
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Docker engine unavailable; received messages remain pending. Start Docker Desktop manually."
} catch {
    Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) $($_.Exception.Message)"
    throw
}
