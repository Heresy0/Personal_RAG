import imaplib
import json
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest

from personal_rag.mail import Account, Collector, IMAPMailbox, MAX_BYTES, MailError, Gone, load_accounts
from personal_rag.service import MemoryService
from personal_rag.config import ROOT


def raw_mail(text='new email body', subject='New message', image=False, html=False):
    message = EmailMessage()
    message['From'] = 'sender@example.test'
    message['To'] = 'user@qq.com'
    message['Subject'] = subject
    message['Message-ID'] = '<same-id@example.test>'
    message['Date'] = 'Mon, 01 Jan 2001 00:00:00 +0000'  # never used as receive cutoff
    message.set_content(text,subtype='html' if html else 'plain')
    if image:
        message.add_attachment(b'ORIGINAL_ATTACHMENT',maintype='image',subtype='png',filename='../../original.png')
    return message.as_bytes()


class Mailbox:
    def __init__(self):
        self.validity = 42
        self.uidnext = 11
        self.messages = {10:(raw_mail('HISTORICAL'),datetime.now(timezone.utc)-timedelta(days=1))}
        self.calls = []
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def search(self,start,end):
        self.calls.append(('search',start,end))
        assert start <= end
        return sorted(uid for uid in self.messages if start <= uid <= end)
    def metadata(self,uid):
        self.calls.append(('metadata',uid))
        if uid not in self.messages: raise Gone('message_removed')
        raw,stamp = self.messages[uid]
        return stamp,len(raw)
    def fetch(self,uid):
        self.calls.append(('fetch',uid))
        if uid not in self.messages: raise Gone('message_removed')
        return self.messages[uid][0]
    def add(self,uid,raw=None,old=False):
        self.messages[uid] = (raw or raw_mail(),datetime.now(timezone.utc)+timedelta(hours=-48 if old else 1))
        self.uidnext = max(self.uidnext,uid+1)


def collector(manager,box,**kwargs):
    return Collector(manager.settings,[Account('qq-test','qq','user@qq.com','test_auth_code')],mailbox_factory=lambda _:box,
        service_factory=lambda settings,policy:MemoryService(settings,policy,embeddings=manager.embeddings),**kwargs)


@pytest.mark.integration
def test_first_enable_never_searches_or_fetches_history_and_restart_has_no_backfill(manager):
    box = Mailbox(); worker = collector(manager,box)
    assert worker.poll()[0]['state'] == 'initialized'
    assert box.calls == []
    assert worker.poll()[0]['saved'] == 0 and box.calls == []
    box.add(11,raw_mail('NEW_KNOWLEDGE'))
    assert collector(manager,box).poll()[0]['saved'] == 1
    assert [call for call in box.calls if call[0] == 'fetch'] == [('fetch',11)]
    with manager.db.connect() as conn:
        note = conn.execute('SELECT body FROM notes').fetchone()['body']
    assert 'NEW_KNOWLEDGE' in note and 'HISTORICAL' not in note
    assert worker.poll()[0]['saved'] == 0


@pytest.mark.integration
def test_moved_old_mail_skipped_before_body_fetch_and_uid_responses_bounded(manager):
    box = Mailbox(); worker = collector(manager,box); worker.poll()
    box.add(11,old=True); box.add(12)
    box.search = lambda start,end:[1,10,11,12,999999]
    report = worker.poll()[0]
    assert report['saved'] == report['skipped'] == 1
    assert [call for call in box.calls if call[0]=='fetch'] == [('fetch',12)]


@pytest.mark.integration
def test_uidvalidity_or_account_change_stops_without_history_fetch(manager):
    box = Mailbox(); worker = collector(manager,box); worker.poll()
    box.validity = 99; box.uidnext = 2
    assert worker.poll()[0]['error_code'] == 'uidvalidity_changed'
    assert box.calls == []
    box.validity = 42; box.uidnext = 11
    worker.accounts = [Account('qq-test','qq','another@qq.com','test_auth_code')]
    assert worker.poll()[0]['error_code'] == 'account_identity_changed'
    assert box.calls == []


@pytest.mark.integration
def test_failed_processing_does_not_block_new_mail_and_retries_cached_raw(manager,monkeypatch):
    box = Mailbox(); worker = collector(manager,box); worker.poll()
    box.add(11); box.add(12,raw_mail('second message'))
    original = manager.embeddings.embed
    calls = []
    def fail_once(texts):
        calls.append(1)
        if len(calls)==1: raise RuntimeError('PRIVATE_PROVIDER_RESPONSE')
        return original(texts)
    monkeypatch.setattr(manager.embeddings,'embed',fail_once)
    report = worker.poll()[0]
    assert report['failed']==1 and report['saved']==1
    del box.messages[11]
    box.calls.clear()
    assert worker.poll()[0]['saved']==1
    assert box.calls == []  # cached original survives deletion from mailbox
    assert 'PRIVATE' not in json.dumps(worker.status(),default=str)


