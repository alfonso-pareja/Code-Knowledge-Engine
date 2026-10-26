"""SQLite unit-of-work: atomic per-project publication and FTS5 search."""
from __future__ import annotations
import sqlite3
import os
from ..config import ensure_home
from ..models import CodeChunk

SCHEMA = '''
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, kb TEXT NOT NULL, source TEXT NOT NULL, project TEXT NOT NULL,
  snapshot TEXT NOT NULL, filepath TEXT NOT NULL, language TEXT NOT NULL,
  symbol TEXT, start_line INTEGER, end_line INTEGER, content TEXT, embedding_text TEXT
);
CREATE INDEX IF NOT EXISTS chunk_scope ON chunks(kb, source, project);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, body, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS publications (
  kb TEXT, source TEXT, project TEXT, snapshot TEXT,
  PRIMARY KEY(kb, source, project)
);
CREATE TABLE IF NOT EXISTS relations (
  kb TEXT, source TEXT, project TEXT, filepath TEXT, target TEXT, kind TEXT, line INTEGER
);
CREATE TABLE IF NOT EXISTS file_cache (kb TEXT, source TEXT, project TEXT, filepath TEXT, hash TEXT, version TEXT, chunks TEXT, relations TEXT, PRIMARY KEY(kb,source,project,filepath));
CREATE TABLE IF NOT EXISTS vector_generations (kb TEXT, collection TEXT, model TEXT, signature TEXT, PRIMARY KEY(kb,collection));

'''

