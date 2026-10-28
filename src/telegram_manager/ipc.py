"""Private, framed JSON IPC adapter for the native app. No HTTP listener or CLI prompts.

Run with ``python -u -m telegram_manager.ipc``. One process holds the existing
application lock and serializes Telegram/mutating operations. Stdout is protocol
only. Request failures never include exception args or Telegram request reprs.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect as pyinspect
import json
import logging
import math
import os
import platform
import re
import secrets
import sqlite3
import sys
import tempfile
import time
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from telethon import TelegramClient, errors

from .cache import CachePolicy
from .configuration import (
    Credentials, bind_account, data_directory, keychain_service,
    load_configuration, resolve_credentials,
)
from .error_messages import telegram_error_message
from .security import ApplicationBusy, KeychainError, MacKeychain, application_lock, private_directory
from .setup_wizard import AUTH_CONNECTION_RETRIES, AUTH_REQUEST_RETRIES, normalize_phone
from .storage import DuplicateMessage, Store
from .telegram import TelegramService
from .terminal import clean_text

VERSION = '0.2.0'
MAX_FRAME = 1024 * 1024
MAX_REQUESTS = 64
LOG = logging.getLogger('telegram_manager.ipc')


class IPCError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def strict_json(data: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    result = json.loads(data, object_pairs_hook=pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite number')))
    if not isinstance(result, dict):
        raise ValueError('Object required')
    return result


def fields(params: dict, allowed: set[str], required: set[str] = frozenset()) -> None:
    if set(params) - allowed or required - set(params):
        raise IPCError('invalid_params', 'Missing or unsupported request parameters.')


def string(params: dict, name: str, default: str | None = None, *, maximum: int = 16384) -> str:
    value = params.get(name, default)
    if not isinstance(value, str) or len(value) > maximum:
        raise IPCError('invalid_params', f'{name} must be text within the supported length.')
    return value


def integer(params: dict, name: str, default: int | None = None, *, minimum: int = -(2**63), maximum: int = 2**63-1) -> int:
    value = params.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise IPCError('invalid_params', f'{name} must be an integer within the supported range.')
    return value


def boolean(params: dict, name: str, default: bool = False) -> bool:
    value = params.get(name, default)
    if type(value) is not bool:
        raise IPCError('invalid_params', f'{name} must be true or false.')
    return value


def validate_message(value: str) -> int:
    try:
        units = len(value.encode('utf-16-le')) // 2
    except UnicodeError:
        raise IPCError('invalid_message', 'The message contains invalid Unicode.') from None
    if not value.strip() or units > 4096:
        raise IPCError('invalid_message', 'Enter a message containing 1–4096 UTF-16 units of text.')
    return units


def safe_group(data: dict, policy: CachePolicy) -> dict:
    result = dict(data)
    for name in ('name', 'username'):
        if isinstance(result.get(name), str):
            result[name] = clean_text(result[name])
    result['effective_permission'] = policy.permission(data)
    result['metadata_fresh'] = policy.details_fresh(data)
    return result


class Backend:
    """Backend state, usable directly in tests without opening user data."""
    NETWORK = {'connect', 'auth.credentials', 'auth.phone', 'auth.code', 'auth.password', 'auth.bind',
               'discover', 'inspect', 'inspect_pending', 'preview', 'send',
               'draft.save', 'approval.set', 'storage.backup', 'diagnostics.export', 'settings.update'}
    METHODS = NETWORK | {'health', 'status', 'settings', 'groups', 'detail', 'draft.get',
                         'approvals', 'history', 'cancel', 'shutdown'}
    ALIASES = {'groups.list': 'groups', 'groups.get': 'detail', 'destinations.list': 'approvals'}

    def __init__(self, root: Path, store: Store, config: dict, *, client_factory=TelegramClient,
                 emitter: Callable[[dict], None] | None = None):
        self.root, self.store, self.config = root, store, config
        self.client_factory = client_factory
        self.emit = emitter or (lambda event: None)
        self.policy = CachePolicy.from_environment()
        self.inspection_limit = 10
        preferences = root / 'desktop-settings.json'
        if preferences.exists():
            try:
                saved = strict_json(preferences.read_text(encoding='utf-8'))
                self._validate_preferences(saved)
                self.policy = CachePolicy(**saved.get('cache_policy', asdict(self.policy)))
                self.inspection_limit = saved.get('inspection_limit', 10)
            except (ValueError, UnicodeError, IPCError):
                raise IPCError('settings_invalid', 'Desktop settings are invalid and were left unchanged. Restore a valid settings file.') from None
        self.client = None
        self.service: TelegramService | None = None
        self.me = None
        self.credentials: Credentials | None = None
        self.credential_source = 'not loaded'
        self.auth_stage = 'disconnected'
        self.phone: str | None = None
        self.phone_code_hash: str | None = None
        self.preview_tokens: dict[str, dict] = {}
        self.lock = asyncio.Lock()
        self.closing = False

    @staticmethod
    def _validate_preferences(p: dict) -> None:
        fields(p, {'cache_policy', 'inspection_limit'})
        if 'inspection_limit' in p:
            integer(p, 'inspection_limit', minimum=1, maximum=100)
        if 'cache_policy' in p:
            cache = p['cache_policy']
            if not isinstance(cache, dict):
                raise IPCError('invalid_params', 'cache_policy must be an object.')
            fields(cache, {'basic', 'permissions', 'members', 'metadata'})
            for key in cache:
                integer(cache, key, minimum=0, maximum=31536000)

    def _save_preferences(self, p: dict) -> None:
        self._validate_preferences(p)
        updated = {'cache_policy': asdict(self.policy) | p.get('cache_policy', {}),
                   'inspection_limit': p.get('inspection_limit', self.inspection_limit)}
        descriptor, temporary = tempfile.mkstemp(prefix='.desktop-settings-', dir=self.root)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(updated, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.root / 'desktop-settings.json')
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.policy = CachePolicy(**updated['cache_policy'])
        self.inspection_limit = updated['inspection_limit']
        if self.service is not None:
            self.service.policy = self.policy

    def account(self) -> int:
        account = self.config.get('account_id')
        if type(account) is not int:
            raise IPCError('not_bound', 'Connect and explicitly confirm the account before accessing account data.')
        return account

    def connected_service(self) -> TelegramService:
        if self.service is None or self.auth_stage != 'connected':
            raise IPCError('not_connected', 'Connect Telegram before starting this operation.')
        return self.service

    def require_cooldown_expired(self) -> None:
        until = max(self.store.cooldown(0), self.store.cooldown(self.config.get('account_id') or 0))
        remaining = max(0, math.ceil(until - time.time()))
        if remaining:
            raise IPCError('cooldown', f'Telegram requires waiting {remaining} seconds before continuing.')

    def status(self) -> dict:
        account = self.config.get('account_id')
        empty = dict(total=0, allowed=0, denied=0, unknown=0, complete=0, incomplete=0, pending=0, fresh=0, last_seen=None)
        until = max(self.store.cooldown(0), self.store.cooldown(account or 0))
        user = None
        if self.me is not None:
            name = ' '.join(v for v in (getattr(self.me, 'first_name', None), getattr(self.me, 'last_name', None)) if v)
            user = {'id': self.me.id, 'display_name': clean_text(name) or 'Telegram account'}
        return {'connected': self.auth_stage == 'connected' and self.service is not None
                            and self.client is not None and self.client.is_connected(),
                'auth_stage': self.auth_stage, 'account': user, 'bound_account_id': account,
                'overview': self.store.overview(account, self.policy) if account is not None else empty,
                'scan': self.store.scan(account) if account is not None else {},
                'cooldown_until': until, 'remaining_seconds': max(0, math.ceil(until - time.time())),
                'session_present': (self.root / 'account.session').is_file()}

    def progress(self, request_id: str, phase: str):
        def callback(index, group, skipped=False):
            self.emit({'event': 'progress', 'request_id': request_id,
                       'data': {'phase': phase, 'index': index, 'skipped': skipped,
                                'group': safe_group(group.data(), self.policy)}})
        return callback

    async def _new_client(self, *, authentication: bool) -> None:
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
        self.service = None
        assert self.credentials is not None
        self.client = self.client_factory(str(self.root / 'account'), self.credentials.api_id,
            self.credentials.api_hash, request_retries=AUTH_REQUEST_RETRIES if authentication else 0,
            connection_retries=AUTH_CONNECTION_RETRIES if authentication else 0,
            auto_reconnect=False, flood_sleep_threshold=0, receive_updates=not authentication,
            raise_last_call_error=True)
        await self.client.connect()

    async def _authorized(self) -> dict:
        me = await self.client.get_me()
        if me is None or getattr(me, 'bot', False) or getattr(me, 'deleted', False):
            raise IPCError('invalid_account', 'An active personal Telegram account is required.')
        expected = self.config.get('account_id')
        if expected is not None and expected != me.id:
            raise IPCError('account_mismatch', 'This session does not match the bound account. Existing data was preserved.')
        self.me = me
        self.phone = self.phone_code_hash = None
        if expected is None:
            self.auth_stage = 'bind_account'
            return self.status()
        # Constructor retry policy cannot be changed through a supported public
        # setter: reopen the SAME session sequentially before delivery-capable work.
        await self._new_client(authentication=False)
        if not await self.client.is_user_authorized():
            self.auth_stage = 'phone'
            raise IPCError('authorization_expired', 'Authorization expired. Reconnect to sign in; no session was deleted.')
        restored = await self.client.get_me()
        if restored is None or restored.id != expected:
            raise IPCError('account_mismatch', 'Account identity changed while restoring the session. Sending remains blocked.')
        self.me = restored
        self.service = TelegramService(self.client, self.store, restored)
        self.service.policy = self.policy
        self.auth_stage = 'connected'
        return self.status()

    async def connect(self) -> dict:
        if self.service is not None and self.auth_stage == 'connected':
            if self.client is not None and self.client.is_connected():
                return self.status()
            self.service = None
            self.auth_stage = 'disconnected'
        self.require_cooldown_expired()
        if self.credentials is None:
            try:
                self.credentials, self.credential_source = await asyncio.to_thread(resolve_credentials, self.root)
            except (KeychainError, OSError):
                self.auth_stage = 'credentials'
                return self.status()
        if self.credentials is None:
            self.auth_stage = 'credentials'
            return self.status()
        await self._new_client(authentication=True)
        if await self.client.is_user_authorized():
            return await self._authorized()
        self.auth_stage = 'phone'
        return self.status()

    def _client_for_auth(self, stage: str) -> None:
        self.require_cooldown_expired()
        if self.client is None or self.auth_stage != stage:
            raise IPCError('auth_state', 'This authentication step is not currently required. Reconnect if necessary.')

    async def dispatch(self, request_id: str, method: str, params: dict) -> dict:
        method = self.ALIASES.get(method, method)
        if method in {'destinations.approve', 'destinations.revoke'}:
            fields(params, {'destination'}, {'destination'})
            params = params | {'approved': method.endswith('approve')}
            method = 'approval.set'
        if method not in self.METHODS:
            raise IPCError('unknown_method', 'This operation is not supported.')
        if method in self.NETWORK:
            async with self.lock:
                return await self._dispatch(request_id, method, params)
        return await self._dispatch(request_id, method, params)

    async def _dispatch(self, request_id: str, method: str, p: dict) -> dict:
        if method in {'health', 'status', 'settings', 'connect', 'draft.get', 'shutdown'}:
            fields(p, set())
        if method == 'health':
            return {'protocol_version': 1, 'version': VERSION, 'python_version': platform.python_version(), 'ready': True}
        if method == 'status':
            return self.status()
        if method == 'settings':
            return {'storage_location': str(self.root), 'version': VERSION,
                    'python_version': platform.python_version(), 'cache_policy': asdict(self.policy),
                    'inspection_limit': self.inspection_limit, 'session_present': (self.root / 'account.session').is_file(),
                    'bound_account_id': self.config.get('account_id'), 'keychain_supported': platform.system() == 'Darwin',
                    'credential_source': self.credential_source,
                    'security': {'local_ipc': True, 'explicit_approval': True, 'uncertain_retries': False}}
        if method == 'settings.update':
            self._save_preferences(p)
            return await self._dispatch(request_id, 'settings', {})
        if method == 'connect':
            return await self.connect()
        if method == 'auth.credentials':
            fields(p, {'api_id', 'api_hash', 'save'}, {'api_id', 'api_hash'})
            try:
                api_id = Credentials.validate_id(string(p, 'api_id', maximum=64))
            except ValueError as exc:
                raise IPCError('invalid_api_id', str(exc)) from None
            try:
                api_hash = Credentials.validate_hash(string(p, 'api_hash', maximum=128))
            except ValueError as exc:
                raise IPCError('invalid_api_hash', str(exc)) from None
            credentials = Credentials(api_id, api_hash)
            if self.auth_stage not in {'credentials', 'disconnected'}:
                raise IPCError('auth_state', 'Existing credentials were not replaced. Disconnect/relaunch to change configuration.')
            if boolean(p, 'save'):
                keychain = MacKeychain(keychain_service(self.root))
                await asyncio.to_thread(keychain.save_new, json.dumps({'api_id': credentials.api_id, 'api_hash': credentials.api_hash}))
                self.credential_source = 'macOS Keychain'
            else:
                self.credential_source = 'memory only'
            self.credentials = credentials
            return await self.connect()
        if method == 'auth.phone':
            fields(p, {'phone'}, {'phone'})
            self._client_for_auth('phone')
            try:
                phone = normalize_phone(string(p, 'phone', maximum=64))
            except ValueError as exc:
                raise IPCError('invalid_phone', str(exc)) from None
            sent = await self.client.send_code_request(phone)
            self.phone, self.phone_code_hash = phone, sent.phone_code_hash
            self.auth_stage = 'code'
            return self.status()
        if method == 'auth.code':
            fields(p, {'code'}, {'code'})
            self._client_for_auth('code')
            code = string(p, 'code', maximum=32).strip()
            if not re.fullmatch(r'[0-9]{3,12}', code):
                raise IPCError('invalid_code', 'Enter the numeric Telegram verification code.')
            try:
                await self.client.sign_in(phone=self.phone, code=code, phone_code_hash=self.phone_code_hash)
            except errors.SessionPasswordNeededError:
                self.auth_stage = 'password'
                return self.status()
            return await self._authorized()
        if method == 'auth.password':
            fields(p, {'password'}, {'password'})
            self._client_for_auth('password')
            await self.client.sign_in(password=string(p, 'password', maximum=1024))
            return await self._authorized()
        if method == 'auth.bind':
            fields(p, {'account_id', 'confirm'}, {'account_id', 'confirm'})
            account = integer(p, 'account_id', minimum=1)
            if self.auth_stage != 'bind_account' or self.me is None or self.me.id != account or not boolean(p, 'confirm'):
                raise IPCError('confirmation_required', 'Explicitly confirm the verified account ID before binding.')
            bind_account(self.root, self.config, account)
            return await self._authorized()
        if method == 'groups':
            fields(p, {'query', 'permission', 'sort', 'kind', 'page', 'size'})
            account = self.account()
            page = integer(p, 'page', 0, minimum=0, maximum=1000000)
            size = integer(p, 'size', 50, minimum=1, maximum=100)
            rows, total = self.store.page(account, query=string(p, 'query', '', maximum=512),
                permission=string(p, 'permission', 'all', maximum=16), sort=string(p, 'sort', 'name', maximum=16),
                group_type=string(p, 'kind', 'all', maximum=16), page=page, size=size, policy=self.policy)
            return {'groups': [safe_group(g, self.policy) for g in rows], 'total': total, 'page': page, 'size': size}
        if method in {'detail', 'inspect', 'approval.set'}:
            fields(p, {'destination', 'approved'} if method == 'approval.set' else {'destination'}, {'destination'})
            account, destination = self.account(), integer(p, 'destination')
            group = self.store.get_group(account, destination)
            if group is None:
                raise IPCError('group_unavailable', 'Choose an existing discovered group by its Telegram ID.')
            if method == 'inspect':
                group = (await self.connected_service().inspect(destination, force=True)).data()
            if method == 'approval.set':
                fields(p, {'destination', 'approved'}, {'destination', 'approved'})
                approved = boolean(p, 'approved')
                self.store.set_approval(account, destination, approved)
                self.preview_tokens.clear()
                return {'destination': destination, 'approved': approved}
            return {'group': safe_group(group, self.policy)}
        if method == 'discover':
            fields(p, set())
            service = self.connected_service()
            count = await service.discover(on_group=self.progress(request_id, 'discovery'))
            return {'processed': count, 'scan': self.store.scan(self.account())}
        if method == 'inspect_pending':
            fields(p, {'limit', 'destinations', 'force'}, {'limit'})
            limit = integer(p, 'limit', minimum=1, maximum=100)
            destinations = p.get('destinations')
            if destinations is not None and (not isinstance(destinations, list) or len(destinations) > 100
                    or any(type(d) is not int or not -(2**63) <= d < 2**63 for d in destinations)):
                raise IPCError('invalid_params', 'destinations must be a bounded list of integer group IDs.')
            count = await self.connected_service().inspect_pending(limit=limit, destinations=destinations,
                force=boolean(p, 'force'), on_inspected=self.progress(request_id, 'inspection'))
            return {'inspected': count, 'scan': self.store.scan(self.account())}
        if method == 'draft.get':
            return self.store.draft(self.account())
        if method == 'draft.save':
            fields(p, {'message'}, {'message'})
            message = string(p, 'message', maximum=16384)
            # Empty drafts may be saved, but never previewed or sent.
            if len(message.encode('utf-16-le')) // 2 > 4096:
                raise IPCError('invalid_message', 'Draft exceeds 4096 UTF-16 units.')
            self.store.save_draft(self.account(), message)
            self.preview_tokens.clear()
            return self.store.draft(self.account())
        if method == 'approvals':
            fields(p, {'query'})
            rows = self.store.approvals(self.account(), string(p, 'query', '', maximum=512))
            return {'groups': [safe_group(g, self.policy) for g in rows]}
        if method == 'preview':
            fields(p, {'destination', 'message'}, {'destination', 'message'})
            service = self.connected_service()
            account, destination = self.account(), integer(p, 'destination')
            message = string(p, 'message')
            units = validate_message(message)
            if not self.store.is_approved(account, destination):
                raise IPCError('destination_not_approved', 'Explicitly approve this destination before preparing a send.')
            group = await service.inspect(destination, force=True)
            if group.permission != 'allowed':
                raise IPCError('permission_blocked', 'Current posting permission is not allowed for this destination.')
            if group.slowmode_next_send and group.slowmode_next_send > time.time():
                raise IPCError('slow_mode', 'Telegram slow mode is active. Wait before preparing the message.')
            self.preview_tokens.clear()
            token, deadline = secrets.token_urlsafe(32), time.time() + 120
            self.preview_tokens[token] = {'account': account, 'destination': destination,
                'message': message, 'digest': hashlib.sha256(message.encode()).hexdigest(), 'deadline': deadline}
            return {'token': token, 'expires_at': deadline, 'destination': destination,
                    'message': message, 'group': safe_group(group.data(), self.policy),
                    'confirmation': f'SEND {destination}', 'utf16_units': units}
        if method == 'send':
            fields(p, {'token', 'confirmation'}, {'token', 'confirmation'})
            token = string(p, 'token', maximum=128)
            preview = self.preview_tokens.pop(token, None)  # One use, including failed confirmation.
            if preview is None or preview['deadline'] < time.time() or preview['account'] != self.account():
                raise IPCError('preview_expired', 'Preview expired or was consumed. Prepare and confirm a new preview.')
            destination = preview['destination']
            if string(p, 'confirmation', maximum=64) != f'SEND {destination}':
                raise IPCError('confirmation_required', 'Enter the exact destination confirmation shown in the preview.')
            if not self.store.is_approved(self.account(), destination):
                raise IPCError('destination_not_approved', 'The destination approval was revoked. Nothing was sent.')
            result = await self.connected_service().send(destination, preview['message'])
            history = self.store.history(self.account())
            return {'message': result, 'delivery': history[0] if history else None}
        if method == 'history':
            fields(p, {'query'})
            return {'deliveries': self.store.history(self.account(), string(p, 'query', '', maximum=512))}
        if method == 'storage.backup':
            fields(p, {'destination'}, {'destination'})
            from .maintenance import backup_database
            destination = Path(string(p, 'destination', maximum=4096)).expanduser()
            cancelled = threading.Event()
            try:
                result = await asyncio.to_thread(backup_database, self.root / 'manager.sqlite3', destination,
                                                 cancel_event=cancelled)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return result if isinstance(result, dict) else {'path': str(destination), 'verified': True}
        if method == 'diagnostics.export':
            fields(p, {'destination'}, {'destination'})
            from .maintenance import diagnostic_snapshot, export_diagnostics
            destination = Path(string(p, 'destination', maximum=4096)).expanduser()
            snapshot = diagnostic_snapshot(self.root, self.store, self.policy)
            return await asyncio.to_thread(export_diagnostics, snapshot, destination)
        if method == 'shutdown':
            self.closing = True
            return {'shutting_down': True}
        raise IPCError('unknown_method', 'This operation is not supported.')

    async def close(self) -> None:
        self.preview_tokens.clear()
        self.phone = self.phone_code_hash = None
        self.credentials = None
        if self.client is not None:
            await self.client.disconnect()
            self.client = None
        self.service = None
        self.auth_stage = 'disconnected'


class ProtocolServer:
    def __init__(self, backend: Backend, writer):
        self.backend, self.writer = backend, writer
        self.tasks: dict[str, asyncio.Task] = {}
        self.seen: set[str] = set()
        self.queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=128)
        self.backend.emit = self.progress
        self.stopping = False
        self.output_available = True

    def progress(self, event: dict) -> None:
        # Progress is replaceable; bounded queue drops intermediate events under
        # slow-reader backpressure. Final responses and committed counts are not dropped.
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    async def output(self, payload: dict) -> None:
        if self.output_available:
            await self.queue.put(payload)

    async def pump(self) -> None:
        try:
            while True:
                payload = await self.queue.get()
                try:
                    if payload is None:
                        return
                    data = (json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
                    if pyinspect.iscoroutinefunction(self.writer):
                        await self.writer(data)
                    else:
                        await asyncio.to_thread(self.writer, data)
                finally:
                    self.queue.task_done()
        except BaseException:
            self.output_available = False
            raise

    async def handle(self, request_id: str, method: str, params: dict) -> None:
        try:
            result = await self.backend.dispatch(request_id, method, params)
            await self.output({'id': request_id, 'ok': True, 'result': result})
        except asyncio.CancelledError:
            if not self.stopping and self.output_available:
                with contextlib.suppress(asyncio.QueueFull):
                    self.queue.put_nowait({'id': request_id, 'ok': False, 'error': {
                        'code': 'cancelled', 'message': 'Operation cancelled. Saved progress remains; inspect history before another delivery attempt.'}})
        except IPCError as exc:
            await self.error(request_id, exc.code, exc.message)
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            account = self.backend.config.get('account_id') or 0
            self.backend.store.set_cooldown(account, time.time() + exc.seconds)
            await self.error(request_id, 'cooldown', f'Telegram requires waiting {exc.seconds} seconds. No retry was attempted.')
        except errors.RPCError as exc:
            if isinstance(exc, errors.PhoneCodeExpiredError):
                self.backend.auth_stage = 'phone'
                self.backend.phone = self.backend.phone_code_hash = None
            elif isinstance(exc, errors.ApiIdInvalidError):
                self.backend.auth_stage = 'credentials'
                self.backend.credentials = None
                self.backend.service = None
            elif isinstance(exc, (errors.UnauthorizedError, errors.AuthKeyDuplicatedError)):
                self.backend.auth_stage = 'disconnected'
                self.backend.service = None
                self.backend.preview_tokens.clear()
            await self.error(request_id, type(exc).__name__, telegram_error_message(exc))
        except DuplicateMessage:
            await self.error(request_id, 'duplicate', 'This exact message already has a delivery record for this destination. No retry was attempted.')
        except KeychainError:
            await self.error(request_id, 'keychain', 'Keychain access failed or an item already exists. Saved credentials were not overwritten.')
        except sqlite3.Error:
            await self.error(request_id, 'database', 'Database operation failed. Records were not reset; check storage and backups.')
        except (UnicodeError, ValueError):
            await self.error(request_id, 'validation', 'Input is invalid or the requested operation is currently blocked. Check the selected fields and cooldown.')
        except OSError:
            if method in {'connect', 'auth.credentials', 'auth.phone', 'auth.code', 'auth.password',
                          'auth.bind', 'discover', 'inspect', 'inspect_pending', 'preview', 'send'}:
                self.backend.service = None
                self.backend.auth_stage = 'disconnected'
                self.backend.preview_tokens.clear()
            await self.error(request_id, 'io', 'A connection or file operation failed. Progress was preserved; no delivery was retried.')
        except Exception as exc:
            LOG.error('OperationFailure:%s', type(exc).__name__)
            await self.error(request_id, 'internal', 'An internal operation failed. Saved data was preserved; inspect delivery history before another send.')
        finally:
            self.tasks.pop(request_id, None)

    async def error(self, request_id: str | None, code: str, message: str) -> None:
        await self.output({'id': request_id, 'ok': False, 'error': {'code': code, 'message': message}})

    async def accept(self, data: bytes) -> None:
        request_id = None
        if self.stopping:
            await self.error(None, 'shutting_down', 'The backend is shutting down.')
            return
        try:
            if len(data) > MAX_FRAME:
                raise ValueError
            request = strict_json(data.decode('utf-8'))
            if set(request) != {'id', 'method', 'params'}:
                raise ValueError
            request_id, method, params = request['id'], request['method'], request['params']
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
                request_id = None
                raise ValueError
            if not isinstance(method, str) or not isinstance(params, dict):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            await self.error(request_id, 'invalid_request', 'Expected one valid JSON request with id, method and params.')
            return
        if request_id in self.seen:
            await self.error(request_id, 'duplicate_request', 'Request ID has already been used. Requests are never replayed.')
            return
        if len(self.seen) >= 100000:
            await self.error(request_id, 'session_limit', 'Restart the backend to begin another request session.')
            return
        self.seen.add(request_id)
        if method == 'cancel':
            try:
                fields(params, {'request_id'}, {'request_id'})
                target = string(params, 'request_id', maximum=64)
                task = self.tasks.get(target)
                if task:
                    task.cancel()
                await self.output({'id': request_id, 'ok': True, 'result': {'cancelled': task is not None, 'request_id': target}})
            except IPCError as exc:
                await self.error(request_id, exc.code, exc.message)
            return
        if method == 'shutdown':
            if params:
                await self.error(request_id, 'invalid_params', 'Shutdown takes no parameters.')
                return
            self.stopping = True
            self.backend.closing = True
            for task in tuple(self.tasks.values()):
                task.cancel()
            await self.output({'id': request_id, 'ok': True, 'result': {'shutting_down': True}})
            return
        if len(self.tasks) >= MAX_REQUESTS:
            await self.error(request_id, 'busy', 'Too many operations are queued. Wait or cancel a pending operation.')
            return
        self.tasks[request_id] = asyncio.create_task(self.handle(request_id, method, params))

    async def serve(self, reader: asyncio.StreamReader) -> None:
        pump = asyncio.create_task(self.pump())
        read_task = None
        try:
            while not self.stopping:
                read_task = asyncio.create_task(reader.readline())
                done, _ = await asyncio.wait({read_task, pump}, return_when=asyncio.FIRST_COMPLETED)
                if pump in done:
                    # Closed GUI stdout: stop requests, cancel work, preserve state.
                    await pump
                    break
                try:
                    line = read_task.result()
                except ValueError:
                    await self.error(None, 'frame_too_large', 'Request frame exceeds the supported maximum.')
                    break
                if not line:
                    break
                await self.accept(line)
            self.stopping = True
            for task in tuple(self.tasks.values()):
                task.cancel()
            if self.tasks:
                await asyncio.wait(tuple(self.tasks.values()), timeout=2)
            drain = asyncio.create_task(self.queue.join())
            try:
                done, _ = await asyncio.wait({drain, pump}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
                if pump in done:
                    await pump
                elif drain not in done:
                    self.output_available = False
                    LOG.info('ProtocolDrainTimedOut')
            finally:
                if not drain.done():
                    drain.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await drain
        except (BrokenPipeError, ConnectionError):
            LOG.info('ProtocolPipeClosed')
        finally:
            if read_task and not read_task.done():
                read_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await read_task
            self.stopping = True
            for task in tuple(self.tasks.values()):
                task.cancel()
            if self.tasks:
                await asyncio.wait(tuple(self.tasks.values()), timeout=2)
            if not pump.done():
                if self.output_available:
                    try:
                        await asyncio.wait_for(self.queue.put(None), timeout=1)
                        await asyncio.wait_for(pump, timeout=2)
                    except (TimeoutError, BrokenPipeError, ConnectionError):
                        pump.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await pump
                else:
                    pump.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pump
            else:
                with contextlib.suppress(BrokenPipeError, ConnectionError):
                    await pump
            await self.backend.close()


async def run() -> None:
    os.umask(0o077)
    root = private_directory(data_directory())
    with application_lock(root):
        config = load_configuration(root)
        if config.get('account_id') is not None and not (root / 'manager.sqlite3').is_file():
            raise IPCError('database_missing', 'The bound installation database is missing. Restore its backup; no empty ledger was created.')
        store = Store(root / 'manager.sqlite3')
        try:
            backend = Backend(root, store, config)
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader(limit=MAX_FRAME)
            transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
            output_fd = sys.stdout.fileno()
            os.set_blocking(output_fd, False)
            async def writer(data: bytes):
                offset = 0
                while offset < len(data):
                    try:
                        offset += os.write(output_fd, data[offset:])
                    except BlockingIOError:
                        writable = loop.create_future()
                        def ready():
                            if not writable.done():
                                writable.set_result(None)
                        loop.add_writer(output_fd, ready)
                        try:
                            await writable
                        finally:
                            loop.remove_writer(output_fd)
            try:
                await ProtocolServer(backend, writer).serve(reader)
            finally:
                transport.close()
        finally:
            store.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format='{"level":"%(levelname)s","event":"%(message)s"}')
    logging.getLogger('telethon').setLevel(logging.CRITICAL)
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    except Exception as exc:
        # Startup errors have no request ID; stdout remains a framed error only.
        message = exc.message if isinstance(exc, IPCError) else 'Backend startup failed. Check private storage access and configuration.'
        code = exc.code if isinstance(exc, IPCError) else 'startup'
        if isinstance(exc, ApplicationBusy):
            code = 'already_running'
            message = 'Another CLI or desktop backend is using this installation. Quit that instance, then reconnect. Its session was not changed.'
        LOG.error('StartupFailure:%s', type(exc).__name__)
        try:
            sys.stdout.write(json.dumps({'id': None, 'ok': False, 'error': {'code': code, 'message': message}}, ensure_ascii=False) + '\n')
            sys.stdout.flush()
        except OSError:
            pass
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
