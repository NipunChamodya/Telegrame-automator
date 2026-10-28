"""One bounded, scope-frozen projection for the active runtime Telegram client."""
import asyncio
import contextlib
import inspect
import time
import uuid
from collections import OrderedDict

from telethon import events, functions, types, utils, errors

from .chat_store import ChatStore
from .content_policy import project_dialog, require_content_peer
from .message_projection import normalize_message


class UpdatePipeline:
    METHODS = {'updates.watch', 'updates.unwatch', 'sync.snapshot', 'messages.read', 'messages.typing'}
    NETWORK = METHODS
    CAPACITY = 256
    MESSAGE_LIMIT = 200

    def __init__(self, backend):
        self.backend = backend
        self.client = backend.client
        self.scope = {**backend.scope(), 'account_id': backend.account(), 'stream_id': uuid.uuid4().hex}
        self.queue = asyncio.Queue(maxsize=self.CAPACITY)
        self.messages = OrderedDict()
        self.deleted = OrderedDict()
        self.sequence = 0
        self.epoch = 0
        self.dirty = True  # Runtime connects before handlers: initial snapshot is required.
        self.watching = False
        self.peer_id = None
        self.visible = set()
        self.read_max = 0
        self.last_typing = 0.0
        self.worker = None
        self.handlers = []
        self.closed = False
        self.dirty_reported = False

    def current(self):
        b = self.backend
        return (not self.closed and b.client is self.client and b.scope() == {
            k: self.scope[k] for k in ('profile_id', 'account_generation')}
            and b.config.get('account_id') == self.scope['account_id']
            and b.auth_stage == 'connected' and b.service is not None)

    async def start(self):
        if self.worker is not None or self.closed:
            return
        for kind, builder in [('new', events.NewMessage), ('edit', events.MessageEdited),
                              ('delete', events.MessageDeleted), ('read', events.MessageRead),
                              ('typing', events.UserUpdate)]:
            async def handler(event, kind=kind):
                await self.ingest(kind, event)
            self.handlers.append(handler)
            result = self.client.add_event_handler(handler, builder())
            if inspect.isawaitable(result):
                await result
        self.worker = asyncio.create_task(self._work())
        # Public catch_up schedules recovery; it does not certify replay completion.
        await self.client.catch_up()

    async def _cancel_typing(self):
        if self.last_typing and self.current() and self.peer_id is not None:
            try:
                async def cancel():
                    peer = await self.client.get_input_entity(self.peer_id)
                    await self.client(functions.messages.SetTypingRequest(peer=peer, action=types.SendMessageCancelAction()))
                await asyncio.wait_for(cancel(), timeout=1)
            except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
                self.backend.store.set_cooldown(self.scope['account_id'], time.time()+exc.seconds)
            except (OSError, errors.RPCError, TimeoutError):
                pass
        self.last_typing = 0

    async def stop(self):
        await self._cancel_typing()
        self.closed = True
        self.watching = False
        for handler in self.handlers:
            result = self.client.remove_event_handler(handler)
            if inspect.isawaitable(result):
                await result
        self.handlers.clear()
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker
            self.worker = None
        self.messages.clear()
        self.deleted.clear()
        self.visible.clear()
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()

    def publish(self, name, payload):
        if not self.current() or not self.watching:
            return
        self.sequence += 1
        self.backend.emit_control({'event': name, 'data': {
            **self.scope, 'sequence': self.sequence, **payload}})

    def mark_dirty(self, reason):
        if not self.current():
            return
        self.backend._close_media()
        self.dirty = True
        if not self.dirty_reported:
            self.dirty_reported = True
            self.publish('sync.required', {'reason': reason, 'peer_id': self.peer_id})

    async def ingest(self, kind, event):
        if not self.current():
            return
        if kind == 'typing' and not getattr(event, 'typing', False) and not getattr(event, 'cancel', False):
            return
        peer = getattr(event, 'chat_id', None)
        if kind == 'delete' and peer is None:
            self.mark_dirty('ambiguous_delete')
            return
        row = ChatStore(self.backend.store).get(self.scope['account_id'], peer) if type(peer) is int else None
        # Never resolve unknown peers or expose channel/bot/unknown content from
        # the event path. A deliberate snapshot/refresh verifies their support.
        if row is None:
            if kind in {'new', 'edit'}:
                self.mark_dirty('gap')
            return
        if not project_dialog(row)['content_available']:
            if row.get('content_known') is not True and kind in {'new', 'edit'}:
                self.mark_dirty('gap')
            return
        payload = {'peer_id': peer}
        if kind in {'new', 'edit'}:
            message = getattr(event, 'message', None)
            if message is None:
                self.mark_dirty('gap')
                return
            if getattr(message, 'peer_id', None) is None or utils.get_peer_id(message.peer_id) != peer:
                self.mark_dirty('gap')
                return
            payload.update(message=normalize_message(message, self.scope['account_id'], row.get('kind')), change=kind)
        elif kind == 'delete':
            payload['message_ids'] = [i for i in getattr(event, 'deleted_ids', [])[:100] if type(i) is int]
        elif kind == 'read':
            payload.update(max_id=getattr(event, 'max_id', 0), outbox=bool(getattr(event, 'outbox', False)))
        elif kind == 'typing':
            # UserUpdate also represents presence; only actual typing is projected.
            if not getattr(event, 'typing', False) and not getattr(event, 'cancel', False):
                return
            payload.update(user_id=getattr(event, 'user_id', None),
                           active=bool(getattr(event, 'typing', False)), expires_at=time.time()+6)
        else:
            return
        try:
            self.queue.put_nowait((self.epoch, kind, payload))
        except asyncio.QueueFull:
            self.mark_dirty('overflow')

    async def _work(self):
        while True:
            epoch, kind, payload = await self.queue.get()
            try:
                async with self.backend.lock:
                    if self.current() and epoch == self.epoch:
                        self._apply(kind, payload)
            except Exception:
                # Data cannot be certified complete after a malformed update or
                # failed short projection write. No raw event/error is logged.
                self.mark_dirty('gap')
            finally:
                self.queue.task_done()

    def _apply(self, kind, payload):
        peer = payload['peer_id']
        cache = ChatStore(self.backend.store)
        row = cache.get(self.scope['account_id'], peer)
        if row is None:
            self.mark_dirty('gap')
            return
        if kind in {'new', 'edit'}:
            message = payload['message']
            identity = message['id']
            if type(identity) is not int:
                self.mark_dirty('gap')
                return
            key = (peer, identity)
            if key in self.deleted:
                return
            previous = self.messages.get(key)
            if previous == message:
                return
            if previous is not None and not previous.get('content_available') and message.get('content_available'):
                self.mark_dirty('gap')
                return
            if previous is None and message.get('content_available') and identity <= (row.get('last_message_id') or 0):
                self.mark_dirty('gap')
                return
            if previous and message.get('content_available') and (previous.get('edit_date') or previous.get('date') or '') > (message.get('edit_date') or message.get('date') or ''):
                return
            if kind == 'edit':
                try:
                    self.backend.media.invalidate(peer, [identity])
                except OSError:
                    self.mark_dirty('gap')
            self.messages[key] = message
            self.messages.move_to_end(key)
            while len(self.messages) > self.MESSAGE_LIMIT:
                self.messages.popitem(last=False)
            if identity >= (row.get('last_message_id') or 0):
                if kind == 'new' and identity > (row.get('last_message_id') or 0) and not message['outgoing'] and type(row.get('unread_count')) is int:
                    row['unread_count'] += 1
                row.update(last_message=message['text'][:240], last_message_id=identity,
                           last_date=message.get('date'), cached_at=time.time())
                cache.save(self.scope['account_id'], row)
                self.publish('chat.changed', {'peer_id': peer, 'chat': project_dialog(row)})
            if peer == self.peer_id:
                if message.get('content_available') and not message['outgoing']:
                    self.visible.add(identity)
                    if len(self.visible) > self.MESSAGE_LIMIT:
                        self.visible = set(sorted(self.visible)[-self.MESSAGE_LIMIT:])
                self.publish('message.changed', payload)
        elif kind == 'delete':
            try:
                self.backend.media.invalidate(peer, payload['message_ids'])
            except OSError:
                self.mark_dirty('gap')
            for identity in payload['message_ids']:
                self.messages.pop((peer, identity), None)
                self.deleted[(peer, identity)] = None
                while len(self.deleted) > self.MESSAGE_LIMIT:
                    self.deleted.popitem(last=False)
                    self.mark_dirty('gap')
                if peer == self.peer_id:
                    self.visible.discard(identity)
            if row.get('last_message_id') in payload['message_ids']:
                row['last_message'] = ''
                cache.save(self.scope['account_id'], row)
                self.publish('chat.changed', {'peer_id': peer, 'chat': project_dialog(row)})
            if peer == self.peer_id:
                self.publish('message.deleted', payload)
        elif kind == 'read':
            field = 'read_outbox_max_id' if payload['outbox'] else 'read_inbox_max_id'
            maximum = payload['max_id']
            if type(maximum) is not int or maximum <= (row.get(field) or 0):
                return
            row[field] = maximum
            cache.save(self.scope['account_id'], row)
            self.publish('read.changed', payload)
        elif peer == self.peer_id:
            self.publish('typing.changed', payload)

    def record_visible(self, peer, messages):
        if self.current() and self.watching and peer == self.peer_id:
            self.visible = {row['id'] for row in messages if type(row.get('id')) is int
                            and not row.get('outgoing') and row.get('content_available') is True}

    async def dispatch(self, request_id, method, p):
        from .ipc import IPCError, fields, integer, boolean
        fields(p, {'account_id', 'peer_id', 'limit'} if method == 'sync.snapshot' else
               {'account_id', 'peer_id'} if method == 'updates.watch' else
               {'account_id'} if method == 'updates.unwatch' else
               {'account_id', 'peer_id', 'max_id'} if method == 'messages.read' else
               {'account_id', 'peer_id', 'active'},
               {'account_id', 'peer_id', 'max_id'} if method == 'messages.read' else
               {'account_id', 'peer_id', 'active'} if method == 'messages.typing' else {'account_id'})
        expected = integer(p, 'account_id', minimum=1)
        if not self.current() or expected != self.scope['account_id']:
            raise IPCError('account_changed', 'The active account changed. Reconnect and select the conversation again.')
        peer = integer(p, 'peer_id') if 'peer_id' in p else None
        if method == 'updates.unwatch':
            await self._cancel_typing()
            self.watching = False
            self.peer_id = None
            self.visible.clear()
            return self.result()
        if method == 'updates.watch':
            if peer is not None:
                await self.backend.chats.identity(expected)
                await require_content_peer(self.client, expected, peer)
            if peer != self.peer_id:
                await self._cancel_typing()
                self.visible.clear()
                self.read_max = 0
            self.peer_id = peer
            self.watching = True
            self.dirty_reported = False
            if self.dirty:
                self.mark_dirty('reconnect')
            return self.result()
        if not self.watching or peer != self.peer_id:
            raise IPCError('conversation_changed', 'Select and watch this conversation before continuing.')
        if method == 'sync.snapshot':
            self.epoch += 1  # Invalidate queued projections older than this authoritative fetch.
            limit = integer(p, 'limit', default=50, minimum=1, maximum=100)
            rows = []
            if peer is not None:
                result = await self.backend.chats.dispatch(request_id, 'messages.list', {'destination': peer, 'limit': limit})
                rows = [row for row in result['messages'] if (peer, row['id']) not in self.deleted]
                self.record_visible(peer, rows)
                for key in list(self.messages):
                    if key[0] == peer:
                        del self.messages[key]
                for row in rows:
                    self.messages[(peer, row['id'])] = row
                while len(self.messages) > self.MESSAGE_LIMIT:
                    self.messages.popitem(last=False)
            else:
                await self.backend.chats.dispatch(request_id, 'chats.refresh', {'limit': limit})
            # A queued update may postdate this snapshot. Drain ordering cannot be
            # certified while work is pending, so retain the dirty marker then.
            self.dirty = not self.queue.empty()
            self.dirty_reported = False
            chats = ChatStore(self.backend.store).page(expected, size=limit, sort='recent')['chats']
            return {**self.result(), 'chats': [project_dialog(row) for row in chats], 'messages': rows}
        if peer is None:
            raise IPCError('invalid_params', 'Select a conversation first.')
        await self.backend.chats.identity(expected)
        entity = await require_content_peer(self.client, expected, peer)
        if method == 'messages.read':
            maximum = integer(p, 'max_id', minimum=1, maximum=2147483647)
            if maximum not in self.visible:
                raise IPCError('unseen_message', 'Only incoming messages returned for the visible conversation can be marked read.')
            acknowledged = await self.client.send_read_acknowledge(entity, max_id=maximum)
            if acknowledged is False or acknowledged is None:
                raise IPCError('read_unconfirmed', 'Telegram did not confirm the read acknowledgement.')
            self.read_max = max(self.read_max, maximum)
            return {**self.result(), 'max_id': maximum, 'acknowledged': True}
        active = boolean(p, 'active')
        now = time.monotonic()
        if active and now-self.last_typing < 4:
            return {**self.result(), 'accepted': False}
        action = types.SendMessageTypingAction() if active else types.SendMessageCancelAction()
        accepted = await self.client(functions.messages.SetTypingRequest(peer=await self.client.get_input_entity(entity), action=action))
        if accepted is False or accepted is None:
            return {**self.result(), 'accepted': False}
        self.last_typing = now if active else 0
        return {**self.result(), 'accepted': True}

    def result(self):
        return {**self.scope, 'watching': self.watching, 'sequence': self.sequence,
                'dirty': self.dirty, 'peer_id': self.peer_id,
                'freshness_scope': 'conversation' if self.peer_id is not None else 'dialogs',
                'history_complete': False}
