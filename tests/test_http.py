"""Exercise HTTP parsing and routing in memory, without binding a network port."""
import io
import json
import os
import tempfile
import unittest
from http.client import HTTPResponse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cke.catalog import Catalog
from cke.storage.sqlite_store import SQLiteStore
from cke.chunking.service import ChunkingService
from cke.viewer.server import Handler


class MemorySocket:
    def __init__(self, request: bytes):
        self.request = request
        self.output = bytearray()

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.request)

    def sendall(self, data):
        self.output.extend(data)


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'CKE_HOME': str(Path(self.temp.name) / 'home')})
        self.env.start()
        self.addCleanup(self.env.stop)
        repo = Path(self.temp.name) / 'repo'
        repo.mkdir()
        (repo / 'app.py').write_text('def hello():\n    return "hello"\n')
        catalog = Catalog()
        catalog.create_kb('demo')
        catalog.add_source('demo', str(repo), 'local', 'sample')
        store = SQLiteStore()
        try:
            ChunkingService(store).run('demo')
        finally:
            store.close()

    def request(self, path, method='GET', body=None, headers=None):
        payload = json.dumps(body).encode() if body is not None else b''
        fields = {'Host': '127.0.0.1:8765', 'Connection': 'close', **(headers or {})}
        if payload:
            fields.update({'Content-Type': 'application/json', 'Content-Length': str(len(payload))})
        raw = f'{method} {path} HTTP/1.1\r\n' + ''.join(f'{key}: {value}\r\n' for key, value in fields.items()) + '\r\n'
        socket = MemorySocket(raw.encode() + payload)
        QuietHandler(socket, ('127.0.0.1', 12345), SimpleNamespace(server_port=8765))
        response = HTTPResponse(MemorySocket(bytes(socket.output)))
        response.begin()
        return response.status, dict(response.headers), response.read()

    def get(self, path):
        status, headers, body = self.request(path)
        return status, json.loads(body)

    def test_catalog_search_and_source(self):
        self.assertEqual(self.get('/api/kbs')[1], ['demo'])
        status, results = self.get('/api/search?kb=demo&query=hello&mode=keyword&limit=1')
        self.assertEqual(status, 200)
        self.assertEqual(len(results), 1)
        chunk = self.get('/api/source?kb=demo&id=' + results[0]['id'])[1]
        self.assertEqual(chunk['content'], results[0]['content'])

    def test_http_and_cli_same_evidence(self):
        from cke.cli import parser, run
        cli = run(parser().parse_args(['search', 'hello', '--kb', 'demo', '--limit', '1']))
        web = self.get('/api/search?kb=demo&query=hello&mode=keyword&limit=1')[1]
        self.assertEqual(cli, web)

    def test_static_assets_and_security_headers(self):
        for path in ('/', '/static/app.js', '/static/style.css'):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertTrue(body)

    def test_bad_limits_host_and_cross_origin_rejected(self):
        for path in ('/api/search?kb=demo&query=hello&mode=keyword&limit=-1', '/api/source?kb=other&id=anything'):
            self.assertEqual(self.get(path)[0], 400)
        self.assertEqual(self.request('/api/kbs', headers={'Origin': 'https://evil.test'})[0], 403)
        self.assertEqual(self.request('/api/kbs', headers={'Host': 'evil.test'})[0], 403)

    def test_post_rag_uses_service_and_returns_citations(self):
        with patch('cke.integrations.ollama.OllamaClient.answer', return_value='hello [S1]'):
            status, _, body = self.request('/api/ask', 'POST', {'kb': 'demo', 'query': 'hello', 'mode': 'keyword'})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(result['grounded'])
        self.assertEqual(result['citations'], ['S1'])

    def test_configuration_endpoint_and_agent_handoff(self):
        status, _, body = self.request('/api/config', 'POST', {'provider': 'copilot'})
        self.assertEqual(status, 200)
        settings = json.loads(body)
        self.assertEqual(settings['embedding_provider'], 'none')
        self.assertEqual(self.get('/api/config')[1]['provider'], 'copilot')
        status, _, body = self.request('/api/ask', 'POST', {'kb': 'demo', 'query': 'hello'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['handoff'], 'copilot')

    def test_configuration_rejects_api_key_field(self):
        status, _, body = self.request('/api/config', 'POST', {'provider': 'openai', 'api_key': 'do-not-store'})
        self.assertEqual(status, 400)
        self.assertNotIn('do-not-store', body.decode())
