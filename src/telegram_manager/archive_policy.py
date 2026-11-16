"""Ordinary export policy and deterministic, collision-safe organization."""

import asyncio
import hashlib
import json
import os
import re
import stat
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telethon import types, utils

from .media_policy import describe

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "application/zip": "zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def slug(value, fallback="Conversation"):
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", value).strip(" .")[:80]
    value = value.encode("utf-8")[:120].decode("utf-8", errors="ignore")
    return value or fallback


def conversation_folder(profile, account, peer, title):
    suffix = hashlib.sha256(f"{profile}:{account}:{peer}".encode()).hexdigest()[:32]
    return slug(title) + " — " + suffix


def inspect_message(message, peer, config):
    if not isinstance(message, types.Message) or not getattr(message, "media", None):
        return None
    if (
        getattr(message, "peer_id", None) is None
        or utils.get_peer_id(message.peer_id) != peer
    ):
        raise ValueError("Conversation mismatch")
    if type(message.id) is not int or not 0 < message.id <= 2147483647:
        raise ValueError("Invalid message identity")
    date = getattr(message, "date", None)
    if not isinstance(date, datetime) or date.tzinfo is None:
        return ("unsupported", {}, "", "")
    stamp = date.timestamp()
    if not config["start"] <= stamp < config["end"]:
        return None
    metadata = describe(message)
    kind = "audio" if metadata["kind"] == "voice" else metadata["kind"]
    if kind not in config["types"]:
        return None
    state = "pending"
    if (
        metadata["category"] != "ordinary"
        or message.noforwards
        or message.restriction_reason
    ):
        state = "restricted"
    elif (
        isinstance(message.media, (types.MessageMediaPhoto, types.MessageMediaDocument))
        and not getattr(message, "photo", None)
        and not getattr(message, "document", None)
    ):
        state = "deleted"
    elif not metadata["can_download"]:
        state = "unsupported"
    media = getattr(message.media, "document", None) or getattr(
        message.media, "photo", None
    )
    identity = getattr(media, "id", None)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "id": identity,
                "size": metadata["size"],
                "mime": metadata["mime_type"],
                "type": type(media).__name__,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    date = date.astimezone(ZoneInfo(config["timezone"]))
    group = (
        date.strftime("%Y-%m-%d" if config["organization"] == "daily" else "%Y-%m")
        if config["organization"] != "type"
        else kind
    )
    ext = EXTENSIONS.get(metadata["mime_type"], "bin")
    original = slug(Path(metadata["name"].replace("\\", "/")).stem, "")
    leaf = f"{kind}_{message.id}" + ("_" + original if original else "") + "." + ext
    return state, metadata, str(Path(group) / leaf), fingerprint


def safe_tree(root, components=()):
    """Walk/create relative directories through retained no-follow descriptors."""
    root = Path(root)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in components:
            if not part or part in {".", ".."} or "/" in part or "\\" in part:
                raise ValueError("Unsafe folder")
            try:
                os.mkdir(part, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            info = os.fstat(child)
            if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
                os.close(child)
                raise ValueError("Unsafe owner")
            os.close(descriptor)
            descriptor = child
        return root.joinpath(*components), (
            os.fstat(descriptor).st_dev,
            os.fstat(descriptor).st_ino,
        )
    finally:
        os.close(descriptor)


def verified_file(path, size, digest, cancel=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size != size
        ):
            return False
        checksum = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(262144):
                if cancel is not None and cancel.is_set():
                    return False
                checksum.update(chunk)
        return checksum.hexdigest() == digest
    finally:
        os.close(descriptor)


async def verify_async(path, size, digest):
    cancel = threading.Event()
    reader = asyncio.create_task(
        asyncio.to_thread(verified_file, path, size, digest, cancel)
    )
    try:
        return await asyncio.shield(reader)
    except asyncio.CancelledError:
        cancel.set()
        await reader
        raise
