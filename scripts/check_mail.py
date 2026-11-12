"""Container acceptance with simulated providers and an isolated PostgreSQL database."""
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from personal_rag.config import ROOT, Settings


def main():
    settings=Settings.load(); parsed=urlsplit(settings.database_url)
    if parsed.hostname!='127.0.0.1' or parsed.port!=55432 or parsed.path!='/personal_rag':
        raise SystemExit('Only the independent local Personal_RAG database is permitted')
    database='personal_rag_test_mail_'+uuid4().hex[:10]
    admin=urlunsplit(parsed._replace(path='/postgres'))
    image=os.environ.get('PERSONAL_RAG_TEST_IMAGE','ghcr.io/heresy0/personal_rag:0.5.0')
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    (ROOT/'output').mkdir(exist_ok=True)
    try:
        with TemporaryDirectory(prefix='mail-test-',dir=ROOT/'output') as temporary:
            root=Path(temporary)
            for directory in ('vault','logs'): (root/directory).mkdir()
            url=urlunsplit(parsed._replace(netloc=parsed.netloc.rsplit('@',1)[0]+'@postgres:5432',path='/'+database))
            envfile=root/'.env'
            envfile.write_text('PERSONAL_RAG_DATABASE_URL='+url+'\nPERSONAL_RAG_EMBEDDING_PROVIDER=disabled\n'
                'PERSONAL_RAG_EMBEDDING_DIMENSIONS=3\nPERSONAL_RAG_RERANK_URL=\nPERSONAL_RAG_VAULT=/data/vault\n'
                'PERSONAL_RAG_AUDIT_DIR=/data/logs\n',encoding='utf-8')
            base=['docker','run','--rm','--network','personal-rag_default','--env-file',str(envfile)]
            for directory in ('vault','logs'):
                base+=['--mount',f'type=bind,source={root/directory},target=/data/{directory}']
            subprocess.run([*base,image,'init'],check=True,capture_output=True)
            program="""
import sys,json
sys.path.insert(0,'/tests')
from test_mail import Mailbox,raw_mail
from personal_rag.config import Settings
from personal_rag.mail import Account,Collector
settings=Settings.load()
qq,netease=Mailbox(),Mailbox()
worker=Collector(settings,[Account('qq-test','qq','test@qq.com','dummy_auth_code'),Account('163-test','163','test@163.com','dummy_auth_code')],mailbox_factory=lambda a:qq if a.provider=='qq' else netease)
assert all(row['state']=='initialized' for row in worker.poll())
assert qq.calls==netease.calls==[]
qq.add(11,raw_mail('QQ_NEW_MAIL'))
netease.add(11,raw_mail('NETEASE_NEW_MAIL'))
assert all(row['saved']==1 for row in worker.poll())
assert all(row['saved']==0 for row in worker.poll())
assert [c for c in qq.calls if c[0]=='fetch']==[('fetch',11)]
assert [c for c in netease.calls if c[0]=='fetch']==[('fetch',11)]
with worker.db.connect() as conn:
    assert conn.execute('SELECT count(*) AS n FROM notes').fetchone()['n']==2
    assert conn.execute('SELECT count(*) AS n FROM mail_items').fetchone()['n']==2
    assert conn.execute("SELECT count(*) AS n FROM write_audit WHERE operation='capture' AND outcome='success' AND event_kind='attempt'").fetchone()['n']==2
print('Container mail baseline, incrementality, deduplication and audit verified; no real IMAP connections')
"""
            result=subprocess.run([*base,'-i','--mount',f'type=bind,source={ROOT/"tests"},target=/tests,readonly',
                '--entrypoint','python',image,'-'],input=program,text=True,encoding='utf-8',capture_output=True)
            if result.returncode:
                print(result.stderr)
                raise AssertionError('Container mail acceptance failed')
            assert len(list((root/'vault').rglob('*.md')))==2
            assert len(list((root/'vault').rglob('original.eml')))==2
            status=subprocess.run([*base,image,'mail-status'],check=True,capture_output=True,text=True,encoding='utf-8')
            assert len(json.loads(status.stdout)['sources'])==2
            report={'passed':True,'image':image,'real_mailbox_connections':0,'external_model_calls':0,
                'checks':['container init','first QQ baseline','first 163 baseline','no history FETCH','new QQ mail',
                    'new 163 mail','restart deduplication','immutable originals','database notes','capture audit','CLI status']}
            (ROOT/'output/mail-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2))
    finally:
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


if __name__=='__main__': main()
