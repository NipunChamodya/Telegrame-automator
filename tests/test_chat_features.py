import asyncio
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telethon import errors, types

from telegram_manager.chat_features import ChatFeatures
from telegram_manager.chat_store import ChatStore
from telegram_manager.ipc import Backend, IPCError
from telegram_manager.models import Group
from telegram_manager.storage import Store, DuplicateMessage


def file_message(size):
    document = types.Document(id=1, access_hash=0, file_reference=b'', date=datetime.now(timezone.utc),
                              mime_type='application/octet-stream', size=size, dc_id=1, attributes=[])
    return types.Message(id=1, peer_id=types.PeerUser(22), media=types.MessageMediaDocument(document=document))


class ChatFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'manager.sqlite3')
        self.backend = Backend(self.root,self.store,{'version':1,'account_id':11})
        self.backend.service = object()
        self.backend.auth_stage = 'connected'
        self.backend.client = AsyncMock()
        self.backend.client.is_user_authorized.return_value = True
        self.backend.client.get_me.return_value = SimpleNamespace(id=11)
        self.backend.client.get_entity.return_value = types.User(id=22,first_name='Friend')
        self.backend.client.get_input_entity.return_value = types.InputPeerUser(22,0)
        self.chat = ChatFeatures(self.backend)
        self.cache = ChatStore(self.store)
        self.cache.save(11,{'id':22,'name':'ශ්‍රී தமிழ் 👩🏽‍💻','kind':'private','username':'fixture'})

    async def asyncTearDown(self):
        self.store.close(); self.temp.cleanup()

    async def call(self, method, **params):
        return await self.chat.dispatch('test',method,params)

    async def preview(self, **extra):
        return await self.call('chat.preview',account_id=11,destination=22,message='hello',**extra)

    async def test_cached_unicode_search_and_account_isolation(self):
        self.assertEqual((await self.call('chats.list',query='தமிழ்'))['total'],1)
        self.assertEqual(self.cache.page(12)['total'],0)
        self.assertEqual((await self.call('chats.list',kind='group'))['total'],0)
        self.backend.client.get_me.assert_not_awaited()

    async def test_group_scope_includes_basic_and_supergroups_without_network(self):
        self.cache.save(11, {'id': -1, 'name': 'Basic', 'kind': 'group'})
        self.cache.save(11, {'id': -2, 'name': 'Super', 'kind': 'supergroup'})
        self.cache.save(11, {'id': -3, 'name': 'Broadcast', 'kind': 'channel'})
        rows = (await self.call('chats.list', kind='groups'))['chats']
        self.assertEqual({row['id'] for row in rows}, {-1, -2})
        self.backend.client.get_me.assert_not_awaited()

    async def test_dialog_types_archive_migration_and_progress(self):
        entities=[types.User(id=11,first_name='Me'),types.User(id=22,first_name='Friend'),
                  types.Chat(id=3,title='Group',photo=types.ChatPhotoEmpty(),participants_count=2,date=datetime.now(timezone.utc),version=1),
                  types.Channel(id=4,title='Super',photo=types.ChatPhotoEmpty(),date=datetime.now(timezone.utc),megagroup=True),
                  types.Channel(id=5,title='News',photo=types.ChatPhotoEmpty(),date=datetime.now(timezone.utc),broadcast=True)]
        async def dialogs(**kwargs):
            self.assertEqual(kwargs,{'limit':5,'ignore_migrated':True})
            for e in entities: yield SimpleNamespace(entity=e,name='தமிழ்',archived=True,unread_count=2,message=None)
        self.backend.client.iter_dialogs=dialogs
        result=await self.call('chats.refresh',limit=5)
        self.assertEqual(result['processed'],5)
        rows=self.cache.page(11)['chats']
        self.assertEqual({r['kind'] for r in rows},{'saved','private','group','supergroup','channel'})
        self.assertTrue(all(r['archived'] for r in rows))

    async def test_partial_dialog_failure_preserves_cache(self):
        async def dialogs(**kwargs):
            yield SimpleNamespace(entity=types.User(id=33,first_name='New'),name='New',message=None)
            raise BrokenPipeError('sensitive transport details')
        self.backend.client.iter_dialogs=dialogs
        with self.assertRaises(BrokenPipeError): await self.call('chats.refresh')
        self.assertIsNotNone(self.cache.get(11,33))

    async def test_recent_messages_are_bounded_no_sender_fetches(self):
        async def messages(destination,**kwargs):
            self.assertEqual(destination,22);self.assertEqual(kwargs,{'limit':1,'offset_id':42,'search':None})
            yield types.Message(id=40,peer_id=types.PeerUser(22),message='தமிழ் 😀',from_id=types.PeerUser(22),date=datetime.now(timezone.utc),out=False)
        self.backend.client.iter_messages=messages
        result=await self.call('messages.list',destination=22,limit=1,offset_id=42)
        self.assertEqual(result['next_offset_id'],40)
        self.assertTrue(result['has_more']);self.assertEqual(result['messages'][0]['text'],'தமிழ் 😀')
        self.backend.client.get_entity.assert_awaited_once_with(22)

    async def test_conversation_drafts_preserved_and_account_scoped(self):
        await self.call('chatdraft.save',destination=22,message='Draft 👩🏽‍💻')
        self.assertEqual((await self.call('chatdraft.list'))['drafts'][0]['title'],'ශ්‍රී தமிழ் 👩🏽‍💻')
        self.assertEqual(ChatStore(self.store).draft(11,22)['message'],'Draft 👩🏽‍💻')
        self.assertEqual(self.cache.draft(12,22)['message'],'')
        await self.call('chatdraft.delete',destination=22)
        self.assertEqual((await self.call('chatdraft.list'))['drafts'],[])

    async def test_local_labels_never_modify_telegram(self):
        self.store.save_group(11,Group(-3,'Group','group'))
        result=await self.call('label.set',destination=-3,label='Work',enabled=True)
        self.assertEqual(result,{'labels':[{'destination':-3,'label':'Work'}]})
        self.assertEqual(self.cache.labels(12),{'labels':[]})
        await self.call('label.set',destination=-3,label='Work',enabled=False)
        self.assertEqual(await self.call('labels'),{'labels':[]})
        self.backend.client.get_me.assert_not_awaited()

    async def test_personal_send_one_use_exact_confirmation_and_dedup(self):
        self.backend.client.return_value=SimpleNamespace(id=123)
        preview=await self.preview()
        result=await self.call('chat.send',account_id=11,token=preview['token'],confirmation='SEND 22')
        self.assertEqual(result['delivery']['status'],'sent')
        self.assertEqual(result['delivery']['telegram_message_id'],123)
        with self.assertRaises(IPCError): await self.call('chat.send',account_id=11,token=preview['token'],confirmation='SEND 22')
        p=await self.preview()
        with self.assertRaises(DuplicateMessage):await self.call('chat.send',account_id=11,token=p['token'],confirmation='SEND 22')
        self.assertEqual(self.backend.client.await_count,1)

    async def test_wrong_account_or_identity_blocks_before_reservation(self):
        preview=await self.preview()
        with self.assertRaises(IPCError):await self.call('chat.send',account_id=12,token=preview['token'],confirmation='SEND 22')
        self.assertEqual(self.store.history(11),[])
        self.backend.client.get_me.return_value=SimpleNamespace(id=99)
        with self.assertRaises(IPCError):await self.preview()
        self.backend.client.assert_not_awaited()

    async def test_group_cannot_bypass_managed_approval(self):
        self.cache.save(11,{'id':-3,'kind':'group','name':'Group'})
        with self.assertRaises(IPCError):await self.call('chat.preview',account_id=11,destination=-3,message='x')
        self.backend.client.assert_not_awaited()

    async def test_invalid_confirmation_consumes_token(self):
        preview=await self.preview()
        for confirmation in ('yes','SEND 22'):
            with self.assertRaises(IPCError):await self.call('chat.send',account_id=11,token=preview['token'],confirmation=confirmation)
        self.assertEqual(self.store.history(11),[])

    async def test_interrupted_send_uncertain_never_retried(self):
        self.backend.client.side_effect=BrokenPipeError()
        preview=await self.preview()
        with self.assertRaises(BrokenPipeError):await self.call('chat.send',account_id=11,token=preview['token'],confirmation='SEND 22')
        self.assertEqual(self.store.history(11)[0]['status'],'uncertain')
        self.assertEqual(self.backend.client.await_count,1)

    async def test_floodwait_preserves_cooldown_and_blocks_followup(self):
        self.backend.client.side_effect=errors.FloodWaitError(request=None,capture=16)
        preview=await self.preview()
        with self.assertRaises(errors.FloodWaitError):await self.call('chat.send',account_id=11,token=preview['token'],confirmation='SEND 22')
        self.assertGreater(self.store.cooldown(11),time.time())
        self.assertEqual(self.store.history(11)[0]['status'],'blocked')
        with self.assertRaises(IPCError):await self.preview()
        self.assertEqual(self.backend.client.await_count,1)

    async def test_strict_fields_and_limits(self):
        for method,p in [('chats.list',{'size':101}),('chats.refresh',{'limit':0}),
                         ('messages.list',{'destination':22,'offset_id':-1}),
                         ('chat.preview',{'account_id':True,'destination':22,'message':'x'}),
                         ('labels',{'shell':'bad'})]:
            with self.subTest(method=method),self.assertRaises(IPCError):await self.call(method,**p)

    async def test_saved_messages_explicit_account_identity(self):
        result = await self.call('chats.saved')
        self.assertEqual(result['chat']['id'], 11)
        self.assertEqual(self.cache.get(11, 11)['kind'], 'saved')
        self.assertIsNone(self.cache.get(12, 11))

    async def test_media_download_private_atomic_and_non_overwriting(self):
        message = file_message(4)
        self.backend.client.get_messages.return_value = message
        async def download(message, file, progress_callback):
            file.write(b'demo'); progress_callback(file.tell(), 4)
        self.backend.client.download_media.side_effect = download
        output = self.root/'safe.bin'
        result = await self.call('media.download', destination=22, message_id=1, path=str(output))
        self.assertEqual(result, {'saved': True, 'bytes': 4})
        self.assertEqual(output.read_bytes(), b'demo')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(IPCError):
            await self.call('media.download', destination=22, message_id=1, path=str(output))
        self.assertEqual(output.read_bytes(), b'demo')

    async def test_media_cancellation_and_oversize_leave_no_partial_files(self):
        self.backend.client.get_messages.return_value = file_message(4)
        async def interrupted(message, file, progress_callback):
            file.write(b'ab'); raise asyncio.CancelledError()
        self.backend.client.download_media.side_effect = interrupted
        with self.assertRaises(asyncio.CancelledError):
            await self.call('media.download', destination=22, message_id=1, path=str(self.root/'cancel.bin'))
        self.assertFalse((self.root/'cancel.bin').exists())
        self.assertEqual(list(self.root.glob('.telegram-download-*')), [])
        self.backend.client.get_messages.return_value = file_message(65*1024*1024)
        with self.assertRaises(IPCError):
            await self.call('media.download', destination=22, message_id=1, path=str(self.root/'large.bin'))

    async def test_bounded_media_sink_rejects_inaccurate_server_size(self):
        self.backend.client.get_messages.return_value = file_message(1)
        async def oversized(message, file, progress_callback): file.write(b'too large')
        self.backend.client.download_media.side_effect = oversized
        with self.assertRaises(IPCError):
            await self.call('media.download', destination=22, message_id=1, path=str(self.root/'oversize.bin'))
        self.assertFalse((self.root/'oversize.bin').exists())
        self.assertEqual(list(self.root.glob('.telegram-download-*')), [])

    async def test_chat_routes_are_registered_in_strict_ipc_dispatch(self):
        response = await self.backend.dispatch('registered', 'chats.list', {'size': 1})
        self.assertEqual(response['total'], 1)
        self.assertEqual(response['profile_id'], 'legacy')
        with self.assertRaises(IPCError):
            await self.backend.dispatch('unknown', 'chats.execute', {'code': 'never'})

    async def test_preview_expiration_and_same_body_autosave(self):
        preview = await self.preview()
        await self.call('chatdraft.save', destination=22, message='hello')
        self.assertIn(preview['token'], self.backend.preview_tokens)
        self.backend.preview_tokens[preview['token']]['deadline'] = time.time() - 1
        with self.assertRaises(IPCError):
            await self.call('chat.send', account_id=11, token=preview['token'], confirmation='SEND 22')
        self.assertEqual(self.store.history(11), [])
        preview = await self.preview()
        await self.call('chatdraft.save', destination=22, message='edited')
        self.assertNotIn(preview['token'], self.backend.preview_tokens)

    async def test_reply_uses_one_selected_destination_and_raw_random_id(self):
        self.backend.client.return_value = SimpleNamespace(id=123)
        self.backend.client.get_messages.return_value = types.Message(id=9, peer_id=types.PeerUser(22), message='reply target')
        preview = await self.preview(reply_to=9)
        await self.call('chat.send', account_id=11, token=preview['token'], confirmation='SEND 22')
        request = self.backend.client.call_args.args[0]
        self.assertEqual(request.reply_to.reply_to_msg_id, 9)
        self.assertEqual(request.message, 'hello')
        self.assertEqual(request.random_id, self.store.history(11)[0]['random_id'])

    async def test_restricted_identity_blocks_personal_send(self):
        self.backend.client.get_me.return_value = SimpleNamespace(id=11, restricted=True)
        with self.assertRaises(IPCError):
            await self.preview()
        self.backend.client.assert_not_awaited()

    async def test_whitespace_draft_can_be_recovered_but_not_sent(self):
        await self.call('chatdraft.save', destination=22, message=' \n ')
        self.assertEqual((await self.call('chatdraft.get', destination=22))['message'], ' \n ')
        with self.assertRaises(ValueError):
            await self.call('chat.preview', account_id=11, destination=22, message=' \n ')
