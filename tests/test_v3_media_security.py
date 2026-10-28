"""M4 adversarial privacy/cache tests; all Telegram and file data are synthetic."""
import asyncio
import base64
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telethon import types

from telegram_manager.chat_store import ChatStore
from telegram_manager.client_features import ClientFeatures
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.media_preview import MediaPreview
from telegram_manager.storage import Store

DATE = datetime(2026, 10, 28, tzinfo=timezone.utc)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=')
PHONE = 'PRIVATE_PHONE_FIXTURE'
HASH = 9876543212345


def image_message(identity=7, peer=22, size=None, mime='image/png', **changes):
    document = types.Document(id=1, access_hash=HASH, file_reference=b'private-reference', date=DATE,
                              mime_type=mime, size=len(PNG) if size is None else size, dc_id=1,
                              attributes=[types.DocumentAttributeFilename('fixture.png')])
    fields = {'id': identity, 'peer_id': types.PeerUser(peer), 'from_id': types.PeerUser(peer),
              'date': DATE, 'message': 'Synthetic caption', 'media': types.MessageMediaDocument(document=document)}
    return types.Message(**(fields | changes))


class TemporaryBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'manager.sqlite3')
        self.backend = Backend(self.root, self.store, {'version': 1, 'account_id': 11})
        self.backend.service = object()
        self.backend.auth_stage = 'connected'
        self.client = AsyncMock()
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = types.User(11)
        self.client.get_entity.return_value = types.User(22)
        self.client.get_input_entity.return_value = types.InputPeerUser(22, HASH)
        self.backend.client = self.client
        self.cache = ChatStore(self.store)
        self.cache.save(11, {'id': 22, 'name': 'Synthetic peer', 'kind': 'private',
                             'content_known': True, 'content_available': True})
        self.session = self.root / 'account.session'
        self.session.write_bytes(b'opaque synthetic session fixture')

    async def asyncTearDown(self):
        await self.backend.close()
        self.store.close()
        self.temp.cleanup()


