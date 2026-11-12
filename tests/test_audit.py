import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from personal_rag.audit import AuditUnavailable
from personal_rag.config import Policy
from personal_rag.db import Database
from personal_rag.mcp_server import create_server
from personal_rag.service import MemoryService

pytestmark = pytest.mark.integration


def attempts(manager):
    return [row for row in manager.list_audit(limit=200)['results'] if row['event_kind'] == 'attempt']


def test_versions_success_retry_conflict_and_privacy(manager):
    request = str(uuid4())
    body = '  PRIVATE_BODY\r\n  '
    note = manager.capture('PRIVATE_TITLE', body, 'general', request_id=request)
    first = attempts(manager)[0]
    assert (first['outcome'], first['before_revision'], first['after_revision']) == ('success', None, 1)
    assert first['request_id'] == request and first['connection_name'] == 'manager'
    manager.capture('PRIVATE_TITLE', body, 'general', request_id=request)
    assert any(row['operation']=='capture' and row['outcome']=='noop' for row in attempts(manager))
    manager.append(note['id'], 'addition', 1)
    changed = next(row for row in attempts(manager) if row['operation']=='append' and row['outcome']=='success')
    assert (changed['before_revision'], changed['after_revision'], changed['outcome']) == (1, 2, 'success')
    with pytest.raises(ValueError):
        manager.append(note['id'], 'PRIVATE_FAILED_BODY', 1)
    failed = next(row for row in attempts(manager) if row['operation']=='append' and row['outcome']=='failure')
    assert (failed['outcome'], failed['before_revision'], failed['after_revision'], failed['expected_revision']) == ('failure', 2, 2, 1)
    assert failed['error_code'] == 'ValueError'
    assert manager.read_version(note['id'], 1)['body'] == body
    assert manager.read_version(note['id'], 2)['body'].endswith('addition')
    audit = manager.list_audit(note_id=note['id'])
    assert not any(secret in json.dumps(audit) for secret in ('PRIVATE_BODY', 'PRIVATE_TITLE', 'PRIVATE_FAILED_BODY'))
    assert manager.list_audit(operation_id=changed['operation_id'])['results']
    page = manager.list_audit(limit=1)
    assert page['next_offset'] == 1
    assert manager.list_audit(limit=1, offset=1)['results'][0]['id'] != page['results'][0]['id']


def test_failed_transaction_has_no_success_change_or_version(manager, monkeypatch):
    note = manager.capture('base', 'original', 'general')
    def fail(*args):
        raise OSError('PRIVATE_EXCEPTION')
    monkeypatch.setattr(manager, '_atomic_write', fail)
    with pytest.raises(OSError):
        manager.append(note['id'], 'new', 1)
    assert manager.read(note['id'])['revision'] == 1
    # Operation identity is stable even if the database wall clock adjusts.
    failed = next(row for row in attempts(manager) if row['operation']=='append' and row['outcome']=='failure')
    rows = manager.list_audit(operation_id=failed['operation_id'])['results']
    assert len(rows) == 1 and rows[0]['outcome'] == 'failure'
    assert 'PRIVATE_EXCEPTION' not in json.dumps(rows)
    with pytest.raises(LookupError):
        manager.read_version(note['id'], 2)


def test_concurrent_appends_have_separate_attempts_and_actual_conflict_version(manager, monkeypatch):
    note = manager.capture('concurrent', 'base', 'general')
    barrier = Barrier(2)
    prepare = manager._prepare
    def synchronized(*args):
        result = prepare(*args)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(manager, '_prepare', synchronized)
    def append(text):
        try:
            manager.append(note['id'], text, 1)
            return 'success'
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(append, ['one', 'two'])) == ['conflict', 'success']
    rows = [row for row in attempts(manager) if row['operation'] == 'append']
    assert len({row['operation_id'] for row in rows}) == 2
    failure = next(row for row in rows if row['outcome'] == 'failure')
    assert (failure['before_revision'], failure['after_revision']) == (2, 2)
    assert manager.read_version(note['id'], 2)['body'] in {'base\n\none', 'base\n\ntwo'}


