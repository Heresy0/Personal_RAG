"""Verify the installed-cache launcher with real MCP calls and isolated data."""
import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from psycopg import sql

from personal_rag.config import ROOT, Settings


def payload(result):
    assert not result.isError, "Plugin MCP operation failed"
    return result.structuredContent or json.loads(result.content[0].text)


def main():
    settings = Settings.load()
    parsed = urlsplit(settings.database_url)
    if parsed.hostname != '127.0.0.1' or parsed.port != 55432 or parsed.path != '/personal_rag':
        raise SystemExit('只允许本项目独立数据库')
    name = 'personal_rag_test_plugin_' + uuid4().hex[:10]
    admin = urlunsplit(parsed._replace(path='/postgres'))
    image = os.environ.get('PERSONAL_RAG_TEST_IMAGE', 'ghcr.io/heresy0/personal_rag:0.5.0')
    launcher = Path(os.environ.get('PERSONAL_RAG_TEST_LAUNCHER',
                    str(ROOT / 'plugins/personal-memory/scripts/start-memory.ps1')))
    assert launcher.is_file()
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with TemporaryDirectory(prefix='plugin-test-', dir=ROOT / 'output') as temporary:
            root = Path(temporary)
            (root / 'knowledge_workspace/vault').mkdir(parents=True)
            (root / 'logs').mkdir()
            (root / 'config/connections').mkdir(parents=True)
            (root / '.env').write_text('PERSONAL_RAG_DB_PASSWORD=' + parsed.password +
                '\nPERSONAL_RAG_EMBEDDING_PROVIDER=disabled\nPERSONAL_RAG_EMBEDDING_DIMENSIONS=3\n', encoding='utf-8')
            (root / 'compose.yaml').write_bytes((ROOT / 'compose.yaml').read_bytes())
            overlay = (ROOT / 'compose.docker.yaml').read_text(encoding='utf-8').replace(
                'postgres:5432/personal_rag', 'postgres:5432/' + name)
            (root / 'compose.docker.yaml').write_text(overlay, encoding='utf-8')
            (root / 'config/connections/plugin-memory.toml').write_text(
                'name="plugin-test"\nread_spaces=["*"]\nwrite_spaces=["*"]\nmaximum_mode="readwrite"\ninitial_mode="off"\nadmin=false', encoding='utf-8')
            local = root / 'plugin.json'
            local.write_text(json.dumps({'projectRoot':str(root), 'connection':'plugin-memory'}), encoding='utf-8')
            environment = dict(os.environ, PERSONAL_RAG_IMAGE=image)
            subprocess.run(['docker','compose','--project-directory',str(root),'-f',str(root/'compose.yaml'),
                '-f',str(root/'compose.docker.yaml'),'run','--rm','--no-deps','-T','mcp','init'],
                env=environment,check=True,capture_output=True)

            async def scenario():
                params = StdioServerParameters(command='pwsh', args=['-NoLogo','-NoProfile','-File',str(launcher),
                    '-ConfigPath',str(local)], env=environment)
                async with stdio_client(params) as (read,write):
                    async with ClientSession(read,write) as client:
                        await client.initialize()
                        tools = {tool.name for tool in (await client.list_tools()).tools}
                        assert {'capture_note','search_notes'} <= tools
                        assert not {'sync_notes','archive_note','list_write_audit','read_note_version'}.intersection(tools)
                        assert payload(await client.call_tool('memory_status',{}))['mode']=='off'
                        assert (await client.call_tool('search_notes',{'query':'原样'})).isError
                        payload(await client.call_tool('set_memory_mode',{'mode':'readwrite'}))
                        status = payload(await client.call_tool('memory_status', {}))
                        assert status['read_spaces'] == status['write_spaces'] == ['*'] and status['admin'] is False
                        body = "  原样内容\r\n\r\n```text\r\n    保留缩进\r\n```\r\n  "
                        request = str(uuid4())
                        args = {'title':'原样笔记','body':body,'space':'inbox','request_id':request}
                        note = payload(await client.call_tool('capture_note',args))
                        assert payload(await client.call_tool('capture_note',args))['id']==note['id']
                        assert payload(await client.call_tool('read_note',{'note_id':note['id']}))['body']==body
                        summary = payload(await client.call_tool('capture_note',{'title':'自由总结','body':'讨论重点是保留内容原貌。下一步再补充例子。',
                            'space':'project-future','request_id':str(uuid4()),'source_type':'summary','source_ids':[note['id']]}))
                        saved = payload(await client.call_tool('read_note',{'note_id':summary['id']}))
                        assert saved['source_type']=='summary' and saved['source_ids']==[note['id']]
                        found = payload(await client.call_tool('search_notes', {'query':'讨论重点'}))
                        assert any(row['note_id'] == summary['id'] for row in found['results'])
                        assert payload(await client.call_tool('search_notes',{'query':'原样'}))['results']
                        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV0sAAAAASUVORK5CYII=')
                        incoming = root / 'knowledge_workspace/vault/inbox/.incoming/photo.png'
                        incoming.parent.mkdir(parents=True, exist_ok=True)
                        incoming.write_bytes(image)
                        picture = payload(await client.call_tool('capture_note',{'title':'图片识别稿','body':'IMAGE_ORIGINAL_CHECK 识别文字',
                            'space':'inbox','request_id':str(uuid4()),'source_type':'summary','image_paths':['inbox/.incoming/photo.png']}))
                        attachment = picture['images'][0]
                        rendered = await client.call_tool('read_note_image',{'note_id':picture['id'],'image_id':attachment['image_id']})
                        assert not rendered.isError
                        content = next(item for item in rendered.content if item.type == 'image')
                        assert base64.b64decode(content.data) == image
                        assert (root / 'knowledge_workspace/vault' / attachment['relative_path']).read_bytes() == image
                        matches = payload(await client.call_tool('search_notes',{'query':'IMAGE_ORIGINAL_CHECK'}))['results']
                        assert any(row['images'] and row['note_id'] == picture['id'] for row in matches)
                        files = list((root/'knowledge_workspace/vault').rglob('*.md'))
                        assert len(files)==3
                        original = [p for p in files if note['id'] in p.name][0]
                        assert original.read_bytes().split(b'\n',1)[1]==body.encode('utf-8')
                        payload(await client.call_tool('set_memory_mode',{'mode':'off'}))
                        assert (await client.call_tool('capture_note',args)).isError
            asyncio.run(scenario())
        report={'passed':True,'image':image,'launcher':str(launcher),'external_model_calls':0,
                'checks':['cached launcher','tool discovery','initial off','no admin tools','verbatim bytes',
                          'idempotent retry','freeform summary','source linkage','search','host persistence','off blocks writes',
                          'separate wildcard scopes', 'future space cross-scope search', 'original image bytes',
                          'image MCP response', 'image search association']}
        (ROOT/'output/plugin-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


if __name__=='__main__':
    main()