@pytest.mark.integration
def test_commit_then_checkpoint_failure_is_idempotent(manager,monkeypatch):
    box = Mailbox(); worker=collector(manager,box); worker.poll(); box.add(11)
    finish = worker._finish_item
    def fail_once(*args,**kwargs):
        monkeypatch.setattr(worker,'_finish_item',finish)
        raise OSError('fixture failure after note commit')
    monkeypatch.setattr(worker,'_finish_item',fail_once)
    assert worker.poll()[0]['failed']==1
    assert worker.poll()[0]['saved']==1
    with manager.db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM notes').fetchone()['n']==1
        assert conn.execute('SELECT count(*) AS n FROM note_versions').fetchone()['n']==1
        assert conn.execute("SELECT count(*) AS n FROM write_audit WHERE outcome='noop'").fetchone()['n']==1


@pytest.mark.integration
def test_original_attachments_and_html_are_archived_without_ocr_or_external_fetch(manager):
    box=Mailbox(); worker=collector(manager,box); worker.poll()
    raw=raw_mail('<p>VISIBLE_TEXT</p><script>evil_script()</script><img src="https://example.test/tracker">',image=True,html=True)
    box.add(11,raw)
    assert worker.poll()[0]['saved']==1
    root=manager.settings.vault/'inbox/.mail/qq-test/42/11'
    assert (root/'original.eml').read_bytes()==raw
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['attachments'])==1
    attachment=manifest['attachments'][0]
    assert attachment['status']=='pending_review'
    assert (manager.settings.vault/attachment['relative_path']).read_bytes()==b'ORIGINAL_ATTACHMENT'
    with manager.db.connect() as conn:
        row=conn.execute('SELECT * FROM notes').fetchone()
    assert 'VISIBLE_TEXT' in row['body'] and 'evil_script()' not in row['body']
    assert 'original.png' in row['body']
    assert row['source_type']=='original' and manager.read(str(row['id']))['images']==[]
    assert manager.sync()['unchanged']==1


@pytest.mark.integration
def test_discovery_batches_and_corrupted_archive(manager):
    box=Mailbox(); worker=collector(manager,box,batch_size=2); worker.poll()
    for uid in range(11,16): box.add(uid,raw_mail(str(uid)))
    assert worker.poll()[0]['saved']==2
    assert worker.poll()[0]['saved']==2
    assert worker.poll()[0]['saved']==1
    assert worker.poll()[0]['saved']==0
    with manager.db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM notes').fetchone()['n']==5


def test_transport_uses_tls_examine_and_peek_only(monkeypatch):
    calls=[]
    raw=raw_mail()
    class Client:
        capabilities=(b'IMAP4rev1',b'ID')
        def __init__(self,host,port,ssl_context,timeout):
            assert host=='imap.163.com' and port==993
            assert ssl_context.verify_mode==ssl.CERT_REQUIRED and ssl_context.check_hostname
        def login(self,*args): return 'OK',[]
        def capability(self): return 'OK',[b'IMAP4rev1 ID']
        def _simple_command(self,*args): calls.append(args); return 'OK',[]
        def select(self,folder,readonly):
            assert folder=='INBOX' and readonly is True
            calls.append(('EXAMINE',)); return 'OK',[]
        def response(self,name): return name,[b'42' if name=='UIDVALIDITY' else b'12']
        def uid(self,*args):
            calls.append(args)
            if args[0]=='SEARCH': return 'OK',[b'10 11 999']
            if 'INTERNALDATE' in args[-1]:
                return 'OK',[f'1 (UID 11 INTERNALDATE "12-Nov-2026 20:00:00 +0800" RFC822.SIZE {len(raw)})'.encode()]
            return 'OK',[(b'1 (UID 11 BODY[]<0> {100}',raw),b')']
        def logout(self): calls.append(('LOGOUT',))
    monkeypatch.setattr('personal_rag.mail.imaplib.IMAP4_SSL',Client)
    with IMAPMailbox(Account('163-test','163','user@163.com','test_auth_code')) as mailbox:
        assert mailbox.search(11,11)==[11]
        assert mailbox.search(12,11)==[]
        assert mailbox.metadata(11)[1]==len(raw)
        assert mailbox.fetch(11)==raw
    assert any('BODY.PEEK[]' in str(call) for call in calls)
    assert not any(call[0] in {'STORE','CLOSE','EXPUNGE','SELECT'} for call in calls)


