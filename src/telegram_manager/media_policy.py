"""Bounded media descriptors. Telegram objects and file references never cross IPC."""

import math
import time
from datetime import datetime

from telethon import types

from .terminal import clean_text

MAX_BYTES = 512 * 1024 * 1024


def describe(message):
    media = getattr(message, "media", None)
    timer = getattr(media, "ttl_seconds", None)
    period = getattr(message, "ttl_period", None)
    category = (
        "view_once"
        if timer == 2147483647
        else "self_destructing"
        if timer
        else "auto_delete"
        if period
        else "ordinary"
    )
    if isinstance(message, (types.EncryptedMessage, types.EncryptedMessageService)):
        category = "secret_chat"
    file = getattr(message, "file", None)
    size = getattr(file, "size", None)
    raw_mime = getattr(file, "mime_type", "")
    mime = clean_text(raw_mime if isinstance(raw_mime, str) else "").lower()[:128]
    kind = "document"
    document = getattr(media, "document", None)
    raw_attrs = getattr(document, "attributes", None)
    attrs = raw_attrs[:64] if isinstance(raw_attrs, list) else []
    if isinstance(media, types.MessageMediaPhoto):
        kind = "photo"
    elif (
        any(isinstance(a, types.DocumentAttributeAnimated) for a in attrs)
        or mime == "image/gif"
    ):
        kind = "animation"
    elif any(isinstance(a, types.DocumentAttributeVideo) for a in attrs):
        kind = "video"
    elif any(isinstance(a, types.DocumentAttributeAudio) and a.voice for a in attrs):
        kind = "voice"
    elif any(isinstance(a, types.DocumentAttributeAudio) for a in attrs):
        kind = "audio"
    elif mime in {"image/jpeg", "image/png"}:
        kind = "photo"
    valid = type(size) is int and 0 < size <= MAX_BYTES
    protected = bool(
        getattr(message, "noforwards", False)
        or getattr(message, "restriction_reason", None)
    )
    duration = getattr(file, "duration", None)
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 <= duration <= 86400
    ):
        duration = None
    date = getattr(message, "date", None)
    deadline = (
        date.timestamp() + period
        if type(period) is int and period > 0 and isinstance(date, datetime)
        else None
    )
    timed_supported = (
        category in {"view_once", "self_destructing", "auto_delete"}
        and mime in {"image/jpeg", "image/png", "video/mp4"}
        and (category == "auto_delete" or not getattr(message, "out", False))
        and (kind != "photo" or size is not None and size <= 8 * 1024 * 1024)
        and (
            category != "self_destructing" or type(timer) is int and 0 < timer <= 86400
        )
        and (
            category != "auto_delete" or deadline is not None and deadline > time.time()
        )
    )
    from .media_audio import converter

    previewable = (
        mime
        in {
            "image/jpeg",
            "image/png",
            "image/gif",
            "video/mp4",
            "video/quicktime",
            "audio/mpeg",
            "audio/mp4",
            "audio/wav",
            "audio/x-wav",
            "application/pdf",
            "text/plain",
        }
        or mime == "audio/ogg"
        and converter() is not None
    )
    if mime == "audio/ogg" and (
        duration is None or duration > 600 or not valid or size > 64 * 1024 * 1024
    ):
        previewable = False
    raw_name = getattr(file, "name", "")
    return {
        "kind": kind,
        "name": clean_text(raw_name if isinstance(raw_name, str) else "")[:256],
        "size": size if valid else None,
        "mime_type": mime,
        "duration": duration,
        "category": category,
        "can_download": valid and category == "ordinary" and not protected,
        "can_open": valid
        and previewable
        and (category == "ordinary" or timed_supported)
        and not protected,
        "expires_at": deadline,
        "reason": None
        if category == "ordinary" or timed_supported
        else "Timed media viewing is unavailable until its expiration protocol is verified.",
    }


async def fetch_media_message(client, account, destination, identity):
    """Media-only scope validation; never relax the text/action policy."""
    from telethon import utils

    from .content_policy import require_content_peer
    from .ipc import IPCError

    await require_content_peer(client, account, destination)
    message = await client.get_messages(destination, ids=identity)
    if (
        not isinstance(message, types.Message)
        or message.id != identity
        or getattr(message, "peer_id", None) is None
        or utils.get_peer_id(message.peer_id) != destination
        or message.noforwards
        or message.restriction_reason
        or not isinstance(
            message.media, (types.MessageMediaPhoto, types.MessageMediaDocument)
        )
    ):
        raise IPCError(
            "media_unavailable", "The selected attachment is unavailable or protected."
        )
    return message
