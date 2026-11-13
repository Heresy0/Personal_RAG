"""Version-checked local patch for the isolated lab only; no global plugin writes."""
import argparse
import hashlib
import json
import pathlib
import shutil
import socket
import subprocess
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB = ROOT / 'output/openclaw-lab'
PLUGIN = LAB / 'runtime/node_modules/@tencent-weixin/openclaw-weixin'
HERE = pathlib.Path(__file__).resolve().parent
EXPECTED = {
    'src/channel.ts': '70f47061b8eaf199cd70c00d159e6aed9d64698365000c1a5b7eae4377565387',
    'dist/src/channel.js': 'e5fa93140c02d72b6cb637c2e552b30ea02c31daddb24a08e154440dafc99164',
    'index.ts': 'af60230a58414e6fbd2f20bbad2e054b381e6eea65530bfda1b90810c616e74e',
    'dist/index.js': '1178eb3fceda99e9079a94d3aa491c0832c6e86bd5626807e680d728d75e6f20',
    'src/messaging/process-message.ts': '96b7b2fc57758e70c4914138e6ad457edbd0d11a9d778a49a689457946936d64',
    'dist/src/messaging/process-message.js': '5a61f91377be0ed6a4e020072ef0d4de9f6c1b0493c736b5e64502369d2a3b9f',
}
ADAPTERS = ('conversation-bindings','binding-approval','binding-approval-runtime')
NEW_FILES = tuple(name for stem in ADAPTERS for name in (f'src/{stem}.ts',f'dist/src/{stem}.js'))
IMPORT = 'import { weixinBindings, weixinConversationBindings, weixinBindingMessaging } from "./conversation-bindings.js";\n'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def node_command():
    local = LAB/'tools/node/node.exe'
    if local.is_file():
        return str(local)
    command = shutil.which('node')
    require(command, 'Install Node.js 24+ or provide lab/tools/node/node.exe')
    return command

def patched(name, data):
    text = data.decode('utf-8')
    if name in ('index.ts','dist/index.js'):
        anchor='api.registerChannel({ plugin: weixinPlugin });'
        require(text.count(anchor)==1, 'Unexpected plugin registration anchor')
        return ('import { weixinBindingApproval } from "./src/binding-approval-runtime.js";\n'+text.replace(anchor,anchor+'\n    api.registerCommand(weixinBindingApproval.command());')).encode('utf-8')
    if name.endswith('process-message.ts') or name.endswith('process-message.js'):
        anchor='const rawText = payload.text ?? "";'
        require(text.count(anchor)==1, 'Unexpected reply delivery anchor')
        auth_anchor='commands: deps.channelRuntime.commands,'
        require(text.count(auth_anchor)==1, 'Unexpected ingress authorization anchor')
        # Bound Codex turns require commandAuthorized on ordinary text as well.
        # Compute the existing ingress policy; never substitute an unconditional grant.
        text=text.replace(auth_anchor,'commands: { shouldComputeCommandAuthorized: () => true },')
        return ('import { weixinBindingApproval } from "../binding-approval-runtime.js";\n'+text.replace(anchor,'const rawText = weixinBindingApproval.render(payload, deps.accountId, ctx.From);')).encode('utf-8')
    lines = text.splitlines(keepends=True)
    for anchor in ('capabilities: {', 'messaging: {'):
        require(sum(line.strip() == anchor for line in lines) == 1, f'Unexpected anchor {anchor}')
    result = [IMPORT]
    for line in lines:
        indent = line[:len(line)-len(line.lstrip())]
        if line.strip() == 'capabilities: {':
            result += [indent+'bindings: weixinBindings,\n', indent+'conversationBindings: weixinConversationBindings,\n']
        result.append(line)
        if line.strip() == 'messaging: {':
            result.append(indent+'  ...weixinBindingMessaging,\n')
    return ''.join(result).encode('utf-8')

