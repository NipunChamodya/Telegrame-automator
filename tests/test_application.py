"""Integration tests use real Telethon types and mock every network operation."""
import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec('telethon') is None:
    raise unittest.SkipTest('Telethon is required for mocked application integration tests')

from telethon import errors

from telegram_manager.application import startup
from telegram_manager.configuration import Credentials, bind_account, load_configuration
from telegram_manager.dashboard import Dashboard
from telegram_manager.models import Group, now
from telegram_manager.setup_wizard import authenticate, credential_wizard, hidden
from telegram_manager.storage import Store


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_does_not_request_code(self):
        client = AsyncMock()
        client.is_user_authorized.return_value = True
        client.get_me.return_value = NS(id=1, bot=False, deleted=False)
        self.assertEqual((await authenticate(client)).id, 1)
        client.send_code_request.assert_not_awaited()
        client.sign_in.assert_not_awaited()

    @patch('telegram_manager.setup_wizard.hidden', side_effect=['+123456789', '12345', 'sensitive-2fa-test-value'])
    async def test_expired_session_and_2fa(self, hidden_input):
        client = AsyncMock()
        client.is_user_authorized.return_value = False
        client.send_code_request.return_value = NS(phone_code_hash='opaque')
        client.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
        client.get_me.return_value = NS(id=1, bot=False, deleted=False)
        with patch('sys.stdout', new=io.StringIO()) as output:
            self.assertEqual((await authenticate(client)).id, 1)
        self.assertNotIn('sensitive-2fa-test-value', output.getvalue())
        self.assertEqual(client.sign_in.await_count, 2)
        self.assertEqual(client.sign_in.call_args.kwargs, {'password': 'sensitive-2fa-test-value'})

    @patch('telegram_manager.setup_wizard.sys.stdin.isatty', return_value=False)
    def test_non_terminal_cannot_collect_secrets(self, tty):
        with self.assertRaises(ValueError):
            hidden('Secret: ')

    @patch('telegram_manager.setup_wizard.resolve_credentials', return_value=(None, 'unset'))
    @patch('telegram_manager.setup_wizard.platform.system', return_value='Darwin')
    @patch('telegram_manager.setup_wizard.hidden', return_value='a' * 32)
    @patch('builtins.input', return_value='123')
    @patch('telegram_manager.setup_wizard.api_tutorial')
    @patch('telegram_manager.setup_wizard.yes', return_value=True)
    @patch('telegram_manager.setup_wizard.MacKeychain')
    def test_first_run_keychain_save(self, keychain, yes, tutorial, api_input, hidden_input, system, resolve):
        with tempfile.TemporaryDirectory() as directory, patch('sys.stdout', new=io.StringIO()) as output:
            credentials, source = credential_wizard(Path(directory))
        self.assertEqual(credentials.api_id, 123)
        self.assertEqual(source, 'macOS Keychain')
        keychain.return_value.save_new.assert_called_once()
        self.assertNotIn('a' * 32, output.getvalue())


class StartupIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.client = AsyncMock()
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = NS(id=11, bot=False, deleted=False)
        self.patches = [
            patch.dict(os.environ, {'TGM_DATA_DIR': str(self.root)}),
            patch('telegram_manager.application.sys.stdin.isatty', return_value=True),
            patch('telegram_manager.application.credential_wizard', return_value=(Credentials(123, 'a' * 32), 'test')),
            patch('telegram_manager.application.TelegramClient', return_value=self.client),
            patch('telegram_manager.application.yes', return_value=True),
            patch('telegram_manager.application.Dashboard'),
            patch('sys.stdout', new=io.StringIO()),
        ]
        self.patches.insert(0, patch('telegram_manager.application.welcome'))
        self.started = [p.start() for p in self.patches]
        self.started[-2].return_value.run = AsyncMock()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.directory.cleanup()

    async def test_first_run_initializes_and_opens_dashboard(self):
        await startup()
        self.assertEqual(load_configuration(self.root)['account_id'], 11)
        self.assertTrue((self.root / 'manager.sqlite3').exists())
        self.started[-2].return_value.run.assert_awaited_once()
        self.assertEqual(self.client.disconnect.await_count, 2)

    async def test_existing_startup_keeps_session_and_records(self):
        bind_account(self.root, load_configuration(self.root), 11)
        session = self.root / 'account.session'
        session.write_bytes(b'existing-session-placeholder')
        store = Store(self.root / 'manager.sqlite3')
        store.save_group(11, Group(-1, 'Existing', 'group'))
        store.reserve(11, -1, 'previously attempted')
        store.set_cooldown(11, 9999999999)
        history = store.history(11)
        store.close()
        await startup()
        reopened = Store(self.root / 'manager.sqlite3')
        try:
            self.assertEqual(reopened.history(11), history)
            self.assertEqual(reopened.cooldown(11), 9999999999)
            self.assertEqual(len(reopened.groups(11)), 1)
            self.assertEqual(session.read_bytes(), b'existing-session-placeholder')
            self.client.send_code_request.assert_not_awaited()
        finally:
            reopened.close()

    async def test_wrong_identity_never_opens_dashboard(self):
        bind_account(self.root, load_configuration(self.root), 22)
        Store(self.root / 'manager.sqlite3').close()
        with self.assertRaises(ValueError):
            await startup()
        self.started[-2].return_value.run.assert_not_awaited()
        self.assertEqual(load_configuration(self.root)['account_id'], 22)
        self.client.disconnect.assert_awaited_once()

    async def test_missing_bound_database_requires_recovery(self):
        bind_account(self.root, load_configuration(self.root), 11)
        with self.assertRaises(ValueError):
            await startup()
        self.assertFalse((self.root / 'manager.sqlite3').exists())
        self.client.connect.assert_not_awaited()

    async def test_interruption_releases_resources(self):
        self.client.connect.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            await startup()
        self.client.disconnect.assert_awaited_once()
        self.assertTrue((self.root / 'manager.sqlite3').exists())
        from telegram_manager.security import application_lock
        with application_lock(self.root):
            pass

    async def test_invalid_database_stops_before_credentials(self):
        path = self.root / 'manager.sqlite3'
        path.write_bytes(b'invalid-database-fixture')
        with patch('telegram_manager.application.credential_wizard') as wizard:
            with self.assertRaises(sqlite3.DatabaseError):
                await startup()
            wizard.assert_not_called()
        self.client.connect.assert_not_awaited()
        self.assertEqual(path.read_bytes(), b'invalid-database-fixture')

    async def test_permission_error_does_not_touch_session(self):
        with patch('telegram_manager.application.private_directory', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                await startup()
        self.client.connect.assert_not_awaited()


class DashboardIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / 'manager.sqlite3')
        self.group = Group(-1, 'Test', 'group', permission='allowed', permissions_checked_at=now())
        self.store.save_group(1, self.group)
        self.service = NS(store=self.store, me=NS(id=1), client=AsyncMock(),
                          inspect=AsyncMock(return_value=self.group), discover=AsyncMock(return_value=1),
                          send=AsyncMock(return_value='sent'))
        self.dashboard = Dashboard(self.service, self.root, 'test')

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    @patch('telegram_manager.dashboard.yes', return_value=False)
    @patch('builtins.input', return_value='0')
    async def test_dashboard_header_and_exit(self, answer, yes):
        with patch('sys.stdout', new=io.StringIO()) as output:
            await self.dashboard.run()
        self.assertIn('Posting allowed: 1', output.getvalue())
        self.service.send.assert_not_awaited()

    async def test_first_run_discovery_respects_answer_once(self):
        for answer, expected_calls in [('y', 1), ('', 1), ('n', 0)]:
            with self.subTest(answer=answer), patch('builtins.input', side_effect=[answer, '0']), \
                    patch('sys.stdout', new=io.StringIO()) as output:
                self.service.discover.reset_mock()
                await self.dashboard.run(first_run=True)
                self.assertEqual(self.service.discover.await_count, expected_calls)
                self.assertIn('Posting allowed: 1', output.getvalue())
                self.service.send.assert_not_awaited()

    async def test_send_requires_draft_and_selection(self):
        with self.assertRaises(ValueError):
            await self.dashboard.send()
        self.service.send.assert_not_awaited()

    @patch('telegram_manager.dashboard.authenticate', new_callable=AsyncMock)
    async def test_exact_confirmation_required(self, auth):
        auth.return_value = NS(id=1)
        self.dashboard.message, self.dashboard.destination = 'complete message', -1
        with patch('builtins.input', return_value='yes'), patch('sys.stdout', new=io.StringIO()) as output:
            await self.dashboard.send()
        self.assertIn('complete message', output.getvalue())
        self.service.send.assert_not_awaited()
        with patch('builtins.input', return_value='SEND -1'), patch('sys.stdout', new=io.StringIO()):
            await self.dashboard.send()
        self.service.send.assert_awaited_once_with(-1, 'complete message')
        self.assertIsNone(self.dashboard.destination)

    @patch('telegram_manager.dashboard.authenticate', new_callable=AsyncMock)
    async def test_changed_permission_blocks_approved_selection(self, auth):
        auth.return_value = NS(id=1)
        self.dashboard.message, self.dashboard.destination = 'hello', -1
        self.group.permission = 'denied'
        with self.assertRaises(ValueError):
            await self.dashboard.send()
        self.service.send.assert_not_awaited()

    async def test_composition_clears_destination(self):
        self.dashboard.destination = -1
        with patch('builtins.input', return_value=''), patch('telegram_manager.dashboard.compose', return_value='new'), patch('sys.stdout', new=io.StringIO()):
            await self.dashboard.perform('5')
        self.assertEqual(self.dashboard.message, 'new')
        self.assertIsNone(self.dashboard.destination)

    async def test_search_history_status_and_settings(self):
        with patch('builtins.input', return_value='Test'), patch('sys.stdout', new=io.StringIO()) as output:
            for choice in ('2', '3', '8', '9', '10'):
                await self.dashboard.perform(choice)
        self.assertIn('Test', output.getvalue())
        self.assertIn('cooldown_until_epoch', output.getvalue())
        self.service.send.assert_not_awaited()

    async def test_refresh_rate_limit_persists(self):
        self.service.discover.side_effect = errors.FloodWaitError(None, capture=60)
        with patch('sys.stdout', new=io.StringIO()):
            await self.dashboard.perform('1')
            await self.dashboard.perform('1')
        self.assertEqual(self.service.discover.await_count, 1)
        self.assertGreater(self.store.cooldown(1), 0)
