import tempfile
import unittest
from pathlib import Path

from telegram_manager.models import Group
from telegram_manager.storage import DuplicateMessage, Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'test.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_account_isolation_and_search(self):
        self.store.save_group(1, Group(-1, 'Engineering', 'group'))
        self.store.save_group(2, Group(-2, 'Private', 'group'))
        self.assertEqual(len(self.store.groups(1, 'ENGINEER')), 1)
        self.assertEqual(self.store.groups(1, 'Private'), [])

    def test_duplicate_survives_restart_and_failure(self):
        delivery, random_id = self.store.reserve(1, -1, 'hello')
        self.assertGreater(random_id, 0)
        self.store.finish(delivery, 'uncertain', 'transport failure')
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaises(DuplicateMessage):
            self.store.reserve(1, -1, 'hello')
        self.assertEqual(self.store.history(1)[0]['status'], 'uncertain')
        self.store.reserve(1, -2, 'hello')
        self.store.reserve(2, -1, 'hello')

    def test_atomic_reservation_across_connections(self):
        other = Store(self.path)
        try:
            self.store.reserve(1, -1, 'same')
            with self.assertRaises(DuplicateMessage):
                other.reserve(1, -1, 'same')
        finally:
            other.close()

    def test_cooldown_never_shortened(self):
        self.store.set_cooldown(1, 500)
        self.store.set_cooldown(1, 100)
        self.assertEqual(self.store.cooldown(1), 500)
        self.assertEqual(self.store.cooldown(2), 0)


if __name__ == '__main__':
    unittest.main()
