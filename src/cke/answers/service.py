"""Bounded evidence and validated citation identifiers for local RAG."""
import re
from ..contracts import Generator
from ..providers import answer_client
from ..settings import load_settings, AGENTS, setup_instructions
from ..retrieval.service import RetrievalService


class AnswerService:
    def __init__(self, retrieval: RetrievalService, generator: Generator | None = None):
        self.retrieval = retrieval
        self.generator = generator

    def ask(self, kb: str, query: str, mode: str | None = None, model: str | None = None,
            repos=None, limit: int = 8, language=None) -> dict:
        settings = load_settings()
        results = self.retrieval.search(kb, query, mode or settings.search_mode, repos, limit, language)
        if not results:
            return {'answer': 'No hay evidencia suficiente en el índice.', 'evidence': [], 'citations': [], 'grounded': False}
        evidence, blocks, remaining = [], [], 24000
        for row in results:
            content = row['content']
            citation = f'S{len(evidence) + 1}'
            block = f'[{citation}] KB={kb} source={row["source"]} project={row["project"]} file={row["filepath"]}:{row["start_line"]}-{row["end_line"]} snapshot={row["snapshot"]}\n{content}'
            if len(block) > remaining:
                continue
            evidence.append({**row, 'citation': citation})
            blocks.append(block)
            remaining -= len(block)
        if not evidence:
            return {'answer': 'La evidencia excede el límite de contexto.', 'evidence': [], 'citations': [], 'grounded': False}
        context = '\n\n'.join(blocks)
        if self.generator is None and settings.provider in AGENTS:
            return {'answer': 'Contexto preparado para ' + settings.provider + '; envíalo desde tu cliente autorizado.',
                    'context': context, 'question': query, 'evidence': evidence, 'citations': [], 'grounded': False,
                    'handoff': settings.provider, 'instructions': setup_instructions(settings)}
        generator = self.generator or answer_client()
        answer = generator.answer(query, context, model or settings.model)
        references = set(re.findall(r'\[(S\d+)\]', answer))
        known = {row['citation'] for row in evidence}
        grounded = bool(references) and references <= known
        if not grounded:
            answer = 'El modelo no devolvió citas válidas. Revisa los fragmentos recuperados.'
        return {'answer': answer, 'evidence': evidence, 'citations': sorted(references & known), 'grounded': grounded}
