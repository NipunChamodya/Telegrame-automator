"""Use real Telethon TL/permission objects, with every network operation mocked."""
import importlib.util
import io
import logging
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

if importlib.util.find_spec('telethon') is None:
    raise unittest.SkipTest('Telethon is required for discovery regression tests')

from telethon import errors, functions, types, utils
from telethon.tl.custom import ParticipantPermissions

from telegram_manager import diagnostics
from telegram_manager.dashboard import Dashboard
from telegram_manager.diagnostics import report_programming_error
from telegram_manager.storage import Store
from telegram_manager.telegram import TelegramService, analyze, discover_with_output


def chat(chat_id=1, **kwargs):
    return types.Chat(id=chat_id, title=f'Basic {chat_id}', photo=types.ChatPhotoEmpty(),
                      participants_count=1, date=None, version=1, **kwargs)


def channel(channel_id=2, **kwargs):
    return types.Channel(id=channel_id, title=f'Super {channel_id}', photo=types.ChatPhotoEmpty(),
                         date=None, megagroup=True, participants_count=3, **kwargs)


def participant(entity, *, admin=False):
    if isinstance(entity, types.Chat):
        kind = types.ChatParticipantAdmin if admin else types.ChatParticipant
        member = kind(user_id=10, inviter_id=20, date=None)
    else:
        member = types.ChannelParticipant(user_id=10, date=None)
    return ParticipantPermissions(member, chat=isinstance(entity, types.Chat))


