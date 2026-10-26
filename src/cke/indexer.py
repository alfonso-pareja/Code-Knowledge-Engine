"""Idempotent vector publication; incomplete generations are never queryable."""
from collections.abc import Callable
from .storage.sqlite_store import SQLiteStore
from .providers import embedding_client, vector_client
from .catalog import Catalog
from .contracts import Embedder, VectorStore


def index_kb(kb: str, batch_size: int = 8, embedder: Embedder | None = None, vectors: VectorStore | None = None, progress: Callable[[str, int, int], None] | None = None) -> dict:
    from .locking import exclusive
    if progress:
        progress('Esperando acceso al índice', 0, 0)
    with exclusive('kb:' + kb):
        return _index_kb(kb, batch_size, embedder, vectors, progress)


def _index_kb(kb, batch_size, embedder, vectors, progress=None):
    Catalog().sources(kb)
    if not 1 <= batch_size <= 100:
        raise ValueError('Batch size must be between 1 and 100')
    store = SQLiteStore()
    try:
        rows = store.chunks(kb)
        signature = store.signature(kb)
        ollama, qdrant = embedder or embedding_client(), vectors or vector_client()
        if not rows:
            qdrant.delete_kb(kb)
            return {'kb': kb, 'indexed': 0, 'collection': qdrant.collection}
        if progress:
            progress('Comprobando modelo', 0, len(rows))
        model_identity = ollama.identity()
        if store.vectors_current(kb, qdrant.collection, model_identity):
            return {'kb': kb, 'indexed': 0, 'reused': len(rows), 'model': ollama.model, 'model_revision': model_identity, 'collection': qdrant.collection}
        # Invalidate before any remote mutation. Failed runs require an explicit retry.
        store.mark_vectors(kb, qdrant.collection, model_identity, '')
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            if progress:
                progress(f'Generando embeddings · lote {offset // batch_size + 1}/{(len(rows) + batch_size - 1) // batch_size}', offset, len(rows))
            embeddings = ollama.embed([row['embedding_text'] for row in batch])
            if offset == 0:
                qdrant.ensure(len(embeddings[0]))
                qdrant.delete_kb(kb)
            if progress:
                progress('Guardando vectores en Qdrant', offset, len(rows))
            qdrant.upsert(batch, embeddings)
            if progress:
                progress('Lote completado', offset + len(batch), len(rows))
        if store.signature(kb) != signature:
            raise RuntimeError('Chunks changed while embedding; rerun cke index')
        store.mark_vectors(kb, qdrant.collection, model_identity, signature)
        return {'kb': kb, 'indexed': len(rows), 'model': ollama.model, 'model_revision': model_identity, 'collection': qdrant.collection}
    finally:
        store.close()
