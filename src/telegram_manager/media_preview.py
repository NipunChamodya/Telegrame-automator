"""Explicit static-image previews; private bounded cache, never TTL/protected media."""
from __future__ import annotations

import os
import json
import re
import secrets
import stat
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from telethon import types

from .content_policy import fetch_scoped_message
from .security import private_directory

if TYPE_CHECKING:
    from .ipc import Backend


class MediaPreview:
    NETWORK = {'media.preview.get', 'media.preview.release'}
    METHODS = NETWORK
    MAX_BYTES = 8 * 1024 * 1024
    MAX_FILES = 4
    TTL = 900
    OWN_NAME = re.compile(r'preview_[a-f0-9]{32}\.(?:jpg|png)')

    def __init__(self, backend: Backend):
        self.backend = backend
        self.context = None
        self.directory = None
        self.entries: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.revision = 0

    def write_index(self, pending: dict | None = None) -> None:
        if self.directory is None:
            return
        entries = list(self.entries.values()) + list(self.pending.values())
        if pending and all(entry['path'] != pending['path'] for entry in entries):
            entries.append(pending)
        data = {'version':1,'entries':[{'name':entry['path'].name,'device':entry['identity'][0],
                                       'inode':entry['identity'][1]} for entry in entries]}
        descriptor, temporary = tempfile.mkstemp(prefix='.preview-index-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.directory / 'index.json')
        finally:
            Path(temporary).unlink(missing_ok=True)

    def recover_index(self, directory: Path) -> None:
        from .ipc import IPCError, strict_json
        index = directory / 'index.json'
        if index.exists():
            descriptor = os.open(index, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > 16384:
                    raise IPCError('cache_unavailable', 'The private image cache index needs review; no unknown files were removed.')
                try: data = strict_json(stream.read(16385).decode('utf-8'))
                except (ValueError, UnicodeError):
                    raise IPCError('cache_unavailable', 'The private image cache index is invalid and was preserved.') from None
            if (set(data) != {'version','entries'} or data['version'] != 1 or not isinstance(data['entries'], list)
                    or len(data['entries']) > self.MAX_FILES):
                raise IPCError('cache_unavailable', 'The private image cache index is invalid and was preserved.')
            for entry in data['entries']:
                if (not isinstance(entry, dict) or set(entry) != {'name','device','inode'}
                        or not isinstance(entry['name'], str) or not self.OWN_NAME.fullmatch(entry['name'])
                        or type(entry['device']) is not int or type(entry['inode']) is not int):
                    raise IPCError('cache_unavailable', 'The private image cache index is invalid and was preserved.')
            for entry in data['entries']:
                self.unlink_owned({'path':directory/entry['name'],'identity':(entry['device'],entry['inode'])})
        if any(self.OWN_NAME.fullmatch(path.name) and path.exists() for path in directory.iterdir()):
            raise IPCError('cache_unavailable', 'Unrecognized image cache files were preserved. Review the private cache before previewing more images.')

    @staticmethod
    def unlink_owned(entry: dict) -> None:
        path = entry['path']
        try:
            info = path.lstat()
            if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == entry['identity']):
                path.unlink()
        except FileNotFoundError:
            pass

    def close(self) -> None:
        self.revision += 1
        entries = list(self.entries.values()) + list(self.pending.values())
        self.entries.clear()
        self.pending.clear()
        error = None
        try:
            for entry in entries:
                try: self.unlink_owned(entry)
                except OSError as exc: error = exc
            self.write_index()
        finally:
            self.context = None
            self.directory = None
        if error is not None: raise error

    def invalidate(self, destination: int, message_ids: list[int]) -> None:
        self.revision += 1
        changed = False
        error = None
        for token, entry in tuple(self.entries.items()):
            if entry['destination'] == destination and entry['message_id'] in message_ids:
                self.entries.pop(token); changed = True
                try: self.unlink_owned(entry)
                except OSError as exc: error = exc
        for key, entry in tuple(self.pending.items()):
            if entry['destination'] == destination and entry['message_id'] in message_ids:
                self.pending.pop(key); changed = True
                try: self.unlink_owned(entry)
                except OSError as exc: error = exc
        if changed:
            self.write_index()
        if error is not None: raise error

    def cache(self) -> Path:
        from .ipc import IPCError
        def directory_for_scope():
            try:
                return private_directory(self.backend.root / 'image-preview-cache')
            except ValueError:
                raise IPCError('cache_unavailable', 'The private image cache contains unsafe filesystem objects. No files were removed.') from None
        context = (str(self.backend.root), self.backend.account(), tuple(self.backend.scope().items()))
        if context != self.context:
            self.close()
            directory = directory_for_scope()
            self.recover_index(directory)
            self.directory = directory
            self.write_index()
            self.context = context
        directory = directory_for_scope()
        for token, entry in tuple(self.entries.items()):
            if time.time() - entry['created'] >= self.TTL:
                self.unlink_owned(entry); self.entries.pop(token)
        self.write_index()
        return directory

    async def dispatch(self, request_id: str, method: str, p: dict) -> dict:
        from .ipc import IPCError, fields, integer, string
        b = self.backend
        fields(p, {'account_id','token'} if method == 'media.preview.release' else
               {'account_id','destination','message_id'}, {'account_id','token'} if method == 'media.preview.release' else {'account_id','destination','message_id'})
        account = integer(p, 'account_id', minimum=1)
        if account != b.account():
            raise IPCError('account_changed', 'Select the correct account before opening this image.')
        if method == 'media.preview.release':
            token = string(p, 'token', maximum=128)
            entry = self.entries.get(token)
            if entry is None or entry['scope'] != b.scope() or entry['account'] != account:
                return {'released':False}
            self.entries.pop(token); self.unlink_owned(entry)
            self.write_index()
            return {'released':True}
        await b.chats.identity(account)
        destination = integer(p, 'destination')
        message_id = integer(p, 'message_id', minimum=1, maximum=2147483647)
        if b.chats.store().get(account, destination) is None:
            raise IPCError('destination_unavailable', 'Choose an existing cached conversation first.')
        message = await fetch_scoped_message(b.client, account, destination, message_id)
        file = getattr(message, 'file', None)
        size = getattr(file, 'size', None)
        mime = (getattr(file, 'mime_type', '') or '').lower()
        if (not isinstance(message.media, (types.MessageMediaPhoto, types.MessageMediaDocument))
                or type(size) is not int or not 0 < size <= self.MAX_BYTES
                or mime not in {'image/jpeg','image/png'}):
            raise IPCError('preview_unavailable', 'Only known-size JPEG/PNG images up to 8 MiB support static previews. Other attachments can use the supported Save action.')
        directory = self.cache()
        for token, entry in tuple(self.entries.items()):
            if entry['destination'] == destination and entry['message_id'] == message_id:
                self.unlink_owned(entry); self.entries.pop(token)
        while len(self.entries) >= self.MAX_FILES:
            token = next(iter(self.entries))
            self.unlink_owned(self.entries.pop(token))
        extension = 'jpg' if mime == 'image/jpeg' else 'png'
        path = directory / ('preview_' + secrets.token_hex(16) + '.' + extension)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        info = os.fstat(descriptor)
        entry = {'path':path,'identity':(info.st_dev,info.st_ino),'created':time.time(),
                 'account':account,'scope':dict(b.scope()),'destination':destination,'message_id':message_id}
        revision = self.revision
        owner = self
        self.pending[path.name] = entry
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                self.write_index(entry)  # Reservation survives a crash before download.
                class BoundedImage:
                    written = 0
                    def write(self, data):
                        if owner.revision != revision:
                            raise IPCError('preview_invalidated', 'The conversation changed. The image preview was cancelled.')
                        if self.written + len(data) > size:
                            raise IPCError('file_size', 'The image exceeded its declared size. Preview cancelled.')
                        count = stream.write(data); self.written += count; return count
                    def tell(self): return self.written
                    def flush(self): stream.flush()
                sink = BoundedImage()
                def progress(current, total):
                    b.emit({'event':'progress','request_id':request_id,'data':{'phase':'image_preview','index':current,'total':total}})
                await b.client.download_media(message, file=sink, progress_callback=progress)
                if self.revision != revision:
                    raise IPCError('preview_invalidated', 'The conversation changed. The image preview was cancelled.')
                if sink.written != size:
                    raise IPCError('download_incomplete', 'The image preview was incomplete.')
                stream.flush(); os.fsync(stream.fileno())
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                prefix = stream.read(8)
            if (mime == 'image/png' and prefix != b'\x89PNG\r\n\x1a\n') or (mime == 'image/jpeg' and not prefix.startswith(b'\xff\xd8\xff')):
                raise IPCError('preview_unavailable', 'This attachment does not match its declared image format.')
        except BaseException:
            self.pending.pop(path.name, None)
            self.unlink_owned(entry)
            self.write_index()
            raise
        self.pending.pop(path.name, None)
        token = secrets.token_urlsafe(32)
        self.entries[token] = entry
        self.write_index()
        return {'token':token,'path':str(path),'bytes':size,'mime_type':mime,
                'destination':destination,'message_id':message_id,'expires_at':entry['created']+self.TTL}
