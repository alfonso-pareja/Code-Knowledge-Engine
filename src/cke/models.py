"""Contracts shared between adapters; add features here before changing infrastructure."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

SourceType = Literal['local', 'workspace', 'git']

@dataclass(frozen=True)
class KnowledgeSource:
    id: str
    kb: str
    type: SourceType
    location: str
    ref: str = 'HEAD'

@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int

@dataclass(frozen=True)
class CodeChunk:
    id: str
    kb: str
    source: str
    project: str
    snapshot: str
    filepath: str
    language: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    embedding_text: str

    def to_dict(self) -> dict:
        return asdict(self)
