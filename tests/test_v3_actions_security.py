"""Adversarial M3 action tests: no real accounts, network, or user files."""
import asyncio
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from telethon import errors, types

from telegram_manager.chat_store import ChatStore
from telegram_manager.conversation_actions import ConversationActions
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.storage import Store

DATE = datetime(2026, 10, 28, tzinfo=timezone.utc)


def own_message(**changes):
    fields = {'id': 7, 'peer_id': types.PeerUser(22), 'from_id': types.PeerUser(11),
              'date': DATE, 'message': 'Original synthetic text', 'out': True}
    return types.Message(**(fields | changes))


class ConversationActionSecurityTests(unittest.IsolatedAsyncioTestCase):
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
        self.client.get_input_entity.return_value = types.InputPeerUser(22, 0)
        self.client.get_messages.return_value = own_message()
        self.backend.client = self.client
        self.cache = ChatStore(self.store)
        self.cache.save(11, {'id': 22, 'name': 'Synthetic peer', 'kind': 'private',
                             'content_known': True, 'content_available': True})
        self.actions = ConversationActions(self.backend)
        self.old_delivery, _ = self.store.reserve(11, 22, 'Existing ledger fixture')
        self.store.finish(self.old_delivery, 'sent', 'Existing record')
        self.old_history = self.store.history(11)

    async def asyncTearDown(self):
        await self.backend.close()
        self.store.close()
        self.temp.cleanup()

    async def call(self, method, **params):
        return await self.actions.dispatch('qa-m3', method, params)

    async def preview(self, action='edit', **changes):
        params = {'account_id': 11, 'destination': 22, 'message_id': 7, 'action': action}
        if action == 'edit':
            params['message'] = 'Replacement සිංහල தமிழ் 👩🏽‍💻'
        return await self.call('message.action.preview', **(params | changes))

    async def commit(self, preview, **changes):
        return await self.call('message.action.commit', **({'account_id': 11, 'token': preview['token'],
                               'confirmation': preview['confirmation']} | changes))

    async def operations(self):
        return (await self.call('message.operations'))['operations']

    async def test_outgoing_flag_does_not_establish_actual_authorship(self):
        for value in [own_message(from_id=types.PeerUser(23)), own_message(out=False),
                      own_message(from_id=None), own_message(peer_id=types.PeerUser(23)), own_message(id=8)]:
            self.client.get_messages.return_value = value
            with self.subTest(sender=value.sender_id, peer=value.peer_id, identity=value.id), self.assertRaises(IPCError):
                await self.preview()
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])
        self.assertEqual(self.backend.preview_tokens, {})

    async def test_restricted_media_formatted_and_forwarded_targets_refused(self):
        values = [own_message(noforwards=True), own_message(ttl_period=10),
                  own_message(restriction_reason=[types.RestrictionReason('all', 'sensitive', 'fixture')]),
                  own_message(media=types.MessageMediaUnsupported()),
                  own_message(entities=[types.MessageEntityBold(0, 3)]),
                  own_message(fwd_from=types.MessageFwdHeader(date=DATE)),
                  own_message(via_bot_id=55), own_message(post=True)]
        for value in values:
            self.client.get_messages.return_value = value
            with self.subTest(value=value.to_dict()), self.assertRaises(IPCError):
                await self.preview()
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_bot_channel_and_managed_group_routes_cannot_use_personal_actions(self):
        from telethon import utils
        peers = [types.User(22, bot=True), types.User(22, restricted=True),
                 types.Channel(33, 'Channel', types.ChatPhotoEmpty(), DATE, broadcast=True),
                 types.Chat(34, 'Group', types.ChatPhotoEmpty(), 2, DATE, 1)]
        for peer in peers:
            destination = utils.get_peer_id(peer)
            self.client.get_entity.return_value = peer
            self.cache.save(11, {'id': destination, 'name': 'Fixture', 'kind': 'private',
                                'content_known': True, 'content_available': True})
            with self.subTest(peer=type(peer).__name__), self.assertRaises(IPCError):
                await self.preview(destination=destination)
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_exact_confirmation_is_single_use_without_network_submission(self):
        preview = await self.preview()
        with self.assertRaises(IPCError) as caught:
            await self.commit(preview, confirmation='yes')
        self.assertEqual(caught.exception.code, 'confirmation_required')
        with self.assertRaises(IPCError):
            await self.commit(preview)
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_token_account_profile_generation_expiry_and_kind_binding(self):
        for change in ('account', 'profile', 'generation', 'expiry', 'kind'):
            preview = await self.preview()
            data = self.backend.preview_tokens[preview['token']]
            if change == 'account':
                params = {'account_id': 12}
            else:
                params = {}
                if change == 'profile': data['profile_id'] = 'another-profile'
                elif change == 'generation': data['account_generation'] += 1
                elif change == 'expiry': data['deadline'] = time.time() - 1
                else: data['kind'] = 'personal'
            with self.subTest(change=change), self.assertRaises(IPCError):
                await self.commit(preview, **params)
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_changed_target_and_wrong_peer_on_commit_reject_before_reservation(self):
        for changed in [own_message(message='Changed on another device'),
                        own_message(edit_date=DATE + timedelta(seconds=1)),
                        own_message(peer_id=types.PeerUser(23)), own_message(from_id=types.PeerUser(23))]:
            self.client.get_messages.return_value = own_message()
            preview = await self.preview()
            self.client.get_messages.return_value = changed
            with self.subTest(changed=changed.to_dict()), self.assertRaises(IPCError):
                await self.commit(preview)
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_delete_is_one_exact_id_for_me_only_and_send_ledger_unchanged(self):
        preview = await self.preview(action='delete')
        self.assertFalse(preview['delete_for_everyone'])
        result = await self.commit(preview)
        request = self.client.await_args.args[0]
        self.assertIsInstance(request, types.TLObject)
        self.assertEqual(type(request).__name__, 'DeleteMessagesRequest')
        self.assertEqual(request.id, [7])
        self.assertFalse(request.revoke)
        self.assertEqual(result['operation']['status'], 'acknowledged')
        self.assertEqual(self.store.history(11), self.old_history)
        self.assertTrue((self.root / 'manager.sqlite3').exists())
        self.assertEqual((await self.operations())[0]['action'], 'delete')

    async def test_transport_failure_and_cancel_are_uncertain_and_never_retried(self):
        for failure in (BrokenPipeError(), asyncio.CancelledError()):
            # Separate action targets avoid testing a second reservation for the first target.
            target = 7 if isinstance(failure, BrokenPipeError) else 8
            self.client.get_messages.return_value = own_message(id=target)
            preview = await self.preview(message_id=target)
            self.client.side_effect = failure
            with self.assertRaises(type(failure)):
                await self.commit(preview)
            self.assertEqual((await self.operations())[0]['status'], 'uncertain')
            calls = self.client.await_count
            self.client.side_effect = None
            second_preview = await self.preview(message_id=target)
            with self.assertRaises(IPCError) as caught:
                await self.commit(second_preview)
            self.assertEqual(caught.exception.code, 'operation_duplicate')
            self.assertEqual(self.client.await_count, calls)
        self.assertEqual(self.store.history(11), self.old_history)

    async def test_rpc_rejection_and_server_error_have_distinct_durable_status(self):
        for target, failure, expected in [(7, errors.MessageAuthorRequiredError(None), 'rejected'),
                                           (8, errors.ServerError(None, 'fixture unavailable'), 'uncertain')]:
            self.client.get_messages.return_value = own_message(id=target)
            preview = await self.preview(message_id=target)
            self.client.side_effect = failure
            with self.assertRaises(type(failure)):
                await self.commit(preview)
            self.assertEqual((await self.operations())[0]['status'], expected)
        self.assertEqual(self.store.history(11), self.old_history)

    async def test_operation_history_is_account_isolated_and_contains_no_bodies(self):
        preview = await self.preview()
        await self.commit(preview)
        operations = await self.operations()
        self.assertEqual(len(operations), 1)
        self.assertNotIn(preview['message'], str(operations))
        self.assertNotIn(preview['original_text'], str(operations))
        self.backend.config['account_id'] = 12
        self.assertEqual(await self.operations(), [])
        self.backend.config['account_id'] = 11
        self.assertEqual(self.store.history(11), self.old_history)

    async def test_strict_parameters_refuse_bulk_revoke_unknown_or_unchanged_action(self):
        for params in [{'action': 'all'}, {'message_id': True}, {'destination': [22, 23]},
                       {'message': 'Original synthetic text'}, {'message_id': 0}]:
            with self.subTest(params=params), self.assertRaises((IPCError, ValueError)):
                await self.preview(**params)
        with self.assertRaises(IPCError):
            await self.preview(action='delete', revoke=True)
        self.client.assert_not_awaited()
        self.assertEqual(await self.operations(), [])

    async def test_floodwait_persists_exact_cooldown_and_never_retries(self):
        preview = await self.preview()
        began = time.time()
        self.client.side_effect = errors.FloodWaitError(request=None, capture=17)
        with self.assertRaises(errors.FloodWaitError):
            await self.commit(preview)
        self.assertGreaterEqual(self.store.cooldown(11), began + 17)
        self.assertLess(self.store.cooldown(11), began + 19)
        self.assertEqual((await self.operations())[0]['status'], 'rejected')
        calls = self.client.await_count
        with self.assertRaises(IPCError) as caught:
            await self.preview()
        self.assertEqual(caught.exception.code, 'cooldown')
        self.assertEqual(self.client.await_count, calls)
        self.assertEqual(self.store.history(11), self.old_history)

    async def test_uncertain_reservation_survives_backend_and_database_reopen(self):
        preview = await self.preview()
        self.client.side_effect = BrokenPipeError()
        with self.assertRaises(BrokenPipeError):
            await self.commit(preview)
        await self.backend.close()
        self.store.close()
        self.store = Store(self.root / 'manager.sqlite3')
        self.backend = Backend(self.root, self.store, {'version': 1, 'account_id': 11})
        self.backend.service = object()
        self.backend.auth_stage = 'connected'
        self.backend.client = self.client
        self.actions = ConversationActions(self.backend)
        self.client.side_effect = None
        preview = await self.preview()
        calls = self.client.await_count
        with self.assertRaises(IPCError) as caught:
            await self.commit(preview)
        self.assertEqual(caught.exception.code, 'operation_duplicate')
        self.assertEqual(self.client.await_count, calls)
        self.assertEqual((await self.operations())[0]['status'], 'uncertain')
        self.assertEqual(self.store.history(11), self.old_history)

    async def test_incompatible_operation_schema_without_unique_reservation_blocks_mutation(self):
        db = self.store.db
        db.execute("CREATE TABLE conversation_operations (id INTEGER PRIMARY KEY, account INTEGER NOT NULL, destination INTEGER NOT NULL, message_id INTEGER NOT NULL, action TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, detail TEXT NOT NULL)")
        preview = await self.preview()
        with self.assertRaises(sqlite3.DatabaseError):
            await self.commit(preview)
        self.client.assert_not_awaited()
        self.assertEqual(db.execute('SELECT count(*) FROM conversation_operations').fetchone()[0], 0)
        self.assertEqual(self.store.history(11), self.old_history)
