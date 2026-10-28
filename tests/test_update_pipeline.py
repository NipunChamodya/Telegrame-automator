"""Bounded real-time adapter integration with isolated SQLite and mock Telegram."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from telethon import types

from telegram_manager.chat_store import ChatStore
from telegram_manager.content_policy import classify_entity
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.message_projection import normalize_message
from telegram_manager.storage import Store
from telegram_manager.update_pipeline import UpdatePipeline


class UpdatePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'manager.sqlite3')
        self.backend = Backend(Path(self.temp.name), self.store, {'version': 1, 'account_id': 11})
        self.client = AsyncMock()
        self.client.add_event_handler = Mock()
        self.client.remove_event_handler = Mock()
        self.client.is_connected = Mock(return_value=True)
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = types.User(11)
        self.client.get_entity.return_value = types.User(22)
        self.client.get_input_entity.return_value = types.InputPeerUser(22, 0)
        self.backend.client = self.client
        self.backend.service = object()
        self.backend.auth_stage = 'connected'
        self.events = []
        self.backend.emit_control = self.events.append
        self.cache = ChatStore(self.store)
        self.cache.save(11, {'id': 22, 'name': 'தமிழ் ශ්‍රී 👩🏽‍💻', 'kind': 'private',
                             'unread_count': 2, **classify_entity(types.User(22), 11)})
        self.pipeline = UpdatePipeline(self.backend)
        self.backend.updates = self.pipeline

    async def asyncTearDown(self):
        await self.pipeline.stop()
        self.store.close()
        self.temp.cleanup()

    def message(self, identity=1, **extra):
        return types.Message(id=identity, peer_id=types.PeerUser(22), date=datetime.now(timezone.utc),
                             message='தமிழ் 👩🏽‍💻', **extra)

    async def watch(self):
        return await self.backend.dispatch('w', 'updates.watch', {'account_id': 11, 'peer_id': 22})

    async def test_single_handler_set_and_catchup_then_cleanup(self):
        await self.pipeline.start()
        await self.pipeline.start()
        self.assertEqual(self.client.add_event_handler.call_count, 5)
        self.client.catch_up.assert_awaited_once()
        self.assertTrue(self.pipeline.dirty)
        await self.pipeline.stop()
        self.assertEqual(self.client.remove_event_handler.call_count, 5)
        self.assertIsNone(self.pipeline.worker)

    async def test_false_server_read_or_typing_result_is_not_reported_confirmed(self):
        await self.watch()
        self.pipeline.record_visible(22, [normalize_message(self.message())])
        self.client.send_read_acknowledge.return_value = False
        with self.assertRaises(IPCError) as error:
            await self.backend.dispatch('read', 'messages.read', {'account_id': 11, 'peer_id': 22, 'max_id': 1})
        self.assertEqual(error.exception.code, 'read_unconfirmed')
        self.assertEqual(self.pipeline.read_max, 0)
        self.client.return_value = False
        result = await self.backend.dispatch('typing', 'messages.typing', {'account_id': 11, 'peer_id': 22, 'active': True})
        self.assertFalse(result['accepted'])

    async def test_snapshot_one_fetch_registers_bounded_read_frontier(self):
        await self.watch()
        async def history(*args, **kwargs):
            yield self.message(7)
            yield self.message(6, out=True)
        self.client.iter_messages = Mock(side_effect=history)
        result = await self.backend.dispatch('s', 'sync.snapshot', {'account_id': 11, 'peer_id': 22, 'limit': 2})
        self.assertFalse(result['dirty'])
        self.assertEqual(result['freshness_scope'], 'conversation')
        self.assertFalse(result['history_complete'])
        self.assertEqual(self.pipeline.visible, {7})
        self.assertEqual(self.client.iter_messages.call_count, 1)
        ack = await self.backend.dispatch('r', 'messages.read', {'account_id': 11, 'peer_id': 22, 'max_id': 7})
        self.assertTrue(ack['acknowledged'])
        with self.assertRaises(IPCError):
            await self.backend.dispatch('x', 'messages.read', {'account_id': 11, 'peer_id': 22, 'max_id': 6})

    async def test_stream_identity_changes_on_same_account_reconnect(self):
        second = UpdatePipeline(self.backend)
        self.assertNotEqual(self.pipeline.scope['stream_id'], second.scope['stream_id'])
        self.assertEqual(self.pipeline.scope['account_id'], second.scope['account_id'])
        await second.stop()

    async def test_bounded_messages_and_new_unread_count_duplicate_safe(self):
        await self.watch()
        for identity in range(1, 221):
            value = normalize_message(self.message(identity))
            self.pipeline._apply('new', {'peer_id': 22, 'message': value, 'change': 'new'})
            self.pipeline._apply('new', {'peer_id': 22, 'message': value, 'change': 'new'})
        self.assertEqual(len(self.pipeline.messages), 200)
        self.assertEqual(self.cache.get(11, 22)['unread_count'], 222)
        self.assertLessEqual(len(self.pipeline.visible), 200)
        sequences = [event['data']['sequence'] for event in self.events]
        self.assertEqual(sequences, list(range(1, len(sequences)+1)))

    async def test_presence_does_not_trigger_unknown_peer_sync(self):
        self.pipeline.dirty = False
        await self.pipeline.ingest('typing', SimpleNamespace(chat_id=999, typing=False, cancel=False))
        self.assertFalse(self.pipeline.dirty)
        self.assertTrue(self.pipeline.queue.empty())

    async def test_typing_throttle_cancel_and_reset_between_peers(self):
        await self.watch()
        first = await self.backend.dispatch('t', 'messages.typing', {'account_id': 11, 'peer_id': 22, 'active': True})
        second = await self.backend.dispatch('t2', 'messages.typing', {'account_id': 11, 'peer_id': 22, 'active': True})
        self.assertTrue(first['accepted'])
        self.assertFalse(second['accepted'])
        await self.backend.dispatch('u', 'updates.unwatch', {'account_id': 11})
        self.assertEqual(self.pipeline.last_typing, 0)
        self.assertIsInstance(self.client.call_args.args[0].action, types.SendMessageCancelAction)

    async def test_snapshot_epoch_rejects_pre_snapshot_queued_payload(self):
        await self.watch()
        await self.pipeline.ingest('new', SimpleNamespace(chat_id=22, message=self.message()))
        self.assertEqual(self.pipeline.queue.qsize(), 1)
        async def history(*args, **kwargs):
            yield self.message(3)
        self.client.iter_messages = history
        await self.backend.dispatch('s', 'sync.snapshot', {'account_id': 11, 'peer_id': 22})
        # Start worker only after snapshot to model a slow worker waiting on lock.
        await self.pipeline.start()
        await asyncio.wait_for(self.pipeline.queue.join(), timeout=2)
        self.assertNotIn((22, 1), self.pipeline.messages)
        self.assertIn((22, 3), self.pipeline.messages)

    async def test_recent_chat_order_pins_then_actual_date(self):
        base = {'kind': 'private', **classify_entity(types.User(22), 11)}
        self.cache.save(11, {'id': 23, 'name': 'A', 'last_date': '2026-10-28T10:00:00+00:00', **base})
        self.cache.save(11, {'id': 24, 'name': 'Z', 'last_date': '2026-10-27T10:00:00+00:00', 'pinned': True, **base})
        rows = (await self.backend.dispatch('l', 'chats.list', {'sort': 'recent'}))['chats']
        self.assertEqual([row['id'] for row in rows][:2], [24, 23])

    async def test_protected_edit_clears_prior_body_and_invalidates_media(self):
        await self.watch()
        original = normalize_message(self.message(1))
        self.pipeline._apply('new', {'peer_id':22, 'message':original, 'change':'new'})
        self.backend.media.invalidate = Mock()
        protected = normalize_message(self.message(1, noforwards=True))
        self.pipeline._apply('edit', {'peer_id':22, 'message':protected, 'change':'edit'})
        self.assertEqual(self.pipeline.messages[(22, 1)]['text'], '')
        self.assertEqual(self.cache.get(11, 22)['last_message'], '')
        self.backend.media.invalidate.assert_called_once_with(22, [1])
        self.pipeline._apply('new', {'peer_id':22, 'message':original, 'change':'new'})
        self.assertEqual(self.pipeline.messages[(22, 1)]['text'], '')
