"""Application paths and safety limits. No business logic belongs here."""
from __future__ import annotations
import os
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 100_000
EXCLUDED_DIRECTORIES = frozenset({
    '.git', 'node_modules', '.dart_tool', '.next', '.nx', 'dist', 'build',
    'coverage', '.venv', 'venv', 'target', '.gradle', '.idea', '.cache',
    '__pycache__', '.terraform', '.cke',
})
SECRET_SUFFIXES = frozenset({'.pem', '.p12', '.pfx', '.key'})


def home() -> Path:
    return Path(os.environ.get('CKE_HOME', '~/.cke-python')).expanduser().resolve()


def ensure_home() -> Path:
    root = home()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for name in ('snapshots', 'mirrors', 'exports'):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
