"""Optional syntax adapter. Grammars are installed locally, never downloaded at runtime."""
from importlib import import_module, metadata
from pathlib import Path

GRAMMARS = {
    '.ts': ('tree_sitter_typescript', 'language_typescript'),
    '.tsx': ('tree_sitter_typescript', 'language_tsx'),
    '.js': ('tree_sitter_javascript', 'language'),
    '.jsx': ('tree_sitter_javascript', 'language'),
}


def parser_for(filename: str):
    grammar = GRAMMARS.get(Path(filename).suffix)
    if grammar is None:
        return None
    try:
        from tree_sitter import Language, Parser
        module = import_module(grammar[0])
    except ImportError:
        return None
    return Parser(Language(getattr(module, grammar[1])()))


def fingerprint() -> str:
    versions = []
    for package in ('tree-sitter', 'tree-sitter-typescript', 'tree-sitter-javascript'):
        try:
            versions.append(package + '=' + metadata.version(package))
        except metadata.PackageNotFoundError:
            versions.append(package + '=absent')
    return '|'.join(versions)


def syntax_nodes(content: str, filename: str):
    parser = parser_for(filename)
    if parser is None:
        return None
    tree = parser.parse(content.encode('utf-8'))
    if tree.root_node.has_error:
        return None
    stack, nodes = [tree.root_node], []
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(node.named_children))
    return nodes


def relations(snapshot: dict, filepath: str, content: str):
    nodes = syntax_nodes(content, filepath)
    if nodes is None:
        return None
    prefix = (snapshot['kb'], snapshot['source'], snapshot['project'], filepath)
    rows = []
    for node in nodes:
        if node.type in ('class_declaration', 'function_declaration', 'method_definition', 'interface_declaration'):
            name = node.child_by_field_name('name')
            if name:
                rows.append((*prefix, name.text.decode(), 'symbol_ast', node.start_point.row + 1))
        elif node.type in ('import_statement', 'export_statement'):
            target = node.child_by_field_name('source')
            if target:
                rows.append((*prefix, target.text.decode()[1:-1], 'import_ast', node.start_point.row + 1))
        elif node.type == 'call_expression':
            target = node.child_by_field_name('function')
            if target:
                rows.append((*prefix, target.text.decode(), 'call_ast_unresolved', node.start_point.row + 1))
    return rows