def test_denied_and_validation_attempts_persist(manager, db_settings):
    writer = MemoryService(db_settings, Policy('plugin', ('general',), 'readwrite', 'off'))
    with pytest.raises(PermissionError):
        writer.capture('secret', 'secret', 'general')
    assert attempts(manager)[0]['outcome'] == 'denied'
    writer.set_mode('readwrite')
    with pytest.raises(ValueError):
        writer.capture('secret', '', 'general')
    assert any(row['outcome']=='failure' for row in attempts(manager))
    with pytest.raises(PermissionError):
        writer.list_audit()
    with pytest.raises(PermissionError):
        writer.read_version(str(uuid4()), 1)
    scoped_admin = MemoryService(db_settings, Policy('scoped', ('general',), 'read', 'read', True))
    with pytest.raises(PermissionError):
        scoped_admin.list_audit()
    with pytest.raises(PermissionError):
        scoped_admin.read_version(str(uuid4()), 1)


def test_database_and_fallback_both_unavailable_fail_closed(manager, monkeypatch):
    def fail():
        raise OSError('unavailable')
    monkeypatch.setattr(manager.db, 'connect', fail)
    directory = manager.settings.vault.parent / 'blocked-logs'
    directory.write_text('file, not directory', encoding='utf-8')
    manager.audit.directory = directory
    with pytest.raises(AuditUnavailable):
        manager.capture('secret', 'secret', 'general')
    assert not list(manager.settings.vault.rglob('*.md'))


def test_archive_and_prune_retain_before_after_snapshots(manager):
    archived = manager.capture('archive', 'before archive', 'general')
    manager.archive(archived['id'], 1)
    assert next(row for row in attempts(manager) if row['operation']=='archive')['after_revision'] == 2
    assert manager.read_version(archived['id'], 1)['metadata']['deleted'] is False
    assert manager.read_version(archived['id'], 2)['metadata']['deleted'] is True
    missing = manager.capture('prune', 'before prune', 'general')
    Path(missing['path']).unlink()
    assert manager.sync(prune=True)['removed'] == 1
    pruned = next(row for row in attempts(manager) if row['operation'] == 'prune')
    assert (pruned['before_revision'], pruned['after_revision'], pruned['outcome']) == (1, 2, 'success')
    assert pruned['parent_operation_id']
    assert manager.read_version(missing['id'], 2)['metadata']['deleted'] is True


def test_sync_partial_and_child_results(manager):
    root = manager.settings.vault / 'general'
    root.mkdir(parents=True)
    (root / 'ok.md').write_text('Python original', encoding='utf-8')
    (root / 'bad.md').write_bytes(b'\xff')
    report = manager.sync()
    assert report['indexed'] == 1 and len(report['errors']) == 1
    rows = attempts(manager)
    parent = next(row for row in rows if row['operation'] == 'sync')
    children = [row for row in rows if row['parent_operation_id'] == parent['operation_id']]
    assert parent['outcome'] == 'partial' and parent['details']['failed'] == 1
    assert {row['outcome'] for row in children} == {'success', 'failure'}
    manager.sync()
    assert any(row['operation'] == 'sync_file' and row['outcome'] == 'noop' for row in attempts(manager))


def test_raw_sql_change_delete_and_repeated_migration(manager):
    note = manager.capture('sql', 'first', 'general')
    with manager.db.connect() as conn:
        conn.execute('UPDATE notes SET body=%s WHERE id=%s', ['second', note['id']])
    assert manager.read_version(note['id'], 2)['body'] == 'second'
    with manager.db.connect() as conn:
        conn.execute('DELETE FROM notes WHERE id=%s', [note['id']])
    rows = manager.list_audit(note_id=note['id'])['results']
    assert rows[0]['change_kind'] == 'delete' and rows[0]['after_revision'] is None
    assert rows[0]['operation'] == 'database_write'
    Database(manager.settings).initialize()
    Database(manager.settings).initialize()
    assert manager.read_version(note['id'], 1)['body'] == 'first'
    assert manager.read_version(note['id'], 2)['body'] == 'second'
    assert len(manager.list_audit(note_id=note['id'])['results']) == len(rows)


