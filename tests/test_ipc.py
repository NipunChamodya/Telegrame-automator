"""IPC tests use isolated private databases and mock all Telegram/Keychain work."""
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telethon import errors

from telegram_manager.configuration import Credentials, bind_account, load_configuration
from telegram_manager.ipc import Backend, IPCError, MAX_FRAME, ProtocolServer, strict_json
from telegram_manager.models import Group, now
from telegram_manager.storage import Store


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / 'manager.sqlite3')
        self.config = load_configuration(self.root)
        bind_account(self.root, self.config, 10)
        self.backend = Backend(self.root, self.store, self.config)
        self.group = Group(-1, 'ශ්‍රී ලංකා தமிழ் 👩🏽‍💻', 'group', permission='allowed', permissions_checked_at=now())
        self.store.save_group(10, self.group)

    async def asyncTearDown(self):
        await self.backend.close()
        self.store.close()
        self.directory.cleanup()

    async def call(self, method, **params):
        return await self.backend.dispatch('test-request', method, params)

    async def test_cached_reads_and_status_without_connecting(self):
        with patch('telegram_manager.ipc.resolve_credentials') as credentials:
            status = await self.call('status')
            groups = await self.call('groups', query='ශ්‍රී')
            history = await self.call('history')
            settings = await self.call('settings')
        self.assertFalse(status['connected'])
        self.assertEqual(status['overview']['total'], 1)
        self.assertEqual(groups['groups'][0]['name'], self.group.name)
        self.assertEqual(history['deliveries'], [])
        self.assertNotIn('api_hash', json.dumps(settings))
        credentials.assert_not_called()

    async def test_strict_request_parameters(self):
        for method, params in [('groups', {'size': True}), ('groups', {'page': -1}),
                               ('inspect', {'destination': 'all'}), ('discover', {'all': True}),
                               ('draft.save', {'message': [], 'extra': 'secret'}),
                               ('approval.set', {'destination': -1}), ('shell', {'command': 'ls'})]:
            with self.subTest(method=method, params=params), self.assertRaises(IPCError):
                await self.backend.dispatch('test', method, params)

    async def test_account_isolation(self):
        self.store.save_group(20, Group(-2, 'Other account', 'group'))
        rows = await self.call('groups')
        self.assertEqual(len(rows['groups']), 1)
        with self.assertRaises(IPCError):
            await self.call('detail', destination=-2)

    async def test_persistent_drafts_and_explicit_approvals(self):
        await self.call('draft.save', message='தமிழ் 👩🏽‍💻')
        self.assertEqual((await self.call('draft.get'))['message'], 'தமிழ் 👩🏽‍💻')
        self.assertEqual((await self.call('approvals'))['groups'], [])
        await self.call('approval.set', destination=-1, approved=True)
        self.assertEqual(len((await self.call('approvals'))['groups']), 1)
        await self.call('approval.set', destination=-1, approved=False)
        self.assertEqual((await self.call('approvals'))['groups'], [])

    async def test_preview_send_requires_approval_exact_confirmation_and_one_use(self):
        service = NS(inspect=AsyncMock(return_value=self.group), send=AsyncMock(return_value='Sent'))
        self.backend.service, self.backend.auth_stage = service, 'connected'
        with self.assertRaises(IPCError):
            await self.call('preview', destination=-1, message='explicit message')
        await self.call('approval.set', destination=-1, approved=True)
        preview = await self.call('preview', destination=-1, message='explicit message')
        with self.assertRaises(IPCError):
            await self.call('send', token=preview['token'], confirmation='yes')
        service.send.assert_not_awaited()
        with self.assertRaises(IPCError):
            await self.call('send', token=preview['token'], confirmation='SEND -1')
        preview = await self.call('preview', destination=-1, message='explicit message')
        await self.call('send', token=preview['token'], confirmation='SEND -1')
        service.send.assert_awaited_once_with(-1, 'explicit message')
        with self.assertRaises(IPCError):
            await self.call('send', token=preview['token'], confirmation='SEND -1')

    async def test_draft_change_revocation_and_expiry_invalidate_preview(self):
        service = NS(inspect=AsyncMock(return_value=self.group), send=AsyncMock())
        self.backend.service, self.backend.auth_stage = service, 'connected'
        await self.call('approval.set', destination=-1, approved=True)
        preview = await self.call('preview', destination=-1, message='hello')
        await self.call('draft.save', message='changed')
        with self.assertRaises(IPCError):
            await self.call('send', token=preview['token'], confirmation='SEND -1')
        preview = await self.call('preview', destination=-1, message='hello')
        await self.call('approval.set', destination=-1, approved=False)
        with self.assertRaises(IPCError):
            await self.call('send', token=preview['token'], confirmation='SEND -1')
        await self.call('approval.set', destination=-1, approved=True)
        preview = await self.call('preview', destination=-1, message='hello')
        with patch('telegram_manager.ipc.time.time', return_value=preview['expires_at'] + 1):
            with self.assertRaises(IPCError):
                await self.call('send', token=preview['token'], confirmation='SEND -1')
        service.send.assert_not_awaited()

    async def test_preview_denied_empty_and_utf16_limits(self):
        self.backend.service = NS(inspect=AsyncMock(return_value=self.group))
        self.backend.auth_stage = 'connected'
        await self.call('approval.set', destination=-1, approved=True)
        for text in ('', '😀' * 2049):
            with self.assertRaises(IPCError):
                await self.call('preview', destination=-1, message=text)
        self.group.permission = 'unknown'
        with self.assertRaises(IPCError):
            await self.call('preview', destination=-1, message='hello')

    async def test_existing_authorized_session_reuses_path_and_bounded_auth_policy(self):
        client, runtime = AsyncMock(), AsyncMock()
        for instance in (client, runtime):
            instance.is_connected = Mock(return_value=True)
            instance.is_user_authorized.return_value = True
            instance.get_me.return_value = NS(id=10, bot=False, deleted=False, first_name='Test', last_name='Account')
        factory = Mock(side_effect=[client, runtime])
        self.backend.client_factory = factory
        with patch('telegram_manager.ipc.resolve_credentials', return_value=(Credentials(123, 'a' * 32), 'test')):
            status = await self.call('connect')
        self.assertTrue(status['connected'])
        self.assertEqual(status['account']['display_name'], 'Test Account')
        self.assertEqual([c.args[0] for c in factory.call_args_list], [str(self.root / 'account')] * 2)
        self.assertEqual([c.kwargs['request_retries'] for c in factory.call_args_list], [3, 0])
        client.send_code_request.assert_not_awaited()
        runtime.send_code_request.assert_not_awaited()

    async def test_authentication_and_binding_never_echo_secrets(self):
        self.config['account_id'] = None
        # Isolated config file is removed only in this test fixture, not product code.
        (self.root / 'config.json').unlink()
        auth, runtime = AsyncMock(), AsyncMock()
        auth.is_user_authorized.return_value = False
        auth.send_code_request.return_value = NS(phone_code_hash='private-auth-token')
        auth.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
        for client in (auth, runtime):
            client.is_connected = Mock(return_value=True)
            client.get_me.return_value = NS(id=10, bot=False, deleted=False, first_name='Test')
        runtime.is_user_authorized.return_value = True
        self.backend.client_factory = Mock(side_effect=[auth, runtime])
        with patch('telegram_manager.ipc.resolve_credentials', return_value=(None, 'unset')):
            self.assertEqual((await self.call('connect'))['auth_stage'], 'credentials')
        status = await self.call('auth.credentials', api_id='123', api_hash='a' * 32, save=False)
        self.assertEqual(status['auth_stage'], 'phone')
        status = await self.call('auth.phone', phone='+94 71 234 5678')
        self.assertEqual(status['auth_stage'], 'code')
        status = await self.call('auth.code', code='12345')
        self.assertEqual(status['auth_stage'], 'password')
        status = await self.call('auth.password', password='private-password')
        self.assertEqual(status['auth_stage'], 'bind_account')
        with self.assertRaises(IPCError):
            await self.call('auth.bind', account_id=10, confirm=False)
        status = await self.call('auth.bind', account_id=10, confirm=True)
        self.assertTrue(status['connected'])
        payload = json.dumps(status)
        for secret in ('a' * 32, 'private-password', '94712345678', 'private-auth-token', '12345'):
            self.assertNotIn(secret, payload)

    async def test_specific_credential_phone_validation_and_private_settings_persistence(self):
        self.backend.auth_stage = 'credentials'
        for params, expected in [({'api_id': 'invalid-secret-id', 'api_hash': 'a' * 32}, 'invalid_api_id'),
                                 ({'api_id': '123', 'api_hash': 'private-invalid-hash'}, 'invalid_api_hash')]:
            with self.assertRaises(IPCError) as caught:
                await self.call('auth.credentials', **params)
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('private-invalid-hash', caught.exception.message)
            self.assertNotIn('invalid-secret-id', caught.exception.message)
        self.backend.auth_stage = 'phone'
        self.backend.client = AsyncMock()
        with self.assertRaises(IPCError) as caught:
            await self.call('auth.phone', phone='private-invalid-number')
        self.assertEqual(caught.exception.code, 'invalid_phone')
        self.assertIn('+947XXXXXXXX', caught.exception.message)
        self.assertNotIn('private-invalid-number', caught.exception.message)
        result = await self.call('settings.update', cache_policy={'permissions': 30}, inspection_limit=7)
        self.assertEqual(result['cache_policy']['permissions'], 30)
        self.assertEqual(result['inspection_limit'], 7)
        settings_path = self.root / 'desktop-settings.json'
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
        existing = settings_path.read_bytes()
        with self.assertRaises(IPCError):
            await self.call('settings.update', cache_policy={'permissions': -1})
        self.assertEqual(settings_path.read_bytes(), existing)
        restored = Backend(self.root, self.store, self.config)
        self.assertEqual(restored.policy.permissions, 30)
        self.assertEqual(restored.inspection_limit, 7)

    async def test_explicit_reconnect_restores_a_disconnected_transport(self):
        stale, authentication, runtime = AsyncMock(), AsyncMock(), AsyncMock()
        stale.is_connected = Mock(return_value=False)
        for client in (authentication, runtime):
            client.is_connected = Mock(return_value=True)
            client.is_user_authorized.return_value = True
            client.get_me.return_value = NS(id=10, bot=False, deleted=False, first_name='Restored')
        self.backend.client = stale
        self.backend.service = NS()
        self.backend.auth_stage = 'connected'
        self.backend.credentials = Credentials(123, 'a' * 32)
        self.backend.client_factory = Mock(side_effect=[authentication, runtime])
        self.assertFalse((await self.call('status'))['connected'])
        status = await self.call('connect')
        self.assertTrue(status['connected'])
        stale.disconnect.assert_awaited_once()
        authentication.send_code_request.assert_not_awaited()
        runtime.send_code_request.assert_not_awaited()

    async def test_network_mutations_serialize_but_cached_reads_remain_available(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def discover(**kwargs):
            started.set()
            await finish.wait()
            return 1
        self.backend.service = NS(discover=discover)
        self.backend.auth_stage = 'connected'
        task = asyncio.create_task(self.call('discover'))
        await started.wait()
        status = await asyncio.wait_for(self.call('status'), 0.2)
        self.assertEqual(status['overview']['total'], 1)
        finish.set()
        await task


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / 'manager.sqlite3')
        self.backend = Backend(self.root, self.store, {'version': 1, 'account_id': 10})
        self.server = ProtocolServer(self.backend, lambda data: None)

    async def asyncTearDown(self):
        for task in tuple(self.server.tasks.values()):
            task.cancel()
        if self.server.tasks:
            await asyncio.gather(*tuple(self.server.tasks.values()), return_exceptions=True)
        await self.backend.close()
        self.store.close()
        self.directory.cleanup()

    async def request(self, ident, method, params=None):
        await self.server.accept(json.dumps({'id': ident, 'method': method, 'params': params or {}}).encode())
        task = self.server.tasks.get(ident)
        if task:
            await task
        return self.server.queue.get_nowait()

    async def test_health_invalid_json_unknown_methods_and_duplicate_ids(self):
        result = await self.request('health', 'health')
        self.assertTrue(result['ok'])
        await self.server.accept(b'{broken secret')
        error = self.server.queue.get_nowait()
        self.assertEqual(error['error']['code'], 'invalid_request')
        self.assertNotIn('secret', json.dumps(error))
        error = await self.request('unknown', 'arbitrary.exec', {'code': 'print("secret")'})
        self.assertEqual(error['error']['code'], 'unknown_method')
        error = await self.request('health', 'health')
        self.assertEqual(error['error']['code'], 'duplicate_request')

    async def test_duplicate_keys_nonfinite_numbers_and_oversized_frames(self):
        for frame in (b'{"id":"one","id":"two","method":"health","params":{}}',
                      b'{"id":"a","method":"health","params":{"x":NaN}}', b'a' * (MAX_FRAME + 1)):
            await self.server.accept(frame)
            self.assertFalse(self.server.queue.get_nowait()['ok'])
        with self.assertRaises(ValueError):
            strict_json('{"x":1,"x":2}')

    async def test_cancel_queued_or_active_operation_preserves_protocol(self):
        started = asyncio.Event()
        async def wait(**kwargs):
            started.set()
            await asyncio.Event().wait()
        self.backend.service, self.backend.auth_stage = NS(discover=wait), 'connected'
        await self.server.accept(b'{"id":"work","method":"discover","params":{}}')
        task = self.server.tasks['work']
        await started.wait()
        await self.server.accept(b'{"id":"cancel","method":"cancel","params":{"request_id":"work"}}')
        await task
        messages = [self.server.queue.get_nowait(), self.server.queue.get_nowait()]
        self.assertTrue(any(m.get('error', {}).get('code') == 'cancelled' for m in messages))
        self.assertTrue(any(m.get('result', {}).get('cancelled') is True for m in messages))

    async def test_error_serialization_and_cooldown_never_echo_exception_payload(self):
        self.backend.service = NS(discover=AsyncMock(side_effect=ConnectionError('private-session-and-hash')))
        self.backend.auth_stage = 'connected'
        result = await self.request('io', 'discover')
        self.assertEqual(result['error']['code'], 'io')
        self.assertNotIn('private-session-and-hash', json.dumps(result))
        self.backend.service = NS(discover=AsyncMock(side_effect=errors.FloodWaitError(None, capture=16)))
        self.backend.auth_stage = 'connected' 
        result = await self.request('flood', 'discover')
        self.assertEqual(result['error']['code'], 'cooldown')
        self.assertGreater(self.store.cooldown(10), 0)

    async def test_progress_events_and_shutdown_are_framed(self):
        self.server.progress({'event': 'progress', 'request_id': 'job', 'data': {'index': 1}})
        self.assertEqual(self.server.queue.get_nowait()['event'], 'progress')
        result = await self.request('bye', 'shutdown')
        self.assertTrue(result['result']['shutting_down'])
        self.assertTrue(self.server.stopping)

    async def test_output_failure_after_eof_does_not_hang(self):
        def broken(data):
            raise BrokenPipeError('private-pipe')
        server = ProtocolServer(self.backend, broken)
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"id":"health","method":"health","params":{}}\n')
        reader.feed_eof()
        await asyncio.wait_for(server.serve(reader), timeout=2)
        self.assertFalse(server.output_available)

    async def test_full_output_queue_does_not_block_cancelled_handler_during_shutdown(self):
        reader = asyncio.StreamReader()
        blocked = asyncio.Event()
        async def writer(data):
            await blocked.wait()
        server = ProtocolServer(self.backend, writer)
        started = asyncio.Event()
        async def discover(**kwargs):
            started.set()
            await asyncio.Event().wait()
        self.backend.service, self.backend.auth_stage = NS(discover=discover), 'connected'
        serve = asyncio.create_task(server.serve(reader))
        await server.accept(b'{"id":"operation","method":"discover","params":{}}')
        await started.wait()
        for index in range(128):
            server.progress({'event': 'progress', 'request_id': 'operation', 'data': {'index': index}})
        reader.feed_eof()
        await asyncio.sleep(0.03)
        self.assertNotIn('operation', server.tasks)  # Cancelled handler did not await queue.put.
        blocked.set()
        await asyncio.wait_for(serve, timeout=1)

    async def test_eof_disconnects_and_closes_pending_operation(self):
        self.backend.client = AsyncMock()
        reader = asyncio.StreamReader()
        reader.feed_eof()
        await self.server.serve(reader)
        self.assertIsNone(self.backend.client)


class ProcessProtocolTests(unittest.TestCase):
    def test_real_backend_process_stdout_is_protocol_only(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, TGM_DATA_DIR=directory)
            env.pop('TELEGRAM_API_ID', None)
            env.pop('TELEGRAM_API_HASH', None)
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
            process = subprocess.Popen([sys.executable, '-u', '-m', 'telegram_manager.ipc'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                process.stdin.write(b'{"id":"health","method":"health","params":{}}\n')
                process.stdin.flush()
                result = json.loads(process.stdout.readline())
                self.assertEqual(result['id'], 'health')
                self.assertTrue(result['ok'])
                process.stdin.write(b'{"id":"bye","method":"shutdown","params":{}}\n')
                process.stdin.flush()
                result = json.loads(process.stdout.readline())
                self.assertTrue(result['result']['shutting_down'])
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(process.stdout.read(), b'')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
