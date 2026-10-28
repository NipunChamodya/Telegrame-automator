"""M2 adversarial regressions. Synthetic TL objects and mocked network only."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from telethon import types

from telegram_manager.chat_store import ChatStore
from telegram_manager.content_policy import classify_entity, project_dialog
from telegram_manager.ipc import Backend, IPCError, ProtocolServer
from telegram_manager.message_projection import normalize_message
from telegram_manager.storage import Store
from telegram_manager.update_pipeline import UpdatePipeline

DATE = datetime(2026, 10, 28, tzinfo=timezone.utc)
SECRET = 'sensitive fixture body — සිංහල தமிழ் 👩🏽‍💻'


def message(identity=1, peer=22, **extra):
    return types.Message(id=identity, peer_id=types.PeerUser(peer), date=DATE,
                         message=SECRET, **extra)


class ContentProjectionSecurityTests(unittest.TestCase):
    def assert_hidden(self, value):
        projected = normalize_message(value)
        self.assertFalse(projected['content_available'])
        self.assertEqual(projected['text'], '')
        self.assertIsNone(projected['media'])
        self.assertNotIn(SECRET, str(projected))

    def test_ephemeral_and_protected_body_never_projected(self):
        for value in [message(ttl_period=30), message(noforwards=True),
                      message(media=types.MessageMediaPhoto(photo=types.PhotoEmpty(1), ttl_seconds=5))]:
            with self.subTest(kind=type(value.media).__name__ if value.media else 'text'):
                self.assert_hidden(value)

    def test_restricted_and_unknown_messages_fail_closed(self):
        for value in [NS(id=1, message=SECRET),
                      message(restriction_reason=[types.RestrictionReason('all', 'sensitive', 'fixture')]),
                      message(media=types.MessageMediaUnsupported())]:
            with self.subTest(kind=type(value).__name__):
                self.assert_hidden(value)

    def test_known_unicode_text_remains_unchanged(self):
        value = normalize_message(message())
        self.assertTrue(value['content_available'])
        self.assertEqual(value['text'], SECRET)

    def test_bots_channels_unknown_and_protected_entities_fail_closed(self):
        entities = [types.User(22, bot=True), types.User(22, restricted=True), NS(id=22),
                    types.Channel(33, 'channel', types.ChatPhotoEmpty(), DATE, broadcast=True),
                    types.Channel(33, 'protected group', types.ChatPhotoEmpty(), DATE, megagroup=True, noforwards=True)]
        for entity in entities:
            with self.subTest(entity=type(entity).__name__):
                self.assertFalse(classify_entity(entity, 11)['content_available'])
        self.assertTrue(classify_entity(types.User(22), 11)['content_available'])

    def test_legacy_or_channel_preview_never_leaks_from_cache(self):
        for flags in [{}, {'kind': 'channel', 'content_known': True, 'content_available': True},
                      {'kind': 'private', 'is_bot': True, 'content_known': True, 'content_available': True}]:
            row = {'id': 22, 'kind': 'private', 'last_message': SECRET} | flags
            projected = project_dialog(row)
            self.assertFalse(projected['content_available'])
            self.assertEqual(projected['last_message'], '')
            self.assertEqual(row['last_message'], SECRET, 'Projection must not mutate caller state')


class UpdateSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'manager.sqlite3')
        self.backend = Backend(self.root, self.store, {'version': 1, 'account_id': 11})
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.remove_event_handler = Mock()
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = types.User(11, first_name='Account')
        self.client.get_entity.return_value = types.User(22, first_name='Friend')
        self.client.get_input_entity.return_value = types.InputPeerUser(22, 0)
        self.backend.client = self.client
        self.backend.service = object()
        self.backend.auth_stage = 'connected'
        self.events = []
        self.backend.emit_control = self.events.append
        self.cache = ChatStore(self.store)
        for peer in (22, 23):
            self.cache.save(11, {'id': peer, 'name': 'Synthetic peer', 'kind': 'private',
                                'content_known': True, 'content_available': True,
                                'last_message': '', 'last_message_id': 0})
        self.pipeline = UpdatePipeline(self.backend)
        self.pipeline.watching = True
        self.pipeline.peer_id = 22
        self.pipeline.dirty = False

    async def asyncTearDown(self):
        await self.pipeline.stop()
        await self.backend.close()
        self.store.close()
        self.temp.cleanup()

    async def call(self, method, **params):
        return await self.pipeline.dispatch('qa-v3', method, {'account_id': 11} | params)

    async def test_stale_generation_and_replaced_client_emit_nothing(self):
        self.backend.account_generation += 1
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        self.assertTrue(self.pipeline.queue.empty())
        self.assertEqual(self.events, [])
        with self.assertRaises(IPCError):
            await self.call('messages.read', peer_id=22, max_id=1)
        self.client.send_read_acknowledge.assert_not_awaited()
        self.backend.account_generation -= 1
        self.backend.client = AsyncMock()
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        self.assertTrue(self.pipeline.queue.empty())
        self.assertEqual(self.events, [])

    async def test_wrong_account_and_peer_read_blocked_before_network(self):
        self.pipeline.record_visible(22, [{'id': 3, 'outgoing': False, 'content_available': True}])
        with self.assertRaises(IPCError):
            await self.pipeline.dispatch('wrong-account', 'messages.read', {'account_id': 12, 'peer_id': 22, 'max_id': 3})
        with self.assertRaises(IPCError):
            await self.call('messages.read', peer_id=23, max_id=3)
        self.client.send_read_acknowledge.assert_not_awaited()

    async def test_read_frontier_contains_only_returned_incoming_supported_ids(self):
        self.pipeline.record_visible(22, [{'id': 3, 'outgoing': False, 'content_available': True},
                                          {'id': 7, 'outgoing': True, 'content_available': True},
                                          {'id': 9, 'outgoing': False, 'content_available': False}])
        for identity in (2, 4, 7, 9, 500):
            with self.subTest(identity=identity), self.assertRaises(IPCError):
                await self.call('messages.read', peer_id=22, max_id=identity)
        self.client.send_read_acknowledge.assert_not_awaited()
        await self.call('messages.read', peer_id=22, max_id=3)
        self.assertEqual(self.client.send_read_acknowledge.await_args.kwargs, {'max_id': 3})
        self.assertEqual(self.pipeline.read_max, 3)

    async def test_ambiguous_delete_marks_dirty_without_deleting_selected_message(self):
        self.pipeline.messages[(22, 1)] = normalize_message(message())
        await self.pipeline.ingest('delete', NS(chat_id=None, deleted_ids=[1]))
        self.assertIn((22, 1), self.pipeline.messages)
        self.assertTrue(self.pipeline.dirty)
        self.assertEqual(self.events[-1]['event'], 'sync.required')
        self.assertEqual(self.events[-1]['data']['reason'], 'ambiguous_delete')

    async def test_queue_overflow_requires_resync_instead_of_silently_losing_delete(self):
        for identity in range(self.pipeline.CAPACITY):
            await self.pipeline.ingest('new', NS(chat_id=22, message=message(identity + 1)))
        self.assertEqual(self.pipeline.queue.qsize(), self.pipeline.CAPACITY)
        await self.pipeline.ingest('delete', NS(chat_id=22, deleted_ids=[1]))
        self.assertTrue(self.pipeline.dirty)
        self.assertTrue(any(e['event'] == 'sync.required' and e['data']['reason'] == 'overflow' for e in self.events))
        self.assertLessEqual(self.pipeline.queue.qsize(), self.pipeline.CAPACITY)

    async def test_peer_change_resets_visible_frontier(self):
        self.pipeline.record_visible(22, [{'id': 3, 'outgoing': False, 'content_available': True}])
        self.client.get_entity.return_value = types.User(23)
        await self.call('updates.watch', peer_id=23)
        self.assertEqual(self.pipeline.visible, set())
        with self.assertRaises(IPCError):
            await self.call('messages.read', peer_id=23, max_id=3)
        self.client.send_read_acknowledge.assert_not_awaited()

    async def test_stopping_removes_handlers_and_private_message_memory(self):
        await self.pipeline.start()
        self.pipeline.messages[(22, 1)] = normalize_message(message())
        await self.pipeline.stop()
        self.assertEqual(self.client.remove_event_handler.call_count, 5)
        self.assertEqual(self.pipeline.messages, {})
        self.assertEqual(self.pipeline.visible, set())
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        self.assertTrue(self.pipeline.queue.empty())

    async def test_unavailable_cached_peer_never_exposes_event_body(self):
        self.cache.save(11, {'id': 22, 'name': 'unknown', 'kind': 'private', 'last_message': ''})
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        self.assertTrue(self.pipeline.queue.empty())
        self.assertNotIn(SECRET, str(self.events))
        self.assertTrue(self.pipeline.dirty)

    async def test_presence_event_does_not_invent_typing(self):
        await self.pipeline.ingest('typing', NS(chat_id=22, user_id=22, typing=False, cancel=False, online=True))
        self.assertTrue(self.pipeline.queue.empty())
        self.assertEqual(self.events, [])

    async def test_deleted_message_not_resurrected_by_delayed_edit(self):
        await self.pipeline.start()
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        await self.pipeline.ingest('delete', NS(chat_id=22, deleted_ids=[1]))
        await self.pipeline.ingest('edit', NS(chat_id=22, message=message(edit_date=DATE + timedelta(seconds=1))))
        await asyncio.wait_for(self.pipeline.queue.join(), timeout=2)
        self.assertNotIn((22, 1), self.pipeline.messages)
        self.assertNotEqual(self.cache.get(11, 22).get('last_message'), SECRET)

    async def test_older_update_cannot_overwrite_newer_edit(self):
        await self.pipeline.start()
        newer = message(edit_date=DATE + timedelta(seconds=10))
        newer.message = 'newer authoritative text'
        await self.pipeline.ingest('edit', NS(chat_id=22, message=newer))
        await self.pipeline.ingest('new', NS(chat_id=22, message=message()))
        await asyncio.wait_for(self.pipeline.queue.join(), timeout=2)
        self.assertEqual(self.pipeline.messages[(22, 1)]['text'], 'newer authoritative text')

    async def test_control_transport_overflow_disconnects_instead_of_dropping_delete(self):
        server = ProtocolServer(self.backend, lambda data: None)
        for index in range(server.queue.maxsize):
            server.progress({'event': 'progress', 'data': {'index': index}})
        server.control({'event': 'message.deleted', 'data': {'peer_id': 22, 'message_ids': [1]}})
        self.assertTrue(server.failed.is_set())
        self.assertFalse(server.output_available)
        self.assertEqual(server.queue.qsize(), server.queue.maxsize)

    async def test_live_channel_bot_and_protected_peer_block_all_content_routes(self):
        entities = [types.User(22, bot=True), types.User(22, restricted=True)]
        channel = types.Channel(33, 'broadcast', types.ChatPhotoEmpty(), DATE, broadcast=True)
        protected = types.Channel(34, 'protected', types.ChatPhotoEmpty(), DATE, megagroup=True, noforwards=True)
        from telethon import utils
        for entity in entities + [channel, protected]:
            destination = utils.get_peer_id(entity)
            self.cache.save(11, {'id': destination, 'name': 'cached allowed before change', 'kind': 'private',
                                'content_known': True, 'content_available': True})
            self.client.get_entity.return_value = entity
            for method, params in [('messages.list', {'destination': destination}),
                                   ('media.download', {'destination': destination, 'message_id': 1, 'path': str(self.root / 'private-export.bin')}),
                                   ('chat.preview', {'account_id': 11, 'destination': destination, 'message': 'user draft'})]:
                with self.subTest(entity=type(entity).__name__, method=method), self.assertRaises(IPCError):
                    await self.backend.chats.dispatch('gate', method, params)
        self.client.get_messages.assert_not_awaited()
        self.client.download_media.assert_not_awaited()
        self.assertEqual(self.backend.preview_tokens, {})
        self.assertEqual(self.backend.store.history(11), [])

    async def test_wrong_peer_media_and_reply_rejected_before_export_or_token(self):
        self.client.get_messages.return_value = message(peer=23)
        output = self.root / 'wrong-peer.bin'
        with self.assertRaises(IPCError):
            await self.backend.chats.dispatch('media', 'media.download',
                                             {'destination': 22, 'message_id': 1, 'path': str(output)})
        with self.assertRaises(IPCError):
            await self.backend.chats.dispatch('reply', 'chat.preview',
                                             {'account_id': 11, 'destination': 22, 'reply_to': 1, 'message': 'user draft'})
        self.assertFalse(output.exists())
        self.client.download_media.assert_not_awaited()
        self.assertEqual(self.backend.preview_tokens, {})

    async def test_history_peer_binding_and_disappearing_message_placeholder(self):
        def rows(value):
            async def iterator(*args, **kwargs):
                yield value
            return iterator
        self.client.iter_messages = rows(message(peer=23))
        with self.assertRaises(IPCError):
            await self.backend.chats.dispatch('history', 'messages.list', {'destination': 22})
        self.client.iter_messages = rows(message(ttl_period=5))
        result = await self.backend.chats.dispatch('history', 'messages.list', {'destination': 22})
        self.assertNotIn(SECRET, str(result))
        self.assertFalse(result['messages'][0]['content_available'])

    async def test_restricted_dialog_bodies_not_committed_to_sqlite(self):
        entities = [types.User(22, bot=True), types.User(23, restricted=True),
                    types.Channel(33, 'broadcast', types.ChatPhotoEmpty(), DATE, broadcast=True)]
        async def dialogs(**kwargs):
            for entity in entities:
                yield NS(entity=entity, name='fixture', message=message(), unread_count=1)
        self.client.iter_dialogs = dialogs
        await self.backend.chats.dispatch('refresh', 'chats.refresh', {'limit': 10})
        for row in self.store.db.execute('SELECT data FROM dialog_cache WHERE account=11'):
            self.assertNotIn(SECRET, row[0])

    async def test_duplicate_event_does_not_publish_twice(self):
        await self.pipeline.start()
        value = NS(chat_id=22, message=message())
        await self.pipeline.ingest('new', value)
        await self.pipeline.ingest('new', value)
        await asyncio.wait_for(self.pipeline.queue.join(), timeout=2)
        changed = [event for event in self.events if event['event'] == 'message.changed']
        self.assertEqual(len(changed), 1)

    async def test_read_updates_never_regress_known_boundary(self):
        await self.pipeline.start()
        await self.pipeline.ingest('read', NS(chat_id=22, max_id=12, outbox=True))
        await self.pipeline.ingest('read', NS(chat_id=22, max_id=3, outbox=True))
        await asyncio.wait_for(self.pipeline.queue.join(), timeout=2)
        self.assertEqual(self.cache.get(11, 22)['read_outbox_max_id'], 12)
