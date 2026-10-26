"""Evidence navigation and conservative dependency graph, independent of presentation."""
from collections import deque
import json
from pathlib import PurePosixPath
from .catalog import Catalog
from .storage.sqlite_store import SQLiteStore


class KnowledgeService:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def graph(self, kb: str) -> dict:
        Catalog().sources(kb)
        rows = self.store.chunks(kb)
        nodes, packages = {}, {}
        for row in rows:
            key = self.node_id(row)
            nodes.setdefault(key, {'id': key, 'source': row['source'], 'project': row['project'], 'filepath': row['filepath'], 'chunk_id': row['id']})
            if row['filepath'] == 'package.json' and row['start_line'] == 1:
                try:
                    name = json.loads(row['content']).get('name')
                    if name:
                        packages.setdefault(name, []).append(key)
                except (ValueError, TypeError):
                    pass
        edges = []
        for row in self.store.graph(kb, limit=100000):
            origin = self.node_id(row)
            if not row['kind'].startswith('import') or origin not in nodes:
                continue
            targets = []
            if row['target'].startswith('.'):
                base = PurePosixPath(row['filepath']).parent
                parts = []
                for part in (base / row['target']).parts:
                    if part == '..':
                        if parts:
                            parts.pop()
                    elif part != '.':
                        parts.append(part)
                path = '/'.join(parts)
                candidates = {path, *(path + ext for ext in ('.ts','.tsx','.js','.jsx','.py','/index.ts','/index.js','/__init__.py'))}
                targets = [key for key, node in nodes.items() if node['source'] == row['source'] and node['project'] == row['project'] and node['filepath'] in candidates]
            else:
                for package, keys in packages.items():
                    if row['target'] == package or row['target'].startswith(package + '/'):
                        targets.extend(keys)
            if targets:
                for target in targets:
                    edges.append({'source': origin, 'target': target, 'kind': row['kind'], 'line': row['line'], 'evidence': row['target'], 'resolution': 'candidate_static'})
            else:
                target = 'external:' + row['target']
                nodes.setdefault(target, {'id': target, 'filepath': row['target'], 'external': True})
                edges.append({'source': origin, 'target': target, 'kind': row['kind'], 'line': row['line'], 'evidence': row['target'], 'resolution': 'unresolved'})
        return {'nodes': list(nodes.values()), 'edges': edges, 'warning': 'Static import candidates only; aliases, HTTP, queues and runtime dispatch are not resolved.'}

    @staticmethod
    def node_id(row: dict) -> str:
        return json.dumps([row['source'], row['project'], row['filepath']], separators=(',', ':'))

    def traverse(self, kb: str, node: str, reverse: bool = False, depth: int = 3) -> dict:
        if type(depth) is not int or not 1 <= depth <= 10:
            raise ValueError('Depth must be between 1 and 10')
        graph = self.graph(kb)
        if node not in {item['id'] for item in graph['nodes']}:
            raise ValueError('Unknown graph node')
        seen, queue, evidence = {node}, deque([(node, 0)]), []
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for edge in graph['edges']:
                origin, target = (edge['target'], edge['source']) if reverse else (edge['source'], edge['target'])
                if origin == current:
                    evidence.append(edge)
                    if target not in seen:
                        seen.add(target)
                        queue.append((target, level + 1))
        return {'nodes': [item for item in graph['nodes'] if item['id'] in seen], 'edges': evidence, 'warning': graph['warning']}
