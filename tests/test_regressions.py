"""Synthetic regressions: no corporate sources or network services required."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cke.catalog import Catalog
from cke.chunking.service import ChunkingService
from cke.chunking.builder import ChunkBuilder
from cke.chunking.strategies import StructuralChunkStrategy
from cke.storage.sqlite_store import SQLiteStore
from cke.retrieval.service import RetrievalService
from cke.answers.service import AnswerService
from cke.integrations.transport import validate_endpoint
from cke.integrations.mcp import handle
from cke.indexer import index_kb
from cke.cli import parser, run
from cke.knowledge import KnowledgeService


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'CKE_HOME': str(self.root / 'engine'), 'CKE_ALLOWED_ENDPOINTS': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.file = self.repo / 'app.py'
        self.file.write_text('def hello():\n    return "hello"\n')
        cat = Catalog()
        cat.create_kb('demo')
        cat.create_kb('other')
        cat.add_source('demo', str(self.repo), 'local', 'sample')
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        ChunkingService(self.store).run('demo')

    def providers(self):
        embedder = Mock(model='test')
        embedder.identity.return_value = 'test'
        embedder.embed.side_effect = lambda texts: [[1.0, 0.0] for _ in texts]
        vectors = Mock(collection='test')
        vectors.search.return_value = []
        return embedder, vectors

    def test_cli_limit_is_forwarded(self):
        with patch('cke.cli.RetrievalService.search', return_value=[]) as search:
            run(parser().parse_args(['search', 'hello', '--kb', 'demo', '--limit', '1']))
            self.assertEqual(search.call_args.args[4], 1)

    def test_atomic_failure_preserves_all_previous_chunks(self):
        previous = self.store.chunks('demo')
        self.file.write_text('def changed():\n    return 2\n')
        second = self.repo / 'second.py'
        second.write_text('def second():\n    return 3\n')
        original = ChunkBuilder.build_content
        def racing(builder, snapshot, entry, content):
            result = original(builder, snapshot, entry, content)
            if entry['path'] == 'second.py':
                self.file.write_text('concurrent update')
            return result
        with patch.object(ChunkBuilder, 'build_content', racing):
            with self.assertRaises(RuntimeError):
                ChunkingService(self.store).run('demo')
        self.assertEqual(self.store.chunks('demo'), previous)

    def test_deleted_file_removed_from_fts(self):
        self.file.unlink()
        ChunkingService(self.store).run('demo')
        self.assertEqual(self.store.keyword_search('demo', 'hello'), [])

    def test_removed_registration_reconciles(self):
        Catalog().remove_source('demo', 'sample')
        ChunkingService(self.store).run('demo')
        self.assertEqual(self.store.chunks('demo'), [])

    def test_removed_workspace_project_reconciles(self):
        workspace = self.root / 'workspace'
        repo = workspace / 'child'
        repo.mkdir(parents=True)
        (repo / '.git').mkdir()
        (repo / 'old.py').write_text('def old():\n    pass\n')
        Catalog().add_source('demo', str(workspace), 'workspace', 'workspace')
        ChunkingService(self.store).run('demo')
        shutil.rmtree(repo)
        ChunkingService(self.store).run('demo')
        self.assertFalse(any(row['source'] == 'workspace' for row in self.store.chunks('demo')))

    def test_missing_root_does_not_delete_publication(self):
        shutil.rmtree(self.repo)
        with self.assertRaises(ValueError):
            ChunkingService(self.store).run('demo')
        self.assertTrue(self.store.chunks('demo'))

    def test_incremental_only_rebuilds_changed_file(self):
        extra = self.repo / 'extra.py'
        extra.write_text('def extra():\n    pass\n')
        ChunkingService(self.store).run('demo')
        self.file.write_text('def changed():\n    pass\n')
        with patch.object(ChunkBuilder, 'build_content', wraps=ChunkBuilder().build_content) as builder:
            result = ChunkingService(self.store).run('demo')
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(result['reused_files'], 1)

    def test_changed_pipeline_version_rebuilds(self):
        with patch('cke.chunking.service.PIPELINE_VERSION', 'new-version'), patch.object(ChunkBuilder, 'build_content', wraps=ChunkBuilder().build_content) as builder:
            ChunkingService(self.store).run('demo')
            self.assertEqual(builder.call_count, 1)

    def test_isolation_and_language_filter(self):
        retrieval = RetrievalService(self.store)
        self.assertEqual(retrieval.search('other', 'hello'), [])
        self.assertEqual(retrieval.search('demo', 'hello', language='typescript'), [])
        self.assertTrue(retrieval.search('demo', 'hello', language='python'))

    def test_invalid_limits(self):
        for limit in (0, -1, 101, True, '2'):
            with self.assertRaises(ValueError):
                RetrievalService(self.store).search('demo', 'hello', limit=limit)

    def test_vectors_require_current_model_and_generation(self):
        embedder, vectors = self.providers()
        retrieval = RetrievalService(self.store, embedder, vectors)
        with self.assertRaises(ValueError):
            retrieval.search('demo', 'hello', 'semantic')
        self.store.mark_vectors('demo', 'test', 'different-model', self.store.signature('demo'))
        with self.assertRaises(ValueError):
            retrieval.search('demo', 'hello', 'semantic')

    def test_semantic_payload_is_hydrated_and_validated(self):
        embedder, vectors = self.providers()
        self.store.mark_vectors('demo', 'test', 'test', self.store.signature('demo'))
        row = self.store.chunks('demo')[0]
        vectors.search.return_value = [dict(row, content='tampered', score=.9), {'id': 'obsolete', 'score': 1.0}, dict(row, snapshot='stale', score=.8)]
        results = RetrievalService(self.store, embedder, vectors).search('demo', 'hello', 'semantic', repos=['sample'], language='python')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['content'], row['content'])
        self.assertEqual(vectors.search.call_args.args[3:], (['sample'], 'python'))

    def test_index_replaces_only_requested_kb(self):
        embedder, vectors = self.providers()
        result = index_kb('demo', embedder=embedder, vectors=vectors)
        vectors.delete_kb.assert_called_once_with('demo')
        self.assertTrue(self.store.vectors_current('demo', 'test', 'test'))
        self.assertEqual(result['indexed'], len(self.store.chunks('demo')))

    def test_failed_index_is_not_queryable(self):
        embedder, vectors = self.providers()
        vectors.upsert.side_effect = RuntimeError('failure')
        with self.assertRaises(RuntimeError):
            index_kb('demo', embedder=embedder, vectors=vectors)
        self.assertFalse(self.store.vectors_current('demo', 'test', 'test'))

    def test_index_change_invalidates_vectors(self):
        embedder, vectors = self.providers()
        index_kb('demo', embedder=embedder, vectors=vectors)
        self.file.write_text('def replacement():\n    pass\n')
        ChunkingService(self.store).run('demo')
        self.assertFalse(self.store.vectors_current('demo', 'test', 'test'))

    def test_external_endpoints_require_explicit_authorization(self):
        for endpoint in ('https://example.com', 'http://127.0.0.1.evil.test', 'file:///tmp/test', 'http://token@localhost'):
            with self.assertRaises(ValueError):
                validate_endpoint(endpoint)
        self.assertEqual(validate_endpoint('http://127.0.0.1:11434'), 'http://127.0.0.1:11434')
        with patch.dict(os.environ, {'CKE_ALLOWED_ENDPOINTS': 'https://example.com'}):
            self.assertEqual(validate_endpoint('https://example.com'), 'https://example.com')

    def test_symlinks_secrets_and_exclusions_are_not_indexed(self):
        secret = self.root / 'secret.txt'
        secret.write_text('outside_private')
        (self.repo / 'link.py').symlink_to(secret)
        (self.repo / 'secret.py').write_text('api_key = "abcdefghijklmnop"')
        (self.repo / 'ignored.py').write_text('ignored_content')
        (self.repo / '.ckeignore').write_text('ignored.py\n')
        ChunkingService(self.store).run('demo')
        content = '\n'.join(row['content'] for row in self.store.chunks('demo'))
        self.assertNotIn('outside_private', content)
        self.assertNotIn('abcdefghijklmnop', content)
        self.assertNotIn('ignored_content', content)

    def test_source_chunk_cannot_cross_kb(self):
        with self.assertRaises(ValueError):
            self.store.get_chunk('other', self.store.chunks('demo')[0]['id'])

    def test_rag_rejects_invented_or_missing_citations(self):
        generator = Mock()
        service = AnswerService(RetrievalService(self.store), generator)
        for answer in ('unreferenced claim', 'claim [S999]'):
            generator.answer.return_value = answer
            result = service.ask('demo', 'hello', mode='keyword')
            self.assertFalse(result['grounded'])
        generator.answer.return_value = 'Function hello [S1]'
        self.assertTrue(service.ask('demo', 'hello', mode='keyword')['grounded'])

    def test_rag_abstains_without_evidence(self):
        generator = Mock()
        result = AnswerService(RetrievalService(self.store), generator).ask('other', 'hello', mode='keyword')
        self.assertFalse(result['grounded'])
        generator.answer.assert_not_called()

    def test_mcp_returns_error_for_bad_arguments(self):
        result = handle({'id': 1, 'method': 'tools/call', 'params': {'name': 'search_code', 'arguments': {'kb': 'demo'}}})
        self.assertTrue(result['result']['isError'])
        self.assertEqual(result['id'], 1)

    def test_python_ast_relations_and_structural_chunks(self):
        self.file.write_text('import math\nclass Example:\n    def method(self):\n        return math.sqrt(4)\n')
        ChunkingService(self.store).run('demo')
        kinds = {row['kind'] for row in self.store.graph('demo')}
        self.assertTrue({'symbol_ast', 'import_ast', 'call_ast_unresolved'} <= kinds)
        self.assertTrue(any(row['symbol'] == 'method' for row in self.store.chunks('demo')))

    def test_graph_static_resolution_and_reverse_impact(self):
        (self.repo / 'main.ts').write_text('import {hello} from "./helper";\nhello();\n')
        (self.repo / 'helper.ts').write_text('export function hello() { return 1; }\n')
        ChunkingService(self.store).run('demo')
        service = KnowledgeService(self.store)
        graph = service.graph('demo')
        edge = next(edge for edge in graph['edges'] if edge['evidence'] == './helper')
        self.assertEqual(edge['resolution'], 'candidate_static')
        impact = service.traverse('demo', edge['target'], reverse=True)
        self.assertTrue(any(node['filepath'] == 'main.ts' for node in impact['nodes']))

    def test_catalog_stale_instances_do_not_lose_updates(self):
        first, second = Catalog(), Catalog()
        first.create_kb('first')
        second.create_kb('second')
        self.assertIn('first', Catalog().data['knowledge_bases'])
        self.assertIn('second', Catalog().data['knowledge_bases'])

    def test_sqlite_permissions(self):
        self.assertEqual((self.root / 'engine' / 'knowledge.sqlite').stat().st_mode & 0o777, 0o600)

    def test_mcp_authorization_and_source_read(self):
        row = self.store.chunks('demo')[0]
        message = {'id': 2, 'method': 'tools/call', 'params': {'name': 'get_source', 'arguments': {'kb': 'demo', 'chunk_id': row['id']}}}
        with patch.dict(os.environ, {'CKE_MCP_ALLOWED_KBS': ''}):
            self.assertTrue(handle(message)['result']['isError'])
        with patch.dict(os.environ, {'CKE_MCP_ALLOWED_KBS': 'demo'}):
            result = handle(message)['result']
            self.assertNotIn('isError', result)
            self.assertEqual(json.loads(result['content'][0]['text'])['id'], row['id'])

    def test_retrieval_metrics(self):
        from cke.evaluation import evaluate_dataset
        dataset = self.root / 'evaluation.json'
        dataset.write_text(json.dumps([{'query': 'hello', 'expected_files': ['app.py']}]))
        metrics = evaluate_dataset(RetrievalService(self.store), 'demo', str(dataset))
        self.assertEqual(metrics['recall_at_k'], 1.0)
        self.assertEqual(metrics['mrr'], 1.0)

    def test_gitignore_and_local_changes(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / '.gitignore').write_text('private.py\n')
        (self.repo / 'private.py').write_text('ignored private contents')
        self.file.write_text('def local_change():\n    pass\n')
        ChunkingService(self.store).run('demo')
        self.assertTrue(self.store.keyword_search('demo', 'local_change'))
        self.assertFalse(any(row['filepath'] == 'private.py' for row in self.store.chunks('demo')))

    def test_descriptor_reader_rejects_intermediate_symlink(self):
        from cke.security import read_safe_file
        (self.repo / 'nested').symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(read_safe_file(self.repo, 'nested/repo/app.py'))
        self.assertIsNone(read_safe_file(self.repo, '../repo/app.py'))

    def test_qdrant_filters_are_applied_before_top_k(self):
        from cke.integrations.qdrant import QdrantClient
        client = QdrantClient()
        with patch.object(client, 'call', return_value={'result': {'points': []}}) as call:
            client.search('demo', [1.0], 5, ['sample'], 'python')
        payload = call.call_args.args[2]
        self.assertEqual(payload['limit'], 5)
        self.assertEqual(payload['filter']['must'][0]['match']['value'], 'demo')
        self.assertEqual(payload['filter']['must'][1]['should'][0]['match']['any'], ['sample'])
        self.assertEqual(payload['filter']['must'][2]['match']['value'], 'python')

    def test_many_projects_incremental(self):
        workspace = self.root / 'many'
        for index in range(20):
            repo = workspace / f'project-{index}'
            repo.mkdir(parents=True)
            (repo / '.git').mkdir()
            (repo / 'sample.py').write_text(f'def function_{index}():\n    return {index}\n')
        Catalog().add_source('other', str(workspace), 'workspace', 'many')
        initial = ChunkingService(self.store).run('other')
        repeated = ChunkingService(self.store).run('other')
        self.assertEqual(initial['projects'], 20)
        self.assertEqual(repeated['unchanged_projects'], 20)
        self.assertEqual(repeated['chunks_created'], 0)

    def test_optional_typescript_ast(self):
        from cke.chunking.treesitter import parser_for
        if parser_for('app.ts') is None:
            self.skipTest('Optional Tree-sitter grammars are not installed')
        (self.repo / 'service.ts').write_text('export class Service { execute() { return helper(); } }\n')
        ChunkingService(self.store).run('demo')
        relations = [row for row in self.store.graph('demo') if row['filepath'] == 'service.ts']
        self.assertTrue(any(row['kind'] == 'symbol_ast' and row['target'] == 'execute' for row in relations))
        self.assertTrue(any(row['kind'] == 'call_ast_unresolved' and row['target'] == 'helper' for row in relations))

    def test_current_vector_generation_reuses_embeddings(self):
        embedder, vectors = self.providers()
        index_kb('demo', embedder=embedder, vectors=vectors)
        embedder.embed.reset_mock()
        vectors.upsert.reset_mock()
        result = index_kb('demo', embedder=embedder, vectors=vectors)
        self.assertGreater(result['reused'], 0)
        embedder.embed.assert_not_called()
        vectors.upsert.assert_not_called()

    def test_model_revision_change_invalidates_generation(self):
        embedder, vectors = self.providers()
        index_kb('demo', embedder=embedder, vectors=vectors)
        embedder.identity.return_value = 'test@updated-digest'
        with self.assertRaises(ValueError):
            RetrievalService(self.store, embedder, vectors).search('demo', 'hello', 'semantic')

    def test_empty_kb_retires_vectors(self):
        self.file.unlink()
        ChunkingService(self.store).run('demo')
        embedder, vectors = self.providers()
        result = index_kb('demo', embedder=embedder, vectors=vectors)
        vectors.delete_kb.assert_called_once_with('demo')
        self.assertEqual(result['indexed'], 0)
        embedder.embed.assert_not_called()

    def test_ollama_rejects_malformed_embeddings(self):
        from cke.integrations.ollama import OllamaClient
        client = OllamaClient()
        for embeddings in ([[float('nan')]], [['invalid']], [[]], [[1], [1, 2]]):
            with patch.object(client, 'post', return_value={'embeddings': embeddings}):
                with self.assertRaises(RuntimeError):
                    client.embed(['a', 'b'] if len(embeddings) == 2 else ['a'])

    def test_transport_refuses_redirects(self):
        from cke.integrations.transport import NoRedirect
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')

    def test_connection_error_identifies_service_and_recovery(self):
        from urllib.error import URLError
        from urllib.request import Request
        from cke.integrations.transport import open_request
        for route, service in (('http://127.0.0.1:11434/api/tags', 'Ollama'), ('http://127.0.0.1:6333/collections', 'Qdrant')):
            with patch('cke.integrations.transport.build_opener') as opener:
                opener.return_value.open.side_effect = URLError(ConnectionRefusedError(61, 'Connection refused'))
                with self.assertRaisesRegex(RuntimeError, service):
                    open_request(Request(route))

    def test_index_progress_reports_only_persisted_batches_as_complete(self):
        embedder, vectors = self.providers()
        events = []
        vectors.upsert.side_effect = lambda *args: events.append(('persisted', 0, 0))
        index_kb('demo', embedder=embedder, vectors=vectors, progress=lambda *event: events.append(event))
        completed = next(index for index, event in enumerate(events) if event[0] == 'Lote completado')
        persisted = next(index for index, event in enumerate(events) if event[0] == 'persisted')
        self.assertGreater(completed, persisted)
        self.assertEqual(events[completed][1], events[completed][2])

    def test_progress_goes_to_selected_stream(self):
        import io
        from cke.progress import IndexProgress
        stream = io.StringIO()
        IndexProgress(stream)('Generando embeddings', 8, 16)
        self.assertIn('8/16 chunks (50.0%)', stream.getvalue())