def test_disabled_sources_and_secret_handling(tmp_path,monkeypatch):
    path=tmp_path/'mail.toml'
    path.write_text('[[accounts]]\nid="qq"\nprovider="qq"\nenabled=false',encoding='utf-8')
    assert load_accounts(path)==[]
    secret='PRIVATE_AUTH_CODE'
    monkeypatch.setenv('PERSONAL_RAG_MAIL_QQ_AUTH_CODE',secret)
    path.write_text('[[accounts]]\nid="qq"\nprovider="qq"\nusername="user@qq.com"\nenabled=true\nauth_code_env="PERSONAL_RAG_MAIL_QQ_AUTH_CODE"',encoding='utf-8')
    account=load_accounts(path)[0]
    assert secret not in repr(account) and 'user@qq.com' not in repr(account)


def test_setup_mail_preserves_local_codes_and_account_configuration(tmp_path):
    (tmp_path/'scripts').mkdir(); (tmp_path/'config').mkdir()
    script=tmp_path/'scripts/setup-mail.ps1'
    script.write_bytes((ROOT/'scripts/setup-mail.ps1').read_bytes())
    (tmp_path/'config/mail.example.toml').write_bytes((ROOT/'config/mail.example.toml').read_bytes())
    (tmp_path/'.env').write_text('PERSONAL_RAG_MAIL_QQ_AUTH_CODE=PRIVATE_AUTH_CODE\nOTHER_SETTING=keep\n',encoding='utf-8')
    first=subprocess.run(['pwsh','-NoProfile','-File',str(script)],capture_output=True,text=True,encoding='utf-8')
    assert first.returncode==0,first.stderr
    assert 'PRIVATE_AUTH_CODE' not in first.stdout+first.stderr
    policy=tmp_path/'config/mail.toml'
    assert load_accounts(policy)==[]
    original=policy.read_bytes()
    repeated=subprocess.run(['pwsh','-NoProfile','-File',str(script)],capture_output=True)
    assert repeated.returncode==0 and policy.read_bytes()==original
    text=(tmp_path/'.env').read_text(encoding='utf-8')
    assert text.count('PERSONAL_RAG_MAIL_QQ_AUTH_CODE=')==1
    assert 'PRIVATE_AUTH_CODE' in text and 'OTHER_SETTING=keep' in text


@pytest.mark.integration
def test_auth_error_is_redacted_and_does_not_initialize_or_block_other_account(manager):
    box=Mailbox()
    accounts=[Account('qq-test','qq','user@qq.com','PRIVATE_AUTH_CODE'),Account('163-test','163','user@163.com','OTHER_AUTH_CODE')]
    def connect(account):
        if account.provider=='qq': raise imaplib.IMAP4.error('PRIVATE_AUTH_CODE user@qq.com')
        return box
    worker=Collector(manager.settings,accounts,mailbox_factory=connect)
    result=worker.poll()
    assert result[0]['state']=='failed' and result[1]['state']=='initialized'
    assert 'PRIVATE' not in json.dumps(result) and 'user@qq.com' not in json.dumps(result)
    assert [source['id'] for source in worker.status()['sources']] == ['163-test']


@pytest.mark.integration
def test_oversize_and_missing_messages_do_not_block_queue(manager):
    box=Mailbox(); worker=collector(manager,box); worker.poll()
    for uid in (11,12,13): box.add(uid)
    metadata=box.metadata
    def custom(uid):
        if uid==11: return datetime.now(timezone.utc)+timedelta(hours=1),MAX_BYTES+1
        if uid==12: raise Gone('message_removed')
        return metadata(uid)
    box.metadata=custom
    result=worker.poll()[0]
    assert result['failed']==result['missing']==result['saved']==1
    assert [call for call in box.calls if call[0]=='fetch']==[('fetch',13)]


@pytest.mark.integration
def test_corrupt_cached_original_is_not_silently_replaced(manager,monkeypatch):
    box=Mailbox(); worker=collector(manager,box); worker.poll(); box.add(11)
    def fail(texts): raise RuntimeError('fixture embed unavailable')
    monkeypatch.setattr(manager.embeddings,'embed',fail)
    assert worker.poll()[0]['failed']==1
    raw=manager.settings.vault/'inbox/.mail/qq-test/42/11/original.eml'
    raw.write_bytes(b'tampered')
    box.calls.clear()
    assert worker.poll()[0]['failed']==1 and box.calls==[]
    assert worker.status()['items'][0]['status']=='failed'
    with manager.db.connect() as conn:
        assert conn.execute("SELECT last_error FROM mail_items").fetchone()['last_error']=='archive_corrupt'


@pytest.mark.integration
def test_source_session_lock_prevents_parallel_collectors(manager):
    box=Mailbox(); worker=collector(manager,box)
    with worker.db.connect() as lock:
        lock.execute("SELECT pg_advisory_lock(hashtextextended('mail:qq-test',741))")
        lock.commit()
        assert worker.poll()[0]['state']=='busy'
        assert box.calls==[]
    assert worker.poll()[0]['state']=='initialized'
