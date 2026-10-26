"""Reusable primitives. External processes are invoked without shell expansion."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def slug(value: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]+', '-', value).strip('-').lower()


def git(directory: Path, *args: str, optional: bool = False) -> str | None:
    result = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        if optional:
            return None
        raise RuntimeError(result.stderr.strip() or 'Git command failed')
    return result.stdout.strip()


def write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.cke-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(content, file, ensure_ascii=False, indent=2)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path: Path, default: object = None):
    return json.loads(path.read_text()) if path.exists() else default
