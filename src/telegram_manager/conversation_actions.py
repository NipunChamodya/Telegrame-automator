"""One confirmed own-text edit/delete, with a separate persistent operation ledger.

Never reuses the send ledger or retries uncertain outcomes. Delete is for the
current account only (revoke=False); deleting for everyone is not exposed.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from datetime import datetime
from typing import TYPE_CHECKING

from telethon import errors, functions, types

from .content_policy import require_message_scope
from .messaging import validate_message
from .models import now

if TYPE_CHECKING:
    from .ipc import Backend


class ConversationActions:
    NETWORK = {'message.action.preview', 'message.action.commit'}
    METHODS = NETWORK | {'message.operations'}

    def __init__(self, backend: Backend):
        self.backend = backend

    def database(self):
        db = self.backend.store.db
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_operations (
                id INTEGER PRIMARY KEY, account INTEGER NOT NULL,
                destination INTEGER NOT NULL, message_id INTEGER NOT NULL,
                action TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, detail TEXT NOT NULL,
                UNIQUE(account,destination,message_id,action,digest))''')
        expected = {'id','account','destination','message_id','action','digest','status','created_at','updated_at','detail'}
        if not expected.issubset({row[1] for row in db.execute('PRAGMA table_info(conversation_operations)')}):
            raise sqlite3.DatabaseError('Incompatible operation ledger; no reset performed.')
        unique_columns = []
        for index in db.execute('PRAGMA index_list(conversation_operations)'):
            if index[2] and not index[4]:
                name = index[1].replace('"', '""')
                unique_columns.append([row[2] for row in db.execute(f'PRAGMA index_info("{name}")')])
        if ['account','destination','message_id','action','digest'] not in unique_columns:
            raise sqlite3.DatabaseError('Operation duplicate protection is missing; no reset performed.')
        return db

    @staticmethod
    def version(message) -> str:
        edited = message.edit_date.isoformat() if isinstance(message.edit_date, datetime) else ''
        return hashlib.sha256((message.message + '\0' + edited).encode('utf-8')).hexdigest()

    async def own_text(self, account: int, destination: int, message_id: int):
        from .ipc import IPCError
        b = self.backend
        await b.chats.identity(account)
        peer = await b.chats.personal_peer(destination)
        message = require_message_scope(await b.client.get_messages(destination, ids=message_id), destination, message_id)
        if (not message.out or message.sender_id != account or not message.message
                or message.media is not None and not isinstance(message.media, types.MessageMediaEmpty)
                or message.entities or message.fwd_from is not None or message.via_bot_id is not None
                or message.post):
            raise IPCError('action_unavailable', 'Only verified own plain-text personal messages are supported for this action.')
        return peer, message

    async def dispatch(self, request_id: str, method: str, p: dict) -> dict:
        from .ipc import IPCError, fields, integer, string
        b = self.backend
        if method == 'message.operations':
            fields(p, set())
            rows = self.database().execute('SELECT * FROM conversation_operations WHERE account=? ORDER BY id DESC LIMIT 100', (b.account(),))
            return {'operations': [dict(row) for row in rows]}
        if method == 'message.action.preview':
            fields(p, {'account_id','destination','message_id','action','message'}, {'account_id','destination','message_id','action'})
            account = integer(p, 'account_id', minimum=1)
            destination = integer(p, 'destination')
            message_id = integer(p, 'message_id', minimum=1, maximum=2147483647)
            action = string(p, 'action', maximum=12)
            if action not in {'edit','delete'}:
                raise IPCError('invalid_params', 'Choose edit or delete; bulk actions are not supported.')
            text = string(p, 'message', maximum=16384) if action == 'edit' else ''
            if action == 'edit': validate_message(text)
            elif 'message' in p:
                raise IPCError('invalid_params', 'Delete has no replacement message field.')
            _, original = await self.own_text(account, destination, message_id)
            if action == 'edit' and original.message == text:
                raise IPCError('unchanged', 'The new text is identical. No edit is necessary.')
            phrase = f'EDIT {message_id} IN {destination}' if action == 'edit' else f'DELETE {message_id} FROM {destination}'
            token = secrets.token_urlsafe(32)
            deadline = time.time() + 120
            b.preview_tokens.clear()
            b.preview_tokens[token] = {'kind':'message_action','action':action,'account':account,
                'destination':destination,'message_id':message_id,'message':text,
                'version':self.version(original),'confirmation':phrase,'deadline':deadline, **b.scope()}
            return {'token':token,'action':action,'account_id':account,'destination':destination,
                    'message_id':message_id,'original_text':original.message,'message':text,
                    'confirmation':phrase,'expires_at':deadline,'delete_for_everyone':False}
        if method != 'message.action.commit':
            raise IPCError('unknown_method', 'This message action is unsupported.')
        fields(p, {'account_id','token','confirmation'}, {'account_id','token','confirmation'})
        account = integer(p, 'account_id', minimum=1)
        preview = b.preview_tokens.pop(string(p, 'token', maximum=128), None)
        if (preview is None or preview.get('kind') != 'message_action' or preview['deadline'] < time.time()
                or preview['account'] != account or b.account() != account
                or any(preview.get(key) != value for key, value in b.scope().items())):
            raise IPCError('preview_expired', 'The account or action preview changed. Prepare a new preview.')
        if string(p, 'confirmation', maximum=128) != preview['confirmation']:
            raise IPCError('confirmation_required', 'Type the exact message-action confirmation shown in the preview.')
        destination, message_id = preview['destination'], preview['message_id']
        peer, original = await self.own_text(account, destination, message_id)
        if self.version(original) != preview['version']:
            raise IPCError('message_changed', 'The message changed after preview. Review its current contents before continuing.')
        action, text = preview['action'], preview['message']
        digest = hashlib.sha256((text if action == 'edit' else 'delete-for-me').encode('utf-8')).hexdigest()
        db = self.database()
        try:
            with db:
                cursor = db.execute('INSERT INTO conversation_operations(account,destination,message_id,action,digest,status,created_at,updated_at,detail) VALUES (?,?,?,?,?,?,?,?,?)',
                    (account,destination,message_id,action,digest,'pending',now(),now(),'Reserved before submission; no automatic retry.'))
                operation = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            if getattr(exc, 'sqlite_errorname', '') != 'SQLITE_CONSTRAINT_UNIQUE':
                raise
            raise IPCError('operation_duplicate', 'This exact action has a previous operation record. Inspect Telegram manually; it was not retried.') from None
        def finish(status: str, detail: str) -> dict:
            with db:
                db.execute('UPDATE conversation_operations SET status=?,updated_at=?,detail=? WHERE id=? AND account=?', (status,now(),detail,operation,account))
            row = db.execute('SELECT * FROM conversation_operations WHERE id=? AND account=?', (operation,account)).fetchone()
            return {'operation':dict(row)}
        try:
            if action == 'edit':
                await b.client(functions.messages.EditMessageRequest(peer=await b.client.get_input_entity(peer), id=message_id, message=text, entities=[], no_webpage=True))
            else:
                # Strictly personal/Saved Messages; never revoke another participant's copy.
                await b.client(functions.messages.DeleteMessagesRequest(id=[message_id], revoke=False))
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            b.store.set_cooldown(account, time.time() + exc.seconds)
            finish('rejected', type(exc).__name__)
            raise
        except errors.RPCError as exc:
            if isinstance(exc, errors.PeerFloodError): b.store.set_cooldown(account, time.time()+86400)
            finish('uncertain' if isinstance(exc, errors.ServerError) else 'rejected', type(exc).__name__)
            raise
        except BaseException:
            finish('uncertain', 'Interrupted or transport failure. Check Telegram manually; no retry.')
            raise
        return finish('acknowledged', 'Telegram acknowledged the edit.' if action == 'edit' else 'Telegram acknowledged deletion for the current account only.')
