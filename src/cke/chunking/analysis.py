"""Language adapters emit syntax evidence, never claims of runtime execution."""
import ast
import re

IMPORT_RE = re.compile(r"^\s*(?:import\s+.*?from\s*|export\s+.*?from\s*|import\s*)['\"]([^'\"]+)['\"]")


def analyze(snapshot: dict, filepath: str, content: str) -> list[tuple]:
    prefix = (snapshot['kb'], snapshot['source'], snapshot['project'], filepath)
    result = []
    if filepath.endswith('.py'):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                result.append((*prefix, node.name, 'symbol_ast', node.lineno))
            elif isinstance(node, ast.Import):
                result.extend((*prefix, alias.name, 'import_ast', node.lineno) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                result.append((*prefix, '.' * node.level + (node.module or ''), 'import_ast', node.lineno))
            elif isinstance(node, ast.Call):
                result.append((*prefix, ast.unparse(node.func), 'call_ast_unresolved', node.lineno))
        return result
    from .treesitter import relations
    parsed = relations(snapshot, filepath, content)
    if parsed is not None:
        return parsed
    for line_number, line in enumerate(content.splitlines(), 1):
        match = IMPORT_RE.search(line)
        if match:
            result.append((*prefix, match.group(1), 'import_heuristic', line_number))
    return result
