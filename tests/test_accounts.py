"""Multi-account profiles use isolated fixtures; no Telegram or real Keychain I/O."""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from telegram_manager.accounts import AccountRegistry, ProfileError
from telegram_manager.configuration import Credentials, bind_account, keychain_service, load_configuration
from telegram_manager.ipc import Backend, IPCError, ProtocolServer
from telegram_manager.models import Group
from telegram_manager.storage import Store


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.registry = AccountRegistry(self.root, {'version': 1, 'account_id': 11})

    def tearDown(self):
        self.directory.cleanup()

    def test_registry_is_private_stable_and_never_uses_phone_paths(self):
        identity = self.registry.create('தமிழ் ශ්‍රී 👩🏽‍💻')
        root = self.registry.root_for(identity)
        self.assertEqual(root.parent, self.root / 'profiles')
        self.assertRegex(identity, r'^profile_[0-9a-f]{32}$')
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.registry.path.stat().st_mode & 0o777, 0o600)
        self.registry.verify(identity, 22, 'Second account')
        self.assertEqual(self.registry.root_for(identity), root)
        self.assertNotEqual(keychain_service(root), keychain_service(self.root))
        reloaded = AccountRegistry(self.root, {'version': 1, 'account_id': 11})
        self.assertEqual(reloaded.profile(identity)['telegram_id'], 22)
        self.assertEqual(reloaded.root_for('legacy'), self.root)

    def test_duplicate_verified_accounts_include_archived_profiles(self):
        identity = self.registry.create('Second')
        self.registry.verify(identity, 22, 'Second')
        self.registry.update(identity, archived=True)
        another = self.registry.create('Third')
        with self.assertRaises(ProfileError):
            self.registry.verify(another, 22, 'Duplicate')
        with self.assertRaises(ProfileError):
            self.registry.verify(another, 11, 'Duplicate original')
        self.assertIsNone(self.registry.profile(another)['telegram_id'])

    def test_paths_symlinks_hardlinks_and_fifo_registry_are_rejected(self):
        for identity in ('../other', '/tmp/unrelated', 'profile_../../secret'):
            with self.assertRaises(ProfileError):
                self.registry.root_for(identity)
        identity = self.registry.create('Second')
        root = self.registry.root_for(identity)
        outside = self.root / 'outside.txt'
        outside.write_text('preserve')
        (root / 'link').symlink_to(outside)
        with patch('telegram_manager.accounts.delete_profile_credentials') as keychain:
            with self.assertRaises(ProfileError):
                self.registry.remove_files(identity)
        keychain.assert_not_called()
        self.assertEqual(outside.read_text(), 'preserve')
        (root / 'link').unlink()
        os.link(outside, root / 'hardlink')
        with self.assertRaises(ProfileError):
            self.registry.remove_files(identity)
        self.registry.path.unlink()
        os.mkfifo(self.registry.path)
        with self.assertRaises(ProfileError):
            AccountRegistry(self.root, {'version': 1, 'account_id': 11})

    def test_invalid_registry_and_external_edits_are_not_reset(self):
        original = self.registry.path.read_bytes()
        self.registry.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ProfileError):
            AccountRegistry(self.root, {'version': 1, 'account_id': 11})
        self.assertEqual(self.registry.path.read_text(), '{broken')
        self.registry.path.write_bytes(original)
        altered = json.loads(original)
        altered['profiles'][0]['label'] = 'External edit'
        self.registry.path.write_text(json.dumps(altered), encoding='utf-8')
        with self.assertRaises(ProfileError):
            self.registry.activate('legacy')
        self.assertEqual(json.loads(self.registry.path.read_text())['profiles'][0]['label'], 'External edit')


class ProfileBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = load_configuration(self.root)
        bind_account(self.root, self.config, 11)
        self.store = Store(self.root / 'manager.sqlite3')
        self.store.save_group(11, Group(-1, 'Original', 'group'))
        self.store.save_draft(11, 'original draft')
        self.store.reserve(11, -1, 'original delivery')
        self.store.set_cooldown(11, 9999999999)
        self.session = self.root / 'account.session'
        self.session.write_bytes(b'opaque legacy session fixture')
        self.legacy_config = (self.root / 'config.json').read_bytes()
        self.backend = Backend(self.root, self.store, self.config)

    async def asyncTearDown(self):
        await self.backend.close()
        self.backend.store.close()
        self.directory.cleanup()

    async def call(self, method, **params):
        return await self.backend.dispatch('profile-test', method, params)

    async def add(self):
        result = await self.call('accounts.add', label='Second account', confirm=True)
        return result['created_profile_id']

    async def test_switch_preserves_legacy_state_and_isolates_new_database(self):
        self.backend.preview_tokens['old'] = {'account': 11}
        self.backend.credentials = Credentials(123, 'a' * 32)
        self.backend.phone = 'never persisted phone fixture'
        identity = await self.add()
        self.assertEqual(self.backend.profile_id, identity)
        self.assertEqual(self.backend.preview_tokens, {})
        self.assertIsNone(self.backend.credentials)
        self.assertIsNone(self.backend.phone)
        self.assertIsNone(self.backend.me)
        self.assertEqual(self.backend.config['account_id'], None)
        self.assertEqual(self.backend.store.groups(11), [])
        bind_account(self.backend.root, self.backend.config, 22)
        self.backend.registry.verify(identity, 22, 'Second')
        self.backend.store.save_draft(22, 'second draft')
        self.backend.store.save_group(22, Group(-2, 'Second group', 'group'))
        self.backend.store.set_cooldown(22, 88)
        await self.call('accounts.switch', profile_id='legacy', confirm=True)
        self.assertEqual((await self.call('draft.get'))['message'], 'original draft')
        self.assertEqual(len((await self.call('groups'))['groups']), 1)
        self.assertEqual(self.backend.store.cooldown(11), 9999999999)
        self.assertEqual(len(self.backend.store.history(11)), 1)
        self.assertEqual(self.session.read_bytes(), b'opaque legacy session fixture')
        self.assertEqual((self.root / 'config.json').read_bytes(), self.legacy_config)
        await self.call('accounts.switch', profile_id=identity, confirm=True)
        self.assertEqual((await self.call('draft.get'))['message'], 'second draft')
        self.assertEqual(self.backend.store.cooldown(22), 88)

    async def test_restart_uses_registry_active_profile_and_never_recreates_missing_bound_database(self):
        identity = await self.add()
        root = self.backend.root
        bind_account(root, self.backend.config, 22)
        self.backend.registry.verify(identity, 22, 'Second')
        self.backend.store.save_draft(22, 'kept')
        await self.call('accounts.switch', profile_id='legacy', confirm=True)
        (root / 'manager.sqlite3').unlink()
        with self.assertRaises(IPCError) as caught:
            await self.call('accounts.switch', profile_id=identity, confirm=True)
        self.assertEqual(caught.exception.code, 'database_missing')
        self.assertEqual(self.backend.profile_id, 'legacy')
        self.assertFalse((root / 'manager.sqlite3').exists())

    async def test_old_profile_preview_cannot_be_used_after_switch_or_switch_back(self):
        self.backend.preview_tokens['secret-preview'] = {'account': 11, 'destination': -1,
            'message': 'must not send', 'deadline': 9999999999, **self.backend.scope()}
        identity = await self.add()
        with self.assertRaises(IPCError):
            await self.call('send', token='secret-preview', confirmation='SEND -1')
        await self.call('accounts.switch', profile_id='legacy', confirm=True)
        with self.assertRaises(IPCError):
            await self.call('send', token='secret-preview', confirmation='SEND -1')
        self.assertTrue(self.session.exists())

    async def test_protocol_captures_generation_when_request_is_accepted(self):
        identity = self.backend.registry.create('Second')
        server = ProtocolServer(self.backend, lambda data: None)
        await self.backend.lock.acquire()
        await server.accept(json.dumps({'id': 'switch', 'method': 'accounts.switch',
            'params': {'profile_id': identity, 'confirm': True}}).encode())
        await server.accept(json.dumps({'id': 'old-draft', 'method': 'draft.save',
            'params': {'message': 'old account unsaved text'}}).encode())
        jobs = tuple(server.tasks.values())
        self.backend.lock.release()
        await asyncio.gather(*jobs)
        responses = [server.queue.get_nowait(), server.queue.get_nowait()]
        old = next(response for response in responses if response['id'] == 'old-draft')
        self.assertFalse(old['ok'])
        self.assertEqual(old['error']['code'], 'account_changed')
        self.assertEqual(self.backend.store.draft(11)['message'], '')

    async def test_logout_is_explicit_preserves_files_and_marks_unknown_transport_outcome(self):
        self.backend.client = AsyncMock()
        self.backend.client.is_connected = Mock(return_value=True)
        self.backend.client.get_me.return_value = NS(id=11)
        self.backend.client.side_effect = ConnectionError('private-network-details')
        with self.assertRaises(ConnectionError):
            await self.call('accounts.logout', profile_id='legacy', confirmation='LOG OUT legacy')
        self.assertEqual(self.backend.registry.profile('legacy')['session_state'], 'logout_unknown')
        self.assertEqual(self.backend.preview_tokens, {})
        self.assertTrue(self.session.exists())
        self.assertEqual((self.root / 'config.json').read_bytes(), self.legacy_config)

    async def test_logout_revalidates_live_identity_before_revocation(self):
        client = AsyncMock()
        client.is_connected = Mock(return_value=True)
        client.get_me.return_value = NS(id=99)
        self.backend.client = client
        with self.assertRaises(IPCError) as caught:
            await self.call('accounts.logout', profile_id='legacy', confirmation='LOG OUT legacy')
        self.assertEqual(caught.exception.code, 'account_changed')
        client.assert_not_awaited()
        self.assertEqual(self.session.read_bytes(), b'opaque legacy session fixture')

    async def test_remove_is_explicitly_scoped_and_preserves_other_profile_data(self):
        identity = await self.add()
        selected_root = self.backend.root
        (selected_root / 'account.session').write_bytes(b'selected fixture')
        with self.assertRaises(IPCError):
            await self.call('accounts.remove', profile_id=identity, confirmation='REMOVE all')
        self.assertTrue(selected_root.exists())
        with patch('telegram_manager.accounts.delete_profile_credentials', return_value=False) as keychain:
            result = await self.call('accounts.remove', profile_id=identity, confirmation=f'REMOVE {identity}')
        keychain.assert_called_once_with(selected_root)
        self.assertFalse(selected_root.exists())
        self.assertEqual(result['active_profile_id'], 'legacy')
        self.assertEqual(self.session.read_bytes(), b'opaque legacy session fixture')
        self.assertEqual((await self.call('draft.get'))['message'], 'original draft')
        self.assertEqual((self.root / 'config.json').read_bytes(), self.legacy_config)
