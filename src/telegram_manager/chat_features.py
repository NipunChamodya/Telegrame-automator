"""Explicit bounded conversation reads and single-destination personal messaging.

No live update subscription, automatic history downloads or media downloads.
Managed groups retain their separate approval and permission workflow.
"""
import os
import secrets
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ipc import Backend

from telethon import errors, functions, types, utils

from .chat_store import ChatStore
from .messaging import message_units, validate_message
from .terminal import clean_text


def timestamp(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def peer_kind(entity: Any, account: int) -> str | None:
    if isinstance(entity, types.User):
        return 'saved' if entity.id == account else 'private'
    if isinstance(entity, types.Chat):
        return 'group'
    if isinstance(entity, types.Channel):
        return 'supergroup' if entity.megagroup else 'channel'
    return None


class ChatFeatures:
    NETWORK = {'chats.refresh', 'chats.saved', 'messages.list', 'media.download', 'chat.preview', 'chat.send',
               'chatdraft.save', 'chatdraft.delete', 'label.set'}
    METHODS = NETWORK | {'chats.list', 'chatdraft.get', 'chatdraft.list', 'labels'}

    def __init__(self, backend: "Backend") -> None:
        self.backend = backend

    def store(self) -> ChatStore:
        return ChatStore(self.backend.store)

    async def identity(self, expected: int | None = None) -> int:
        from .ipc import IPCError
        b = self.backend
        b.connected_service()
        b.require_cooldown_expired()
        account = b.account()
        if expected is not None and account != expected:
            raise IPCError('account_changed', 'The active account changed. Review the destination and prepare a new preview.')
        if not await b.client.is_user_authorized():
            raise IPCError('authorization_expired', 'Reconnect this account before continuing.')
        me = await b.client.get_me()
        if me is None or me.id != account:
            raise IPCError('account_changed', 'Telegram identity does not match the active account. Operation blocked.')
        if getattr(me, 'deleted', False) or getattr(me, 'bot', False) or getattr(me, 'restricted', False):
            raise IPCError('account_restricted', 'Telegram reports that this account is unavailable or restricted. Operation blocked.')
        return account

    async def personal_peer(self, destination: int) -> types.User:
        from .ipc import IPCError
        account = self.backend.account()
        cached = self.store().get(account, destination)
        if cached is None or cached['kind'] not in ('private','saved'):
            raise IPCError('managed_destination', 'Choose a cached personal chat or Saved Messages. Groups require the managed composer approval workflow.')
        peer = await self.backend.client.get_entity(destination)
        if not isinstance(peer, types.User) or utils.get_peer_id(peer) != destination or getattr(peer, 'deleted', False):
            raise IPCError('destination_unavailable', 'This personal destination is unavailable. No message was sent.')
        return peer

    async def dispatch(self, request_id: str, method: str, p: dict) -> dict:
        from .ipc import IPCError, boolean, fields, integer, string
        b = self.backend
        if method == 'chats.list':
            fields(p, {'query','kind','page','size'})
            kind = string(p, 'kind', default='all', maximum=16)
            if kind not in {'all','private','saved','group','supergroup','channel'}:
                raise IPCError('invalid_params', 'Choose a supported chat type.')
            return self.store().page(b.account(), string(p,'query',default='',maximum=256), kind,
                                     integer(p,'page',default=0,minimum=0,maximum=100000),
                                     integer(p,'size',default=50,minimum=1,maximum=100))
        if method == 'chats.refresh':
            fields(p, {'limit', 'after'})
            limit = integer(p,'limit',default=100,minimum=1,maximum=100)
            account = await self.identity()
            options = {'limit': limit, 'ignore_migrated': True}
            if 'after' in p:
                after = integer(p, 'after')
                cursor = self.store().get(account, after)
                if cursor is None or not cursor.get('last_message_id') or not cursor.get('last_date'):
                    raise IPCError('cursor_unavailable', 'This chat cannot be used as a continuation. Refresh the recent dialogs instead.')
                options.update(offset_id=cursor['last_message_id'],
                               offset_date=datetime.fromisoformat(cursor['last_date']),
                               offset_peer=await b.client.get_input_entity(after), ignore_pinned=True)
            count = 0
            last_id = None
            async for dialog in b.client.iter_dialogs(**options):
                entity = dialog.entity
                kind = peer_kind(entity, account)
                if kind is None or getattr(entity,'migrated_to',None):
                    continue
                msg = getattr(dialog,'message',None)
                data = {'id':utils.get_peer_id(entity),'name':clean_text(getattr(dialog,'name','') or 'Unnamed chat'),
                        'kind':kind,'username':clean_text(getattr(entity,'username','') or '') or None,
                        'unread_count':getattr(dialog,'unread_count',0) or 0,
                        'last_message':clean_text(getattr(msg,'message','') or '')[:240],
                        'last_message_id':getattr(msg,'id',None),
                        'last_date':timestamp(getattr(msg,'date',None)),
                        'archived':getattr(dialog,'archived',None), 'cached_at':time.time()}
                self.store().save(account,data)
                last_id = data['id']
                count += 1
                b.emit({'event':'progress','request_id':request_id,'data':{'phase':'chats','index':count}})
            return {'processed':count,'limit':limit,'possibly_more':count == limit,
                    'next_cursor':last_id if count == limit else None}
        if method == 'chats.saved':
            fields(p, set())
            account = await self.identity()
            data = {'id': account, 'name': 'Saved Messages', 'kind': 'saved',
                    'username': None, 'unread_count': 0, 'last_message': '',
                    'last_date': None, 'archived': False, 'cached_at': time.time()}
            self.store().save(account, data)
            return {'chat': data}
        if method == 'messages.list':
            fields(p, {'destination','limit','offset_id','search'}, {'destination'})
            destination = integer(p,'destination')
            limit = integer(p,'limit',default=50,minimum=1,maximum=100)
            offset = integer(p,'offset_id',default=0,minimum=0,maximum=2147483647)
            search = string(p,'search',default='',maximum=256)
            account = await self.identity()
            if self.store().get(account,destination) is None:
                raise IPCError('destination_unavailable','Refresh chats and select an available conversation first.')
            messages=[]
            async for message in b.client.iter_messages(destination,limit=limit,offset_id=offset,search=search or None):
                sender = getattr(message,'sender',None)
                name = utils.get_display_name(sender) if sender is not None else 'Unknown sender'
                media = None
                file = getattr(message,'file',None)
                if file is not None:
                    media={'kind':'image' if getattr(message,'photo',None) else 'document',
                           'name':clean_text(getattr(file,'name','') or ''),'size':getattr(file,'size',None)}
                messages.append({'id':message.id,'text':clean_text(getattr(message,'message','') or '', multiline=True),
                                 'sender_name':clean_text(name),'sender_id':getattr(message,'sender_id',None),
                                 'date':timestamp(getattr(message,'date',None)),
                                 'outgoing':bool(getattr(message,'out',False)),'media':media})
            return {'messages':messages,'next_offset_id':messages[-1]['id'] if messages else offset,
                    'has_more':len(messages)==limit}
        if method == 'media.download':
            fields(p, {'destination', 'message_id', 'path'}, {'destination', 'message_id', 'path'})
            destination = integer(p, 'destination')
            message_id = integer(p, 'message_id', minimum=1, maximum=2147483647)
            output = Path(string(p, 'path', maximum=4096)).expanduser().absolute()
            account = await self.identity()
            if self.store().get(account, destination) is None:
                raise IPCError('destination_unavailable', 'Select a cached conversation first.')
            if output.exists() or output.is_symlink() or not output.parent.is_dir():
                raise IPCError('file_access', 'Choose a new filename in an existing folder. Existing files are never overwritten.')
            message = await b.client.get_messages(destination, ids=message_id)
            file = getattr(message, 'file', None)
            size = getattr(file, 'size', None)
            maximum = 64 * 1024 * 1024
            if type(size) is not int or not 0 < size <= maximum:
                raise IPCError('file_size', 'Only known-size attachments up to 64 MiB can be downloaded.')
            descriptor, temporary = tempfile.mkstemp(prefix='.telegram-download-', dir=output.parent)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    class BoundedOutput:
                        def __init__(self): self.written = 0
                        def write(self, data):
                            if self.written + len(data) > min(size, maximum):
                                raise IPCError('file_size', 'Attachment exceeded its declared size. Download cancelled.')
                            count = stream.write(data); self.written += count; return count
                        def flush(self): stream.flush()
                        def tell(self): return self.written
                    sink = BoundedOutput()
                    def progress(current, total):
                        b.emit({'event': 'progress', 'request_id': request_id,
                                'data': {'phase': 'download', 'index': current, 'total': total}})
                    await b.client.download_media(message, file=sink, progress_callback=progress)
                    if sink.written != size:
                        raise IPCError('download_incomplete', 'Attachment download was incomplete. No final file was created.')
                    stream.flush(); os.fsync(stream.fileno())
                os.link(temporary, output)  # Atomic publication; never overwrites a raced filename.
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {'saved': True, 'bytes': size}
        if method in {'chatdraft.get','chatdraft.save','chatdraft.delete'}:
            fields(p, {'destination','message'} if method=='chatdraft.save' else {'destination'},
                   {'destination','message'} if method=='chatdraft.save' else {'destination'})
            destination=integer(p,'destination');account=b.account()
            if method=='chatdraft.get': return self.store().draft(account,destination)
            message=string(p,'message',maximum=16384) if method=='chatdraft.save' else ''
            if message_units(message) > 4096:
                raise IPCError('invalid_message', 'Draft exceeds 4096 UTF-16 units.')
            b.preview_tokens = {token: preview for token, preview in b.preview_tokens.items()
                                if not (preview.get('kind') == 'personal'
                                        and preview.get('destination') == destination
                                        and preview.get('message') != message)}
            return self.store().save_draft(account,destination,message)
        if method=='chatdraft.list':
            fields(p,set());return self.store().drafts(b.account())
        if method=='labels':
            fields(p,set());return self.store().labels(b.account())
        if method=='label.set':
            fields(p,{'destination','label','enabled'},{'destination','label','enabled'})
            destination=integer(p,'destination'); label=string(p,'label',maximum=40).strip()
            if not label or clean_text(label)!=label:
                raise IPCError('invalid_params','Use a non-empty label without control characters, up to 40 characters.')
            if not b.store.contains_group(b.account(),destination):
                raise IPCError('destination_unavailable','Select a discovered group before adding a local label.')
            self.store().label(b.account(),destination,label,boolean(p,'enabled'))
            return self.store().labels(b.account())
        if method=='chat.preview':
            fields(p,{'account_id','destination','message','reply_to'},{'account_id','destination','message'})
            expected=integer(p,'account_id',minimum=1); destination=integer(p,'destination')
            message=string(p,'message',maximum=16384);validate_message(message)
            reply=integer(p,'reply_to',default=0,minimum=0,maximum=2147483647)
            account=await self.identity(expected);await self.personal_peer(destination)
            b.preview_tokens.clear();token=secrets.token_urlsafe(32);deadline=time.time()+120
            b.preview_tokens[token]={'kind':'personal','account':account,'destination':destination,
                                     'message':message,'reply_to':reply,'deadline':deadline}
            return {'token':token,'account_id':account,'destination':destination,'message':message,
                    'reply_to':reply,'confirmation':f'SEND {destination}','expires_at':deadline}
        if method=='chat.send':
            fields(p,{'account_id','token','confirmation'},{'account_id','token','confirmation'})
            expected=integer(p,'account_id',minimum=1);token=string(p,'token',maximum=128)
            confirmation=string(p,'confirmation',maximum=80)
            preview=b.preview_tokens.pop(token,None)
            if (preview is None or preview.get('kind')!='personal' or preview['deadline']<time.time()
                    or preview['account']!=b.account() or preview['account']!=expected):
                raise IPCError('preview_expired','Account or preview changed. Prepare and confirm a new preview.')
            destination=preview['destination']
            if confirmation!=f'SEND {destination}':
                raise IPCError('confirmation_required','Enter the exact destination confirmation shown in the preview.')
            account=await self.identity(expected);peer=await self.personal_peer(destination)
            delivery,random_id=b.store.reserve(account,destination,preview['message'])
            summary=clean_text(' '.join(preview['message'].splitlines()))
            summary=summary[:160]+('…' if len(summary)>160 else '')
            b.store.delivery_note(account,delivery,summary)
            try:
                response=await b.client(functions.messages.SendMessageRequest(
                    peer=await b.client.get_input_entity(peer),message=preview['message'],random_id=random_id,
                    no_webpage=True,reply_to=types.InputReplyToMessage(preview['reply_to']) if preview['reply_to'] else None))
            except (errors.FloodWaitError,errors.SlowModeWaitError) as exc:
                b.store.set_cooldown(account,time.time()+exc.seconds)
                b.store.finish(delivery,'blocked',type(exc).__name__)
                raise
            except errors.RPCError as exc:
                if isinstance(exc,errors.PeerFloodError): b.store.set_cooldown(account,time.time()+86400)
                b.store.finish(delivery,'uncertain' if isinstance(exc,errors.ServerError) else 'rejected',type(exc).__name__)
                raise
            except BaseException:
                b.store.finish(delivery,'uncertain','Interrupted or transport failure; inspect Telegram manually.')
                raise
            b.store.finish(delivery,'sent','Telegram acknowledged the send request.')
            message_id=getattr(response,'id',None)
            if type(message_id) is int:b.store.delivery_note(account,delivery,summary,message_id)
            return {'message':'Sent; delivery recorded.','delivery':b.store.history(account)[0]}
        raise IPCError('unknown_method','This conversation operation is unsupported.')
