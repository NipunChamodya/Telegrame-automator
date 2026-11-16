"""Account-scoped ordinary media transfers outside the shared mutation lock."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from telethon import functions

from .media_policy import describe, fetch_media_message
from .media_preview import MediaPreview
from .security import private_directory


class TransferCache(MediaPreview):
    MAX_FILES = 8
    OWN_NAME = re.compile(r"\.telegram-media-[a-zA-Z0-9_-]+\.[a-z0-9]+")


class MediaTransfers:
    METHODS = frozenset(
        {
            "media.get_metadata",
            "media.download",
            "media.open",
            "media.release",
            "media.get_progress",
            "media.pause",
            "media.resume",
        }
    )
    LIMIT = 2

    def __init__(self, backend):
        self.backend = backend
        self.active = {}
        self.entries = {}
        self.tasks = set()
        self.closed = False
        self.cache = TransferCache(backend)
        self.cache_error = False
        directory = backend.root / "media-cache"
        if directory.exists():
            from .ipc import IPCError

            try:
                directory = private_directory(directory)
                self.cache.recover_index(directory)
                self.cache.directory = directory
                self.cache.write_index()
            except (OSError, ValueError, IPCError):
                self.cache_error = True

    def invalidate(self, peer, ids):
        for entry in tuple(self.active.values()):
            if entry["destination"] == peer and entry["message_id"] in ids:
                entry["task"].cancel()
        for token, entry in tuple(self.entries.items()):
            if entry["destination"] == peer and entry["message_id"] in ids:
                self.release(token)

    def release(self, token):
        entry = self.entries.get(token)
        if entry:
            self.cache.unlink_owned(entry)
            self.entries.pop(token, None)
            entry["expiry"].cancel()
            self.cache.entries.pop(token, None)
            self.cache.write_index()
        return entry is not None

    def close(self):
        self.closed = True
        for entry in tuple(self.active.values()):
            entry["task"].cancel()
        for token in tuple(self.entries):
            try:
                self.release(token)
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "MediaCleanup:%s", type(exc).__name__
                )

    async def stop(self):
        self.close()
        tasks = [task for task in self.tasks if task is not asyncio.current_task()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def dispatch(self, request_id, method, p, generation):
        from .ipc import IPCError, fields, integer, string

        b = self.backend
        fields(
            p,
            {"account_id", "destination", "message_id", "path"}
            if method == "media.download"
            else {"account_id", "destination", "message_id"}
            if method in {"media.open", "media.get_metadata"}
            else {"account_id", "token"}
            if method == "media.release"
            else {"account_id", "request_id"},
            {"destination", "message_id", "path"}
            if method == "media.download"
            else {"account_id", "destination", "message_id"}
            if method in {"media.open", "media.get_metadata"}
            else {"account_id", "token"}
            if method == "media.release"
            else {"account_id", "request_id"},
        )
        expected = (
            integer(p, "account_id", minimum=1) if "account_id" in p else b.account()
        )
        scope = dict(b.scope())
        if generation != b.account_generation or expected != b.account() or self.closed:
            raise IPCError(
                "account_changed", "The account changed. Select the attachment again."
            )
        if method == "media.release":
            return {"released": self.release(string(p, "token", maximum=128)), **scope}
        if method in {"media.get_progress", "media.pause", "media.resume"}:
            entry = self.active.get(string(p, "request_id", maximum=64))
            if entry is None:
                raise IPCError(
                    "transfer_unavailable",
                    "This transfer has finished or was cancelled.",
                )
            if method == "media.pause":
                entry["gate"].clear()
            if method == "media.resume":
                entry["gate"].set()
            return {
                "bytes": entry["bytes"],
                "total": entry["total"],
                "paused": not entry["gate"].is_set(),
                **scope,
            }
        peer = integer(p, "destination")
        identity = integer(p, "message_id", minimum=1, maximum=2147483647)
        task = asyncio.current_task()
        if method != "media.get_metadata" and len(self.active) >= self.LIMIT:
            raise IPCError(
                "transfer_limit",
                "Two transfers are already active. Wait or cancel one.",
            )
        gate = asyncio.Event()
        gate.set()
        entry = {
            "destination": peer,
            "message_id": identity,
            "task": task,
            "gate": gate,
            "bytes": 0,
            "total": 0,
            "preview": method == "media.open",
        }
        # Reserve before the first await; even authorization queues remain bounded.
        if method != "media.get_metadata":
            self.active[request_id] = entry
        self.tasks.add(task)
        temporary = None
        deadline_task = None
        try:
            async with b.lock:
                if generation != b.account_generation or self.closed:
                    raise IPCError(
                        "account_changed",
                        "The account changed. Select the attachment again.",
                    )
                await b.chats.identity(expected)
                if b.chats.store().get(expected, peer) is None:
                    raise IPCError(
                        "destination_unavailable",
                        "Select an existing conversation first.",
                    )
                message = await fetch_media_message(b.client, expected, peer, identity)
                client = b.client
                metadata = describe(message)
                b.store.db.execute(
                    "CREATE TABLE IF NOT EXISTS media_consumed (account INTEGER, peer INTEGER, message INTEGER, PRIMARY KEY(account, peer, message))"
                )
                consumed = b.store.db.execute(
                    "SELECT 1 FROM media_consumed WHERE account=? AND peer=? AND message=?",
                    (expected, peer, identity),
                ).fetchone()
                if consumed:
                    raise IPCError(
                        "media_expired",
                        "This timed attachment has already been opened or expired.",
                    )
                deadline = metadata["expires_at"] or time.time() + 900
                if (
                    method == "media.open"
                    and metadata["category"] in {"view_once", "self_destructing"}
                    and metadata["can_open"]
                ):
                    # Persist before acknowledgement. An interrupted open fails closed after restart.
                    b.store.db.execute(
                        "INSERT INTO media_consumed VALUES (?,?,?)",
                        (expected, peer, identity),
                    )
                    b.store.db.commit()
                entry["deadline"] = deadline
            if method == "media.get_metadata":
                return {**metadata, **scope}
            if not metadata[
                "can_download" if method == "media.download" else "can_open"
            ]:
                raise IPCError(
                    "media_unavailable", "This attachment cannot be downloaded safely."
                )

            async def transfer_deadline():
                await asyncio.sleep(max(0, deadline - time.time()))
                task.cancel()

            deadline_task = asyncio.create_task(transfer_deadline())
            size = metadata["size"]
            entry["total"] = size
            if method == "media.download":
                output = Path(string(p, "path", maximum=4096)).expanduser().absolute()
                if output.exists() or output.is_symlink() or not output.parent.is_dir():
                    raise IPCError(
                        "file_access", "Choose a new filename in an existing folder."
                    )
                directory = output.parent
            else:
                if self.cache_error:
                    raise IPCError(
                        "cache_unavailable",
                        "The private media cache needs review. Unknown files were preserved; ordinary Save As remains available.",
                    )
                directory = private_directory(b.root / "media-cache")
                if self.cache.directory is None:
                    self.cache.recover_index(directory)
                    self.cache.directory = directory
                    self.cache.write_index()
                if (
                    len(self.entries) >= 4
                    or sum(item["total"] for item in self.entries.values())
                    + sum(
                        item["total"]
                        for item in self.active.values()
                        if item.get("preview")
                    )
                    > 512 * 1024 * 1024
                ):
                    raise IPCError(
                        "cache_full",
                        "Close another media viewer before opening this attachment.",
                    )
                output = None
            extensions = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/gif": "gif",
                "video/mp4": "mp4",
                "video/quicktime": "mov",
                "audio/ogg": "ogg",
                "audio/mpeg": "mp3",
                "audio/mp4": "m4a",
                "audio/x-wav": "wav",
                "audio/wav": "wav",
                "application/pdf": "pdf",
                "text/plain": "txt",
            }
            suffix = "." + extensions.get(metadata["mime_type"], "bin")
            fd, name = tempfile.mkstemp(
                prefix=".telegram-media-", suffix=suffix, dir=directory
            )
            temporary = Path(name)
            info = os.fstat(fd)
            entry.update(path=temporary, identity=(info.st_dev, info.st_ino))
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as stream:
                if output is None:
                    self.cache.pending[name] = entry
                    self.cache.write_index()
                attempts = 0
                while entry["bytes"] < size:
                    iterator = client.iter_download(
                        message.media,
                        offset=entry["bytes"],
                        request_size=262144,
                        chunk_size=262144,
                    )
                    try:
                        while entry["bytes"] < size:
                            await gate.wait()
                            try:
                                chunk = await iterator.__anext__()
                            except StopAsyncIteration:
                                break
                            if time.time() >= deadline:
                                raise IPCError(
                                    "media_expired", "This attachment has expired."
                                )
                            if self.closed or generation != b.account_generation:
                                raise IPCError(
                                    "account_changed",
                                    "The account changed. Download cancelled.",
                                )
                            if not chunk or entry["bytes"] + len(chunk) > size:
                                raise IPCError(
                                    "file_size",
                                    "The attachment exceeded its declared size.",
                                )
                            stream.write(chunk)
                            digest.update(chunk)
                            entry["bytes"] += len(chunk)
                            b.emit(
                                {
                                    "event": "progress",
                                    "request_id": request_id,
                                    "data": {
                                        "phase": "download",
                                        "index": entry["bytes"],
                                        "total": size,
                                        **scope,
                                    },
                                }
                            )
                    except (ConnectionError, TimeoutError):
                        if attempts >= 2 or metadata["category"] != "ordinary":
                            raise IPCError(
                                "download_interrupted",
                                "The connection was interrupted. Try again.",
                            ) from None
                        attempts += 1
                        await asyncio.sleep(2 ** (attempts - 1))
                        continue
                    finally:
                        await iterator.close()
                    break
                if entry["bytes"] != size:
                    raise IPCError(
                        "download_incomplete",
                        "The attachment was incomplete. Try again.",
                    )
                stream.flush()
                os.fsync(stream.fileno())
            preview_bytes = size
            preview_mime = metadata["mime_type"]
            if (
                method == "media.open"
                and preview_mime == "audio/ogg"
                and metadata["category"] == "ordinary"
            ):
                from .media_audio import decode_voice

                audio_fd, audio_name = tempfile.mkstemp(
                    prefix=".telegram-media-", suffix=".wav", dir=directory
                )
                audio_info = os.fstat(audio_fd)
                audio_entry = {
                    **entry,
                    "path": Path(audio_name),
                    "identity": (audio_info.st_dev, audio_info.st_ino),
                }
                try:
                    with os.fdopen(audio_fd, "wb") as audio_stream:
                        self.cache.pending[audio_name] = audio_entry
                        self.cache.write_index()
                        preview_bytes = await decode_voice(temporary, audio_stream)
                        audio_stream.flush()
                        os.fsync(audio_stream.fileno())
                except BaseException:
                    self.cache.unlink_owned(audio_entry)
                    self.cache.pending.pop(audio_name, None)
                    self.cache.write_index()
                    raise
                self.cache.unlink_owned(entry)
                self.cache.pending.pop(name, None)
                temporary = Path(audio_name)
                name = audio_name
                entry.update(audio_entry)
                preview_mime = "audio/wav"
                self.cache.write_index()
            # Recheck policy and file identity before publishing an ordinary export.
            async with b.lock:
                if time.time() >= deadline:
                    raise IPCError("media_expired", "This attachment has expired.")
                if self.closed or generation != b.account_generation:
                    raise IPCError(
                        "account_changed", "The account changed. Download cancelled."
                    )
                fresh = await fetch_media_message(client, expected, peer, identity)
                if describe(fresh) != metadata or fresh.media != message.media:
                    raise IPCError(
                        "media_changed", "The attachment changed. Select it again."
                    )
                if output:
                    os.link(temporary, output)
                    return {
                        "saved": True,
                        "bytes": size,
                        "sha256": digest.hexdigest(),
                        **scope,
                    }
                if metadata["category"] in {"view_once", "self_destructing"}:
                    # Prepare privately first, then acknowledge immediately before exposure.
                    # Re-fetching after the acknowledgement can legitimately return expired media.
                    if metadata["category"] == "self_destructing":
                        deadline = time.time() + message.media.ttl_seconds
                    async with asyncio.timeout(max(0.001, deadline - time.time())):
                        if peer < -1000000000000:
                            await client(
                                functions.channels.ReadMessageContentsRequest(
                                    await client.get_input_entity(peer), [identity]
                                )
                            )
                        else:
                            await client(
                                functions.messages.ReadMessageContentsRequest(
                                    [identity]
                                )
                            )
                    if time.time() >= deadline:
                        raise IPCError("media_expired", "This attachment has expired.")
                token = secrets.token_urlsafe(32)

                async def expire():
                    await asyncio.sleep(max(0, deadline - time.time()))
                    try:
                        self.release(token)
                    except OSError as exc:
                        logging.getLogger(__name__).warning(
                            "MediaCleanup:%s", type(exc).__name__
                        )
                    b.emit_control(
                        {"event": "media.expired", "data": {**scope, "token": token}}
                    )

                self.entries[token] = {
                    **entry,
                    "path": temporary,
                    "expiry": asyncio.create_task(expire()),
                }
                self.cache.pending.pop(name, None)
                self.cache.entries[token] = self.entries[token]
                self.cache.write_index()
                path = str(temporary)
                temporary = None
                return {
                    **metadata,
                    "token": token,
                    "path": path,
                    "bytes": preview_bytes,
                    "mime_type": preview_mime,
                    "destination": peer,
                    "message_id": identity,
                    "expires_at": deadline,
                    **scope,
                }
        finally:
            if deadline_task:
                deadline_task.cancel()
            self.tasks.discard(task)
            self.active.pop(request_id, None)
            if temporary:
                try:
                    self.cache.unlink_owned(entry)
                finally:
                    for key, pending in tuple(self.cache.pending.items()):
                        if pending.get("task") is task:
                            try:
                                self.cache.unlink_owned(pending)
                                self.cache.pending.pop(key, None)
                            except OSError as exc:
                                logging.getLogger(__name__).warning(
                                    "MediaCleanup:%s", type(exc).__name__
                                )
                    self.cache.write_index()
