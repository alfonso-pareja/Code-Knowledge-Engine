"""Source adapters: local folders, workspace discovery, managed remote Git clones."""
from __future__ import annotations
import subprocess
from pathlib import Path
from ..catalog import Catalog
from ..config import ensure_home, EXCLUDED_DIRECTORIES, MAX_FILE_BYTES, MAX_FILES
from ..models import FileEntry, KnowledgeSource
from ..security import allowed_path
from ..utils import git, digest, slug, write_json, read_json


def resolve_source(source: KnowledgeSource, sync_remote: bool) -> Path:
    if source.type != 'git':
        root = Path(source.location)
        if not root.is_dir():
            raise ValueError(f'Source directory unavailable: {source.id}')
        return root
    mirror = ensure_home() / 'mirrors' / f'{slug(source.kb)}__{slug(source.id)}'
    if mirror.is_symlink():
        raise ValueError('Managed clone must not be a symbolic link')
    if not mirror.exists():
        if not sync_remote:
            raise RuntimeError(f'Remote source {source.id} requires scan --sync')
        subprocess.run(['git', 'clone', '--no-checkout', '--', source.location, str(mirror)], check=True, timeout=180)
    if sync_remote:
        subprocess.run(['git', '-C', str(mirror), 'fetch', '--all', '--prune'], check=True, timeout=180)
        remote_ref = 'origin/HEAD' if source.ref == 'HEAD' else f'origin/{source.ref}'
        resolved_ref = git(mirror, 'rev-parse', '--verify', remote_ref, optional=True) or git(mirror, 'rev-parse', '--verify', source.ref)
        subprocess.run(['git', '-C', str(mirror), 'checkout', '--detach', '--force', resolved_ref], check=True, timeout=90)
    return mirror


def project_roots(source: KnowledgeSource, root: Path) -> list[Path]:
    if source.type != 'workspace':
        return [root]
    import os
    repositories: list[Path] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        current = Path(directory)
        if '.git' in dirs or '.git' in files:
            repositories.append(current)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRECTORIES and not (current / d).is_symlink())
    return sorted(set(repositories)) or [root]


def list_files(root: Path) -> list[FileEntry]:
    import fnmatch
    import os
    patterns = [p.strip() for p in os.environ.get('CKE_EXCLUDE', '').split(',') if p.strip()]
    exclusion_file = root / '.ckeignore'
    if exclusion_file.is_file() and not exclusion_file.is_symlink():
        patterns += [p.strip() for p in exclusion_file.read_text().splitlines() if p.strip() and not p.startswith('#')]
    files: list[FileEntry] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRECTORIES and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            filename = Path(directory) / name
            relative = filename.relative_to(root)
            if any(fnmatch.fnmatch(relative.as_posix(), pattern) for pattern in patterns):
                continue
            if filename.is_symlink() or not allowed_path(relative):
                continue
            try:
                if not filename.is_file() or not 0 < filename.stat().st_size <= MAX_FILE_BYTES:
                    continue
                data = filename.read_bytes()
                if b'\0' in data[:4096]:
                    continue
                data.decode('utf-8')
            except (OSError, UnicodeError):
                continue
            files.append(FileEntry(relative.as_posix(), digest(data), len(data)))
            if len(files) > MAX_FILES:
                raise RuntimeError('Maximum number of files exceeded')
    # Git's own matcher correctly handles nested ignore files and negated patterns.
    if git(root, 'rev-parse', '--show-toplevel', optional=True):
        result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--no-index', '-z', '--stdin'],
                                input='\0'.join(entry.path for entry in files) + '\0', capture_output=True,
                                text=True, timeout=60)
        if result.returncode not in (0, 1):
            raise RuntimeError('Could not evaluate Git exclusions')
        ignored = set(result.stdout.split('\0'))
        files = [entry for entry in files if entry.path not in ignored]
    return files


def scan_kb(kb: str, sync_remote: bool = False) -> list[dict]:
    result = []
    for source in Catalog().sources(kb):
        source_root = resolve_source(source, sync_remote)
        for project_root in project_roots(source, source_root):
            entries = list_files(project_root)
            project = project_root.relative_to(source_root).as_posix()
            manifest = digest(repr([(x.path, x.sha256) for x in entries]))
            snapshot_id = digest(f'{kb}|{source.id}|{project}|{manifest}')
            snapshot = {
                'id': snapshot_id, 'kb': kb, 'source': source.id,
                'project': project, 'root': str(project_root),
                'commit': git(project_root, 'rev-parse', 'HEAD', optional=True),
                'manifest_hash': manifest, 'files': [x.__dict__ for x in entries],
            }
            write_json(ensure_home() / 'snapshots' / f'{snapshot_id}.json', snapshot)
            result.append({'source': source.id, 'project': project, 'snapshot': snapshot_id, 'files': len(entries)})
    return result


def load_snapshot(snapshot_id: str) -> dict:
    if len(snapshot_id) != 64 or not all(c in '0123456789abcdef' for c in snapshot_id):
        raise ValueError('Invalid snapshot ID')
    snapshot = read_json(ensure_home() / 'snapshots' / f'{snapshot_id}.json')
    if snapshot is None:
        raise ValueError('Snapshot not found')
    return snapshot