class MediaPreviewSecurityTests(TemporaryBackendTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.preview = MediaPreview(self.backend)
        self.payload = PNG
        async def download(message, file, **kwargs):
            return file.write(self.payload)
        self.client.download_media.side_effect = download
        self.client.get_messages.return_value = image_message()

    async def asyncTearDown(self):
        self.preview.close()
        await super().asyncTearDown()

    async def get(self, identity=7, **changes):
        return await self.preview.dispatch('qa-image', 'media.preview.get',
                                          {'account_id': 11, 'destination': 22, 'message_id': identity} | changes)

    async def test_private_preview_release_never_touches_session_or_database(self):
        result = await self.get()
        path = Path(result['path'])
        self.assertEqual(path.read_bytes(), PNG)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.parent, self.root / 'image-preview-cache')
        self.assertNotIn(PHONE, json.dumps(result))
        self.assertNotIn(str(HASH), json.dumps(result))
        released = await self.preview.dispatch('release', 'media.preview.release', {'account_id': 11, 'token': result['token']})
        self.assertTrue(released['released'])
        self.assertFalse(path.exists())
        self.assertTrue((self.root / 'manager.sqlite3').exists())
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')

    async def test_wrong_account_generation_and_token_cannot_release_another_preview(self):
        result = await self.get()
        path = Path(result['path'])
        with self.assertRaises(IPCError):
            await self.preview.dispatch('release', 'media.preview.release', {'account_id': 12, 'token': result['token']})
        self.backend.account_generation += 1
        response = await self.preview.dispatch('release', 'media.preview.release', {'account_id': 11, 'token': result['token']})
        self.assertFalse(response['released'])
        self.assertTrue(path.exists())
        self.backend.account_generation -= 1

    async def test_wrong_peer_ttl_and_protected_media_fail_before_creating_files(self):
        for value in [image_message(peer=23), image_message(ttl_period=10), image_message(noforwards=True),
                      image_message(restriction_reason=[types.RestrictionReason('all', 'sensitive', 'fixture')])]:
            self.client.get_messages.return_value = value
            with self.subTest(message=value.to_dict()), self.assertRaises(IPCError):
                await self.get()
        self.client.get_entity.return_value = types.User(22, bot=True)
        with self.assertRaises(IPCError):
            await self.get()
        self.client.download_media.assert_not_awaited()
        self.assertFalse((self.root / 'image-preview-cache').exists())

    async def test_declared_format_size_and_signature_gates(self):
        for value in [image_message(size=8 * 1024 * 1024 + 1), image_message(size=True),
                      image_message(mime='image/gif'), image_message(mime='image/svg+xml')]:
            self.client.get_messages.return_value = value
            with self.subTest(mime=value.file.mime_type, size=value.file.size), self.assertRaises(IPCError):
                await self.get()
        self.client.download_media.assert_not_awaited()
        self.payload = b'not-a-png-image'
        self.client.get_messages.return_value = image_message(size=len(self.payload))
        with self.assertRaises(IPCError):
            await self.get()
        self.assertEqual(list((self.root / 'image-preview-cache').glob('preview_*')), [])

    async def test_oversized_incomplete_and_cancelled_streams_leave_no_preview(self):
        for mode in ('oversized', 'incomplete', 'cancelled'):
            async def download(message, file, **kwargs):
                if mode == 'oversized':
                    file.write(PNG + b'extra')
                else:
                    file.write(PNG[:8])
                    if mode == 'cancelled':
                        raise asyncio.CancelledError()
            self.client.download_media.side_effect = download
            with self.subTest(mode=mode), self.assertRaises(asyncio.CancelledError if mode == 'cancelled' else IPCError):
                await self.get()
            self.assertEqual(list((self.root / 'image-preview-cache').glob('preview_*')), [])
            self.assertEqual(self.preview.entries, {})
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')

    async def test_cache_bound_and_lazy_expiry_only_remove_owned_previews(self):
        paths = []
        for identity in range(1, 6):
            self.client.get_messages.return_value = image_message(identity=identity)
            paths.append(Path((await self.get(identity))['path']))
        self.assertFalse(paths[0].exists())
        existing = [path for path in paths if path.exists()]
        self.assertEqual(len(existing), 4)
        self.assertLessEqual(sum(path.stat().st_size for path in existing), 32 * 1024 * 1024)
        marker = existing[0].parent / 'unrelated-note.txt'
        marker.write_text('preserve this', encoding='utf-8')
        for entry in self.preview.entries.values():
            entry['created'] = time.time() - self.preview.TTL - 1
        self.preview.cache()
        self.assertTrue(all(not path.exists() for path in existing))
        self.assertEqual(marker.read_text(), 'preserve this')
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')

    async def test_crash_index_recovers_only_recorded_inode_and_refuses_replacements(self):
        result = await self.get()
        path = Path(result['path'])
        index = json.loads((path.parent / 'index.json').read_text())
        self.assertEqual(set(index), {'version', 'entries'})
        self.assertEqual(set(index['entries'][0]), {'name', 'device', 'inode'})
        recovered = MediaPreview(self.backend)
        recovered.cache()
        self.assertFalse(path.exists())
        recovered.close()
        # A filename alone never authorizes deletion of its replacement inode.
        self.preview.close()
        result = await self.get()
        path = Path(result['path'])
        replacement = path.parent / 'user-file.txt'
        replacement.write_bytes(b'unrelated replacement')
        os.replace(replacement, path)
        other = MediaPreview(self.backend)
        with self.assertRaises(IPCError):
            other.cache()
        self.assertEqual(path.read_bytes(), b'unrelated replacement')
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')

    async def test_index_reservation_failure_closes_descriptor_and_cleans_owned_file(self):
        original = self.preview.write_index
        real_open = os.open
        descriptors = []
        def capture(path, flags, *args, **kwargs):
            result = real_open(path, flags, *args, **kwargs)
            if Path(path).name.startswith('preview_') and flags & os.O_CREAT:
                descriptors.append(result)
            return result
        def fail_pending(pending=None):
            if pending is not None or self.preview.pending:
                raise OSError('synthetic index failure')
            return original()
        with patch('telegram_manager.media_preview.os.open', side_effect=capture), patch.object(self.preview, 'write_index', side_effect=fail_pending):
            with self.assertRaises(OSError):
                await self.get()
        self.assertEqual(len(descriptors), 1)
        opened = False
        try:
            os.fstat(descriptors[0]); opened = True
        except OSError:
            pass
        finally:
            if opened:
                os.close(descriptors[0])
        self.assertFalse(opened, 'Failed index reservation must not leak a file descriptor')
        self.assertEqual(list((self.root / 'image-preview-cache').glob('preview_*')), [])

    async def test_malicious_index_path_and_hardlink_cannot_remove_session(self):
        directory = self.root / 'image-preview-cache'
        directory.mkdir(mode=0o700)
        info = self.session.stat()
        index = directory / 'index.json'
        index.write_text(json.dumps({'version': 1, 'entries': [{'name': '../account.session', 'device': info.st_dev, 'inode': info.st_ino}]}))
        with self.assertRaises(IPCError):
            self.preview.cache()
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')
        linked = directory / ('preview_' + 'a' * 32 + '.png')
        os.link(self.session, linked)
        index.write_text(json.dumps({'version': 1, 'entries': [{'name': linked.name, 'device': info.st_dev, 'inode': info.st_ino}]}))
        with self.assertRaises((IPCError, ValueError)):
            self.preview.cache()
        self.assertTrue(linked.exists())
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')

    async def test_invalidation_clears_open_preview_and_cancels_pending_download(self):
        result = await self.get()
        path = Path(result['path'])
        self.preview.invalidate(22, [7])
        self.assertFalse(path.exists())
        self.assertNotIn(result['token'], self.preview.entries)
        async def invalidated_download(message, file, **kwargs):
            file.write(PNG[:8])
            self.preview.invalidate(22, [7])
            file.write(PNG[8:])
        self.client.download_media.side_effect = invalidated_download
        with self.assertRaises(IPCError) as caught:
            await self.get()
        self.assertEqual(caught.exception.code, 'preview_invalidated')
        self.assertEqual(self.preview.entries, {})
        self.assertEqual(self.preview.pending, {})
        self.assertEqual(list((self.root / 'image-preview-cache').glob('preview_*')), [])
        self.assertEqual(self.session.read_bytes(), b'opaque synthetic session fixture')