def main():
    global LAB, PLUGIN
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=pathlib.Path)
    parser.add_argument('--lab-root', type=pathlib.Path)
    parser.add_argument('--port', type=int, default=19889)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    require(1 <= args.port <= 65535, 'Invalid Gateway port')
    if args.lab_root:
        LAB = args.lab_root.resolve()
        require(LAB.is_relative_to((ROOT/'output').resolve()) and LAB != (ROOT/'output').resolve(), 'Runtime must remain under this project output directory')
        PLUGIN = LAB/'runtime/node_modules/@tencent-weixin/openclaw-weixin'
    if args.verify:
        manifest = json.loads((LAB/'bindings-patch.json').read_text(encoding='utf-8'))
        require(set(manifest['deployed']) == {*EXPECTED, *NEW_FILES}, 'Unexpected patch manifest')
        require(all(digest((PLUGIN/name).read_bytes()) == sha for name,sha in manifest['deployed'].items()), 'Patched files changed; inspect before continuing')
        print('Adapter deployed files verified')
        return
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(('127.0.0.1',args.port)) == 0:
            raise SystemExit('Stop only the experimental Gateway before changing its plugin')
    require(PLUGIN.resolve().is_relative_to(LAB.resolve()), 'Plugin target must remain inside the isolated lab')
    package = json.loads((PLUGIN/'package.json').read_text(encoding='utf-8'))
    require((package['name'], package['version']) == ('@tencent-weixin/openclaw-weixin','2.4.10'), 'Only the pinned Tencent plugin 2.4.10 is supported')
    if args.rollback:
        backup = args.rollback.resolve()
        require(backup.is_relative_to((LAB/'backups').resolve()), 'Backup must remain inside the lab backup directory')
        manifest = json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
        require(set(manifest['deployed']) == {*EXPECTED, *NEW_FILES}, 'Incomplete or unexpected rollback manifest')
        for name, sha in manifest['deployed'].items():
            require(name in {*EXPECTED, *NEW_FILES}, 'Unexpected manifest path')
            require(digest((PLUGIN/name).read_bytes()) == sha, f'Changed since patch: {name}')
        for name in EXPECTED:
            data = (backup/name).read_bytes()
            require(digest(data) == EXPECTED[name], 'Backup does not match the pinned upstream')
            (PLUGIN/name).write_bytes(data)
        for name in NEW_FILES:
            (PLUGIN/name).unlink()
        print('Restored pinned upstream files and removed only this adapter')
        return
    originals = {name:(PLUGIN/name).read_bytes() for name in EXPECTED}
    require(all(digest(originals[name]) == sha for name,sha in EXPECTED.items()), 'Unexpected upstream files; inspect before applying')
    for name in NEW_FILES:
        require(not (PLUGIN/name).exists(), 'Adapter already exists; do not overwrite')
    compiler = LAB/'runtime/node_modules/esbuild/lib/main.js'
    node = node_command()
    version = subprocess.check_output([node, '--version'], text=True).strip()
    require(version.startswith('v') and int(version[1:].split('.')[0]) >= 24, 'Node.js 24+ is required')
    program = 'const fs=require("node:fs");const e=require(process.argv[1]);process.stdout.write(e.transformSync(fs.readFileSync(process.argv[2],"utf8"),{loader:"ts",format:"esm",target:"node24"}).code)'
    outputs = {name:patched(name,data) for name,data in originals.items()}
    for stem in ADAPTERS:
        outputs[f'src/{stem}.ts'] = (HERE/f'{stem}.ts').read_bytes()
        outputs[f'dist/src/{stem}.js'] = subprocess.check_output([node,'-e',program,str(compiler),str(HERE/f'{stem}.ts')])
    if not args.apply:
        print(f'Dry run passed: pinned 2.4.10, exact upstream hashes, {len(outputs)} local files to write')
        return
    backup = LAB/'backups'/('weixin-bindings-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    for name,data in originals.items():
        target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    manifest={'version':'2.4.10+personal-rag-bindings.3','upstream':EXPECTED,
              'deployed':{name:digest(data) for name,data in outputs.items()}}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    try:
        for name,data in outputs.items(): (PLUGIN/name).write_bytes(data)
    except Exception:
        for name,data in originals.items(): (PLUGIN/name).write_bytes(data)
        for name in NEW_FILES:
            (PLUGIN/name).unlink(missing_ok=True)
        raise
    (LAB/'bindings-patch.json').write_text(json.dumps({'backup':str(backup),**manifest},indent=2),encoding='utf-8')
    print('Patched isolated Tencent plugin; backup:',backup)

if __name__=='__main__':main()
