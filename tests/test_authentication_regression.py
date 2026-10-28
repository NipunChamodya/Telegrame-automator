"""Offline authentication regressions, including Telethon's real migration loop.

Private library hooks are mocked only as transport boundaries in these tests.
Application code uses public authentication methods and constructor options only.
"""
import asyncio
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec('telethon') is None:
    raise unittest.SkipTest('Telethon is required for authentication regression tests')

from telethon import TelegramClient, errors, functions, types
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession

from telegram_manager.application import startup
from telegram_manager.configuration import Credentials, bind_account, load_configuration
from telegram_manager.error_messages import telegram_error_message
from telegram_manager.setup_wizard import (
    AUTH_CONNECTION_RETRIES, AUTH_REQUEST_RETRIES, authenticate, normalize_phone,
)
from telegram_manager.storage import Store


class PhoneValidationTests(unittest.TestCase):
    def test_international_phone_formats(self):
        for value, expected in [('+94712345678', '+94712345678'),
                                (' +94 71 234 5678 ', '+94712345678'),
                                ('+94 (71) 234-5678', '+94712345678'),
                                ('+1 (202) 555-0123', '+12025550123'),
                                ('+44 7700 900123', '+447700900123')]:
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), expected)

    def test_invalid_values_are_explained_without_echo(self):
        for value in ('', ' ', '0771234567', '94712345678', '++94712345678', '+0 712345678',
                      '+94secret', '+123', '+1234567890123456', '+９４７１２３４５６７８', '+94\x1b[31m'):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                normalize_phone(value)
            self.assertIn('Sri Lanka', str(caught.exception))
            if value.strip():
                self.assertNotIn(value, str(caught.exception))


class AuthenticationInputTests(unittest.IsolatedAsyncioTestCase):
    def client(self):
        client = AsyncMock()
        client.is_user_authorized.return_value = False
        client.send_code_request.return_value = NS(phone_code_hash='test-hash')
        client.get_me.return_value = NS(id=123, bot=False, deleted=False)
        return client

    async def test_invalid_input_can_be_corrected_before_any_request(self):
        client = self.client()
        with patch('telegram_manager.setup_wizard.hidden', side_effect=['', '0712345678', '+94 (71) 234-5678', '54321']), \
                patch('sys.stdout', new=io.StringIO()) as output:
            me = await authenticate(client)
        self.assertEqual(me.id, 123)
        client.send_code_request.assert_awaited_once_with('+94712345678')
        client.sign_in.assert_awaited_once_with(phone='+94712345678', code='54321', phone_code_hash='test-hash')
        self.assertIn('+947XXXXXXXX', output.getvalue())
        self.assertNotIn('0712345678', output.getvalue())
        self.assertNotIn('+94 (71) 234-5678', output.getvalue())

    async def test_telegram_rejected_number_can_be_corrected(self):
        client = self.client()
        client.send_code_request.side_effect = [errors.PhoneNumberInvalidError(None), NS(phone_code_hash='valid-hash')]
        with patch('telegram_manager.setup_wizard.hidden', side_effect=['+94712345678', '+94712345679', '54321']), \
                patch('sys.stdout', new=io.StringIO()) as output, \
                self.assertLogs('telegram_manager.authentication', level='WARNING') as logs:
            await authenticate(client)
        self.assertEqual(client.send_code_request.await_count, 2)
        self.assertEqual(client.sign_in.call_args.kwargs['phone'], '+94712345679')
        self.assertNotIn('+94712345678', output.getvalue() + ''.join(logs.output))
        self.assertNotIn('+94712345679', output.getvalue() + ''.join(logs.output))

    async def test_wait_network_failure_and_migration_exhaustion_do_not_loop(self):
        for failure in (errors.FloodWaitError(None, capture=60), ConnectionError('private-phone'),
                        errors.PhoneMigrateError(None, capture=4)):
            with self.subTest(failure=type(failure).__name__):
                client = self.client()
                client.send_code_request.side_effect = failure
                with patch('telegram_manager.setup_wizard.hidden', return_value='+94712345678') as hidden, \
                        patch('sys.stdout', new=io.StringIO()):
                    with self.assertRaises(type(failure)):
                        await authenticate(client)
                hidden.assert_called_once()
                client.send_code_request.assert_awaited_once()
                client.sign_in.assert_not_awaited()

    async def test_interrupted_phone_or_code_never_signs_in(self):
        for entries, code_requests in [([KeyboardInterrupt()], 0), (['+94712345678', EOFError()], 1)]:
            client = self.client()
            with patch('telegram_manager.setup_wizard.hidden', side_effect=entries), patch('sys.stdout', new=io.StringIO()):
                with self.assertRaises((KeyboardInterrupt, EOFError)):
                    await authenticate(client)
            self.assertEqual(client.send_code_request.await_count, code_requests)
            client.sign_in.assert_not_awaited()

    async def test_runtime_authorization_expiry_never_starts_login(self):
        client = self.client()
        with patch('telegram_manager.setup_wizard.hidden') as hidden:
            with self.assertRaises(errors.SessionExpiredError):
                await authenticate(client, allow_login=False)
        hidden.assert_not_called()
        client.send_code_request.assert_not_awaited()

    def test_migration_and_2fa_explanations_are_sanitized(self):
        for exc in (errors.PhoneMigrateError(None, capture=4), errors.NetworkMigrateError(None, capture=4),
                    errors.UserMigrateError(None, capture=4)):
            self.assertIn('data center', telegram_error_message(exc))
            self.assertIn('session was preserved', telegram_error_message(exc))
        self.assertIn('two-step verification', telegram_error_message(errors.SessionPasswordNeededError(None)))


class TelethonMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def simulate_migration(self, retries: int, *, reconnect_failure: bool = False):
        """Real send_code_request/_call/_switch_dc; fake wire and connection only."""
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory) / 'account'
            client = TelegramClient(str(session_path), 123, 'a' * 32,
                                    request_retries=retries, connection_retries=AUTH_CONNECTION_RETRIES,
                                    flood_sleep_threshold=0, raise_last_call_error=True,
                                    auto_reconnect=False, receive_updates=False)
            original_session = client.session
            timestamp = datetime.now(timezone.utc)
            update_state = types.updates.State(pts=7, qts=0, date=timestamp, seq=2, unread_count=0)
            client.session.set_update_state(123, update_state)
            client.session.save()
            target_dc = 4  # Synthetic Telegram response; never a production setting.
            sent_code = types.auth.SentCode(types.auth.SentCodeTypeApp(length=5), 'test-code-hash')
            responses = iter([errors.PhoneMigrateError(None, capture=target_dc), sent_code])
            requests = []

            def send(request, **kwargs):
                requests.append(request)
                self.assertIsInstance(request, functions.InvokeWithoutUpdatesRequest)
                self.assertIsInstance(request.query, functions.auth.SendCodeRequest)
                future = asyncio.get_running_loop().create_future()
                response = next(responses)
                if isinstance(response, Exception):
                    future.set_exception(response)
                else:
                    future.set_result(response)
                return future

            # No sockets can be used: sender, DC lookup and reconnect are mocked.
            client._sender = NS(send=send, auth_key=AuthKey(bytes(range(256))))
            client.is_user_authorized = AsyncMock(return_value=False)
            client._get_dc = AsyncMock(return_value=types.DcOption(target_dc, '127.0.0.1', 443))
            client._disconnect = AsyncMock()
            client.connect = AsyncMock(side_effect=ConnectionError('offline') if reconnect_failure else None)
            try:
                if reconnect_failure:
                    with self.assertRaises(ConnectionError):
                        await client.send_code_request('+94712345678')
                elif retries == 0:
                    # Reproduce the original app bug with the installed Telethon.
                    with self.assertRaises(errors.PhoneMigrateError):
                        await client.send_code_request('+94712345678')
                else:
                    result = await client.send_code_request('+94712345678')
                    self.assertEqual(result.phone_code_hash, 'test-code-hash')
                self.assertEqual(len(requests), 1 if retries == 0 or reconnect_failure else 2)
                client._get_dc.assert_awaited_once_with(target_dc)
                client._disconnect.assert_awaited_once()
                client.connect.assert_awaited_once()
                self.assertIs(client.session, original_session)
                self.assertEqual(client.session.dc_id, target_dc)
            finally:
                client.session.close()
            self.assertTrue(session_path.with_suffix('.session').is_file())
            restored = SQLiteSession(str(session_path))
            try:
                self.assertEqual(restored.dc_id, target_dc)
                self.assertEqual(restored.get_update_state(123).pts, 7)
            finally:
                restored.close()

    async def test_zero_retries_reproduces_migration_failure(self):
        await self.simulate_migration(0)

    async def test_supported_retry_budget_completes_migration(self):
        await self.simulate_migration(AUTH_REQUEST_RETRIES)

    async def test_reconnect_failure_preserves_migrated_session(self):
        await self.simulate_migration(AUTH_REQUEST_RETRIES, reconnect_failure=True)


class AuthenticationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_session_reopened_sequentially_without_delivery_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bind_account(root, load_configuration(root), 123)
            session = root / 'account.session'
            session.write_bytes(b'preserve-existing-session-fixture')
            store = Store(root / 'manager.sqlite3')
            store.reserve(123, -1, 'existing-delivery')
            store.set_cooldown(123, 9999999999)
            before = store.history(123)
            store.close()
            auth, runtime = AsyncMock(), AsyncMock()
            for client in (auth, runtime):
                client.is_user_authorized.return_value = True
                client.get_me.return_value = NS(id=123, bot=False, deleted=False)
            events = []
            auth.disconnect.side_effect = lambda: events.append('auth disconnected')
            runtime.connect.side_effect = lambda: events.append('runtime connected')
            with patch.dict(os.environ, {'TGM_DATA_DIR': directory}), \
                    patch('telegram_manager.application.sys.stdin.isatty', return_value=True), \
                    patch('telegram_manager.application.credential_wizard', return_value=(Credentials(123, 'a' * 32), 'test')), \
                    patch('telegram_manager.application.TelegramClient', side_effect=[auth, runtime]) as factory, \
                    patch('telegram_manager.application.Dashboard') as dashboard, \
                    patch('sys.stdout', new=io.StringIO()):
                dashboard.return_value.run = AsyncMock()
                await startup()
            self.assertEqual(events, ['auth disconnected', 'runtime connected'])
            self.assertEqual([c.args[0] for c in factory.call_args_list], [str(root / 'account')] * 2)
            self.assertEqual([c.kwargs['request_retries'] for c in factory.call_args_list], [AUTH_REQUEST_RETRIES, 0])
            self.assertEqual([c.kwargs['connection_retries'] for c in factory.call_args_list], [AUTH_CONNECTION_RETRIES, 0])
            self.assertTrue(all(c.kwargs['flood_sleep_threshold'] == 0 for c in factory.call_args_list))
            dashboard.return_value.run.assert_awaited_once()
            runtime.disconnect.assert_awaited_once()
            auth.send_code_request.assert_not_awaited()
            runtime.send_code_request.assert_not_awaited()
            self.assertEqual(session.read_bytes(), b'preserve-existing-session-fixture')
            reopened = Store(root / 'manager.sqlite3')
            try:
                self.assertEqual(reopened.history(123), before)
                self.assertEqual(reopened.cooldown(123), 9999999999)
            finally:
                reopened.close()
