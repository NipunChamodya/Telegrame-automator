"""Explicit read-only client metadata, strict DTOs and derived-cache isolation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from telethon import functions, types

from telegram_manager.chat_store import ChatStore
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.storage import Store


class ClientFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'manager.sqlite3')
        self.backend = Backend(Path(self.temp.name), self.store, {'version': 1, 'account_id': 11})
        self.client = AsyncMock()
        self.client.is_connected = Mock(return_value=True)
        self.client.get_me.return_value = types.User(11)
        self.client.is_user_authorized.return_value = True
        self.client.get_entity.return_value = types.User(22, first_name='தமிழ்', phone='private-phone', access_hash=987654)
        self.client.get_input_entity.return_value = types.InputPeerUser(22, 987654)
        self.backend.client = self.client
        self.backend.service = object()
        self.backend.auth_stage = 'connected'

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def call(self, method, **p):
        return await self.backend.dispatch('fixture', method, p)

    async def refresh(self):
        self.client.return_value = types.contacts.Contacts([types.Contact(22, True)], 1,
            [types.User(22, first_name='தமிழ்', phone='private-phone', access_hash=987654, mutual_contact=True)])
        return await self.call('contacts.refresh', account_id=11)

    async def test_contacts_cached_privacy_unicode_and_membership_vector(self):
        self.client.return_value = types.contacts.Contacts([types.Contact(22, True)], 1,
            [types.User(22, first_name='தமிழ்', phone='private-phone', access_hash=987654), types.User(99, first_name='Not contact')])
        await self.call('contacts.refresh', account_id=11)
        self.client.reset_mock()
        result = await self.call('contacts.list', query='தமிழ்')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['contacts'][0]['id'], 22)
        self.assertNotIn('private-phone', json.dumps(result))
        self.assertNotIn('987654', json.dumps(result))
        self.client.assert_not_awaited()
        self.client.get_me.assert_not_awaited()
        self.assertEqual(self.backend.features.contacts(12)['total'], 0)

    async def test_refresh_caps_cache_and_reports_no_server_pagination(self):
        self.client.return_value = types.contacts.Contacts([types.Contact(i, False) for i in range(1001, 2002)], 1001,
            [types.User(i, first_name=str(i)) for i in range(1001, 2002)])
        result = await self.call('contacts.refresh', account_id=11)
        self.assertEqual(result['processed'], 1000)
        self.assertTrue(result['truncated'])
        self.assertEqual((await self.call('contacts.list', size=100))['total'], 1000)
        request = self.client.call_args.args[0]
        self.assertIsInstance(request, functions.contacts.GetContactsRequest)
        self.assertEqual(request.hash, 0)

    async def test_contacts_open_seeds_supported_dialog_and_never_sends(self):
        await self.refresh()
        row = (await self.call('contacts.open', account_id=11, user_id=22))['chat']
        self.assertEqual(row['id'], 22)
        self.assertTrue(row['content_available'])
        self.assertEqual(row['last_message'], '')
        self.assertIsNotNone(ChatStore(self.store).get(11, 22))
        with self.assertRaises(IPCError):
            await self.call('contacts.open', account_id=11, user_id=99)

    async def test_profile_only_cached_peer_and_allowlisted_full_user(self):
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=22)
        self.client.get_entity.assert_not_awaited()
        await self.refresh()
        full = types.UserFull(id=22, settings=types.PeerSettings(), notify_settings=types.PeerNotifySettings(),
                              common_chats_count=2, about='Hello සිංහල')
        self.client.return_value = types.users.UserFull(full, [], [])
        result = (await self.call('profile.get', account_id=11, peer_id=22))['profile']
        self.assertEqual(result['about'], 'Hello සිංහල')
        self.assertIsNone(result['members'])
        self.assertGreater(result['checked_at'], 0)
        self.assertNotIn('private-phone', json.dumps(result))
        self.assertNotIn('access_hash', json.dumps(result))

    async def test_wrong_profile_identity_and_wrong_account_blocked(self):
        await self.refresh()
        self.client.return_value = types.users.UserFull(types.UserFull(99, types.PeerSettings(), types.PeerNotifySettings(), 0), [], [])
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=22)
        with self.assertRaises(IPCError):
            await self.call('contacts.refresh', account_id=12)

    async def test_folder_source_actual_flags_peer_ids_and_no_remote_mutations(self):
        folder = types.DialogFilter(2, types.TextWithEntities('ශ්‍රී 👩🏽‍💻', []),
            [types.InputPeerUser(22, 987654)], [types.InputPeerSelf()], [types.InputPeerChannel(3, 123456)], groups=True, exclude_read=True)
        self.client.return_value = types.messages.DialogFilters([types.DialogFilterDefault(), folder])
        result = await self.call('folders.refresh', account_id=11)
        self.assertEqual(result['source'], 'telegram_read_only')
        self.assertFalse(result['membership_supported'])
        row = result['folders'][1]
        self.assertEqual(row['pinned_peer_ids'], [22])
        self.assertEqual(row['include_peer_ids'], [11])
        self.assertEqual(row['exclude_peer_ids'], [-1000000000003])
        self.assertTrue(row['groups'])
        self.assertTrue(row['exclude_read'])
        self.assertNotIn('987654', json.dumps(result))
        self.assertIsInstance(self.client.call_args.args[0], functions.messages.GetDialogFiltersRequest)
        self.client.reset_mock()
        self.assertEqual((await self.call('folders.list'))['folders'], result['folders'])
        self.client.assert_not_awaited()

    async def test_snapshot_refresh_preserves_other_account_and_delivery_ledger(self):
        await self.refresh()
        db = self.backend.features.database()
        with db:
            db.execute('INSERT INTO contact_cache VALUES (?,?,?,?)', (12, 99, 'Other', json.dumps({'id':99, 'name':'Other'})))
        self.store.reserve(11, 22, 'Original delivery')
        self.client.return_value = types.contacts.Contacts([], 0, [])
        await self.call('contacts.refresh', account_id=11)
        self.assertEqual(self.backend.features.contacts(11)['total'], 0)
        self.assertEqual(self.backend.features.contacts(12)['total'], 1)
        self.assertEqual(len(self.store.history(11)), 1)

    async def test_strict_parameters_no_import_contact_or_folder_mutation(self):
        for method, params in [('contacts.list', {'size':101}), ('contacts.refresh', {'account_id':True}),
                               ('folders.refresh', {'account_id':11, 'delete':True}), ('contacts.import', {'phone':'secret'})]:
            with self.subTest(method=method), self.assertRaises(IPCError):
                await self.call(method, **params)

    async def test_derived_cache_output_revalidates_scalar_allowlist(self):
        db = self.backend.features.database()
        contact = {'id':22, 'name':{'phone':'secret'}, 'phone':'secret', 'access_hash':987654,
                   'username':'safe', 'cached_at':{'token':'secret'}, 'content_available':{'secret':True}}
        folder = {'id':2, 'title':{'token':'secret'}, 'phone':'secret', 'include_peer_ids':[22, {'phone':'secret'}]}
        with db:
            db.execute('INSERT INTO contact_cache VALUES (?,?,?,?)', (11,22,'Fixture',json.dumps(contact)))
            db.execute('INSERT INTO telegram_folder_cache VALUES (?,?,?)', (11,2,json.dumps(folder)))
        self.assertNotIn('secret', json.dumps(await self.call('contacts.list')))
        self.assertNotIn('secret', json.dumps(await self.call('folders.list')))
        self.assertNotIn('access_hash', json.dumps(await self.call('contacts.list')))

    async def test_refresh_failure_and_unknown_full_constructor_preserve_cache(self):
        from types import SimpleNamespace
        await self.refresh()
        self.client.return_value = types.contacts.ContactsNotModified()
        with self.assertRaises(IPCError):
            await self.call('contacts.refresh', account_id=11)
        self.assertEqual((await self.call('contacts.list'))['total'], 1)
        self.client.return_value = SimpleNamespace(full_user=SimpleNamespace(id=22, about='unknown constructor body'))
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=22)

    async def test_basic_and_supergroup_profiles_use_full_metadata_without_participant_scan(self):
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc)
        basic = types.Chat(3, 'Basic', types.ChatPhotoEmpty(), 42, date, 1)
        basic_full = types.ChatFull(3, 'Basic about', types.ChatParticipantsForbidden(3), types.PeerNotifySettings())
        supergroup = types.Channel(4, 'Super', types.ChatPhotoEmpty(), date, megagroup=True)
        super_full = types.ChannelFull(4, 'Super about', 0, 0, 0, types.PhotoEmpty(1), types.PeerNotifySettings(), [], 0,
                                       participants_count=84)
        for entity, full, expected_count in [(basic, basic_full, 42), (supergroup, super_full, 84)]:
            from telethon import utils
            identity = utils.get_peer_id(entity)
            ChatStore(self.store).save(11, {'id':identity, 'name':entity.title, 'kind':'group'})
            self.client.get_entity.return_value = entity
            self.client.get_input_entity.return_value = types.InputPeerChannel(entity.id, 0)
            self.client.return_value = types.messages.ChatFull(full, [entity], [])
            result = await self.call('profile.get', account_id=11, peer_id=identity)
            self.assertEqual(result['profile']['members'], expected_count)
        self.client.iter_participants.assert_not_called()
