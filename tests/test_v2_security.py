"""Adversarial account lifecycle regressions; no network or real user data."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram_manager.accounts import ProfileError
from telegram_manager.configuration import bind_account, load_configuration
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.models import Group
from telegram_manager.security import KeychainError
from telegram_manager.storage import Store


class AccountSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = load_configuration(self.root)
        bind_account(self.root, config, 11)
        store = Store(self.root / 'manager.sqlite3')
        store.save_group(11, Group(-1, 'தமிழ் ශ්‍රී 👩🏽‍💻', 'group'))
        store.save_draft(11, 'original draft')
        self.backend = Backend(self.root, store, config)
        self.session = self.root / 'account.session'
        self.session.write_bytes(b'opaque fixture session; never opened')

    async def asyncTearDown(self):
        await self.backend.close()
        self.backend.store.close()
        self.temp.cleanup()

    async def call(self, method, **params):
        return await self.backend.dispatch('security-test', method, params)

    async def test_switch_invalidates_context_but_preserves_legacy_files(self):
        self.backend.preview_tokens['old'] = {'account': 11}
        client = SimpleNamespace(disconnect=AsyncMock())
        self.backend.client = client
        result = await self.call('accounts.add', label='Second account', confirm=True)
        second = result['created_profile_id']
        client.disconnect.assert_awaited_once()
        self.assertEqual(self.backend.preview_tokens, {})
        self.assertIsNone(self.backend.me)
        self.assertIsNone(self.backend.credentials)
        self.assertIsNone(self.backend.phone)
        self.assertNotEqual(self.backend.root, self.root)
        self.assertTrue(self.session.exists())
        await self.call('accounts.switch', profile_id='legacy', confirm=True)
        self.assertEqual((await self.call('draft.get'))['message'], 'original draft')
        self.assertEqual((await self.call('groups'))['groups'][0]['id'], -1)
        self.assertEqual(self.session.read_bytes(), b'opaque fixture session; never opened')
        self.assertTrue(self.backend.registry.root_for(second).is_dir())

    async def test_queued_old_generation_request_is_rejected(self):
        second = self.backend.registry.create('Other account')
        await self.backend.lock.acquire()
        switch = asyncio.create_task(self.call('accounts.switch', profile_id=second, confirm=True))
        await asyncio.sleep(0)
        mutation = asyncio.create_task(self.call('accounts.disconnect', profile_id='legacy', confirm=True))
        await asyncio.sleep(0)
        self.backend.lock.release()
        await switch
        with self.assertRaises(IPCError) as caught:
            await mutation
        self.assertEqual(caught.exception.code, 'account_changed')
        self.assertEqual(self.backend.profile_id, second)

    async def test_archive_restore_and_removal_are_distinct_and_scoped(self):
        second = self.backend.registry.create('Other account')
        root = self.backend.registry.root_for(second)
        marker = root / 'fixture.txt'
        marker.write_text('retained', encoding='utf-8')
        await self.call('accounts.archive', profile_id=second, confirm=True)
        self.assertTrue(marker.exists())
        with self.assertRaises(ProfileError):
            self.backend.registry.profile(second)
        await self.call('accounts.restore', profile_id=second, confirm=True)
        self.assertTrue(marker.exists())
        with patch('telegram_manager.accounts.delete_profile_credentials', return_value=False):
            await self.call('accounts.remove', profile_id=second, confirmation=f'REMOVE {second}')
        self.assertFalse(root.exists())
        self.assertTrue(self.session.exists())
        self.assertEqual(self.backend.store.draft(11)['message'], 'original draft')
        with self.assertRaises(IPCError):
            await self.call('accounts.remove', profile_id='legacy', confirmation='REMOVE legacy')

    async def test_duplicate_identity_and_path_traversal_blocked(self):
        second = self.backend.registry.create('Other account')
        with self.assertRaises(ProfileError):
            self.backend.registry.verify(second, 11, 'duplicate identity')
        with self.assertRaises(ProfileError):
            self.backend.registry.root_for('../escape')
        self.assertIsNone(self.backend.registry.profile(second)['telegram_id'])

    async def test_logout_requires_exact_phrase_and_preserves_database(self):
        client = AsyncMock()
        client.is_connected = Mock(return_value=True)
        client.get_me.return_value = SimpleNamespace(id=11)
        self.backend.client = client
        with self.assertRaises(IPCError):
            await self.call('accounts.logout', profile_id='legacy', confirmation='yes')
        client.assert_not_awaited()
        await self.call('accounts.logout', profile_id='legacy', confirmation='LOG OUT legacy')
        client.assert_awaited_once()
        self.assertEqual(type(client.call_args.args[0]).__name__, 'LogOutRequest')
        client.disconnect.assert_awaited_once()
        self.assertTrue(self.session.exists())
        self.assertEqual(self.backend.store.draft(11)['message'], 'original draft')
        self.assertEqual(self.backend.auth_stage, 'disconnected')

    async def test_declined_keychain_removal_preserves_selected_and_other_files(self):
        second = self.backend.registry.create('Other account')
        root = self.backend.registry.root_for(second)
        marker = root / 'manager.sqlite3'
        marker.write_bytes(b'fixture database')
        with patch('telegram_manager.accounts.delete_profile_credentials', side_effect=KeychainError('declined')):
            with self.assertRaises(KeychainError):
                await self.call('accounts.remove', profile_id=second, confirmation=f'REMOVE {second}')
        self.assertEqual(marker.read_bytes(), b'fixture database')
        self.assertEqual(self.backend.registry.profile(second)['telegram_id'], None)
        self.assertTrue(self.session.exists())
        self.assertEqual(self.backend.store.draft(11)['message'], 'original draft')