def full_chat(entity):
    if isinstance(entity, types.Chat):
        info = types.ChatFull(id=entity.id, about='',
                              participants=types.ChatParticipants(chat_id=entity.id,
                                  participants=[types.ChatParticipant(user_id=10, inviter_id=20, date=None)], version=1),
                              notify_settings=types.PeerNotifySettings(), bot_info=[])
    else:
        info = types.ChannelFull(id=entity.id, about='', read_inbox_max_id=0,
            read_outbox_max_id=0, unread_count=0, chat_photo=types.PhotoEmpty(id=0),
            notify_settings=types.PeerNotifySettings(), bot_info=[], pts=0, participants_count=3)
    return types.messages.ChatFull(full_chat=info, chats=[], users=[])


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'manager.sqlite3'
        self.store = Store(self.path)
        self.client = AsyncMock()
        self.me = NS(id=10, restricted=False)
        self.service = TelegramService(self.client, self.store, self.me)
        self.entities = [chat()]
        self.client.get_entity.side_effect = lambda entity: entity
        self.client.get_permissions.side_effect = lambda entity, me: participant(entity)
        self.client.side_effect = lambda request: full_chat(
            next(e for e in self.entities if e.id == (
                request.chat_id if isinstance(request, functions.messages.GetFullChatRequest) else request.channel.id)))
        # Request.channel is the entity before serialization; no socket is used.
        async def dialogs(**kwargs):
            for entity in self.entities:
                yield NS(entity=entity, archived=True)
        self.client.iter_dialogs = Mock(side_effect=dialogs)

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_real_participant_permissions_have_no_send_messages_property(self):
        permissions = participant(chat())
        self.assertFalse(hasattr(permissions, 'send_messages'))
        self.assertEqual(analyze(chat(), permissions, self.me)[0], 'allowed')
        self.assertEqual(await self.service.discover(), 1)
        self.assertEqual(self.store.groups(10)[0]['permission'], 'allowed')

    async def test_groups_archives_filters_and_duplicate_dialogs(self):
        basic, supergroup = chat(), channel()
        broadcast = types.Channel(id=3, title='Broadcast', photo=types.ChatPhotoEmpty(), date=None, broadcast=True)
        migrated = chat(4, migrated_to=types.InputChannel(channel_id=2, access_hash=0))
        self.entities = [basic, supergroup, broadcast, migrated, chat(5, left=True), basic, types.User(id=6)]
        self.assertEqual(await self.service.discover(), 2)
        self.client.iter_dialogs.assert_called_once_with(ignore_migrated=True)
        groups = self.store.groups(10)
        self.assertEqual({g['kind'] for g in groups}, {'group', 'supergroup'})
        self.assertEqual({g['id'] for g in groups}, {utils.get_peer_id(basic), utils.get_peer_id(supergroup)})
        self.assertTrue(all(g['permission'] == 'allowed' for g in groups))
        self.assertEqual(self.store.groups(99), [])
        await self.service.discover()
        self.assertEqual(len(self.store.groups(10)), 2)
        self.client.send_message.assert_not_called()
        self.assertTrue(all(isinstance(c.args[0], (functions.messages.GetFullChatRequest,
                                                  functions.channels.GetFullChannelRequest))
                            for c in self.client.call_args_list))

    async def test_missing_optional_metadata(self):
        entity = channel(slowmode_enabled=True)
        entity.participants_count = None
        self.entities = [entity]
        self.client.return_value = None
        self.client.side_effect = lambda request: NS(full_chat=NS(bot_info=[NS(), types.BotInfo(user_id=123)]))
        self.assertEqual(await self.service.discover(), 1)
        result = self.store.groups(10)[0]
        self.assertIsNone(result['members'])
        self.assertIsNone(result['slowmode_seconds'])
        self.assertIsNone(result['slowmode_next_send'])
        self.assertEqual(result['visible_bots'], ['123'])
        self.assertEqual(result['metadata_status'], 'partial')

    async def test_missing_full_chat_object_is_unknown(self):
        self.client.side_effect = lambda request: NS()
        await self.service.discover()
        result = self.store.groups(10)[0]
        self.assertEqual(result['name'], 'Basic 1')
        self.assertEqual(result['metadata_status'], 'partial')
        self.assertIsNone(result['slowmode_seconds'])
        self.assertTrue(any('missing' in rule for rule in result['unknown_rules']))

    async def test_slow_mode_and_visible_bot_metadata(self):
        entity = channel(slowmode_enabled=True)
        self.entities = [entity]
        full = full_chat(entity)
        full.full_chat.slowmode_seconds = 30
        full.full_chat.slowmode_next_send_date = datetime.fromtimestamp(2000000000, timezone.utc)
        full.full_chat.bot_info = [types.BotInfo(user_id=123)]
        self.client.side_effect = lambda request: full
        await self.service.discover()
        result = self.store.groups(10)[0]
        self.assertEqual(result['slowmode_seconds'], 30)
        self.assertEqual(result['slowmode_next_send'], 2000000000)
        self.assertEqual(result['visible_bots'], ['123'])
        self.assertEqual(result['members'], 3)

    async def test_restrictions_and_admin_exemption(self):
        entity = chat(default_banned_rights=types.ChatBannedRights(until_date=None, send_plain=True))
        self.assertEqual(analyze(entity, participant(entity), self.me)[0], 'denied')
        self.assertEqual(analyze(entity, participant(entity, admin=True), self.me)[0], 'allowed')
        entity = channel()
        banned = types.ChannelParticipantBanned(peer=types.PeerUser(10), kicked_by=20,
            date=None, banned_rights=types.ChatBannedRights(until_date=None, send_messages=True))
        self.assertEqual(analyze(entity, ParticipantPermissions(banned, chat=False), self.me)[0], 'denied')
        self.assertEqual(analyze(entity, NS(), self.me)[0], 'unknown')

    async def test_inaccessible_dialogs_preserved_but_denied(self):
        self.entities = [types.ChatForbidden(id=1, title='Inaccessible'),
                         types.ChannelForbidden(id=2, access_hash=0, title='Private', megagroup=True)]
        self.assertEqual(await self.service.discover(), 2)
        self.assertTrue(all(g['permission'] == 'denied' for g in self.store.groups(10)))
        self.client.get_entity.assert_not_called()
        self.client.get_permissions.assert_not_called()

    async def test_one_group_permission_failure_does_not_stop_following_groups(self):
        self.entities = [chat(), chat(2)]
        self.client.get_permissions.side_effect = [errors.ChatAdminRequiredError(None), participant(chat(2))]
        self.assertEqual(await self.service.discover(), 2)
        results = self.store.groups(10)
        self.assertEqual([g['permission'] for g in results], ['unknown', 'allowed'])

    async def test_entity_lookup_failure_preserves_basic_record(self):
        self.entities = [chat(), chat(2)]
        self.client.get_entity.side_effect = [errors.ChannelPrivateError(None), chat(2)]
        self.assertEqual(await self.service.discover(), 2)
        self.assertEqual([g['permission'] for g in self.store.groups(10)], ['denied', 'allowed'])

    async def test_malformed_group_reports_programming_error_and_continues(self):
        self.entities = [chat(), chat(2)]
        # A malformed API response causes a TypeError while iterating bot metadata.
        self.client.side_effect = [NS(full_chat=NS(bot_info=1)), full_chat(chat(2))]
        with self.assertLogs('telegram_manager.discovery', level='ERROR') as logs:
            self.assertEqual(await self.service.discover(), 2)
        self.assertIn('ProgrammingError:TypeError', ''.join(logs.output))
        results = self.store.groups(10)
        self.assertEqual(results[0]['permission'], 'unknown')
        self.assertEqual(results[0]['metadata_status'], 'error')
        self.assertEqual(results[1]['permission'], 'allowed')

    async def test_rate_limit_stops_and_preserves_current_and_prior_records(self):
        self.entities = [chat(), chat(2), chat(3)]
        self.client.side_effect = [full_chat(chat()), errors.FloodWaitError(None, capture=60)]
        with self.assertRaises(errors.FloodWaitError):
            await self.service.discover()
        self.assertEqual(len(self.store.groups(10)), 2)
        self.assertGreater(self.store.cooldown(10), 0)
        self.assertEqual(self.client.call_count, 2)

    async def test_network_failure_during_iteration_retains_records(self):
        async def interrupted(**kwargs):
            yield NS(entity=chat())
            raise ConnectionError('private-network-details')
        self.client.iter_dialogs.side_effect = interrupted
        with self.assertRaises(ConnectionError):
            await self.service.discover()
        self.assertEqual(len(self.store.groups(10)), 1)

    async def test_database_failure_is_not_swallowed_as_group_metadata_failure(self):
        with patch.object(self.store, 'save_group', side_effect=sqlite3.OperationalError('private-db-path')):
            with self.assertRaises(sqlite3.OperationalError):
                await self.service.discover()

    async def test_full_metadata_error_keeps_base_and_permissions(self):
        self.client.side_effect = errors.ChatAdminRequiredError(None)
        await self.service.discover()
        result = self.store.groups(10)[0]
        self.assertEqual(result['permission'], 'allowed')
        self.assertEqual(result['metadata_status'], 'partial')
        self.assertIsNone(result['slowmode_seconds'])

    async def test_first_run_discovery_continues_to_dashboard(self):
        self.entities = [chat(), channel()]
        dashboard = Dashboard(self.service, Path(self.directory.name), 'mock credentials')
        with patch('builtins.input', side_effect=['y', '0']), patch('sys.stdout', new=io.StringIO()) as output:
            await dashboard.run(first_run=True)
        self.assertIn('Loaded 0 cached groups', output.getvalue())
        self.assertIn('Discovery completed.', output.getvalue())
        self.assertIn('Total groups: 2', output.getvalue())
        self.assertIn('Groups discovered: 2', output.getvalue())
        self.assertIn('Posting allowed: 2', output.getvalue())
        self.assertIn('Goodbye', output.getvalue())
        self.assertEqual(len(self.store.groups(10)), 2)
        self.client.send_message.assert_not_called()

    async def test_progress_counts_are_actual_and_terminal_safe(self):
        self.entities = [chat(), channel()]
        self.entities[0].title = 'Name\x1b[31m'
        with patch('sys.stdout', new=io.StringIO()) as output:
            self.assertEqual(await discover_with_output(self.service), 2)
        self.assertIn('[1]', output.getvalue())
        self.assertIn('Total groups: 2', output.getvalue())
        self.assertIn('Posting allowed: 2', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('/125', output.getvalue())


class DiagnosticTests(unittest.TestCase):
    def test_development_traceback_omits_secrets_locals_messages_and_absolute_paths(self):
        namespace = {}
        filename = str(diagnostics.PACKAGE / 'telegram.py')
        exec(compile('def broken(value):\n    return value.send_messages\n', filename, 'exec'), namespace)
        try:
            namespace['broken'](NS(api_hash='private-api-hash', phone='private-phone', session='private-session'))
        except AttributeError as exc:
            with patch.dict(os.environ, {'TGM_DEV_MODE': '1'}), self.assertLogs('test.safe') as logs:
                report_programming_error(logging.getLogger('test.safe'), exc)
        output = ''.join(logs.output)
        self.assertIn('send_messages', output)
        self.assertIn('src/telegram_manager/telegram.py', output)
        self.assertIn('"line": 2', output)
        self.assertNotIn(str(diagnostics.PACKAGE), output)
        for secret in ('private-api-hash', 'private-phone', 'private-session'):
            self.assertNotIn(secret, output)

    def test_normal_mode_only_reports_error_class(self):
        with patch.dict(os.environ, {'TGM_DEV_MODE': '0'}), self.assertLogs('test.safe') as logs:
            report_programming_error(logging.getLogger('test.safe'), AttributeError('secret-value'))
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn('secret-value', ''.join(logs.output))
