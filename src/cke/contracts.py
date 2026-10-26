"""Small typed extension contracts for providers and published evidence."""
from typing import Protocol, TypedDict, NotRequired


class SearchResult(TypedDict):
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
    embedding_text: NotRequired[str]
    score: NotRequired[float]
    rank: NotRequired[float]
    rank_score: NotRequired[float]


class Embedder(Protocol):
    model: str
    def identity(self) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Generator(Protocol):
    def answer(self, question: str, context: str, model: str = 'llama3.2') -> str: ...


class VectorStore(Protocol):
    collection: str
    def ensure(self, dimensions: int) -> None: ...
    def delete_kb(self, kb: str) -> None: ...
    def upsert(self, rows: list[dict], vectors: list[list[float]]) -> None: ...
    def search(self, kb: str, vector: list[float], limit: int = 10,
               repos: list[str] | None = None, language: str | None = None) -> list[dict]: ...
