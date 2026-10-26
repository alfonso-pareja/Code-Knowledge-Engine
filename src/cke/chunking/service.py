"""Prepare consistent publications before atomically replacing KB evidence."""
from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
from ..sources.manager import scan_kb, load_snapshot
from ..storage.sqlite_store import SQLiteStore
from ..security import read_safe_file
from ..models import CodeChunk
from .builder import ChunkBuilder
from .analysis import analyze

from .treesitter import fingerprint
PIPELINE_VERSION = '3.0|' + fingerprint()


class ChunkingService:
    def __init__(self, store: SQLiteStore, builder: ChunkBuilder | None = None):
        self.store = store
        self.builder = builder or ChunkBuilder()

    def run(self, kb: str, sync_remote: bool = False) -> dict:
        from ..locking import exclusive
        with exclusive('kb:' + kb):
            return self._run(kb, sync_remote)

    def _run(self, kb: str, sync_remote: bool = False) -> dict:
        version = PIPELINE_VERSION + '|' + self.builder.version
        snapshots = scan_kb(kb, sync_remote=sync_remote)
        publications, cache_updates = [], []
        created = reused_files = omitted = 0
        active = set()
        for item in snapshots:
            snapshot = load_snapshot(item['snapshot'])
            active.add((item['source'], item['project']))
            chunks, relations = [], []
            for entry in snapshot['files']:
                content = read_safe_file(Path(snapshot['root']), entry['path'], entry['sha256'])
                if content is None:
                    omitted += 1
                    continue
                cached = self.store.cached_file(kb, item['source'], item['project'], entry['path'], entry['sha256'], version)
                if cached:
                    file_chunks = [replace(CodeChunk(**row), snapshot=snapshot['id']) for row in cached[0]]
                    file_relations = [tuple(row) for row in cached[1]]
                    reused_files += 1
                else:
                    file_chunks = self.builder.build_content(snapshot, entry, content)
                    file_relations = analyze(snapshot, entry['path'], content)
                    created += len(file_chunks)
                chunks.extend(file_chunks)
                relations.extend(file_relations)
                cache_updates.append((kb, item['source'], item['project'], entry['path'], entry['sha256'], version, json.dumps([c.to_dict() for c in file_chunks]), json.dumps(file_relations)))
            # Validate every file again before publishing; failed reads preserve the prior KB.
            for entry in snapshot['files']:
                read_safe_file(Path(snapshot['root']), entry['path'], entry['sha256'])
            publications.append((snapshot, chunks, relations))
        unchanged = sum(self.store.published(kb, s['source'], s['project']) == s['id'] for s, _, _ in publications)
        self.store.publish_kb(kb, publications, active, cache_updates)
        return {'kb': kb, 'projects': len(snapshots), 'chunks_created': created, 'unchanged_projects': unchanged,
                'reused_files': reused_files, 'skipped_files': omitted, 'total_chunks': len(self.store.chunks(kb))}
