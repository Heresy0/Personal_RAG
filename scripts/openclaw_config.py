"""Private configuration for the optional Windows OpenClaw runtime; no model calls."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tomllib
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'personal-rag-openclaw.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize(root):
    path = root/'config/openclaw.local.json'
    if path.exists():
        return False
    write(path, read(root/'config/openclaw.example.json'))
    return True


def settings(root):
    value = read(root/'config/openclaw.local.json')
    mode = value.setdefault('mode', 'app-server')
    if mode not in ('app-server','desktop'):
        raise ValueError('mode must be app-server or desktop')
    model = value.get('model', '')
    if mode == 'app-server' and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]+', model)):
        raise ValueError('Fill model in config/openclaw.local.json, e.g. the OpenClaw model ID supported by your Codex account')
    if mode == 'desktop':
        if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',value.get('desktopThreadId','')):
            raise ValueError('Fill desktopThreadId with the original desktop conversation UUID')
        if not Path(value.get('desktopWorkspace','')).is_absolute():
            raise ValueError('desktopWorkspace must be the original conversation absolute directory')
    value.setdefault('model','')
    if type(value.get('port')) is not int or not 1024 <= value['port'] <= 65535:
        raise ValueError('port must be an integer from 1024 to 65535')
    relative = Path(value.get('runtimeDir', ''))
    runtime = (root/relative).resolve()
    output = (root/'output').resolve()
    if relative.is_absolute() or not runtime.is_relative_to(output) or runtime == output:
        raise ValueError('runtimeDir must stay within this repository output directory')
    if runtime == (output/'openclaw-lab').resolve():
        raise ValueError('Existing manual openclaw-lab is reserved; choose a separate runtime')
    if not isinstance(value.get('codexPath', ''), str):
        raise ValueError('codexPath must be a string')
    value['runtime'] = str(runtime)
    return value


def managed(root, runtime):
    marker = runtime/MARKER
    if not marker.is_file() or Path(read(marker)['projectRoot']).resolve() != root.resolve():
        raise ValueError('Runtime is not managed by this repository; refusing to change it')


def merge(target, incoming):
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def require_native_detached(runtime):
    database = runtime/'state/state/openclaw.sqlite'
    if not database.exists():
        return
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='current_conversation_bindings'").fetchone():
            return
        rows=connection.execute("SELECT metadata_json FROM current_conversation_bindings WHERE channel='openclaw-weixin' AND status='active'").fetchall()
    if any(json.loads(row[0] or '{}').get('pluginId')=='codex' for row in rows):
        raise ValueError('Detach the native binding with /codex detach in Weixin before switching this stopped runtime to desktop mode')


def prepare(root, codex_path, node_path, *, bootstrap=False):
    value = settings(root)
    runtime = Path(value['runtime'])
    marker = runtime/MARKER
    if runtime.exists() and any(runtime.iterdir()) and not marker.exists():
        raise ValueError('Runtime already contains unmanaged files; choose a fresh runtimeDir')
    if marker.exists():
        managed(root, runtime)
    if value['mode'] == 'desktop':
        require_native_detached(runtime)
    codex, node = Path(codex_path).resolve(), Path(node_path).resolve()
    if not codex.is_file() or not node.is_file():
        raise ValueError('Codex and Node executable paths must exist')
    for name in ('runtime', 'state', 'workspace', 'logs'):
        (runtime/name).mkdir(parents=True, exist_ok=True)
    template = read(root/'integrations/openclaw-weixin-bindings/openclaw.example.json')
    config_path = runtime/'state/openclaw.json'
    previous = read(config_path) if config_path.exists() else {}
    template['gateway']['port'] = value['port']
    template['gateway']['auth']['token'] = previous.get('gateway', {}).get('auth', {}).get('token') or secrets.token_hex(32)
    template['agents']['defaults']['workspace'] = (runtime/'workspace').as_posix()
    template['agents']['defaults']['model']['primary'] = value['model']
    template['plugins']['load']['paths'] = [(runtime/'runtime/node_modules/@tencent-weixin/openclaw-weixin').as_posix()]
    app = template['plugins']['entries']['codex']['config']['appServer']
    app['command'] = str(codex)
    app['defaultWorkspaceDir'] = (runtime/'workspace').as_posix()
    launcher = (root/'plugins/personal-memory/scripts/start-memory.ps1').as_posix()
    app['args'][3] = 'mcp_servers.personal_memory.args='+json.dumps(['-NoLogo','-NoProfile','-File',launcher])
    template['mcp']['servers']['personal_memory']['args'][-1] = launcher
    template['commands']['ownerAllowFrom'] = previous.get('commands', {}).get('ownerAllowFrom', [])
    if value['mode'] == 'desktop':
        source = root/'integrations/openclaw-desktop'
        destination = runtime/'runtime/node_modules/@personal-rag/openclaw-desktop'
        # Copy only our public source files, never runtime state or tests.
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('index.mjs','queue.mjs','catalog.mjs','worker.mjs','package.json','openclaw.plugin.json'):
            shutil.copy2(source/name,destination/name)
        template['plugins']['allow'].remove('codex')
        template['plugins']['allow'].append('personal-rag-desktop')
        template['plugins']['load']['paths'].append(destination.as_posix())
        template['plugins']['entries']['codex'] = {'enabled':False}
        template['plugins']['entries']['personal-rag-desktop'] = {'enabled':True,'config':{
            'threadId':value['desktopThreadId'], 'workspace':str(Path(value['desktopWorkspace']).resolve()),
            'runtimeDir':str(runtime), 'codexHome':str(Path(value.get('desktopCodexHome') or Path.home()/'.codex').resolve()),
            'codexPath':str(codex), 'projectRoot':str(root.resolve()), 'autoOpen':value.get('desktopAutoOpen',True)}}
        template['agents']['defaults'].pop('model')
        template.pop('mcp')
        # Explicitly remove old app-server/MCP config when switching a stopped managed runtime.
        previous.get('plugins',{}).get('entries',{}).pop('codex',None)
        previous.get('agents',{}).get('defaults',{}).pop('model',None)
        previous.get('mcp',{}).get('servers',{}).pop('personal_memory',None)
    else:
        previous.get('plugins',{}).get('entries',{}).pop('personal-rag-desktop',None)
    if bootstrap:
        # A missing plugin entry must not prevent its own official installation.
        if value['mode'] == 'app-server':
            template['plugins']['allow'].remove('codex')
            template['plugins']['entries'].pop('codex')
            template.pop('mcp')
    # Keep official installer records, account metadata, and unrelated keys.
    merge(previous, template)
    if config_path.exists():
        backup = runtime/'backups'/('config-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, backup)
    write(config_path, previous)
    write(marker, {'projectRoot': str(root.resolve()), 'nodePath': str(node), 'codexPath': str(codex), 'port': value['port']})
    package = runtime/'runtime/package.json'
    if not package.exists():
        write(package, {'private': True,
            'dependencies': {'openclaw': '2026.11.3', '@tencent-weixin/openclaw-weixin': '2.4.10'},
            'allowScripts': {'openclaw@2026.11.3': True, 'esbuild@0.28.2': True,
                             'protobufjs@7.6.6': True, '@google/genai@2.27.0': True}})
    return value


def sync_owner(root, account=None):
    value = settings(root)
    runtime = Path(value['runtime'])
    managed(root, runtime)
    base = runtime/'state/openclaw-weixin'
    indexed = read(base/'accounts.json')
    candidates = []
    for identifier in indexed:
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
            raise ValueError('Invalid account identifier')
        if account and identifier != account:
            continue
        path = base/'accounts'/f'{identifier}.json'
        data = read(path)
        peer = data.get('userId', '')
        if isinstance(peer, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}@im\.wechat', peer):
            candidates.append(peer)
    if len(candidates) != 1:
        raise ValueError('Expected exactly one logged-in account; login first or specify -Account')
    config_path = runtime/'state/openclaw.json'
    config = read(config_path)
    # Explicit login operation authorizes only the selected scanner, never all contacts.
    config.setdefault('commands', {})['ownerAllowFrom'] = ['openclaw-weixin:'+candidates[0]]
    write(config_path, config)
    return {'ownerConfigured': True}


def check_plugin(root, path):
    config = read(path)
    if Path(config.get('projectRoot', '')).resolve() != root.resolve():
        raise ValueError('Personal Memory plugin points to a different repository; configure your plugin first')
    connection = config.get('connection', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', connection):
        raise ValueError('Invalid Personal Memory connection')
    policy = tomllib.loads((root/f'config/connections/{connection}.toml').read_text(encoding='utf-8-sig'))
    if policy.get('admin', False):
        raise ValueError('Weixin must use a non-admin Personal Memory connection')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init','settings','prepare','owner','plugin'])
    parser.add_argument('--codex-path')
    parser.add_argument('--node-path')
    parser.add_argument('--account')
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--plugin-config', type=Path)
    args = parser.parse_args()
    if args.action == 'init':
        result = {'created': initialize(ROOT)}
    elif args.action == 'settings':
        result = settings(ROOT)
    elif args.action == 'prepare':
        result = prepare(ROOT, args.codex_path, args.node_path, bootstrap=args.bootstrap)
    elif args.action == 'owner':
        result = sync_owner(ROOT, args.account)
    else:
        check_plugin(ROOT, args.plugin_config)
        result = {'ordinaryPlugin': True}
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        raise SystemExit(str(error)) from None
