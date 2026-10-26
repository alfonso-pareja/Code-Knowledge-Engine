"""Conservative secret exclusions and descriptor-based, no-symlink source reads."""
from __future__ import annotations
import os
import re
from pathlib import Path
from .config import EXCLUDED_DIRECTORIES, SECRET_SUFFIXES, MAX_FILE_BYTES
from .utils import digest

SECRET_PATTERN = re.compile(
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
    r'\bAKIA[A-Z0-9]{16}\b|'
    r'''(?:password|client_secret|api[_-]?key)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]''', re.IGNORECASE)


def allowed_path(path: Path) -> bool:
    return not (
        path.is_absolute() or '..' in path.parts
        or any(part in EXCLUDED_DIRECTORIES or part.startswith('.env') for part in path.parts)
        or path.suffix.lower() in SECRET_SUFFIXES
        or path.name.startswith(('id_rsa', 'id_ed25519'))
    )


def read_safe_file(base: Path, relative: str, expected_hash: str | None = None) -> str | None:
    path = Path(relative)
    if not allowed_path(path) or not path.parts:
        return None
    descriptors = []
    try:
        # Open each component relative to the preceding descriptor: symlink swaps
        # cannot redirect a later read outside the registered canonical root.
        directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for part in path.parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            descriptors.append(directory)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        descriptors.append(descriptor)
        import stat
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
            raise ValueError('Source is no longer an indexable regular file')
        with os.fdopen(os.dup(descriptor), 'rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES or (expected_hash and digest(data) != expected_hash):
            raise ValueError('Source changed')
        if b'\0' in data[:4096]:
            return None
        content = data.decode('utf-8')
        return None if SECRET_PATTERN.search(content) else content
    except (OSError, UnicodeError, ValueError) as exc:
        if expected_hash:
            raise RuntimeError(f'Source changed or unavailable during indexing: {relative}; retry indexing') from exc
        return None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
