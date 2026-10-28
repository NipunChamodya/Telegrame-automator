import json
import tempfile
import threading
import unittest
from pathlib import Path

from telegram_manager.cache import CachePolicy
from telegram_manager.maintenance import backup_database, diagnostic_snapshot, export_diagnostics
from telegram_manager.models import Group
from telegram_manager.storage import Store


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / 'manager.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_backup_includes_committed_wal_and_never_overwrites(self):
        self.store.save_group(1, Group(-1, 'ශ්‍රී தமிழ் 👩🏽‍💻', 'group'))
        self.store.reserve(1, -1, 'already attempted')
        self.store.set_cooldown(1, 9999999999)
        target = self.root / 'backup.sqlite3'
        result = backup_database(self.path, target)
        self.assertTrue(result['verified'])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        copy = Store(target)
        try:
            self.assertEqual(copy.groups(1), self.store.groups(1))
            self.assertEqual(copy.history(1), self.store.history(1))
            self.assertEqual(copy.cooldown(1), self.store.cooldown(1))
        finally:
            copy.close()
        with self.assertRaises(ValueError):
            backup_database(self.path, target)

    def test_cancelled_backup_does_not_publish_or_modify_source(self):
        self.store.reserve(1, -1, 'preserve')
        before = self.store.history(1)
        event = threading.Event()
        event.set()
        destination = self.root / 'cancelled.sqlite3'
        with self.assertRaises(InterruptedError):
            backup_database(self.path, destination, cancel_event=event)
        self.assertFalse(destination.exists())
        self.assertEqual(self.store.history(1), before)

    def test_diagnostic_export_contains_no_account_group_or_paths(self):
        self.store.save_group(1234567, Group(-1, 'private-group-secret', 'group'))
        snapshot = diagnostic_snapshot(self.root, self.store, CachePolicy())
        text = json.dumps(snapshot)
        self.assertNotIn('1234567', text)
        self.assertNotIn('private-group-secret', text)
        self.assertNotIn(str(self.root), text)
        target = self.root / 'diagnostics.json'
        export_diagnostics(snapshot, target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(json.loads(target.read_text())['security']['secrets_exported'])

    def test_backup_rejects_symlink_without_touching_target(self):
        target = self.root / 'other'
        target.write_text('preserve')
        link = self.root / 'link'
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            backup_database(self.path, link)
        self.assertEqual(target.read_text(), 'preserve')

    def test_delivery_preview_account_isolation_and_legacy_rows(self):
        delivery, _ = self.store.reserve(1, -1, 'draft')
        self.assertIsNone(self.store.history(1)[0]['message_preview'])
        self.store.delivery_note(1, delivery, 'ශ්‍රී preview', 42)
        self.assertEqual(self.store.history(1, 'ශ්‍රී')[0]['telegram_message_id'], 42)
        self.assertEqual(self.store.history(2), [])
        with self.assertRaises(ValueError):
            self.store.delivery_note(2, delivery, 'wrong account')
