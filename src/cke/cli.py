"""CLI adapter: argument parsing, service dispatch, JSON output."""
from __future__ import annotations
import argparse
import json
from .catalog import Catalog
from .config import ensure_home
from .sources.manager import scan_kb
from .storage.sqlite_store import SQLiteStore
from .chunking.service import ChunkingService
from .retrieval.service import RetrievalService


def search_options(command: argparse.ArgumentParser, default_mode: str = 'keyword') -> None:
    command.add_argument('query')
    command.add_argument('--kb', required=True)
    command.add_argument('--mode', choices=['keyword', 'semantic', 'hybrid'], default=default_mode)
    command.add_argument('--repo', action='append')
    command.add_argument('--language')
    command.add_argument('--limit', type=int, default=8)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog='cke', description='Local-first code knowledge engine')
    commands = result.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('doctor')
    configuration = commands.add_parser('config')
    configuration.add_argument('action', choices=['show', 'set', 'check'])
    configuration.add_argument('--provider', choices=['ollama', 'openai', 'copilot', 'chatgpt', 'codex'])
    configuration.add_argument('--model')
    configuration.add_argument('--embedding-provider', choices=['none', 'ollama', 'openai'])
    configuration.add_argument('--embedding-model')
    configuration.add_argument('--allow-cloud-code', action='store_true')
    kb = commands.add_parser('kb')
    kb.add_argument('action', choices=['create', 'list'])
    kb.add_argument('name', nargs='?')
    source = commands.add_parser('source')
    source.add_argument('action', choices=['add', 'list', 'remove'])
    source.add_argument('location', nargs='?')
    source.add_argument('--kb', required=True)
    source.add_argument('--type', default='auto', choices=['auto', 'local', 'workspace', 'git'])
    source.add_argument('--id')
    source.add_argument('--ref', default='HEAD')
    for name in ('scan', 'chunks', 'sync', 'index', 'graph'):
        command = commands.add_parser(name)
        command.add_argument('--kb', required=True)
        if name in ('scan', 'chunks', 'sync'):
            command.add_argument('--sync', action='store_true')
        if name == 'graph':
            command.add_argument('--network', action='store_true')
    search_options(commands.add_parser('search'))
    ask = commands.add_parser('ask')
    search_options(ask, default_mode=None)
    ask.add_argument('--model')
    mcp = commands.add_parser('mcp')
    mcp.add_argument('action', choices=['serve'])
    viewer = commands.add_parser('viewer')
    viewer.add_argument('action', choices=['serve'])
    viewer.add_argument('--port', type=int, default=8765)
    evaluate = commands.add_parser('evaluate')
    evaluate.add_argument('--kb', required=True)
    evaluate.add_argument('--dataset', required=True)
    evaluate.add_argument('--mode', choices=['keyword', 'semantic', 'hybrid'], default='keyword')
    evaluate.add_argument('--limit', type=int, default=8)
    return result


def run(args: argparse.Namespace):
    if args.command == 'init':
        return {'home': str(ensure_home())}
    if args.command == 'config':
        from .settings import configure, settings_status
        if args.action == 'check':
            from .diagnostics import doctor
            return doctor()
        if args.action == 'set':
            if not args.provider:
                raise ValueError('Provide --provider ollama/openai/copilot/chatgpt/codex')
            configure(args.provider, args.model, args.embedding_provider, args.embedding_model, args.allow_cloud_code)
        return settings_status()
    if args.command == 'doctor':
        from .diagnostics import doctor
        return doctor()
    if args.command == 'kb':
        catalog = Catalog()
        if args.action == 'create':
            if not args.name:
                raise ValueError('Provide a KB name')
            catalog.create_kb(args.name)
        return {'knowledge_bases': catalog.data['knowledge_bases']}
    if args.command == 'source':
        catalog = Catalog()
        if args.action == 'add':
            if not args.location:
                raise ValueError('Provide a source path or Git URL')
            return vars(catalog.add_source(args.kb, args.location, args.type, args.id, args.ref))
        if args.action == 'remove':
            if not args.id:
                raise ValueError('Provide --id to remove a source registration')
            catalog.remove_source(args.kb, args.id)
            return {'removed': args.id, 'next': 'Run cke chunks to reconcile indexed evidence'}
        return [vars(source) for source in catalog.sources(args.kb)]
    if args.command == 'scan':
        from .locking import exclusive
        with exclusive('kb:' + args.kb):
            return scan_kb(args.kb, args.sync)
    if args.command == 'index':
        from .indexer import index_kb
        from .progress import IndexProgress
        return index_kb(args.kb, progress=IndexProgress())
    if args.command == 'mcp':
        from .integrations.mcp import serve
        return serve()
    if args.command == 'viewer':
        from .viewer.server import serve
        return serve(args.port)
    store = SQLiteStore()
    try:
        if args.command in ('chunks', 'sync'):
            return ChunkingService(store).run(args.kb, args.sync)
        Catalog().sources(args.kb)
        if args.command == 'graph':
            if args.network:
                from .knowledge import KnowledgeService
                return KnowledgeService(store).graph(args.kb)
            return store.graph(args.kb)
        retrieval = RetrievalService(store)
        if args.command == 'evaluate':
            from .evaluation import evaluate_dataset
            return evaluate_dataset(retrieval, args.kb, args.dataset, args.mode, args.limit)
        if args.command == 'ask':
            from .answers.service import AnswerService
            return AnswerService(retrieval).ask(args.kb, args.query, args.mode, args.model,
                                                args.repo, args.limit, args.language)
        return retrieval.search(args.kb, args.query, args.mode, args.repo, args.limit, args.language)
    finally:
        store.close()


def main() -> None:
    arguments = parser().parse_args()
    try:
        result = run(arguments)
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError) as error:
        parser().exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
