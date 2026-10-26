"""Validated search contract shared by CLI, HTTP, MCP and answer generation."""
from __future__ import annotations
from ..catalog import Catalog
from ..contracts import Embedder, VectorStore, SearchResult
from ..storage.sqlite_store import SQLiteStore
from ..providers import embedding_client, vector_client


class RetrievalService:
    def __init__(self, store: SQLiteStore, embedder: Embedder | None = None, vectors: VectorStore | None = None):
        self.store = store
        self.embedder = embedder
        self.vectors = vectors

    def search(self, kb: str, query: str, mode: str = 'keyword', repos: list[str] | None = None,
               limit: int = 10, language: str | None = None) -> list[SearchResult]:
        if kb not in Catalog().data['knowledge_bases']:
            raise ValueError('Unknown KB')
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise ValueError('Query must have between 1 and 2000 characters')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Limit must be an integer between 1 and 100')
        if mode not in ('keyword', 'semantic', 'hybrid'):
            raise ValueError('Unknown search mode')
        if repos is not None and (not isinstance(repos, list) or any(not isinstance(repo, str) for repo in repos)):
            raise ValueError('Repository filters must be a list of strings')
        lexical = []
        if mode in ('keyword', 'hybrid'):
            lexical = self.store.keyword_search(kb, query, repos, min(100, limit * 2), language)
            if mode == 'keyword':
                return lexical[:limit]
        if not self.store.chunks(kb):
            return []
        embedder = self.embedder or embedding_client()
        vectors = self.vectors or vector_client()
        if not self.store.vectors_current(kb, vectors.collection, embedder.identity()):
            raise ValueError('Vector index is missing or outdated for this model; run cke index --kb ' + kb)
        hits = vectors.search(kb, embedder.embed([query])[0], min(200, limit * 2), repos, language)
        semantic = []
        for hit in hits:
            try:
                current = self.store.get_chunk(kb, hit['id'])
            except (ValueError, KeyError):
                continue
            if current['snapshot'] != hit.get('snapshot'):
                continue
            semantic.append({**current, 'score': hit['score']})
        if mode == 'semantic':
            return semantic[:limit]
        merged: dict[str, dict] = {}
        for results in (lexical, semantic):
            for rank, row in enumerate(results, 1):
                entry = merged.setdefault(row['id'], {**row, 'rank_score': 0.0})
                entry['rank_score'] += 1 / (60 + rank)
        return sorted(merged.values(), key=lambda row: row['rank_score'], reverse=True)[:limit]
