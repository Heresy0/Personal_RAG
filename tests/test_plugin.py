import json
import os
import subprocess
from pathlib import Path

from personal_rag.config import ROOT


def test_plugin_paths_and_portable_stdio():
    root = ROOT / 'plugins/personal-memory'
    plugin = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    mcp = json.loads((root / 'mcp.json').read_text(encoding='utf-8'))
    assert plugin['name'] == 'personal-memory'
    interface = plugin['extensions']['com.openai']['interface']
    assert interface['displayName'] == '个人知识库'
    for key in ('composerIcon', 'logo'):
        assert (root / interface[key]).is_file()
    server = mcp['mcpServers']['personal_memory']
    assert server['type'] == 'stdio' and server['command'] == 'pwsh'
    # Plugin stdio manifests have a narrower schema than global TOML MCP
    # config. In the current desktop loader, timeout/required are invalid.
    assert set(server) <= {'type', 'command', 'args', 'env', 'cwd'}
    script = server['args'][-1].replace('${PLUGIN_ROOT}', str(root))
    assert Path(script).is_file()
    catalog = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    assert (ROOT / catalog['plugins'][0]['source']['path']).resolve() == root.resolve()


def test_installer_and_cached_launcher(tmp_path):
    # Use the actual installer in a fresh directory. No global config and no Docker operation.
    root = tmp_path / 'knowledge root'
    (root / 'scripts').mkdir(parents=True)
    for name in ('install-plugin.ps1',):
        (root / 'scripts' / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    (root / '.env').write_text('test fixture only', encoding='utf-8')
    config = tmp_path / 'local config.json'
    result = subprocess.run(['pwsh', '-NoProfile', '-File', str(root / 'scripts/install-plugin.ps1'),
        '-SkipRegistration', '-ConfigPath', str(config)], capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    settings = json.loads(config.read_text(encoding='utf-8'))
    assert Path(settings['projectRoot']) == root and settings['connection'] == 'plugin-memory'
    policy = (root / 'config/connections/plugin-memory.toml').read_text(encoding='utf-8')
    assert 'initial_mode = "off"' in policy and 'admin = false' in policy
    import tomllib
    parsed = tomllib.loads(policy)
    assert parsed['read_spaces'] == ['*'] and parsed['write_spaces'] == ['*']
    # A second run must preserve an explicitly narrowed existing policy.
    narrow = 'name="custom"\nspaces=["inbox"]\nmaximum_mode="read"\ninitial_mode="off"\nadmin=false'
    (root / 'config/connections/plugin-memory.toml').write_text(narrow, encoding='utf-8')
    repeated = subprocess.run(['pwsh', '-NoProfile', '-File', str(root / 'scripts/install-plugin.ps1'),
        '-SkipRegistration', '-ConfigPath', str(config)], capture_output=True, encoding='utf-8')
    assert repeated.returncode == 0
    assert (root / 'config/connections/plugin-memory.toml').read_text(encoding='utf-8') == narrow


def test_launcher_missing_configuration_fails_without_protocol_noise(tmp_path):
    result = subprocess.run(['pwsh', '-NoProfile', '-File',
        str(ROOT / 'plugins/personal-memory/scripts/start-memory.ps1'),
        '-ConfigPath', str(tmp_path / 'missing.json')], capture_output=True, encoding='utf-8')
    assert result.returncode != 0
    assert result.stdout == ''
    assert 'install-plugin.ps1' in result.stderr


def test_installer_separate_scopes_and_readonly(tmp_path):
    import tomllib
    root = tmp_path / 'root'
    (root / 'scripts').mkdir(parents=True)
    (root / 'scripts/install-plugin.ps1').write_bytes((ROOT / 'scripts/install-plugin.ps1').read_bytes())
    (root / '.env').write_text('fixture', encoding='utf-8')
    for name, extra, expected_write in [('separate', ['-ReadSpaces','learning','-WriteSpaces','inbox'], ['inbox']),
                                        ('reader', ['-ReadOnly'], [])]:
        result = subprocess.run(['pwsh','-NoProfile','-File',str(root / 'scripts/install-plugin.ps1'),
            '-Connection',name,'-SkipRegistration','-ConfigPath',str(root / 'plugin.json'), *extra],
            capture_output=True, encoding='utf-8')
        assert result.returncode == 0, result.stderr
        data = tomllib.loads((root / f'config/connections/{name}.toml').read_text(encoding='utf-8'))
        assert data['write_spaces'] == expected_write and data['admin'] is False
        assert data['read_spaces'] == (['learning'] if name == 'separate' else ['*'])
