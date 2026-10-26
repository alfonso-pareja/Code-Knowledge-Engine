"""Small reproducible retrieval evaluation, independent of an answer model."""
import json
from pathlib import Path
from time import perf_counter
from .retrieval.service import RetrievalService


def evaluate_dataset(retrieval: RetrievalService, kb: str, dataset: str,
                     mode: str = 'keyword', limit: int = 8) -> dict:
    cases = json.loads(Path(dataset).read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError('Dataset must be a nonempty JSON list')
    measurements = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('query'), str):
            raise ValueError('Each case requires a query')
        expected = case.get('expected_files')
        if not isinstance(expected, list) or not expected or not all(isinstance(path, str) for path in expected):
            raise ValueError('Each case requires nonempty expected_files')
        started = perf_counter()
        results = retrieval.search(kb, case['query'], mode=mode, limit=limit)
        found = [row['filepath'] for row in results]
        relevant = set(expected)
        first = next((rank for rank, path in enumerate(found, 1) if path in relevant), None)
        measurements.append({'recall': len(set(found) & relevant) / len(relevant),
                             'reciprocal_rank': 1 / first if first else 0,
                             'latency_ms': (perf_counter() - started) * 1000})
    count = len(measurements)
    return {'kb': kb, 'mode': mode, 'limit': limit, 'queries': count,
            'recall_at_k': sum(row['recall'] for row in measurements) / count,
            'mrr': sum(row['reciprocal_rank'] for row in measurements) / count,
            'mean_latency_ms': sum(row['latency_ms'] for row in measurements) / count}
