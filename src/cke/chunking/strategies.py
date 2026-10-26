"""Small, swappable chunk strategies; supports every UTF-8 text file."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

LANGUAGES = {
    '.ts':'typescript','.tsx':'typescript','.js':'javascript','.jsx':'javascript',
    '.dart':'dart','.py':'python','.java':'java','.go':'go','.rs':'rust',
    '.kt':'kotlin','.swift':'swift','.cs':'csharp','.rb':'ruby','.php':'php',
    '.cpp':'cpp','.c':'c','.h':'c','.sql':'sql','.sh':'shell','.tf':'terraform',
    '.md':'markdown','.yaml':'yaml','.yml':'yaml','.json':'json','.xml':'xml',
    '.html':'html','.css':'css','.vue':'vue',
}
SYMBOL_RE = re.compile(r'^\s*(?:(?:export|default|async|public|private|protected|static)\s+)*(?:class|interface|enum|function|def|func|struct|trait|fn)\s+([\w$]+)')

@dataclass(frozen=True)
class Segment:
    start_line: int
    end_line: int
    symbol: str
    text: str

class UniversalChunkStrategy:
    """Text fallback, not a semantic AST parser. Explicit limits and overlap."""
    def __init__(self, max_lines: int = 100, overlap: int = 8):
        if max_lines < 1 or not 0 <= overlap < max_lines:
            raise ValueError('Chunk size must be positive and overlap smaller than chunk size')
        self.max_lines = max_lines
        self.overlap = overlap

    def split(self, content: str, filename: str) -> list[Segment]:
        lines = content.splitlines()
        if not lines:
            return []
        blocks: list[tuple[int, int, str]] = []
        start = 0
        symbol = Path(filename).name
        for index, line in enumerate(lines):
            match = SYMBOL_RE.match(line)
            if match and index > start + 4:
                blocks.append((start, index, symbol))
                start, symbol = index, match.group(1)
            elif match and index == start:
                symbol = match.group(1)
        blocks.append((start, len(lines), symbol))
        segments: list[Segment] = []
        for block_start, block_end, name in blocks:
            cursor = block_start
            while cursor < block_end:
                end = min(cursor + self.max_lines, block_end)
                text = '\n'.join(lines[cursor:end]).strip()
                if text:
                    segments.append(Segment(cursor + 1, end, name, text))
                if end == block_end:
                    break
                cursor = max(cursor + 1, end - self.overlap)
        return segments


class StructuralChunkStrategy(UniversalChunkStrategy):
    """Use syntax definition starts when supported, keeping all text and fallback limits."""
    def split(self, content: str, filename: str) -> list[Segment]:
        import ast
        definitions = []
        if filename.endswith('.py'):
            try:
                tree = ast.parse(content)
                definitions = [(node.lineno, node.name) for node in ast.walk(tree)
                               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            except SyntaxError:
                pass
        else:
            from .treesitter import syntax_nodes
            nodes = syntax_nodes(content, filename)
            for node in nodes or []:
                if node.type in ('class_declaration', 'function_declaration', 'method_definition', 'interface_declaration'):
                    name = node.child_by_field_name('name')
                    if name:
                        definitions.append((node.start_point.row + 1, name.text.decode()))
        if not definitions:
            return super().split(content, filename)
        lines = content.splitlines()
        boundaries = sorted(dict(definitions).items())
        if boundaries[0][0] != 1:
            boundaries.insert(0, (1, Path(filename).name))
        results = []
        for index, (start, symbol) in enumerate(boundaries):
            end = boundaries[index + 1][0] - 1 if index + 1 < len(boundaries) else len(lines)
            for segment in super().split('\n'.join(lines[start - 1:end]), filename):
                results.append(Segment(start + segment.start_line - 1, start + segment.end_line - 1, symbol, segment.text))
        return results
