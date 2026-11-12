"""Local TLS IMAP server: verifies actual imaplib wire commands and unchanged Seen flags."""
import imaplib
import socketserver
import ssl
import threading
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from personal_rag.mail import Account, Collector, IMAPMailbox
from personal_rag.service import MemoryService
from test_mail import raw_mail


@pytest.mark.integration
def test_real_imap_over_local_tls_never_fetches_history_or_sets_seen(manager,tmp_path,monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256()))
    cert_path=tmp_path/'certificate.pem'; key_path=tmp_path/'key.pem'
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(cert_path),str(key_path))
    trust=ssl.create_default_context(cafile=str(cert_path))
    state={'next':11,'calls':[],'bodies':[],'seen':set()}
    raw=raw_mail('WIRE_NEW_MAIL')

    class Handler(socketserver.StreamRequestHandler):
        def setup(self):
            self.request=server_context.wrap_socket(self.request,server_side=True)
            super().setup()
        def send(self,value): self.wfile.write(value+b'\r\n'); self.wfile.flush()
        def handle(self):
            self.send(b'* OK local IMAP fixture ready')
            while True:
                line=self.rfile.readline()
                if not line: break
                tag,command=line.rstrip(b'\r\n').split(b' ',1)
                verb=command.split(b' ',1)[0].upper()
                state['calls'].append(command if verb!=b'LOGIN' else b'LOGIN [redacted]')
                if verb==b'CAPABILITY': self.send(b'* CAPABILITY IMAP4rev1 ID')
                elif verb==b'EXAMINE':
                    self.send(b'* FLAGS (\\Seen)')
                    self.send(b'* 2 EXISTS')
                    self.send(b'* OK [UIDVALIDITY 42] stable')
                    self.send(b'* OK [UIDNEXT '+str(state['next']).encode()+b'] predicted')
                    self.send(tag+b' OK [READ-ONLY] selected'); continue
                elif command.upper().startswith(b'UID SEARCH'):
                    self.send(b'* SEARCH 11')
                elif command.upper().startswith(b'UID FETCH'):
                    uid=int(command.split()[2])
                    if b'BODY' in command.upper():
                        state['bodies'].append(uid)
                        if b'PEEK' not in command.upper(): state['seen'].add(uid)
                        self.send(b'* 2 FETCH (UID 11 BODY[]<0> {'+str(len(raw)).encode()+b'}')
                        self.wfile.write(raw); self.wfile.flush(); self.send(b')')
                    else:
                        stamp=(datetime.now(timezone.utc)+timedelta(hours=1)).strftime('%d-%b-%Y %H:%M:%S +0000')
                        self.send(f'* 2 FETCH (UID 11 INTERNALDATE "{stamp}" RFC822.SIZE {len(raw)})'.encode())
                elif verb==b'LOGOUT':
                    self.send(b'* BYE done'); self.send(tag+b' OK logout'); break
                elif verb not in {b'LOGIN',b'ID'}:
                    self.send(tag+b' BAD forbidden fixture command'); continue
                self.send(tag+b' OK done')

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    server=Server(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    real=imaplib.IMAP4_SSL
    def connect(host,port,ssl_context,timeout):
        assert host=='imap.qq.com' and port==993 and ssl_context.check_hostname
        return real('localhost',server.server_address[1],ssl_context=trust,timeout=timeout)
    monkeypatch.setattr('personal_rag.mail.imaplib.IMAP4_SSL',connect)
    worker=Collector(manager.settings,[Account('wire-test','qq','user@qq.com','test_auth_code')],
        service_factory=lambda settings,policy:MemoryService(settings,policy,embeddings=manager.embeddings))
    try:
        assert worker.poll()[0]['state']=='initialized'
        assert state['bodies']==[] and not any(b'UID SEARCH' in call for call in state['calls'])
        state['next']=12
        assert worker.poll()[0]['saved']==1
        assert state['bodies']==[11] and state['seen']==set()
        assert not any(call.startswith((b'SELECT',b'STORE',b'CLOSE',b'EXPUNGE')) for call in state['calls'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
