import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from personal_rag.config import Policy
from personal_rag.mcp_server import create_server
from personal_rag.service import MemoryService


def test_legacy_and_explicit_precedence(tmp_path):
    path = tmp_path / 'connection.toml'
    path.write_text('name="old"\nspaces=["work"]\nadmin=false', encoding='utf-8')
    old = Policy.load(path)
    assert old.read_spaces == old.write_spaces == ('work',)
    path.write_text('name="mixed"\nspaces=["work"]\nread_spaces=["*"]\nwrite_spaces=[]', encoding='utf-8')
    mixed = Policy.load(path)
    assert mixed.permits('future') and not mixed.permits('work', write=True)
    path.write_text('name="mixed"\nspaces=["work"]\nwrite_spaces=["inbox"]', encoding='utf-8')
    assert Policy.load(path).read_spaces == ('work',)
    assert Policy.load(path).write_spaces == ('inbox',)


@pytest.mark.parametrize('invalid', ['work', [1], ['../private']])
def test_malformed_scope_rejected(invalid):
    with pytest.raises(ValueError):
        Policy('invalid', read_spaces=invalid)


def test_no_scope_fails_closed():
    policy = Policy('empty')
    assert not policy.permits('work') and not policy.permits('work', write=True)


def client(manager, read, write, admin=False):
    return MemoryService(manager.settings, Policy('custom', maximum_mode='readwrite',
        initial_mode='readwrite', admin=admin, read_spaces=read, write_spaces=write), embeddings=manager.embeddings)


@pytest.mark.integration
def test_wildcard_plugin_queries_future_spaces_but_has_no_admin(manager):
    plugin = client(manager, ('*',), ('*',))
    one = plugin.capture('one', 'Python alpha', 'brand-new')
    two = plugin.capture('two', 'Python beta', 'another-space')
    assert {r['note_id'] for r in plugin.search('Python')['results']} == {one['id'], two['id']}
    assert {r['note_id'] for r in plugin.search('Python', space='brand-new')['results']} == {one['id']}
    day = one['event_date']
    assert len(plugin.timeline(day, day)['results']) == 2
    assert plugin.read(one['id'])['body'] == 'Python alpha'
    assert plugin.append(one['id'], 'addition', 1)['revision'] == 2
    status = plugin.status()
    assert status['read_spaces'] == status['write_spaces'] == ['*'] and not status['admin']
    names = {tool.name for tool in asyncio.run(create_server(plugin).list_tools())}
    assert {'capture_note', 'append_note'} <= names
    assert not names.intersection({'sync_notes','archive_note','list_write_audit','read_note_version'})
    for action in (lambda:plugin.sync(), lambda:plugin.archive(one['id'], 2),
                   lambda:plugin.list_audit(), lambda:plugin.read_version(one['id'], 1)):
        with pytest.raises(PermissionError):
            action()
    plugin.set_mode('off')
    with pytest.raises(PermissionError):
        plugin.capture('closed', 'closed', 'brand-new')


@pytest.mark.integration
def test_read_write_scopes_are_independent_and_no_body_leaks(manager):
    visible = manager.capture('visible', 'Python visible', 'learning')
    hidden = manager.capture('hidden', 'PRIVATE Python original', 'inbox')
    plugin = client(manager, ('learning',), ('inbox',))
    assert plugin.read(visible['id'])['body'] == 'Python visible'
    assert {r['note_id'] for r in plugin.search('Python')['results']} == {visible['id']}
    with pytest.raises(LookupError):
        plugin.read(hidden['id'])
    with pytest.raises(PermissionError):
        plugin.search('Python', space='inbox')
    with pytest.raises(LookupError):
        plugin.append(visible['id'], 'denied', 1)
    with pytest.raises(PermissionError):
        plugin.capture('denied', 'denied', 'learning')
    result = plugin.append(hidden['id'], 'new', 1)
    assert result['revision'] == 2 and 'body' not in result and 'title' not in result
    assert manager.read(hidden['id'])['body'].endswith('new')
    request = str(uuid4())
    for _ in range(2):
        result = plugin.capture('write only', 'PRIVATE', 'inbox', request_id=request)
        assert 'body' not in result and result['revision'] == 1
    no_write = client(manager, ('*',), ())
    with pytest.raises(PermissionError):
        no_write.capture('denied', 'denied', 'inbox')
    with pytest.raises(LookupError):
        no_write.append(hidden['id'], 'denied', 2)


@pytest.mark.integration
def test_admin_sync_and_archive_respect_write_scope(manager):
    visible = manager.capture('read', 'read', 'learning')
    admin = client(manager, ('*',), ('inbox',), admin=True)
    with pytest.raises(LookupError):
        admin.archive(visible['id'], 1)
    path = manager.settings.vault / 'inbox/import.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('import', encoding='utf-8')
    report = admin.sync(prune=True)
    assert report['indexed'] == 1 and report['errors']
    assert manager.read(visible['id'])['revision'] == 1
