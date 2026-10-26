"""Loopback HTTP adapter. Search and RAG behavior live in reusable services."""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from ..catalog import Catalog
from ..settings import configure, settings_status, load_settings
from ..retrieval.service import RetrievalService
from ..answers.service import AnswerService
from ..knowledge import KnowledgeService
from ..storage.sqlite_store import SQLiteStore

STATIC = Path(__file__).parent / 'static'
# Backward-compatible export for clients inspecting the page.
PAGE = (STATIC / 'index.html').read_text()


class Handler(BaseHTTPRequestHandler):
    def trusted_request(self) -> bool:
        expected = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') not in (expected, f'localhost:{self.server.server_port}'):
            self.respond_json(403, {'error': 'Host no autorizado'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://{expected}', f'http://localhost:{self.server.server_port}'):
            self.respond_json(403, {'error': 'Origen no autorizado'})
            return False
        return True

    def do_GET(self) -> None:
        if not self.trusted_request():
            return
        url = urlparse(self.path)
        parameters = parse_qs(url.query)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/static/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/static/style.css': ('style.css', 'text/css; charset=utf-8')}
        if url.path in assets:
            filename, content_type = assets[url.path]
            self.respond(200, (STATIC / filename).read_bytes(), content_type)
            return
        self.dispatch(url.path, {key: values[0] for key, values in parameters.items()})

    def do_POST(self) -> None:
        if not self.trusted_request():
            return
        if urlparse(self.path).path not in ('/api/ask', '/api/config'):
            self.respond_json(404, {'error': 'Endpoint no encontrado'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16000:
                raise ValueError('Tamaño de solicitud no permitido')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Se requiere application/json')
            parameters = json.loads(self.rfile.read(length))
            if not isinstance(parameters, dict):
                raise ValueError('Se requiere un objeto JSON')
        except (ValueError, TypeError) as error:
            self.respond_json(400, {'error': str(error)})
            return
        path = urlparse(self.path).path
        if path == '/api/config':
            try:
                allowed = {'provider', 'model', 'embedding_provider', 'embedding_model', 'allow_cloud_code'}
                if set(parameters) - allowed:
                    raise ValueError('Unknown configuration fields; API keys must stay in the environment')
                configure(**parameters)
                self.respond_json(200, settings_status())
            except (ValueError, TypeError) as error:
                self.respond_json(400, {'error': str(error)})
            return
        self.dispatch('/api/ask', parameters)

    def dispatch(self, path: str, args: dict) -> None:
        store = None
        try:
            if path == '/api/config':
                self.respond_json(200, settings_status())
                return
            if path == '/api/kbs':
                self.respond_json(200, Catalog().data['knowledge_bases'])
                return
            if path not in ('/api/search', '/api/graph', '/graph', '/api/network', '/api/source', '/api/ask'):
                self.respond_json(404, {'error': 'Endpoint no encontrado'})
                return
            kb = args.get('kb', '')
            Catalog().sources(kb)
            store = SQLiteStore()
            if path in ('/api/graph', '/graph'):
                result = store.graph(kb)
            elif path == '/api/network':
                result = KnowledgeService(store).graph(kb)
            elif path == '/api/source':
                result = store.get_chunk(kb, args.get('id', ''))
            else:
                repos = args.get('repos') or None
                if isinstance(repos, str):
                    repos = [value.strip() for value in repos.split(',') if value.strip()]
                raw_limit = args.get('limit', 10)
                if type(raw_limit) is int:
                    limit = raw_limit
                elif isinstance(raw_limit, str):
                    limit = int(raw_limit)
                else:
                    raise ValueError('Limit must be an integer between 1 and 100')
                options = dict(kb=kb, query=args.get('query', ''), mode=args.get('mode') or load_settings().search_mode, repos=repos, limit=limit, language=args.get('language') or None)
                retrieval = RetrievalService(store)
                if path == '/api/ask':
                    result = AnswerService(retrieval).ask(**options, model=args.get('model') or None)
                else:
                    result = retrieval.search(**options)
            self.respond_json(200, result)
        except (ValueError, TypeError) as error:
            self.respond_json(400, {'error': str(error)})
        except RuntimeError as error:
            self.respond_json(503, {'error': str(error)})
        except Exception:
            self.respond_json(503, {'error': 'No fue posible consultar el índice. Ejecuta cke config check.'})
        finally:
            if store:
                store.close()

    def respond_json(self, status: int, obj: object) -> None:
        self.respond(status, json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def respond(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)


def serve(port: int = 8765) -> None:
    print(f'CKE Knowledge Explorer: http://127.0.0.1:{port}')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
