"""Long inputs are split only for context errors, with no source text loss."""
import io
import json
import math
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from cke.integrations.ollama import OllamaClient, EmbeddingContextError


class OllamaContextTests(unittest.TestCase):
    def test_long_input_covers_all_content_and_keeps_batch_order(self):
        client = OllamaClient()
        accepted = []
        def post(route, payload):
            if any(len(text) > 10 for text in payload['input']):
                raise EmbeddingContextError('context')
            accepted.extend(payload['input'])
            return {'embeddings': [[1.0, len(text) / 10] for text in payload['input']]}
        original = 'first section\nsecond section\nthird section'
        with patch.object(client, 'post', side_effect=post):
            results = client.embed(['short', original])
        self.assertEqual(len(results), 2)
        self.assertEqual(''.join(accepted[1:]), original)
        self.assertTrue(all(len(vector) == 2 for vector in results))
        self.assertAlmostEqual(sum(value * value for value in results[1]), 1)

    def test_non_context_failure_is_not_retried(self):
        client = OllamaClient()
        with patch.object(client, 'post', side_effect=RuntimeError('HTTP 500')) as request:
            with self.assertRaisesRegex(RuntimeError, '500'):
                client.embed(['text'])
        self.assertEqual(request.call_count, 1)

    def test_context_http_error_classified_without_exposing_source(self):
        client = OllamaClient()
        error = HTTPError('http://localhost/api/embed', 400, 'Bad Request', {}, io.BytesIO(json.dumps({'error': 'input length exceeds maximum context length: PRIVATE_SOURCE'}).encode()))
        with patch('cke.integrations.ollama.open_request', side_effect=error):
            with self.assertRaises(EmbeddingContextError) as caught:
                client.post('/api/embed', {'model': 'embeddinggemma', 'input': ['code']})
        self.assertNotIn('PRIVATE_SOURCE', str(caught.exception))

    def test_other_http_error_identifies_ollama_and_route(self):
        error = HTTPError('http://localhost/api/embed', 400, 'Bad Request', {}, io.BytesIO(b'{"error":"PRIVATE_SOURCE"}'))
        with patch('cke.integrations.ollama.open_request', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'Ollama.*400.*api/embed') as caught:
                OllamaClient().embed(['text'])
        self.assertNotIn('PRIVATE_SOURCE', str(caught.exception))

    def test_short_inputs_keep_existing_vectors_unchanged(self):
        with patch.object(OllamaClient, 'post', return_value={'embeddings': [[.6, .8]]}):
            self.assertEqual(OllamaClient().embed(['short']), [[.6, .8]])
