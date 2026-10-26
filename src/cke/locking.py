"""Process locks for catalog mutations and KB publication (POSIX local runtime)."""
from contextlib import contextmanager
import fcntl
from .config import ensure_home
from .utils import digest


@contextmanager
def exclusive(name: str):
    path = ensure_home() / ('lock-' + digest(name))
    with path.open('a') as stream:
        path.chmod(0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
