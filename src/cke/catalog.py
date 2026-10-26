"""Knowledge bases and registered source configuration."""
from __future__ import annotations
import re
from pathlib import Path
from dataclasses import asdict
from .config import ensure_home
from .models import KnowledgeSource
from .utils import read_json, write_json, slug

def catalog_mutation(method):
    from functools import wraps
    @wraps(method)
    def locked(self, *args, **kwargs):
        from .locking import exclusive
        with exclusive('catalog'):
            self.data = read_json(self.path, {'version': 2, 'knowledge_bases': [], 'sources': []})
            return method(self, *args, **kwargs)
    return locked


class Catalog:
    def __init__(self):
        self.path = ensure_home() / 'catalog.json'
        self.data = read_json(self.path, {'version': 2, 'knowledge_bases': [], 'sources': []})

    def save(self) -> None:
        write_json(self.path, self.data)

    @catalog_mutation
    def create_kb(self, kb: str) -> None:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', kb):
            raise ValueError('Invalid KB ID')
        if kb in self.data['knowledge_bases']:
            raise ValueError('Knowledge base already exists')
        self.data['knowledge_bases'].append(kb)
        self.save()

    @catalog_mutation
    def add_source(self, kb: str, location: str, kind: str = 'auto', source_id: str | None = None, ref: str = 'HEAD') -> KnowledgeSource:
        if kb not in self.data['knowledge_bases']:
            raise ValueError(f'Unknown KB: {kb}')
        if kind == 'auto':
            kind = 'git' if location.startswith(('git@', 'https://', 'ssh://')) else 'local'
        if kind not in ('local', 'workspace', 'git'):
            raise ValueError(f'Unsupported source type: {kind}')
        if kind == 'git':
            from urllib.parse import urlsplit
            parsed = urlsplit(location)
            if parsed.scheme in ('http', 'https') and (parsed.username or parsed.password):
                raise ValueError('Do not store credentials in Git URLs; use a credential helper')
            if ref.startswith('-'):
                raise ValueError('Git ref must not start with a dash')
        if kind != 'git':
            location = str(Path(location).expanduser().resolve())
            if not Path(location).is_dir():
                raise ValueError(f'Not a directory: {location}')
        source_id = source_id or slug(location.rstrip('/').split('/')[-1].removesuffix('.git'))
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', source_id):
            raise ValueError('Invalid source ID')
        if any(s['kb'] == kb and s['id'] == source_id for s in self.data['sources']):
            raise ValueError('Duplicated source ID within KB')
        source = KnowledgeSource(source_id, kb, kind, location, ref)
        self.data['sources'].append(asdict(source))
        self.save()
        return source

    def sources(self, kb: str) -> list[KnowledgeSource]:
        if kb not in self.data['knowledge_bases']:
            raise ValueError(f'Unknown KB: {kb}')
        return [KnowledgeSource(**s) for s in self.data['sources'] if s['kb'] == kb]

    @catalog_mutation
    def remove_source(self, kb: str, source_id: str) -> None:
        self.sources(kb)
        self.data['sources'] = [source for source in self.data['sources'] if not (source['kb'] == kb and source['id'] == source_id)]
        self.save()