def test_upgrade_existing_note_without_inventing_audit(manager):
    identifier = uuid4()
    try:
        with manager.db.connect() as conn:
            conn.execute('DROP TRIGGER personal_rag_note_audit ON notes')
            conn.execute('DROP TRIGGER personal_rag_note_revision ON notes')
            conn.execute('ALTER TABLE note_versions ADD CONSTRAINT note_versions_note_id_fkey FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE')
            conn.execute("""INSERT INTO notes(id,space,title,body,relative_path,event_date,file_hash,revision)
                VALUES (%s,'general','legacy','legacy body','general/legacy.md',CURRENT_DATE,'hash',7)""", [identifier])
        Database(manager.settings).initialize()
        assert manager.read_version(str(identifier), 7)['body'] == 'legacy body'
        assert manager.list_audit()['results'] == []
        with manager.db.connect() as conn:
            conn.execute('UPDATE notes SET title=%s WHERE id=%s', ['updated', identifier])
        assert manager.read_version(str(identifier), 8)['metadata']['title'] == 'updated'
    finally:
        Database(manager.settings).initialize()


def test_response_failure_after_commit_is_not_rollback(manager, monkeypatch):
    def fail(*args):
        raise OSError('response failed')
    monkeypatch.setattr(manager, 'read', fail)
    with pytest.raises(OSError):
        manager.capture('committed', 'saved', 'general')
    row = attempts(manager)[0]
    assert row['outcome'] == 'committed_error' and row['after_revision'] == 1
    assert manager.read_version(row['note_id'], 1)['body'] == 'saved'


def test_audit_start_failure_blocks_write_and_persists_fallback(manager, monkeypatch):
    def fail():
        raise OSError('PRIVATE_DB_SECRET')
    monkeypatch.setattr(manager.db, 'connect', fail)
    with pytest.raises(AuditUnavailable):
        manager.capture('secret', 'PRIVATE_BODY', 'general')
    logs = list(manager.audit.directory.glob('audit-fallback-*.json'))
    assert len(logs) == 1
    event = json.loads(logs[0].read_text(encoding='utf-8'))
    assert event['error_code'] == 'audit_start_unavailable' and event['outcome'] == 'failure'
    assert 'PRIVATE' not in logs[0].read_text(encoding='utf-8')
    assert not list(manager.settings.vault.rglob('*.md'))


def test_finalize_failure_keeps_committed_event_and_unknown_fallback(manager, monkeypatch):
    original_finish = manager.audit.finish
    original_connect = manager.db.connect
    def finish(attempt, **kwargs):
        def fail():
            raise OSError('DB unavailable')
        monkeypatch.setattr(manager.db, 'connect', fail)
        try:
            original_finish(attempt, **kwargs)
        finally:
            monkeypatch.setattr(manager.db, 'connect', original_connect)
    monkeypatch.setattr(manager.audit, 'finish', finish)
    note = manager.capture('committed', 'saved', 'general')
    event = json.loads(next(manager.audit.directory.glob('audit-fallback-*.json')).read_text(encoding='utf-8'))
    assert event['outcome'] == 'unknown'
    rows = manager.list_audit(note_id=note['id'])['results']
    assert {row['outcome'] for row in rows} == {'started', 'success'}


def test_management_tools_through_mcp(manager):
    async def scenario():
        server = create_server(manager)
        note = manager.capture('MCP', 'version body', 'general')
        result = await server.call_tool('list_write_audit', {'note_id':note['id']})
        assert 'success' in str(result)
        result = await server.call_tool('read_note_version', {'note_id':note['id'], 'revision':1})
        assert 'version body' in str(result)
    asyncio.run(scenario())
