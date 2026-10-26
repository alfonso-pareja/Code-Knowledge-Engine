"""Read-only MCP adapter with explicit errors and shared core services."""
from __future__ import annotations
import json
import os
import sys
from ..catalog import Catalog
from ..storage.sqlite_store import SQLiteStore
from ..retrieval.service import RetrievalService


def tool(name, description, properties, required=()):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}}


STRING = {'type': 'string'}
TOOLS = [
    tool('list_knowledge_bases', 'List configured knowledge bases', {}),
    tool('list_sources', 'List sources in a KB', {'kb': STRING}, ['kb']),
    tool('search_code', 'Search current code evidence', {'kb': STRING, 'query': STRING, 'mode': {'enum': ['keyword', 'semantic', 'hybrid']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'repos': {'type': 'array', 'items': STRING}, 'language': STRING}, ['kb', 'query']),
    tool('get_source', 'Read a current indexed chunk, never an arbitrary filesystem path', {'kb': STRING, 'chunk_id': STRING}, ['kb', 'chunk_id']),
    tool('find_symbol', 'Find symbol evidence by name', {'kb': STRING, 'query': STRING}, ['kb', 'query']),
    tool('get_graph', 'Get syntax or heuristic relations; not a runtime call graph', {'kb': STRING}, ['kb']),
    tool('trace_flow', 'Traverse static import candidates, not runtime execution', {'kb': STRING, 'node': STRING}, ['kb', 'node']),
    tool('analyze_impact', 'Find reverse import candidates; impact is not proven', {'kb': STRING, 'node': STRING}, ['kb', 'node']),
    tool('get_dependencies', 'Get imports and unresolved calls', {'kb': STRING}, ['kb']),
]


def execute(name: str, args: dict):
    allowed = {kb.strip() for kb in os.environ.get('CKE_MCP_ALLOWED_KBS', '').split(',') if kb.strip()}
    if name == 'list_knowledge_bases':
        return [kb for kb in Catalog().data['knowledge_bases'] if kb in allowed]
    kb = args['kb']
    if kb not in allowed:
        raise ValueError('KB is not authorized for MCP; configure CKE_MCP_ALLOWED_KBS')
    Catalog().sources(kb)
    if name == 'list_sources':
        return [vars(source) for source in Catalog().sources(kb)]
    store = SQLiteStore()
    try:
        if name == 'search_code':
            return RetrievalService(store).search(kb, args['query'], args.get('mode', 'keyword'), args.get('repos'), args.get('limit', 8), args.get('language'))
        if name == 'get_source':
            return store.get_chunk(kb, args['chunk_id'])
        if name == 'find_symbol':
            return [row for row in store.keyword_search(kb, args['query'], limit=100) if args['query'].lower() in row['symbol'].lower()]
        if name in ('get_graph', 'get_dependencies', 'trace_flow', 'analyze_impact'):
            from ..knowledge import KnowledgeService
            knowledge = KnowledgeService(store)
            if name in ('trace_flow', 'analyze_impact'):
                return knowledge.traverse(kb, args['node'], reverse=name == 'analyze_impact')
            return knowledge.graph(kb)
        raise ValueError('Unknown tool')
    finally:
        store.close()


def handle(message: dict) -> dict | None:
    request_id = message.get('id')
    method = message.get('method', '')
    if 'id' not in message:
        return None
    base = {'jsonrpc': '2.0', 'id': request_id}
    if method == 'initialize':
        result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'cke-python', 'version': '3.0.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'tools/call':
        try:
            params = message['params']
            name, args = params['name'], params.get('arguments', {})
            definition = next((tool for tool in TOOLS if tool['name'] == name), None)
            if definition is None:
                raise ValueError('Unknown tool')
            schema = definition['inputSchema']
            if not isinstance(args, dict) or set(args) - set(schema['properties']) or any(key not in args for key in schema['required']):
                raise ValueError('Invalid tool arguments')
            for key, value in args.items():
                kind = schema['properties'][key].get('type')
                if kind == 'string' and not isinstance(value, str):
                    raise ValueError('Expected a string: ' + key)
            answer = execute(name, args)
            result = {'content': [{'type': 'text', 'text': json.dumps(answer, ensure_ascii=False)}]}
        except Exception as exc:
            result = {'isError': True, 'content': [{'type': 'text', 'text': str(exc) if isinstance(exc, (ValueError, KeyError)) else 'Knowledge service unavailable'}]}
    else:
        return {**base, 'error': {'code': -32601, 'message': 'Unknown method'}}
    return {**base, 'result': result}


def serve() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('Expected JSON-RPC object')
            response = handle(message)
        except (ValueError, TypeError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON-RPC request'}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
            sys.stdout.flush()
