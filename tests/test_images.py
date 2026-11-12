import asyncio
import base64
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from personal_rag.config import Policy
from personal_rag.mcp_server import create_server
from personal_rag.service import MemoryService

# Actual 1x1 PNG, preserved byte-for-byte; no model or image-editing calls.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV0sAAAAASUVORK5CYII=')
pytestmark = pytest.mark.integration


def stage(manager, space='inbox', content=PNG, filename='original.png'):
    relative = f'{space}/.incoming/{filename}'
    path = manager.settings.vault / relative
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(content)
    return relative


def test_image_capture_search_read_and_versioned_links(manager):
    original = stage(manager)
    note = manager.capture('receipt','Python识别内容：付款金额10元。','inbox',image_paths=[original],source_type='summary')
    attachment = note['images'][0]
    assert attachment['image_id'] == hashlib.sha256(PNG).hexdigest()
    assert (manager.settings.vault / attachment['relative_path']).read_bytes() == PNG
    assert manager.read_image(note['id'],attachment['image_id']) == (PNG,'image/png')
    assert manager.search('付款')['results'][0]['images'][0]['image_id'] == attachment['image_id']
    assert len(list(manager.settings.vault.rglob('*.md'))) == 1
    assert manager.sync()['unchanged'] == 1  # hidden incoming/assets aren't ingested as notes
    manager.append(note['id'],'补充说明',1)
    assert manager.read(note['id'])['images'] == note['images']
    assert '.assets/' in manager.read_version(note['id'],1)['body']
    manager.archive(note['id'],2)
    assert (manager.settings.vault / attachment['relative_path']).read_bytes() == PNG
    with pytest.raises(LookupError):
        manager.read_image(note['id'],attachment['image_id'])


def test_image_retry_deduplicates_and_detects_corruption(manager):
    original = stage(manager)
    request = str(uuid4())
    args = dict(request_id=request,image_paths=[original,original])
    first = manager.capture('image','original text','inbox',**args)
    again = manager.capture('image','original text','inbox',**args)
    assert first['id'] == again['id'] and len(again['images']) == 1
    path = manager.settings.vault / first['images'][0]['relative_path']
    path.write_bytes(b'broken')
    with pytest.raises(ValueError):
        manager.read_image(first['id'],first['images'][0]['image_id'])
    with pytest.raises(ValueError):
        manager.capture('image','original text','inbox',**args)


def test_image_permissions_and_path_boundaries(manager):
    staged = stage(manager,'life')
    note = manager.capture('private','private image text','life',image_paths=[staged])
    reader = MemoryService(manager.settings,Policy('reader',('work',),'read','read'))
    with pytest.raises(LookupError):
        reader.read_image(note['id'],note['images'][0]['image_id'])
    with pytest.raises(PermissionError):
        manager.capture('escape','text','work',image_paths=[staged])
    with pytest.raises(PermissionError):
        manager.capture('escape','text','work',image_paths=['../secret.png'])
    with pytest.raises(PermissionError):
        manager.capture('absolute','text','life',image_paths=[str(manager.settings.vault / staged)])
    with pytest.raises(ValueError):
        manager.capture('missing','text','inbox',image_paths=['inbox/.incoming/missing.png'])
    with pytest.raises(LookupError):
        manager.read_image(note['id'],'0'*64)
    with pytest.raises(ValueError):
        manager.capture('fake','text','inbox',image_paths=[stage(manager,content=b'secret')])
    with pytest.raises(ValueError):
        manager.capture('large','text','inbox',image_paths=[stage(manager,content=PNG+b'x'*(10*1024*1024))])


def test_failed_note_write_cleans_new_assets_and_preserves_staging(manager, monkeypatch):
    staged = stage(manager)
    original_write = manager._atomic_write
    def fail_markdown(path, data):
        if path.suffix == '.md':
            raise OSError('fixture markdown failure')
        original_write(path,data)
    monkeypatch.setattr(manager,'_atomic_write',fail_markdown)
    with pytest.raises(OSError):
        manager.capture('fail','text','inbox',image_paths=[staged])
    assert not list(manager.settings.vault.rglob('.assets/**/*.png'))
    assert (manager.settings.vault / staged).read_bytes() == PNG
    with manager.db.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM notes').fetchone()['n'] == 0
    assert manager.list_audit(outcome='failure')['results']


def test_mcp_returns_original_image_content(manager):
    note = manager.capture('image','text','inbox',image_paths=[stage(manager)])
    async def scenario():
        server = create_server(manager)
        result = await server.call_tool('read_note_image',{'note_id':note['id'],'image_id':note['images'][0]['image_id']})
        blocks = result[0] if isinstance(result,tuple) else result
        block = next(item for item in blocks if getattr(item,'type',None) == 'image')
        assert base64.b64decode(block.data) == PNG and block.mimeType == 'image/png'
    asyncio.run(scenario())
