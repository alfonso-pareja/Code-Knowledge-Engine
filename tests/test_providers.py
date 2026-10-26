"""Provider choices, cloud consent, API payloads and agent handoff without network."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from cke.settings import configure, load_settings, settings_status
from cke.providers import embedding_client, answer_client, vector_client
from cke.integrations.openai import OpenAIClient
from cke.answers.service import AnswerService
from cke.cli import parser, run


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'CKE_HOME': self.temp.name, 'OPENAI_API_KEY': '', 'CKE_COLLECTION': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop('CKE_COLLECTION')

    def test_legacy_defaults_remain_local(self):
        self.assertEqual(load_settings().provider, 'ollama')
        self.assertEqual(embedding_client().model, 'embeddinggemma')
        self.assertEqual(vector_client().collection, 'cke_python_v1')

    def test_local_instructions_include_install_and_both_pulls(self):
        configure('ollama', 'custom-chat', embedding_model='custom-embedding')
        steps = '\n'.join(settings_status()['instructions'])
        self.assertIn('https://ollama.com/download', steps)
        self.assertIn('ollama pull custom-chat', steps)
        self.assertIn('ollama pull custom-embedding', steps)

    def test_agent_needs_no_local_or_vector_services(self):
        configure('copilot')
        self.assertEqual(load_settings().search_mode, 'keyword')
        self.assertIsNone(answer_client())
        with self.assertRaisesRegex(ValueError, 'keyword'):
            embedding_client()
        with patch('cke.diagnostics.open_request') as network:
            from cke.diagnostics import doctor
            report = doctor()
        network.assert_not_called()
        self.assertFalse(report['ollama']['required'])
        self.assertFalse(report['qdrant']['required'])

    def test_openai_without_embeddings_needs_no_ollama_qdrant(self):
        configure('openai', embedding_provider='none')
        with patch('cke.diagnostics.open_request') as network:
            from cke.diagnostics import doctor
            report = doctor()
        network.assert_not_called()
        self.assertFalse(report['openai']['credentials_present'])
        self.assertFalse(report['openai']['code_transfer_authorized'])

    def test_cloud_requires_explicit_consent_and_credentials(self):
        configure('openai')
        with patch('cke.integrations.openai.open_request') as network:
            with self.assertRaisesRegex(ValueError, 'autorizado'):
                answer_client().answer('question', 'private code')
            configure('openai', allow_cloud_code=True)
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                answer_client().answer('question', 'private code')
        network.assert_not_called()

    def test_key_never_saved_or_returned(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-private-key'}):
            configure('openai', allow_cloud_code=True)
            result = settings_status()
        self.assertTrue(result['api_key_configured'])
        self.assertNotIn('synthetic-private-key', json.dumps(result))
        self.assertNotIn('synthetic-private-key', (Path(self.temp.name) / 'settings.json').read_text())
        self.assertEqual((Path(self.temp.name) / 'settings.json').stat().st_mode & 0o777, 0o600)

    def test_settings_validation(self):
        for kwargs in ({'provider': 'bad'}, {'provider': 'openai', 'embedding_provider': 'copilot'},
                       {'provider': 'openai', 'allow_cloud_code': 'yes'}, {'provider': 'ollama', 'model': 'model;command'}):
            with self.assertRaises(ValueError):
                configure(**kwargs)

    def test_changing_embedding_model_separates_collections(self):
        configure('ollama')
        local = vector_client().collection
        configure('openai')
        cloud = vector_client().collection
        self.assertNotEqual(local, cloud)
        configure('openai', model='another-answer-model')
        self.assertEqual(vector_client().collection, cloud)

    def test_explicit_collection_override(self):
        configure('openai')
        with patch.dict(os.environ, {'CKE_COLLECTION': 'explicit'}):
            self.assertEqual(vector_client().collection, 'explicit')

    def test_cli_configuration_roundtrip(self):
        result = run(parser().parse_args(['config', 'set', '--provider', 'chatgpt']))
        self.assertEqual(result['provider'], 'chatgpt')
        self.assertEqual(result['embedding_provider'], 'none')
        self.assertIn('stdio', '\n'.join(result['instructions']))
        self.assertEqual(run(parser().parse_args(['config', 'show']))['provider'], 'chatgpt')

    def test_embedding_response_order_and_validation(self):
        client = OpenAIClient('text-embedding-3-small', True)
        with patch.object(client, 'post', return_value={'data': [{'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}]}) as request:
            self.assertEqual(client.embed(['first', 'second']), [[1, 0], [0, 1]])
        self.assertEqual(request.call_args.args[0], '/embeddings')
        for data in ([{'index': 0, 'embedding': [float('nan')]}], [{'index': 1, 'embedding': [1]}], []):
            with patch.object(client, 'post', return_value={'data': data}):
                with self.assertRaises(RuntimeError):
                    client.embed(['text'])

    def test_responses_api_payload_and_output(self):
        client = OpenAIClient('configured-model', True)
        output = {'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Evidence [S1]'}]}]}
        with patch.object(client, 'post', return_value=output) as request:
            self.assertEqual(client.answer('question', '[S1] code'), 'Evidence [S1]')
        route, payload = request.call_args.args
        self.assertEqual(route, '/responses')
        self.assertEqual(payload['model'], 'configured-model')
        self.assertFalse(payload['store'])
        self.assertIn('[S1] code', payload['input'])

    def test_http_error_does_not_expose_key_or_response_body(self):
        client = OpenAIClient('model', True)
        failure = HTTPError('https://api.openai.com', 401, 'authentication failed', {}, io.BytesIO(b''))
        self.addCleanup(failure.close)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-private-key'}), patch('cke.integrations.openai.open_request', side_effect=failure):
            with self.assertRaises(RuntimeError) as caught:
                client.answer('q', 'context')
        self.assertIn('401', str(caught.exception))
        self.assertNotIn('synthetic-private-key', str(caught.exception))

    def test_real_transport_request_uses_bearer_auth(self):
        client = OpenAIClient('model', True)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch('cke.integrations.openai.open_request') as network:
            network.return_value.__enter__.return_value = io.BytesIO(b'{"output": []}')
            client.answer('q', 'context')
        request = network.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')

    def test_agent_handoff_does_not_invoke_generation(self):
        configure('copilot')
        retrieval = Mock()
        retrieval.search.return_value = [{'content': 'def example(): pass', 'source': 'repo', 'project': '.',
                                         'filepath': 'app.py', 'start_line': 1, 'end_line': 1, 'snapshot': 'snapshot'}]
        with patch('cke.answers.service.answer_client') as factory:
            result = AnswerService(retrieval).ask('demo', 'Explain')
        factory.assert_not_called()
        self.assertEqual(result['handoff'], 'copilot')
        self.assertIn('[S1]', result['context'])
        self.assertEqual(retrieval.search.call_args.args[2], 'keyword')

    def test_answer_model_follows_configured_provider(self):
        configure('openai', model='custom-model', embedding_provider='none', allow_cloud_code=True)
        retrieval, generator = Mock(), Mock()
        retrieval.search.return_value = [{'content': 'code', 'source': 'repo', 'project': '.', 'filepath': 'a.py', 'start_line': 1, 'end_line': 1, 'snapshot': 'v1'}]
        generator.answer.return_value = 'answer [S1]'
        result = AnswerService(retrieval, generator).ask('demo', 'q')
        self.assertTrue(result['grounded'])
        self.assertEqual(generator.answer.call_args.args[2], 'custom-model')

    def test_configured_openai_index_and_retrieval_share_provider(self):
        from cke.catalog import Catalog
        from cke.chunking.service import ChunkingService
        from cke.storage.sqlite_store import SQLiteStore
        from cke.indexer import index_kb
        from cke.retrieval.service import RetrievalService
        configure('openai', allow_cloud_code=True)
        repo = Path(self.temp.name) / 'repo'
        repo.mkdir()
        (repo / 'sample.py').write_text('def example(): return 1')
        catalog = Catalog()
        catalog.create_kb('demo')
        catalog.add_source('demo', str(repo), 'local', 'sample')
        store = SQLiteStore()
        self.addCleanup(store.close)
        ChunkingService(store).run('demo')
        row = store.chunks('demo')[0]
        vectors = Mock(collection='test-cloud')
        vectors.search.return_value = [{**row, 'score': .9}]
        with patch('cke.providers.QdrantClient', return_value=vectors), patch.object(OpenAIClient, 'post', return_value={'data': [{'index': 0, 'embedding': [1, 0]}]}) as api:
            result = index_kb('demo')
            hits = RetrievalService(store).search('demo', 'example', mode='semantic')
        self.assertEqual(result['model_revision'], 'openai:text-embedding-3-small')
        self.assertEqual(hits[0]['id'], row['id'])
        self.assertEqual(api.call_count, 2)
