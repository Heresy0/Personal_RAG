"""Content-free write attempts plus transaction-bound note change events."""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

_active: ContextVar[Attempt | None] = ContextVar('personal_rag_write_attempt', default=None)


def as_uuid(value):
    try:
        return UUID(str(value)) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def current_labels():
    attempt = _active.get()
    return attempt.labels() if attempt else {}


def observe_note(row):
    attempt = _active.get()
    if attempt and row:
        attempt.note_id = row['id']
        attempt.space = row['space']
        attempt.before_revision = row['revision']


def identify_note(note_id, space=None):
    attempt = _active.get()
    if attempt:
        attempt.note_id = as_uuid(note_id)
        if space:
            attempt.space = space


@dataclass
class Attempt:
    operation: str
    connection: str
    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    request_id: UUID | None = None
    note_id: UUID | None = None
    space: str | None = None
    before_revision: int | None = None
    expected_revision: int | None = None

    def labels(self):
        return {'operation_id':str(self.id), 'parent_operation_id':str(self.parent_id) if self.parent_id else None,
                'request_id':str(self.request_id) if self.request_id else None,
                'operation':self.operation, 'connection_name':self.connection}


class AuditUnavailable(RuntimeError):
    pass


class AuditStore:
    def __init__(self, database, settings):
        self.database = database
        self.directory = settings.audit_dir or settings.vault.parent / 'logs'

    def _fallback(self, attempt, outcome, error_code):
        # One exclusively-created file per event: no shared-file races across MCP processes.
        now = datetime.now(timezone.utc)
        event = dict(attempt.labels(), note_id=str(attempt.note_id) if attempt.note_id else None,
                     space=attempt.space, before_revision=attempt.before_revision, after_revision=None,
                     outcome=outcome, error_code=error_code, recorded_at=now.isoformat(),
                     database_finalization='unknown', content_included=False)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"audit-fallback-{now:%Y%m%dT%H%M%S%f}-{uuid4().hex}.json"
            with path.open('x', encoding='utf-8') as stream:
                json.dump(event, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            logging.getLogger(__name__).critical('审计存储和应急日志均不可用，操作ID=%s', attempt.id)
            raise AuditUnavailable('审计存储不可用；写入已停止或最终结果需人工核对') from None

    def start(self, attempt):
        try:
            with self.database.connect() as conn:
                conn.execute("""INSERT INTO write_audit(id,operation_id,parent_operation_id,event_kind,
                    operation,connection_name,request_id,note_id,space,expected_revision,outcome)
                    VALUES (%s,%s,%s,'attempt',%s,%s,%s,%s,%s,%s,'started')""",
                    [attempt.id,attempt.id,attempt.parent_id,attempt.operation,attempt.connection,
                     attempt.request_id,attempt.note_id,attempt.space,attempt.expected_revision])
        except Exception:
            self._fallback(attempt, 'failure', 'audit_start_unavailable')
            raise AuditUnavailable('无法持久化写入审计，未执行本次写入；请检查数据库并运行init') from None

    def finish(self, attempt, *, result=None, error=None):
        try:
            with self.database.connect() as conn:
                changes = conn.execute("""SELECT note_id,space,before_revision,after_revision FROM write_audit
                    WHERE event_kind='change' AND operation_id=%s ORDER BY recorded_at,id""", [attempt.id]).fetchall()
                details = {}
                if attempt.operation == 'sync' and isinstance(result, dict):
                    details = {key:result.get(key,0) for key in ('indexed','unchanged','removed')}
                    details['failed'] = len(result.get('errors', []))
                if error is not None:
                    outcome = 'committed_error' if changes else 'denied' if isinstance(error, PermissionError) else 'failure'
                elif details.get('failed'):
                    outcome = 'partial'
                elif isinstance(result, str) and result == 'unchanged':
                    outcome = 'noop'
                elif attempt.operation in {'capture','append','archive','prune'} and not changes:
                    outcome = 'noop'
                else:
                    outcome = 'success'
                before = changes[0]['before_revision'] if changes else attempt.before_revision
                after = changes[-1]['after_revision'] if changes else before
                note_id = changes[-1]['note_id'] if changes else attempt.note_id
                space = changes[-1]['space'] if changes else attempt.space
                updated = conn.execute("""UPDATE write_audit SET outcome=%s,finished_at=clock_timestamp(),note_id=%s,
                    space=%s,before_revision=%s,after_revision=%s,error_code=%s,details=%s WHERE id=%s""",
                    [outcome,note_id,space,before,after,type(error).__name__ if error else None,Jsonb(details),attempt.id])
                if updated.rowcount != 1:
                    raise AuditUnavailable('写入审计尝试记录缺失')
        except Exception:
            # Never invent success/failure when the database commit outcome cannot be read.
            self._fallback(attempt, 'unknown', 'audit_finalize_unavailable')


def audited_write(operation):
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapper(self, *args, **kwargs):
            # Binding errors are not body-bearing log payloads; no arguments are serialized.
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            parent = _active.get()
            expected = values.get('expected_revision')
            attempt = Attempt(operation, self.policy.name[:128], parent_id=parent.id if parent else None,
                request_id=as_uuid(values.get('request_id')), note_id=as_uuid(values.get('note_id')),
                space=values.get('space') if isinstance(values.get('space'),str) and
                      re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',values['space']) else None,
                expected_revision=expected if type(expected) is int else None)
            token = _active.set(attempt)
            try:
                self.audit.start(attempt)
                try:
                    result = function(self, *args, **kwargs)
                except Exception as error:
                    self.audit.finish(attempt, error=error)
                    raise
                self.audit.finish(attempt, result=result)
                return result
            finally:
                _active.reset(token)
        return wrapper
    return decorate
