"""CLI progress on stderr, keeping stdout available for the final JSON result."""
import sys
from time import monotonic
from typing import TextIO


class IndexProgress:
    def __init__(self, stream: TextIO | None = None):
        self.stream = stream or sys.stderr
        self.started = monotonic()

    def __call__(self, stage: str, completed: int, total: int) -> None:
        elapsed = int(monotonic() - self.started)
        count = f'{completed}/{total} chunks ({completed / total:.1%})' if total else 'preparando'
        print(f'[CKE] {stage} · {count} · {elapsed}s', file=self.stream, flush=True)
