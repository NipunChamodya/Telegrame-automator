"""Explicit database backups and credential-free diagnostic exports."""
import json
import contextlib
import os
import platform
import sqlite3
import tempfile
from pathlib import Path


def _destination(destination: Path) -> Path:
    destination = destination.expanduser().absolute()
    if not destination.name or destination.is_symlink() or destination.exists():
        raise ValueError("Choose a new output filename. Existing files are never overwritten.")
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir() or parent.stat().st_uid != os.getuid():
        raise ValueError("Choose a local directory owned by your macOS user.")
    return parent / destination.name


def _publish(temporary: str, destination: Path) -> None:
    # link, rather than replace, preserves the no-overwrite guarantee under races.
    os.link(temporary, destination)
    os.chmod(destination, 0o600)


def backup_database(source: Path, destination: Path, *, cancel_event=None) -> dict:
    """Run in a worker thread. SQLite backup includes committed WAL contents."""
    def check_cancelled(*_):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError('Database backup was cancelled.')
    check_cancelled()
    destination = _destination(destination)
    source = source.resolve(strict=True)
    if source == destination:
        raise ValueError("Backup destination must differ from the application database.")
    descriptor, temporary = tempfile.mkstemp(prefix='.tgm-backup-', dir=destination.parent)
    os.close(descriptor)
    try:
        with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with contextlib.closing(sqlite3.connect(temporary)) as backup:
                original.backup(backup, pages=64, progress=check_cancelled)
                if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError('Backup integrity verification failed.')
        check_cancelled()
        _publish(temporary, destination)
        return {'path': str(destination), 'verified': True,
                'includes_session': False, 'includes_keychain': False}
    finally:
        Path(temporary).unlink(missing_ok=True)


def diagnostic_snapshot(root: Path, store, policy) -> dict:
    """No account IDs, group names, filesystem paths, exception text or credentials."""
    import importlib.metadata
    try:
        telethon = importlib.metadata.version('Telethon')
    except importlib.metadata.PackageNotFoundError:
        telethon = 'unavailable'
    row = store.db.execute('PRAGMA journal_mode').fetchone()
    return {'application_version': '0.2.0', 'python_version': platform.python_version(),
            'system': platform.system(), 'architecture': platform.machine(),
            'telethon_version': telethon, 'sqlite_version': sqlite3.sqlite_version,
            'database_journal_mode': row[0] if row else 'unknown',
            'session_file_present': (root / 'account.session').is_file(),
            'cache_policy_seconds': vars(policy),
            'security': {'secrets_exported': False, 'network_trace_exported': False}}


def export_diagnostics(snapshot: dict, destination: Path) -> dict:
    destination = _destination(destination)
    descriptor, temporary = tempfile.mkstemp(prefix='.tgm-diagnostics-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        _publish(temporary, destination)
        return {'path': str(destination), 'secrets_included': False}
    finally:
        Path(temporary).unlink(missing_ok=True)
