"""Exercise the real PowerShell stdio endpoint across backend outages.

The child is a local JSON-RPC fixture, not Docker or a production database.
"""
import asyncio
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_rag.config import Policy, ROOT
from personal_rag.mcp_server import create_server

SCRIPT = ROOT / 'plugins/personal-memory/scripts/memory-bridge.ps1'
CATALOG = SCRIPT.with_name('tool-catalog.json')

BACKEND = r'''
import json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
if not (root / 'ready').exists():
    sys.stderr.write('private-backend-diagnostic\n')
    sys.exit(1)
mode = 'off'
catalog = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
for line in sys.stdin:
    r = json.loads(line)
    if 'id' not in r:
        continue
    if r['method'] == 'initialize':
        result = {'protocolVersion': r['params']['protocolVersion'], 'capabilities': {}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
    elif r['method'] == 'tools/list':
        result = {'tools': catalog['tools']}
    else:
        name = r['params']['name']
        if name == 'set_memory_mode':
            mode = r['params']['arguments']['mode']
        if name == 'capture_note':
            with (root / 'write-attempts').open('a') as f:
                f.write(r['params']['arguments']['request_id'] + '\n')
            os._exit(7)  # Simulate a write whose result was lost.
        result = {'content': [{'type': 'text', 'text': json.dumps({'mode': mode, 'connection': 'fixture', 'windows_dirs_present': all(os.environ.get(k) for k in ['ProgramData', 'ProgramFiles'])})}], 'isError': False}
    print(json.dumps({'jsonrpc': '2.0', 'id': r['id'], 'result': result}), flush=True)
'''


class Client:
    def __init__(self, root, *, maximum='readwrite', minimal_env=False):
        import sys
        self.root = root
        policy = root / 'config/connections/test.toml'
        policy.parent.mkdir(parents=True)
        policy.write_text(f'name="test"\nmaximum_mode="{maximum}"\ninitial_mode="off"\nadmin=false\n', encoding='utf-8')
        backend = root / 'fake-backend.py'
        backend.write_text(BACKEND, encoding='utf-8')
        # A PS harness preserves array argument boundaries, including paths with spaces.
        harness = root / 'run.ps1'
        quoted = lambda s: "'" + str(s).replace("'", "''") + "'"
        harness.write_text(
            f'& {quoted(SCRIPT)} -ProjectRoot {quoted(root)} -Connection test '
            f'-BackendCommand {quoted(sys.executable)} '
            f'-BackendPrefixArgs @({quoted(backend)},{quoted(root)},{quoted(CATALOG)}) '
            '-BackendStartupTimeoutSec 2 -ToolTimeoutSec 2', encoding='utf-8')
        from mcp.client.stdio import get_default_environment
        self.p = subprocess.Popen(['pwsh', '-NoLogo', '-NoProfile', '-File', str(harness)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=get_default_environment() if minimal_env else None)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.counter = 0

    def _read(self):
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def call(self, method, params=None):
        self.counter += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.counter, 'method': method, 'params': params or {}}) + '\n')
        self.p.stdin.flush()
        line = self.lines.get(timeout=12)
        assert line is not None, self.p.stderr.read()
        r = json.loads(line)
        assert r['id'] == self.counter, r
        return r

    def tool(self, name, **arguments):
        return self.call('tools/call', {'name': name, 'arguments': arguments})

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=8)
            assert self.p.returncode == 0, self.p.stderr.read()
        finally:
            if self.p.poll() is None:
                self.p.kill()


@pytest.fixture
def bridge(tmp_path):
    c = Client(tmp_path / 'knowledge root')
    try:
        yield c
    finally:
        c.close()


def test_catalog_matches_real_non_admin_mcp():
    server = create_server(SimpleNamespace(policy=Policy(name='catalog', maximum_mode='readwrite', admin=False)))
    actual = [t.model_dump(mode='json', exclude_none=True) for t in asyncio.run(server.list_tools())]
    packaged = json.loads(CATALOG.read_text(encoding='utf-8'))
    assert packaged['tools'] == actual
    assert packaged['instructions'] == server.instructions


def test_docker_not_running_does_not_prevent_handshake_or_hide_tools(bridge):
    hello = bridge.call('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
    assert hello['result']['capabilities']['tools']['listChanged'] is False
    tools = bridge.call('tools/list')['result']['tools']
    assert {'memory_status', 'read_note', 'capture_note'} <= {t['name'] for t in tools}
    assert not list(bridge.root.glob('write-attempts'))
    assert bridge.tool('memory_status')['result']['isError'] is True
    # The same client connection still responds after backend startup fails.
    assert bridge.call('ping')['result'] == {}
    assert bridge.call('tools/list')['result']['tools'] == tools
    (bridge.root / 'ready').touch()
    time.sleep(1.1)  # Backend reconnect backoff, not a client restart.
    status = bridge.tool('memory_status')['result']
    assert status['isError'] is False
    assert json.loads(status['content'][0]['text'])['mode'] == 'off'


def test_write_disconnect_is_not_replayed_and_reconnect_resets_mode(bridge):
    (bridge.root / 'ready').touch()
    bridge.call('initialize', {'protocolVersion': '2025-06-18'})
    assert bridge.tool('set_memory_mode', mode='readwrite')['result']['isError'] is False
    response = bridge.tool('capture_note', body='private-note-body', request_id='same-request-id')['result']
    assert response['isError'] is True
    assert '未确认' in response['content'][0]['text']
    time.sleep(1.1)
    recovered = bridge.tool('memory_status')['result']
    assert json.loads(recovered['content'][0]['text'])['mode'] == 'off'
    assert (bridge.root / 'write-attempts').read_text().splitlines() == ['same-request-id']
    log = ''.join(p.read_text(encoding='utf-8') for p in (bridge.root / 'logs/plugin').glob('*.jsonl'))
    assert 'backend_ready' in log
    assert 'private-note-body' not in log and 'same-request-id' not in log
    assert 'private-backend-diagnostic' not in log


def test_readonly_catalog_and_policy_change_fail_closed(tmp_path):
    c = Client(tmp_path, maximum='read')
    try:
        names = {t['name'] for t in c.call('tools/list')['result']['tools']}
        assert 'read_note' in names and 'capture_note' not in names and 'append_note' not in names
        assert c.tool('capture_note')['error']['code'] == -32602
        (tmp_path / 'ready').touch()
        policy = tmp_path / 'config/connections/test.toml'
        policy.write_text(policy.read_text() + '# policy change\n', encoding='utf-8')
        assert c.tool('memory_status')['result']['isError'] is True
        assert c.call('ping')['result'] == {}
    finally:
        c.close()


def test_invalid_request_does_not_close_transport(bridge):
    bridge.p.stdin.write('[1,2]\n')
    bridge.p.stdin.flush()
    response = json.loads(bridge.lines.get(timeout=12))
    assert response['error']['code'] == -32600
    assert bridge.call('ping')['result'] == {}


def test_minimal_mcp_host_environment_restores_docker_discovery_directories(tmp_path):
    import sys
    if sys.platform != 'win32':
        pytest.skip('Windows Docker CLI plugin discovery')
    c = Client(tmp_path, minimal_env=True)
    try:
        (tmp_path / 'ready').touch()
        result = c.tool('memory_status')['result']
        assert not result['isError']
        assert json.loads(result['content'][0]['text'])['windows_dirs_present'] is True
    finally:
        c.close()
