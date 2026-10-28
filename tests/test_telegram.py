import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

if importlib.util.find_spec("telethon") is None:
    raise unittest.SkipTest("Telethon dependency not installed")

from telethon import errors, types
from telegram_manager.telegram import TelegramService, analyze

from telegram_manager.models import Group
from telegram_manager.storage import DuplicateMessage, Store


def chat(**kwargs):
    return types.Chat(id=1, title='Test', photo=types.ChatPhotoEmpty(), participants_count=2,
                      date=None, version=1, **kwargs)


def permissions(**kwargs):
    return NS(**({'is_admin': False, 'is_creator': False, 'send_messages': True,
                  'participant': None} | kwargs))


class PermissionTests(unittest.TestCase):
    def test_permission_outcomes(self):
        me = NS(restricted=False)
        self.assertEqual(analyze(chat(), permissions(), me)[0], 'allowed')
        self.assertEqual(analyze(chat(), None, me)[0], 'unknown')
        self.assertEqual(analyze(chat(left=True), permissions(), me)[0], 'denied')
        self.assertEqual(analyze(chat(), permissions(), NS(restricted=True))[0], 'denied')

    def test_plain_text_ban_and_admin_exemption(self):
        entity = chat(default_banned_rights=types.ChatBannedRights(until_date=None, send_plain=True))
        self.assertEqual(analyze(entity, permissions(), NS())[0], 'denied')
        self.assertEqual(analyze(entity, permissions(is_admin=True), NS())[0], 'allowed')

    def test_broadcast_and_forum_are_blocked(self):
        entity = types.Channel(id=1, title='Broadcast', photo=types.ChatPhotoEmpty(), date=None)
        self.assertEqual(analyze(entity, permissions(), NS())[0], 'denied')
        entity.megagroup, entity.forum = True, True
        self.assertEqual(analyze(entity, permissions(), NS())[0], 'unknown')


class SendingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'test.sqlite3')
        self.group = Group(-1, 'Test', 'group', permission='allowed')
        self.store.save_group(1, self.group)
        self.client = AsyncMock()
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = NS(id=1)
        self.service = TelegramService(self.client, self.store, NS(id=1))
        self.service.inspect = AsyncMock(return_value=self.group)

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    async def test_success_and_duplicate(self):
        await self.service.send(-1, 'hello')
        self.assertEqual(self.store.history(1)[0]['status'], 'sent')
        with self.assertRaises(DuplicateMessage):
            await self.service.send(-1, 'hello')
        self.assertEqual(self.client.call_count, 1)

    async def test_denied_or_unknown_never_sends(self):
        for state in ('denied', 'unknown'):
            self.group.permission = state
            with self.assertRaises(ValueError):
                await self.service.send(-1, 'hello')
        self.client.assert_not_called()
        self.assertEqual(self.store.history(1), [])

    async def test_wait_is_persisted_and_no_retry(self):
        self.client.side_effect = errors.FloodWaitError(request=None, capture=60)
        await self.service.send(-1, 'hello')
        self.assertEqual(self.store.history(1)[0]['status'], 'blocked')
        with self.assertRaises(ValueError):
            await self.service.send(-1, 'different')
        self.assertEqual(self.client.call_count, 1)

    async def test_transport_failure_is_uncertain(self):
        self.client.side_effect = ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            await self.service.send(-1, 'hello')
        self.assertEqual(self.store.history(1)[0]['status'], 'uncertain')
        with self.assertRaises(DuplicateMessage):
            await self.service.send(-1, 'hello')

    async def test_slowmode_blocks_without_reservation(self):
        self.group.slowmode_next_send = 9999999999
        with self.assertRaises(ValueError):
            await self.service.send(-1, 'hello')
        self.assertEqual(self.store.history(1), [])

    async def test_undiscovered_or_empty_message_blocked(self):
        for destination, message in [(-2, 'hello'), (-1, ' '), (-1, '😀' * 2049)]:
            with self.assertRaises(ValueError):
                await self.service.send(destination, message)
        self.client.assert_not_called()
