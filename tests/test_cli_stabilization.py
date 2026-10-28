"""CLI correction, bounded inspection and persistent account state regressions."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions, utils

from telegram_manager.dashboard import Dashboard
from telegram_manager.messaging import import_message, message_units, validate_message
from telegram_manager.models import Group
from telegram_manager.storage import Store
from telegram_manager.telegram import TelegramService
from telegram_manager.terminal import cell, display_width
from test_discovery import chat, full_chat


class PersistentStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'manager.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_unicode_drafts_survive_restart_and_are_account_isolated(self):
        self.assertEqual(self.store.draft(1)['message'], '')
        self.store.save_draft(1, 'ශ්‍රී தமிழ் 👩🏽‍💻')
        self.assertEqual(self.store.draft(2)['message'], '')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.draft(1)['message'], 'ශ්‍රී தமிழ் 👩🏽‍💻')
        self.store.save_draft(1, '')
        self.assertEqual(self.store.draft(1)['message'], '')

    def test_approval_is_explicit_account_isolated_and_revocable(self):
        self.store.save_group(1, Group(-1, 'Known', 'group'))
        self.assertFalse(self.store.is_approved(1, -1))
        self.store.set_approval(1, -1, True)
        self.assertTrue(self.store.is_approved(1, -1))
        self.assertFalse(self.store.is_approved(2, -1))
        self.assertEqual(self.store.approvals(1)[0]['id'], -1)
        self.assertIn('approved_at', self.store.approvals(1)[0])
        self.store.set_approval(1, -1, False)
        self.assertEqual(self.store.approvals(1), [])
        with self.assertRaises(ValueError):
            self.store.set_approval(1, -2, True)
        with self.assertRaises(ValueError):
            self.store.set_approval(1, -1, 'true')

    def test_new_tables_preserve_existing_ledger_and_cooldowns(self):
        self.store.reserve(1, -1, 'original attempt')
        self.store.set_cooldown(1, 9999999999)
        ledger = self.store.history(1)
        self.store.save_draft(1, 'draft')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.history(1), ledger)
        self.assertEqual(self.store.cooldown(1), 9999999999)

    def test_group_type_filter_and_member_sort(self):
        self.store.save_group(1, Group(-1, 'Basic', 'group', members=2))
        self.store.save_group(1, Group(-2, 'Super', 'supergroup', members=99))
        self.assertEqual(self.store.page(1, group_type='supergroup')[1], 1)
        self.assertEqual(self.store.page(1, sort='members')[0][0]['id'], -2)
        with self.assertRaises(ValueError):
            self.store.page(1, group_type="supergroup' OR 1=1")


class MessageImportTests(unittest.TestCase):
    def test_unicode_regular_file_and_length_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'message.txt'
            path.write_text('ශ්‍රී தமிழ் 👩🏽‍💻', encoding='utf-8')
            self.assertEqual(import_message(path), 'ශ්‍රී தமிழ் 👩🏽‍💻')
            self.assertEqual(message_units('😀'), 2)
            path.write_text('😀' * 2049, encoding='utf-8')
            with self.assertRaises(ValueError):
                import_message(path)
            with self.assertRaises(ValueError):
                validate_message(' ')

    def test_symlinks_missing_invalid_and_oversized_files_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'message.txt'
            path.write_text('text')
            link = root / 'link.txt'
            link.symlink_to(path)
            for candidate in (link, root / 'missing', root):
                with self.assertRaises(ValueError):
                    import_message(candidate)
            path.write_bytes(b'\xff\xfe\xfd')
            with self.assertRaisesRegex(ValueError, 'UTF-8'):
                import_message(path)
            path.write_bytes(b'x' * 65537)
            with self.assertRaises(ValueError):
                import_message(path)

    def test_compact_unicode_cell_width(self):
        self.assertEqual(display_width('👨‍👩‍👧‍👦'), 2)
        self.assertEqual(display_width('🇱🇰'), 2)
        self.assertEqual(display_width('தமிழ்'), 3)
        self.assertEqual(cell('Python', 8), 'Python  ')
        self.assertNotIn('👨', cell('👨‍👩‍👧‍👦', 1))


class CLIInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'manager.sqlite3')
        self.store.save_group(1, Group(-1, 'ශ්‍රී', 'group'))
        self.service = NS(store=self.store, me=NS(id=1), inspect=AsyncMock(), client=AsyncMock())
        self.dashboard = Dashboard(self.service, Path(self.directory.name), 'test')

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_all_and_invalid_selection_never_trigger_inspection(self):
        for value in ('all', 'garbage', '-999'):
            with patch('builtins.input', return_value=value), patch('sys.stdout', new=io.StringIO()) as output:
                await self.dashboard.perform('4')
            self.assertNotIn('invalid literal', output.getvalue())
        self.service.inspect.assert_not_awaited()

    async def test_empty_selection_cancels_and_visible_index_resolves_exact_id(self):
        self.dashboard.visible_groups = [-1]
        for value in ('#1', '1', '-1'):
            with patch('builtins.input', return_value=value):
                self.assertEqual(self.dashboard.read_selection(), -1)
        with patch('builtins.input', return_value=''), patch('sys.stdout', new=io.StringIO()):
            self.assertIsNone(self.dashboard.read_selection())

    async def test_direct_composition_is_not_a_filename_and_persists(self):
        with patch('builtins.input', side_effect=['1', 'This is a message, not a path', '.']), patch('sys.stdout', new=io.StringIO()):
            await self.dashboard.perform('5')
        self.assertEqual(self.dashboard.message, 'This is a message, not a path')
        self.assertEqual(self.store.draft(1)['message'], self.dashboard.message)
        restored = Dashboard(self.service, Path(self.directory.name), 'test')
        self.assertEqual(restored.message, self.dashboard.message)
        self.assertIsNone(restored.destination)

    async def test_cancel_composer_preserves_existing_draft(self):
        self.store.save_draft(1, 'existing')
        self.dashboard.message = 'existing'
        with patch('builtins.input', return_value='0'), patch('sys.stdout', new=io.StringIO()):
            await self.dashboard.perform('5')
        self.assertEqual(self.store.draft(1)['message'], 'existing')


class InspectionLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'manager.sqlite3')
        self.entities = [chat(i) for i in range(1, 14)]
        self.client = AsyncMock()
        async def dialogs(**kwargs):
            for entity in self.entities:
                yield NS(entity=entity, archived=False)
        self.client.iter_dialogs = Mock(side_effect=dialogs)
        self.client.get_entity.side_effect = lambda value: next(e for e in self.entities if utils.get_peer_id(e) == value)
        self.client.side_effect = lambda request: full_chat(next(e for e in self.entities if e.id == request.chat_id))
        self.service = TelegramService(self.client, self.store, NS(id=10))
        self.service.request_interval = 0
        await self.service.discover()

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_default_batch_is_bounded_and_remaining_work_persists(self):
        self.assertEqual(await self.service.inspect_pending(), 10)
        self.assertEqual(self.store.overview(10)['pending'], 3)
        self.assertEqual(await self.service.inspect_pending(limit=2), 2)
        self.assertEqual(self.store.overview(10)['pending'], 1)

    async def test_selected_ids_only_and_bad_limits_do_not_request(self):
        self.assertEqual(await self.service.inspect_pending(limit=1, destinations=[-5]), 1)
        self.assertEqual(self.client.get_entity.call_args.args[0], -5)
        self.client.reset_mock()
        for kwargs in ({'limit': 0}, {'limit': 101}, {'limit': True}, {'destinations': [-999]},
                       {'limit': 1, 'destinations': [-1, -2]}, {'destinations': [-1, -1]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.service.inspect_pending(**kwargs)
        self.client.assert_not_called()
