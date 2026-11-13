"""Protect local upgrades and rollback from overwriting unrelated plugin changes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('weixin_patch',Path(__file__).with_name('apply.py'))
patch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

@pytest.fixture
def installation(tmp_path,monkeypatch):
    lab=tmp_path/'lab';plugin=lab/'plugin';plugin.mkdir(parents=True)
    (plugin/'package.json').write_text(json.dumps({'name':'@tencent-weixin/openclaw-weixin','version':'2.4.10'}))
    originals={'src/channel.ts':b'upstream ts','dist/src/channel.js':b'upstream js'}
    for name,data in originals.items():
        p=plugin/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (plugin/'unrelated.txt').write_bytes(b'keep')
    monkeypatch.setattr(patch,'LAB',lab)
    monkeypatch.setattr(patch,'PLUGIN',plugin)
    monkeypatch.setattr(patch,'EXPECTED',{n:hashlib.sha256(d).hexdigest() for n,d in originals.items()})
    class Offline:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,*args):pass
        def connect_ex(self,*args):return 1
    monkeypatch.setattr(patch.socket,'socket',lambda:Offline())
    return lab,plugin,originals

def stage_rollback(lab,plugin,originals):
    backup=lab/'backups/example';backup.mkdir(parents=True)
    outputs={n:b'patched '+d for n,d in originals.items()}
    outputs.update({name:b'adapter fixture' for name in patch.NEW_FILES})
    for name,data in originals.items():
        p=backup/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    for name,data in outputs.items():(plugin/name).write_bytes(data)
    (backup/'manifest.json').write_text(json.dumps({'deployed':{n:patch.digest(d) for n,d in outputs.items()}}))
    return backup

def test_unknown_upstream_is_rejected_before_compilation_or_writes(installation,monkeypatch):
    lab,plugin,_=installation
    (plugin/'src/channel.ts').write_bytes(b'new upstream version')
    before={str(p):p.read_bytes() for p in plugin.rglob('*') if p.is_file()}
    monkeypatch.setattr('sys.argv',['apply.py','--apply'])
    with pytest.raises(ValueError,match='Unexpected upstream'):patch.main()
    assert {str(p):p.read_bytes() for p in plugin.rglob('*') if p.is_file()}==before
    assert not (lab/'backups').exists()

def test_rollback_refuses_to_discard_post_deployment_edits(installation,monkeypatch):
    lab,plugin,originals=installation;backup=stage_rollback(lab,plugin,originals)
    (plugin/'dist/src/channel.js').write_bytes(b'user edit')
    before={str(p):p.read_bytes() for p in plugin.rglob('*') if p.is_file()}
    monkeypatch.setattr('sys.argv',['apply.py','--rollback',str(backup)])
    with pytest.raises(ValueError,match='Changed since patch'):patch.main()
    assert {str(p):p.read_bytes() for p in plugin.rglob('*') if p.is_file()}==before

def test_rollback_restores_upstream_and_preserves_other_files(installation,monkeypatch):
    lab,plugin,originals=installation;backup=stage_rollback(lab,plugin,originals)
    (lab/'credentials.json').write_bytes(b'private unchanged')
    monkeypatch.setattr('sys.argv',['apply.py','--rollback',str(backup)])
    patch.main()
    assert all((plugin/n).read_bytes()==d for n,d in originals.items())
    assert not (plugin/'src/conversation-bindings.ts').exists()
    assert not (plugin/'dist/src/conversation-bindings.js').exists()
    assert (plugin/'unrelated.txt').read_bytes()==b'keep'
    assert (lab/'credentials.json').read_bytes()==b'private unchanged'

def test_message_patch_computes_policy_instead_of_granting_authorization():
    source=b'commands: deps.channelRuntime.commands,\nconst rawText = payload.text ?? "";'
    for name in ('src/messaging/process-message.ts','dist/src/messaging/process-message.js'):
        result=patch.patched(name,source).decode()
        assert 'commands: { shouldComputeCommandAuthorized: () => true },' in result
        assert 'commandAuthorized: true' not in result
        assert 'weixinBindingApproval.render(payload, deps.accountId, ctx.From)' in result
        with pytest.raises(ValueError,match='authorization anchor'):
            patch.patched(name,b'const rawText = payload.text ?? "";')

def test_node_uses_isolated_binary_or_system_path(installation,monkeypatch):
    lab,_,_=installation
    monkeypatch.setattr(patch.shutil,'which',lambda name:'C:/tools/node.exe')
    assert patch.node_command()=='C:/tools/node.exe'
    local=lab/'tools/node/node.exe';local.parent.mkdir(parents=True);local.write_bytes(b'fixture')
    assert patch.node_command()==str(local)

def test_missing_node_has_actionable_error(installation,monkeypatch):
    monkeypatch.setattr(patch.shutil,'which',lambda name:None)
    with pytest.raises(ValueError,match='Install Node.js'):patch.node_command()
