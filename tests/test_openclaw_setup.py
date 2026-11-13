"""Configuration/lifecycle contracts use temporary directories, never a live gateway."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('claw_config', REPO/'scripts/openclaw_config.py')
claw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(claw)


@pytest.fixture
def project(tmp_path):
    root = tmp_path/'project with spaces'
    for name in ('config','integrations/openclaw-weixin-bindings','scripts'):
        (root/name).mkdir(parents=True, exist_ok=True)
    for relative in ('config/openclaw.example.json','integrations/openclaw-weixin-bindings/openclaw.example.json',
                     'integrations/openclaw-weixin-bindings/apply.py',
                     'scripts/openclaw_config.py','scripts/openclaw-common.ps1','scripts/setup-openclaw.ps1','scripts/openclaw.ps1'):
        shutil.copy2(REPO/relative, root/relative)
    claw.initialize(root)
    config = root/'config/openclaw.local.json'
    settings = claw.read(config)
    settings['model'] = 'openai/example-model'
    claw.write(config, settings)
    exe = root/'fake executable.exe'
    exe.write_bytes(b'not executed')
    return root, exe


def prepared(project):
    root, exe = project
    result = claw.prepare(root, str(exe), str(exe))
    return root, Path(result['runtime'])


def test_prepare_generates_scoped_config_without_placeholders(project):
    root, runtime = prepared(project)
    value = claw.read(runtime/'state/openclaw.json')
    assert value['gateway']['port'] == 19890
    assert len(value['gateway']['auth']['token']) == 64
    assert value['commands']['ownerAllowFrom'] == []
    app = value['plugins']['entries']['codex']['config']['appServer']
    assert app['sandbox'] == 'workspace-write' and app['approvalPolicy'] == 'on-request'
    assert app['args'][3].endswith(']')
    arguments = json.loads(app['args'][3].split('=',1)[1])
    assert arguments[-1] == (root/'plugins/personal-memory/scripts/start-memory.ps1').as_posix()
    assert 'LAB_ROOT' not in json.dumps(value) and 'MEMORY_LAUNCHER' not in json.dumps(value)
    scripts = claw.read(runtime/'runtime/package.json')['allowScripts']
    assert set(scripts) == {'openclaw@2026.11.3','esbuild@0.28.2','protobufjs@7.6.6','@google/genai@2.27.0'}


def test_repeat_prepare_keeps_token_owner_installer_records_and_accounts(project):
    root, runtime = prepared(project)
    file = runtime/'state/openclaw.json'
    value = claw.read(file)
    token = value['gateway']['auth']['token']
    value['commands']['ownerAllowFrom'] = ['openclaw-weixin:Owner@im.wechat']
    value['plugins']['installs'] = {'codex': {'record': 'keep'}}
    value['channels'] = {'openclaw-weixin': {'accountMetadata': 'keep'}}
    claw.write(file, value)
    credentials = runtime/'state/private-credentials.json'
    credentials.write_bytes(b'private unchanged')
    claw.prepare(root, str(project[1]), str(project[1]))
    after = claw.read(file)
    assert after['gateway']['auth']['token'] == token
    assert after['commands'] == value['commands']
    assert after['plugins']['installs'] == value['plugins']['installs']
    assert after['channels'] == value['channels']
    assert credentials.read_bytes() == b'private unchanged'
    assert list((runtime/'backups').glob('config-*.json'))


def test_bootstrap_does_not_reference_the_uninstalled_codex_plugin(project):
    root, exe = project
    value = claw.prepare(root,str(exe),str(exe),bootstrap=True)
    config = claw.read(Path(value['runtime'])/'state/openclaw.json')
    assert 'codex' not in config['plugins']['entries']
    assert 'codex' not in config['plugins']['allow']
    assert 'mcp' not in config
    claw.prepare(root,str(exe),str(exe))
    assert 'codex' in claw.read(Path(value['runtime'])/'state/openclaw.json')['plugins']['entries']


def test_initialize_never_overwrites_user_settings(project):
    root,_ = project
    before = (root/'config/openclaw.local.json').read_bytes()
    assert claw.initialize(root) is False
    assert (root/'config/openclaw.local.json').read_bytes() == before


@pytest.mark.parametrize('relative', ['../elsewhere','output/../config','output','output/openclaw-lab'])
def test_runtime_escape_and_old_lab_are_rejected(project, relative):
    root, _ = project
    path = root/'config/openclaw.local.json'
    value = claw.read(path); value['runtimeDir'] = relative; claw.write(path, value)
    with pytest.raises(ValueError): claw.settings(root)


def test_refuses_unmanaged_directory_without_modification(project):
    root, exe = project
    other = root/'output/openclaw'
    other.mkdir(parents=True); (other/'existing.json').write_bytes(b'keep')
    with pytest.raises(ValueError, match='unmanaged'): claw.prepare(root, str(exe), str(exe))
    assert [p.name for p in other.iterdir()] == ['existing.json']


def accounts(runtime, entries):
    base = runtime/'state/openclaw-weixin'
    claw.write(base/'accounts.json', list(entries))
    for account, peer in entries.items():
        claw.write(base/'accounts'/f'{account}.json', {'userId': peer, 'token': 'not-real-test-token'})


def test_login_sets_only_the_scanner_as_owner(project):
    root, runtime = prepared(project)
    accounts(runtime, {'example-bot': 'Owner_CASE@im.wechat'})
    assert claw.sync_owner(root) == {'ownerConfigured': True}
    assert claw.read(runtime/'state/openclaw.json')['commands']['ownerAllowFrom'] == ['openclaw-weixin:Owner_CASE@im.wechat']
    assert claw.read(runtime/'state/openclaw-weixin/accounts/example-bot.json')['token'] == 'not-real-test-token'


def test_ambiguous_login_needs_explicit_account(project):
    root, runtime = prepared(project)
    accounts(runtime, {'bot-one': 'One@im.wechat','bot-two': 'Two@im.wechat'})
    before = (runtime/'state/openclaw.json').read_bytes()
    with pytest.raises(ValueError, match='exactly one'): claw.sync_owner(root)
    assert (runtime/'state/openclaw.json').read_bytes() == before
    claw.sync_owner(root, 'bot-two')
    assert claw.read(runtime/'state/openclaw.json')['commands']['ownerAllowFrom'] == ['openclaw-weixin:Two@im.wechat']


def test_login_rejects_path_traversal_without_grant(project):
    root, runtime = prepared(project)
    claw.write(runtime/'state/openclaw-weixin/accounts.json', ['../private'])
    with pytest.raises(ValueError, match='identifier'): claw.sync_owner(root)
    assert claw.read(runtime/'state/openclaw.json')['commands']['ownerAllowFrom'] == []


def test_plugin_must_belong_to_this_repo_and_have_no_admin(project):
    root, _ = project
    file = root/'private-plugin.json'
    policy = root/'config/connections/plugin-memory.toml'
    policy.parent.mkdir(parents=True)
    policy.write_text('admin = false\n', encoding='utf-8')
    claw.write(file, {'projectRoot':str(root),'connection':'plugin-memory'})
    claw.check_plugin(root, file)
    policy.write_text('admin = true\n', encoding='utf-8')
    with pytest.raises(ValueError, match='non-admin'): claw.check_plugin(root, file)
    claw.write(file, {'projectRoot':str(root.parent),'connection':'plugin-memory'})
    with pytest.raises(ValueError, match='different repository'): claw.check_plugin(root, file)


def run_ps(code, root):
    command = shutil.which('pwsh')
    if not command: pytest.skip('PowerShell 7 not available')
    result = subprocess.run([command,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=45)
    assert result.returncode == 0, result.stdout+'\n'+result.stderr
    return result.stdout


def test_powershell_argument_arrays_and_environment_restore(project):
    root, exe = project
    # Use the real helper in a copy of the repo, including paths containing spaces.
    code = '''
    . ./scripts/openclaw-common.ps1
    function Get-ClawPython { return $env:CLAW_TEST_PYTHON }
    $before = $env:OPENCLAW_STATE_DIR
    $pathBefore = $env:PATH
    Invoke-ClawConfig -Arguments @('prepare','--codex-path',$env:CLAW_TEST_EXE,'--node-path',$env:CLAW_TEST_EXE) | Out-Null
    $context = Get-ClawContext
    try { Set-ClawEnvironment $context; if ($env:OPENCLAW_STATE_DIR -eq $before) { throw 'State not isolated' } }
    finally { Restore-ClawEnvironment }
    if ($env:OPENCLAW_STATE_DIR -ne $before -or $env:PATH -ne $pathBefore) { throw 'Environment not restored' }
    $fake = [pscustomobject]@{ExecutablePath=$context.Node;CommandLine='unrelated gateway'}
    if (Test-ClawProcessIdentity $context $fake) { throw 'Unrelated process accepted' }
    '''
    previous = {key:os.environ.get(key) for key in ('CLAW_TEST_PYTHON','CLAW_TEST_EXE')}
    try:
        os.environ['CLAW_TEST_PYTHON'] = sys.executable
        os.environ['CLAW_TEST_EXE'] = str(exe)
        run_ps(code, root)
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_powershell_entry_scripts_parse(project):
    code = '''
    $failed = $false
    foreach ($file in @('setup-openclaw.ps1','openclaw.ps1','openclaw-common.ps1')) {
        $tokens=$null; $parseErrors=$null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) "scripts/$file"),[ref]$tokens,[ref]$parseErrors) | Out-Null
        if ($parseErrors.Count) { $parseErrors | Write-Output; $failed=$true }
    }
    if ($failed) { exit 1 }
    '''
    run_ps(code, project[0])


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows lifecycle entry points')
def test_lifecycle_login_start_status_stop_in_isolation(project, monkeypatch):
    root, runtime = prepared(project)
    # Real patch verification with synthetic files; no vendor code is executed.
    patch_spec = importlib.util.spec_from_file_location('patch_fixture',REPO/'integrations/openclaw-weixin-bindings/apply.py')
    module = importlib.util.module_from_spec(patch_spec);patch_spec.loader.exec_module(module)
    deployed = {}
    plugin = runtime/'runtime/node_modules/@tencent-weixin/openclaw-weixin'
    for name in {*module.EXPECTED,*module.NEW_FILES}:
        path = plugin/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'test fixture')
        deployed[name] = module.digest(b'test fixture')
    claw.write(runtime/'bindings-patch.json', {'deployed':deployed})
    monkeypatch.setenv('CLAW_TEST_PYTHON',sys.executable)
    common = root/'scripts/openclaw-common.ps1'
    with common.open('a',encoding='utf-8') as stream:
        stream.write('''
function Get-ClawPython { return $env:CLAW_TEST_PYTHON }
$script:originalConfigFunction = ${function:Invoke-ClawConfig}
function Invoke-ClawConfig {
    param([string[]]$Arguments)
    if ($Arguments[0] -eq 'plugin') { return @{ordinaryPlugin=$true} }
    return (& $script:originalConfigFunction -Arguments $Arguments)
}
function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction) }
function Get-Process { param($Id,$ErrorAction) }
function Invoke-ClawCli {
    param($Context,[string[]]$Arguments)
    if ($Arguments[0] -ne 'channels') { throw 'Unexpected CLI command' }
    $dir = Join-Path $Context.Root 'state/openclaw-weixin'
    New-Item -ItemType Directory -Path (Join-Path $dir 'accounts') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $dir 'accounts.json'),'["test-bot"]')
    [IO.File]::WriteAllText((Join-Path $dir 'accounts/test-bot.json'),'{"userId":"Scanner@im.wechat","token":"test-only"}')
}
function Start-Process {
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)
    if ($WindowStyle -ne 'Hidden') { throw 'Background window must be hidden' }
    [IO.File]::WriteAllText((Join-Path $WorkingDirectory 'start-arguments.json'),(ConvertTo-Json -InputObject $ArgumentList))
    return [pscustomobject]@{Id=424242;HasExited=$false}
}
function Invoke-WebRequest { param($Uri,$TimeoutSec) return [pscustomobject]@{StatusCode=200} }
function Get-CimInstance {
    param($ClassName,$Filter)
    return [pscustomobject]@{ExecutablePath=$context.Node;CommandLine=($context.Entry+' --profile personal-rag-suite gateway run')}
}
function Stop-Process { param($Id) [IO.File]::WriteAllText((Join-Path $context.Root 'stopped.txt'),[string]$Id) }
''')
    result = run_ps('''
    $before = $env:OPENCLAW_STATE_DIR
    & ./scripts/openclaw.ps1 login
    & ./scripts/openclaw.ps1 start -TimeoutSeconds 10
    $status = & ./scripts/openclaw.ps1 status
    if (-not $status.ManagedProcess -or -not $status.Ready) { throw 'Managed gateway not ready' }
    & ./scripts/openclaw.ps1 stop
    if ($env:OPENCLAW_STATE_DIR -ne $before) { throw 'Caller environment changed' }
    ''',root)
    assert 'Scanner configured' in result and 'Gateway ready' in result
    assert (runtime/'gateway.pid').read_text() == '424242'
    assert (runtime/'stopped.txt').read_text() == '424242'
    assert claw.read(runtime/'state/openclaw.json')['commands']['ownerAllowFrom'] == ['openclaw-weixin:Scanner@im.wechat']


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows lifecycle entry points')
def test_stop_refuses_reused_pid(project,monkeypatch):
    root,runtime = prepared(project)
    (runtime/'gateway.pid').write_text('424242')
    monkeypatch.setenv('CLAW_TEST_PYTHON',sys.executable)
    with (root/'scripts/openclaw-common.ps1').open('a',encoding='utf-8') as stream:
        stream.write('''
function Get-ClawPython { return $env:CLAW_TEST_PYTHON }
function Get-CimInstance { param($ClassName,$Filter) return [pscustomobject]@{ExecutablePath='C:/unrelated.exe';CommandLine='gateway'} }
function Stop-Process { param($Id) throw 'Must not stop this process' }
''')
    run_ps('''
    try { & ./scripts/openclaw.ps1 stop; throw 'Expected refusal' }
    catch { if ($_.Exception.Message -notmatch 'identity mismatch') { throw }; Write-Output 'Refused safely' }
    ''',root)
