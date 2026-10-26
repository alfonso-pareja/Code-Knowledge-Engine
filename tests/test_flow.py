import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cke.catalog import Catalog
from cke.sources.manager import scan_kb
from cke.storage.sqlite_store import SQLiteStore
from cke.chunking.service import ChunkingService
from cke.retrieval.service import RetrievalService
from cke.chunking.strategies import UniversalChunkStrategy

class IntegrationTests(unittest.TestCase):
    def test_local_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, {'CKE_HOME': str(root / 'engine')}):
                repo = root / 'example'
                repo.mkdir()
                (repo / 'app.py').write_text('def greet(name):\n    return "hello " + name\n')
                (repo / 'api.ts').write_text('import { greet } from "./greet";\nexport function call() { return greet("x") }\n')
                (repo / '.env').write_text('PASSWORD=ignore')
                cat = Catalog()
                cat.create_kb('demo')
                cat.add_source('demo', str(repo), 'local', 'sample')
                self.assertEqual(scan_kb('demo')[0]['files'], 2)
                store = SQLiteStore()
                try:
                    result = ChunkingService(store).run('demo')
                    self.assertGreaterEqual(result['total_chunks'], 2)
                    self.assertTrue(store.graph('demo'))
                    self.assertTrue(RetrievalService(store).search('demo', 'greet'))
                    self.assertEqual(ChunkingService(store).run('demo')['unchanged_projects'], 1)
                    (repo / 'app.py').write_text('def updated(name):\n    return "new"\n')
                    self.assertEqual(ChunkingService(store).run('demo')['unchanged_projects'], 0)
                    self.assertFalse(any('greet(name)' in row['content'] for row in store.chunks('demo')))
                finally:
                    store.close()

    def test_chunk_fallback(self):
        chunks = UniversalChunkStrategy(max_lines=8, overlap=2).split('\n'.join(f'line {i}' for i in range(24)), 'unknown.ext')
        self.assertGreater(len(chunks), 1)

if __name__ == '__main__':
    unittest.main()
