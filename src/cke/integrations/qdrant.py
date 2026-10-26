"""Minimal Qdrant REST adapter (local by default, no external package required)."""
from __future__ import annotations
import json
import os
import uuid
from urllib.request import Request
from .transport import validate_endpoint, open_request
from urllib.error import HTTPError

class QdrantClient:
    def __init__(self, collection: str | None = None):
        self.url = validate_endpoint(os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333').rstrip('/'))
        self.collection = collection or os.environ.get('CKE_COLLECTION', 'cke_python_v1')

    def call(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=data, method=method,
                          headers={'Content-Type':'application/json'})
        try:
            with open_request(request, timeout=120) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404:
                raise
            error.close()
            raise RuntimeError(f'Qdrant respondió HTTP {error.code} en {method} {path}. Revisa la colección y sus dimensiones.') from None

    def ensure(self, dimensions: int) -> None:
        try:
            result = self.call('GET', f'/collections/{self.collection}')
            params = result['result']['config']['params']['vectors']
            if params['size'] != dimensions or params['distance'] != 'Cosine':
                raise ValueError('Embedding model dimensions changed. Use a new CKE_COLLECTION.')
        except HTTPError as exc:
            if exc.code != 404:
                raise
            self.call('PUT', f'/collections/{self.collection}',
                      {'vectors': {'size': dimensions, 'distance': 'Cosine'}})

    def upsert(self, rows: list[dict], vectors: list[list[float]]) -> None:
        points = [{'id': str(uuid.uuid5(uuid.NAMESPACE_URL, row['id'])), 'vector': vector,
                   'payload': {k: row[k] for k in ('id', 'kb', 'source', 'project', 'snapshot',
                                                  'filepath', 'language', 'symbol', 'start_line', 'end_line', 'content')}}
                  for row, vector in zip(rows, vectors, strict=True)]
        self.call('PUT', f'/collections/{self.collection}/points?wait=true', {'points': points})

    def delete_kb(self, kb: str) -> None:
        try:
            self.call('POST', f'/collections/{self.collection}/points/delete?wait=true',
                      {'filter': {'must': [{'key': 'kb', 'match': {'value': kb}}]}})
        except HTTPError as exc:
            if exc.code != 404:
                raise

    def search(self, kb: str, vector: list[float], limit: int = 10,
               repos: list[str] | None = None, language: str | None = None) -> list[dict]:
        must = [{'key': 'kb', 'match': {'value': kb}}]
        if repos:
            must.append({'should': [{'key': key, 'match': {'any': repos}} for key in ('source', 'project')]})
        if language:
            must.append({'key': 'language', 'match': {'value': language}})
        response = self.call('POST', f'/collections/{self.collection}/points/query', {
            'query': vector, 'limit': limit, 'with_payload': True,
            'filter': {'must': must},
        })
        return [{**point.get('payload', {}), 'score': point['score']} for point in response['result']['points']]
