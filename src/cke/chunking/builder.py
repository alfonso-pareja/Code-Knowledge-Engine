"""Pure transformation of a snapshot file into a list of versioned code chunks."""
from __future__ import annotations
from pathlib import Path
from ..models import CodeChunk
from ..security import read_safe_file
from ..utils import digest
from .strategies import UniversalChunkStrategy, StructuralChunkStrategy, LANGUAGES

class ChunkBuilder:
    def __init__(self, strategy: UniversalChunkStrategy | None = None):
        self.strategy = strategy or StructuralChunkStrategy()

    @property
    def version(self) -> str:
        strategy = self.strategy
        return f'{type(strategy).__module__}.{type(strategy).__name__}:{strategy.max_lines}:{strategy.overlap}'

    def build_file(self, snapshot: dict, entry: dict) -> list[CodeChunk]:
        content = read_safe_file(Path(snapshot['root']), entry['path'], entry['sha256'])
        if content is None:
            return []
        return self.build_content(snapshot, entry, content)

    def build_content(self, snapshot: dict, entry: dict, content: str) -> list[CodeChunk]:
        language = LANGUAGES.get(Path(entry['path']).suffix.lower(), 'text')
        chunks = []
        for part in self.strategy.split(content, entry['path']):
            embedding_text = (f'Language: {language}\nProject: {snapshot["project"]}\n'
                              f'File: {entry["path"]}\nSymbol: {part.symbol}\n\n{part.text}')
            chunk_id = digest('|'.join((snapshot['kb'], snapshot['source'], snapshot['project'],
                                         entry['path'], str(part.start_line), digest(embedding_text))))
            chunks.append(CodeChunk(chunk_id, snapshot['kb'], snapshot['source'], snapshot['project'],
                                    snapshot['id'], entry['path'], language, part.symbol,
                                    part.start_line, part.end_line, part.text, embedding_text))
        return chunks