class ClientReadPrivacySecurityTests(TemporaryBackendTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.features = ClientFeatures(self.backend)

    async def call(self, method, **params):
        return await self.features.dispatch('qa-client-read', method, params)

    def assert_no_secrets(self, data):
        text = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(PHONE, text)
        self.assertNotIn(str(HASH), text)
        for name in ('phone', 'access_hash', 'auth_key', 'session', 'file_reference'):
            self.assertNotIn('"' + name + '"', text)

    async def test_contacts_vector_membership_and_dto_allowlist_exclude_extra_users(self):
        actual = types.User(22, first_name='සිංහල தமிழ் 👩🏽‍💻', phone=PHONE, access_hash=HASH)
        unrelated = types.User(23, first_name='Unrelated', phone=PHONE, access_hash=HASH, contact=True)
        self.client.return_value = types.contacts.Contacts([types.Contact(22, False)], 2, [unrelated, actual])
        result = await self.call('contacts.refresh', account_id=11)
        self.assertEqual(result['processed'], 1)
        cached = await self.call('contacts.list')
        self.assertEqual([row['id'] for row in cached['contacts']], [22])
        self.assertEqual(cached['contacts'][0]['name'], 'සිංහල தமிழ் 👩🏽‍💻')
        self.assert_no_secrets(cached)
        for row in self.store.db.execute('SELECT data FROM contact_cache'):
            self.assert_no_secrets(json.loads(row[0]))
        self.client.reset_mock()
        await self.call('contacts.list', query='தமிழ்')
        self.client.assert_not_awaited()
        self.client.get_me.assert_not_awaited()

    async def test_contacts_cap_is_projection_limit_and_preserves_other_account(self):
        users = [types.User(identity, first_name='Fixture', phone=PHONE, access_hash=HASH) for identity in range(100, 1105)]
        self.client.return_value = types.contacts.Contacts([types.Contact(user.id, False) for user in users], len(users), users)
        db = self.features.database()
        db.execute('INSERT INTO contact_cache VALUES (?,?,?,?)', (12, 99, 'Other account', json.dumps({'id': 99, 'name': 'Other account'})))
        result = await self.call('contacts.refresh', account_id=11)
        self.assertEqual(result['processed'], 1000)
        self.assertTrue(result['truncated'])
        self.assertEqual((await self.call('contacts.list', size=100))['total'], 1000)
        self.assertEqual(len((await self.call('contacts.list', size=100))['contacts']), 100)
        self.assertEqual(db.execute('SELECT count(*) FROM contact_cache WHERE account=12').fetchone()[0], 1)
        request = self.client.await_args.args[0]
        self.assertEqual(type(request).__name__, 'GetContactsRequest')
        self.assertEqual(request.hash, 0)

    async def test_incomplete_contact_snapshot_preserves_cache(self):
        db = self.features.database()
        db.execute('INSERT INTO contact_cache VALUES (?,?,?,?)', (11, 22, 'Known', json.dumps({'id': 22, 'name': 'Known'})))
        self.client.return_value = types.contacts.ContactsNotModified()
        with self.assertRaises(IPCError):
            await self.call('contacts.refresh', account_id=11)
        self.assertEqual((await self.call('contacts.list'))['contacts'][0]['id'], 22)

    async def test_profile_arbitrary_lookup_and_wrong_account_refused_before_entity_request(self):
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=999)
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=12, peer_id=22)
        self.client.get_entity.assert_not_awaited()
        self.client.assert_not_awaited()

    async def test_profile_full_identity_and_dto_are_verified(self):
        selected = types.User(22, first_name='Selected', phone=PHONE, access_hash=HASH)
        self.client.get_entity.return_value = selected
        full = types.UserFull(id=22, settings=types.PeerSettings(), notify_settings=types.PeerNotifySettings(), common_chats_count=0, about='Public synthetic profile')
        self.client.return_value = types.users.UserFull(full_user=full, chats=[], users=[selected, types.User(23, phone=PHONE, access_hash=HASH)])
        result = await self.call('profile.get', account_id=11, peer_id=22)
        self.assertEqual(result['profile']['id'], 22)
        self.assertEqual(result['profile']['about'], 'Public synthetic profile')
        self.assertIsNone(result['profile']['members'])
        self.assert_no_secrets(result)
        full.id = 23
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=22)
        self.client.return_value = NS(full_user=NS(id=22, about=PHONE))
        with self.assertRaises(IPCError):
            await self.call('profile.get', account_id=11, peer_id=22)

    async def test_folder_metadata_is_read_only_bounded_and_strips_peer_hashes(self):
        folder = types.DialogFilter(id=3, title=types.TextWithEntities('සිංහල தமிழ்', []),
                                    pinned_peers=[types.InputPeerUser(22, HASH)],
                                    include_peers=[types.InputPeerSelf(), types.InputPeerChannel(33, HASH)],
                                    exclude_peers=[types.InputPeerUser(23, HASH)], groups=True)
        self.client.return_value = types.messages.DialogFilters(filters=[types.DialogFilterDefault(), folder])
        result = await self.call('folders.refresh', account_id=11)
        self.assertEqual(result['source'], 'telegram_read_only')
        self.assertFalse(result['membership_supported'])
        self.assertEqual(result['folders'][1]['pinned_peer_ids'], [22])
        self.assert_no_secrets(result)
        self.assertEqual(type(self.client.await_args.args[0]).__name__, 'GetDialogFiltersRequest')
        self.client.reset_mock()
        await self.call('folders.list')
        self.client.assert_not_awaited()
        with self.assertRaises(IPCError):
            await self.call('folders.update', account_id=11)

    async def test_cached_nested_sensitive_fields_are_not_serialized(self):
        db = self.features.database()
        db.execute('INSERT INTO contact_cache VALUES (?,?,?,?)', (11, 22, 'Known', json.dumps({'id': 22, 'name': 'Known', 'phone': PHONE, 'access_hash': HASH, 'mutual': {'session': PHONE}})))
        db.execute('INSERT INTO telegram_folder_cache VALUES (?,?,?)', (11, 1, json.dumps({'id': 1, 'title': 'Known', 'pinned_peer_ids': [{'access_hash': HASH}], 'groups': {'session': PHONE}, 'phone': PHONE})))
        self.assert_no_secrets(await self.call('contacts.list'))
        self.assert_no_secrets(await self.call('folders.list'))
