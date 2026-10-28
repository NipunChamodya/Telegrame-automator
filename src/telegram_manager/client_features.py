"""Explicit read-only contacts, profiles and Telegram folder definitions.

These derived caches contain an allowlisted DTO only. Phone numbers, access
hashes and arbitrary Telegram object dictionaries never enter IPC or SQLite.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time

from telethon import functions, types, utils

from .chat_store import ChatStore
from .content_policy import classify_entity, project_dialog
from .terminal import clean_text


def has_photo(entity) -> bool:
    photo = getattr(entity, 'photo', None)
    return photo is not None and not isinstance(photo, (types.UserProfilePhotoEmpty, types.ChatPhotoEmpty, types.PhotoEmpty))


def identity_dto(entity, account: int) -> dict:
    return {'id': utils.get_peer_id(entity), 'name': clean_text(utils.get_display_name(entity))[:256],
            'username': clean_text(getattr(entity, 'username', '') or '')[:64] or None,
            'has_photo': has_photo(entity), 'verified': bool(getattr(entity, 'verified', False)),
            **classify_entity(entity, account)}


CONTACT_FIELDS = {'id', 'name', 'username', 'has_photo', 'verified', 'kind', 'content_known',
                  'content_available', 'content_reason', 'is_bot', 'mutual', 'cached_at'}
FOLDER_FIELDS = {'id', 'title', 'kind', 'checked_at', 'pinned_peer_ids', 'include_peer_ids',
                 'exclude_peer_ids', 'contacts', 'non_contacts', 'groups', 'broadcasts', 'bots',
                 'exclude_muted', 'exclude_read', 'exclude_archived'}


def public_contact(row):
    result = {}
    for key in CONTACT_FIELDS:
        value = row.get(key)
        if key in {'name', 'username', 'content_reason', 'kind'}:
            result[key] = clean_text(value)[:512] if isinstance(value, str) else None
        elif key == 'id':
            result[key] = value if type(value) is int else None
        elif key == 'cached_at':
            result[key] = value if type(value) in (int, float) and math.isfinite(value) else None
        else:
            result[key] = value if type(value) is bool else False
    return result


def public_folder(row):
    result = {}
    for key in FOLDER_FIELDS:
        value = row.get(key)
        if key in {'title', 'kind'}:
            result[key] = clean_text(value)[:128] if isinstance(value, str) else None
        elif key == 'id':
            result[key] = value if type(value) is int else None
        elif key == 'checked_at':
            result[key] = value if type(value) in (int, float) and math.isfinite(value) else None
        elif key.endswith('_peer_ids'):
            result[key] = [identity for identity in value[:1000] if type(identity) is int] if isinstance(value, list) else []
        else:
            result[key] = value if type(value) is bool else None
    return result


class ClientFeatures:
    NETWORK = {'contacts.refresh', 'contacts.open', 'profile.get', 'folders.refresh'}
    METHODS = NETWORK | {'contacts.list', 'folders.list'}
    CONTACT_LIMIT = 1000

    def __init__(self, backend):
        self.backend = backend

    def database(self):
        db = self.backend.store.db
        if getattr(self.backend.store, '_client_tables_ready', False):
            return db
        # Additive derived snapshots only; none of the manager's existing tables
        # are changed, dropped or cleared.
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS contact_cache (
                account INTEGER NOT NULL,user_id INTEGER NOT NULL,name TEXT NOT NULL,
                data TEXT NOT NULL,PRIMARY KEY(account,user_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS telegram_folder_cache (
                account INTEGER NOT NULL,folder_id INTEGER NOT NULL,data TEXT NOT NULL,
                PRIMARY KEY(account,folder_id))''')
        for table, required in [('contact_cache', {'account', 'user_id', 'name', 'data'}),
                                ('telegram_folder_cache', {'account', 'folder_id', 'data'})]:
            if not required.issubset({row[1] for row in db.execute(f'PRAGMA table_info({table})')}):
                raise sqlite3.DatabaseError('Incompatible derived cache schema; no reset performed.')
        db.create_function('client_fold', 1, lambda value: (value or '').casefold(), deterministic=True)
        self.backend.store._client_tables_ready = True
        return db

    def contact(self, account, identity):
        row = self.database().execute('SELECT data FROM contact_cache WHERE account=? AND user_id=?',
                                      (account, identity)).fetchone()
        return json.loads(row[0]) if row else None

    def contacts(self, account, query='', page=0, size=50):
        db = self.database()
        where = "account=? AND instr(client_fold(name || ' ' || COALESCE(json_extract(data,'$.username'),'') || ' ' || user_id),?)>0"
        args = (account, query.casefold())
        total = db.execute('SELECT count(*) FROM contact_cache WHERE '+where, args).fetchone()[0]
        rows = db.execute('SELECT data FROM contact_cache WHERE '+where+
                          ' ORDER BY client_fold(name),user_id LIMIT ? OFFSET ?', (*args, size, page*size))
        return {'contacts': [public_contact(json.loads(row[0])) for row in rows], 'total': total, 'page': page, 'size': size}

    def folders(self, account):
        rows = self.database().execute('SELECT data FROM telegram_folder_cache WHERE account=? ORDER BY folder_id LIMIT 100',
                                       (account,))
        return {'folders': [public_folder(json.loads(row[0])) for row in rows], 'source': 'telegram_read_only',
                'membership_supported': False}

    async def dispatch(self, request_id, method, p):
        from .ipc import IPCError, fields, integer, string
        b = self.backend
        if method == 'contacts.list':
            fields(p, {'query', 'page', 'size'})
            return self.contacts(b.account(), string(p, 'query', default='', maximum=256),
                                 integer(p, 'page', default=0, minimum=0, maximum=100000),
                                 integer(p, 'size', default=50, minimum=1, maximum=100))
        if method == 'folders.list':
            fields(p, set())
            return self.folders(b.account())
        required = {'account_id', 'user_id'} if method == 'contacts.open' else {'account_id', 'peer_id'} if method == 'profile.get' else {'account_id'}
        fields(p, required, required)
        expected = integer(p, 'account_id', minimum=1)
        account = await b.chats.identity(expected)
        db = self.database()
        if method == 'contacts.refresh':
            # Telegram has no limit parameter for this RPC. The server response
            # may be larger; only a bounded membership-verified projection is kept.
            result = await b.client(functions.contacts.GetContactsRequest(hash=0))
            if not isinstance(result, types.contacts.Contacts):
                raise IPCError('metadata_unavailable', 'Telegram did not return a complete contact snapshot. Existing cache was preserved.')
            selected = {contact.user_id: bool(contact.mutual) for contact in result.contacts[:self.CONTACT_LIMIT] if isinstance(contact, types.Contact)}
            values = []
            seen = set()
            for user in result.users:
                if not isinstance(user, types.User) or user.id not in selected or user.id in seen:
                    continue
                seen.add(user.id)
                row = {**identity_dto(user, account), 'mutual': selected[user.id], 'cached_at': time.time()}
                values.append(row)
                if len(values) == self.CONTACT_LIMIT:
                    break
            # Replace only this new derived snapshot. Old manager records and
            # every other account's cache remain untouched.
            with db:
                db.execute('DELETE FROM contact_cache WHERE account=?', (account,))
                db.executemany('INSERT INTO contact_cache VALUES (?,?,?,?)',
                               [(account, row['id'], row['name'], json.dumps(row, ensure_ascii=False)) for row in values])
            return {'processed': len(values), 'cached_count': len(values),
                    'truncated': len(result.contacts) > self.CONTACT_LIMIT, 'incomplete': len(seen) < len(selected)}
        if method == 'contacts.open':
            identity = integer(p, 'user_id', minimum=1)
            if self.contact(account, identity) is None:
                raise IPCError('contact_unavailable', 'Choose a cached contact or refresh contacts first.')
            entity = await b.client.get_entity(identity)
            if not isinstance(entity, types.User) or entity.id != identity:
                raise IPCError('contact_unavailable', 'The returned contact does not match your selection.')
            cache = ChatStore(b.store)
            existing = cache.get(account, identity)
            row = {**(existing or {}), **identity_dto(entity, account), 'unread_count': (existing or {}).get('unread_count'),
                   'last_message': (existing or {}).get('last_message', ''), 'cached_at': time.time()}
            cache.save(account, row)
            return {'chat': project_dialog(row)}
        if method == 'profile.get':
            identity = integer(p, 'peer_id')
            if identity != account and self.contact(account, identity) is None and ChatStore(b.store).get(account, identity) is None:
                raise IPCError('peer_unavailable', 'Choose your account, a cached contact, or a cached conversation first.')
            entity = await b.client.get_entity(identity)
            if not isinstance(entity, (types.User, types.Chat, types.Channel)) or utils.get_peer_id(entity) != identity:
                raise IPCError('peer_unavailable', 'The returned profile does not match your selection.')
            if isinstance(entity, types.User):
                peer = types.InputUserSelf() if identity == account else utils.get_input_user(await b.client.get_input_entity(entity))
                result = await b.client(functions.users.GetFullUserRequest(id=peer))
                full = result.full_user if isinstance(result, types.users.UserFull) else None
                if not isinstance(full, types.UserFull):
                    full = None
            elif isinstance(entity, types.Chat):
                result = await b.client(functions.messages.GetFullChatRequest(chat_id=entity.id))
                full = result.full_chat if isinstance(result, types.messages.ChatFull) else None
                if not isinstance(full, types.ChatFull):
                    full = None
            else:
                peer = utils.get_input_channel(await b.client.get_input_entity(entity))
                result = await b.client(functions.channels.GetFullChannelRequest(channel=peer))
                full = result.full_chat if isinstance(result, types.messages.ChatFull) else None
                if not isinstance(full, types.ChannelFull):
                    full = None
            if full is None or getattr(full, 'id', None) != entity.id:
                raise IPCError('metadata_unavailable', 'Profile details were unavailable or did not match the selected account.')
            source = result.users if isinstance(entity, types.User) else result.chats
            for candidate in source:
                if type(candidate) is type(entity) and utils.get_peer_id(candidate) == identity:
                    entity = candidate
                    break
            members = getattr(full, 'participants_count', None)
            if type(members) is not int:
                members = getattr(entity, 'participants_count', None)
            if type(members) is not int or members < 0 or isinstance(entity, types.User):
                members = None
            return {'profile': {**identity_dto(entity, account),
                    'about': clean_text(getattr(full, 'about', '') or '', multiline=True)[:2048] or None,
                    'members': members, 'checked_at': time.time()}}
        if method == 'folders.refresh':
            result = await b.client(functions.messages.GetDialogFiltersRequest())
            if not isinstance(result, types.messages.DialogFilters):
                raise IPCError('metadata_unavailable', 'Telegram folder metadata was unavailable. Existing cache was preserved.')
            values = []
            def peers(items):
                identities = []
                for peer in items[:1000]:
                    if isinstance(peer, types.InputPeerSelf):
                        identities.append(account)
                    elif isinstance(peer, (types.InputPeerUser, types.InputPeerChat, types.InputPeerChannel)):
                        identities.append(utils.get_peer_id(peer))
                return list(dict.fromkeys(identities))
            for item in result.filters[:100]:
                if isinstance(item, types.DialogFilterDefault):
                    values.append({'id': 0, 'title': 'All Chats', 'kind': 'default', 'checked_at': time.time()})
                    continue
                if not isinstance(item, (types.DialogFilter, types.DialogFilterChatlist)):
                    continue
                title = item.title.text if isinstance(item.title, types.TextWithEntities) else ''
                values.append({'id': item.id, 'title': clean_text(title)[:128],
                    'kind': 'shared' if isinstance(item, types.DialogFilterChatlist) else 'filter',
                    'pinned_peer_ids': peers(item.pinned_peers), 'include_peer_ids': peers(item.include_peers),
                    'exclude_peer_ids': peers(getattr(item, 'exclude_peers', [])),
                    **{flag: getattr(item, flag, None) for flag in ('contacts', 'non_contacts', 'groups', 'broadcasts', 'bots',
                        'exclude_muted', 'exclude_read', 'exclude_archived')}, 'checked_at': time.time()})
            with db:
                db.execute('DELETE FROM telegram_folder_cache WHERE account=?', (account,))
                db.executemany('INSERT INTO telegram_folder_cache VALUES (?,?,?)',
                               [(account, row['id'], json.dumps(row, ensure_ascii=False)) for row in values])
            return {**self.folders(account), 'truncated': len(result.filters) > 100}
        raise IPCError('unknown_method', 'This read-only client feature is unavailable.')