class SQLiteStore:
    def __init__(self):
        database = ensure_home() / 'knowledge.sqlite'
        descriptor = os.open(database, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        database.chmod(0o600)
        self.connection = sqlite3.connect(database, timeout=30)
        self.connection.row_factory = sqlite3.Row
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        if version > 3:
            self.connection.close()
            raise ValueError('Database was created by a newer CKE version')
        self.connection.executescript(SCHEMA)
        self.connection.execute('PRAGMA user_version=3')

    def close(self) -> None:
        self.connection.close()

    def published(self, kb: str, source: str, project: str) -> str | None:
        row = self.connection.execute('SELECT snapshot FROM publications WHERE kb=? AND source=? AND project=?', (kb, source, project)).fetchone()
        return row['snapshot'] if row else None

    def publish(self, snapshot: dict, chunks: list[CodeChunk], relations: list[tuple]) -> None:
        with self.connection:
            self._publish(snapshot, chunks, relations)

    def _publish(self, snapshot: dict, chunks: list[CodeChunk], relations: list[tuple]) -> None:
        kb, source, project = snapshot['kb'], snapshot['source'], snapshot['project']
        self.connection.execute('DELETE FROM chunks_fts WHERE id IN (SELECT id FROM chunks WHERE kb=? AND source=? AND project=?)', (kb, source, project))
        self.connection.execute('DELETE FROM chunks WHERE kb=? AND source=? AND project=?', (kb, source, project))
        self.connection.execute('DELETE FROM relations WHERE kb=? AND source=? AND project=?', (kb, source, project))
        self.connection.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [(chunk.id, chunk.kb, chunk.source, chunk.project, chunk.snapshot, chunk.filepath, chunk.language, chunk.symbol, chunk.start_line, chunk.end_line, chunk.content, chunk.embedding_text) for chunk in chunks])
        self.connection.executemany('INSERT INTO chunks_fts(id,body) VALUES (?,?)', [(chunk.id, chunk.embedding_text) for chunk in chunks])
        self.connection.executemany('INSERT INTO relations VALUES (?,?,?,?,?,?,?)', relations)
        self.connection.execute('INSERT OR REPLACE INTO publications VALUES (?,?,?,?)', (kb, source, project, snapshot['id']))

    def chunks(self, kb: str, source: str | None = None) -> list[dict]:
        sql = 'SELECT * FROM chunks WHERE kb=?'
        args: list[str] = [kb]
        if source:
            sql += ' AND source=?'
            args.append(source)
        return [dict(row) for row in self.connection.execute(sql, args)]

    def keyword_search(self, kb: str, question: str, repos: list[str] | None = None, limit: int = 10, language: str | None = None) -> list[dict]:
        import re
        tokens = re.findall(r'\w+', question, re.UNICODE)[:16]
        if not tokens:
            return []
        match_query = ' OR '.join('"' + token.replace('"', '') + '"' for token in tokens)
        sql = ('SELECT c.*, bm25(chunks_fts) AS rank FROM chunks_fts '
               'JOIN chunks c ON c.id=chunks_fts.id WHERE chunks_fts MATCH ? AND c.kb=?')
        args: list = [match_query, kb]
        if repos:
            sql += f' AND (c.project IN ({",".join("?" for _ in repos)}) OR c.source IN ({",".join("?" for _ in repos)}))'
            args.extend(repos + repos)
        if language:
            sql += ' AND c.language=?'
            args.append(language)
        sql += ' ORDER BY rank, c.id LIMIT ?'
        args.append(max(1, min(limit, 100)))
        return [dict(row) for row in self.connection.execute(sql, args)]

    def graph(self, kb: str, limit: int = 200) -> list[dict]:
        return [dict(row) for row in self.connection.execute('SELECT * FROM relations WHERE kb=? LIMIT ?', (kb, limit))]

    def publish_kb(self, kb: str, publications: list[tuple], active: set[tuple[str, str]], cache: list[tuple]) -> None:
        """Publish every changed project and reconcile deleted projects in one transaction."""
        with self.connection:
            for snapshot, chunks, relations in publications:
                self._publish(snapshot, chunks, relations)
            for row in self.connection.execute('SELECT source,project FROM publications WHERE kb=?', (kb,)).fetchall():
                if (row['source'], row['project']) not in active:
                    scope = (kb, row['source'], row['project'])
                    self.connection.execute('DELETE FROM chunks_fts WHERE id IN (SELECT id FROM chunks WHERE kb=? AND source=? AND project=?)', scope)
                    for table in ('chunks', 'relations', 'publications', 'file_cache'):
                        self.connection.execute(f'DELETE FROM {table} WHERE kb=? AND source=? AND project=?', scope)
            self.connection.executemany('INSERT OR REPLACE INTO file_cache VALUES (?,?,?,?,?,?,?,?)', cache)
            self.connection.execute('DELETE FROM file_cache WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.kb=file_cache.kb AND c.source=file_cache.source AND c.project=file_cache.project AND c.filepath=file_cache.filepath) AND kb=?', (kb,))

    def cached_file(self, kb, source, project, path, file_hash, version):
        import json
        row = self.connection.execute('SELECT chunks,relations FROM file_cache WHERE kb=? AND source=? AND project=? AND filepath=? AND hash=? AND version=?', (kb,source,project,path,file_hash,version)).fetchone()
        return (json.loads(row['chunks']), json.loads(row['relations'])) if row else None

    def signature(self, kb: str) -> str:
        from ..utils import digest
        return digest(repr(sorted((row['id'], row['snapshot']) for row in self.chunks(kb))))

    def mark_vectors(self, kb: str, collection: str, model: str, signature: str) -> None:
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO vector_generations VALUES (?,?,?,?)', (kb, collection, model, signature))

    def vectors_current(self, kb: str, collection: str, model: str) -> bool:
        row = self.connection.execute('SELECT model,signature FROM vector_generations WHERE kb=? AND collection=?', (kb, collection)).fetchone()
        return bool(row and row['model'] == model and row['signature'] == self.signature(kb))

    def get_chunk(self, kb: str, chunk_id: str) -> dict:
        row = self.connection.execute('SELECT * FROM chunks WHERE kb=? AND id=?', (kb,chunk_id)).fetchone()
        if row is None:
            raise ValueError('Chunk does not belong to the current KB publication')
        return dict(row)
