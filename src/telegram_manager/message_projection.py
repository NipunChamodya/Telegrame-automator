"""Pure bounded message metadata normalization; no getters or network requests."""
from datetime import datetime
from urllib.parse import urlsplit
from telethon import types, utils
from .content_policy import PROTECTED, message_supported
from .terminal import clean_text


def stamp(value):
    return value.isoformat() if isinstance(value, datetime) else None



def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or clean_text(value) != value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        # Accessing port validates malformed numeric port values.
        _ = parsed.port
    except ValueError:
        return None
    return value


def normalize_entities(message, text):
    raw = getattr(message, 'message', '') or ''
    # Sanitization/removal changes Telegram's UTF-16 offsets. Never apply the
    # old ranges to shifted text, including a slice that cuts a grapheme.
    if raw != text:
        return []
    encoded = text.encode('utf-16-le')
    values = []
    kinds = {types.MessageEntityBold: 'bold', types.MessageEntityItalic: 'italic',
             types.MessageEntityCode: 'code', types.MessageEntityPre: 'pre',
             types.MessageEntityTextUrl: 'link', types.MessageEntityUrl: 'link'}
    for entity in (getattr(message, 'entities', None) or [])[:128]:
        kind = kinds.get(type(entity))
        offset, length = getattr(entity, 'offset', None), getattr(entity, 'length', None)
        if (kind is None or type(offset) is not int or type(length) is not int
                or offset < 0 or length <= 0 or offset+length > len(encoded)//2):
            continue
        try:
            encoded[:offset*2].decode('utf-16-le')
            fragment = encoded[offset*2:(offset+length)*2].decode('utf-16-le')
        except UnicodeDecodeError:
            continue
        value = {'type': kind, 'offset': offset, 'length': length}
        if kind == 'link':
            url = safe_url(entity.url if isinstance(entity, types.MessageEntityTextUrl) else fragment)
            if url is None:
                continue
            value['url'] = url
        values.append(value)
        if len(values) == 32:
            break
    return values


def normalize_forward(message):
    header = getattr(message, 'fwd_from', None)
    if not isinstance(header, types.MessageFwdHeader):
        return None
    source = header.from_id
    source_id = utils.get_peer_id(source) if isinstance(source, (types.PeerUser, types.PeerChat, types.PeerChannel)) else None
    return {'name': clean_text(header.from_name)[:160] if header.from_name else None,
            'sender_id': source_id, 'date': stamp(header.date)}

def normalize_message(message, account: int | None = None, kind: str | None = None) -> dict:
    identity = getattr(message, 'id', None)
    if not message_supported(message):
        return {'id': identity, 'text': '', 'sender_name': 'Unavailable content',
                'sender_id': None, 'date': None, 'outgoing': bool(getattr(message, 'out', False)),
                'media': None, 'content_available': False, 'content_reason': PROTECTED,
                'reactions': [], 'reply_to_id': None, 'entities': [], 'forward': None, 'pinned': False,
                'can_request_edit': False, 'can_request_delete': False}
    sender = getattr(message, 'sender', None)
    file = getattr(message, 'file', None)
    media = None
    if file is not None:
        media = {'kind': 'image' if getattr(message, 'photo', None) else 'document',
                 'name': clean_text(getattr(file, 'name', '') or '')[:256],
                 'size': getattr(file, 'size', None), 'mime_type': clean_text(getattr(file, 'mime_type', '') or '')[:128] or None}
    reply = getattr(message, 'reply_to', None)
    reply_peer = getattr(reply, 'reply_to_peer_id', None)
    reactions = []
    for item in (getattr(getattr(message, 'reactions', None), 'results', None) or [])[:32]:
        reaction = getattr(item, 'reaction', None)
        if isinstance(reaction, types.ReactionEmoji):
            value = {'emoji': clean_text(reaction.emoticon)[:128], 'custom_emoji_id': None}
        elif isinstance(reaction, types.ReactionCustomEmoji):
            value = {'emoji': None, 'custom_emoji_id': reaction.document_id}
        else:
            continue
        value.update(count=max(0, int(getattr(item, 'count', 0) or 0)),
                     chosen=getattr(item, 'chosen_order', None) is not None)
        reactions.append(value)
    can_modify = (type(account) is int and kind in {'private', 'saved'}
                  and bool(getattr(message, 'out', False)) and getattr(message, 'sender_id', None) == account
                  and bool(getattr(message, 'message', None)) and not getattr(message, 'entities', None)
                  and getattr(message, 'fwd_from', None) is None and not getattr(message, 'via_bot_id', None)
                  and not getattr(message, 'via_business_bot_id', None) and not getattr(message, 'post', False)
                  and isinstance(getattr(message, 'media', None), (type(None), types.MessageMediaEmpty)))
    text = clean_text(getattr(message, 'message', '') or '', multiline=True)[:16384]
    return {'id': identity, 'text': text,
            'sender_name': clean_text(utils.get_display_name(sender)) if sender is not None else 'Unknown sender',
            'sender_id': getattr(message, 'sender_id', None), 'date': stamp(getattr(message, 'date', None)),
            'outgoing': bool(getattr(message, 'out', False)), 'media': media,
            'edit_date': stamp(getattr(message, 'edit_date', None)),
            'reply_to_id': getattr(reply, 'reply_to_msg_id', None),
            'reply_to_peer_id': utils.get_peer_id(reply_peer) if reply_peer is not None else None,
            'grouped_id': getattr(message, 'grouped_id', None), 'views': getattr(message, 'views', None),
            'forwards': getattr(message, 'forwards', None), 'reactions': reactions,
            'read_outbox_max_id': None, 'content_available': True, 'content_reason': None,
            'entities': normalize_entities(message, text), 'forward': normalize_forward(message),
            'pinned': bool(getattr(message, 'pinned', False)),
            'can_request_edit': bool(can_modify), 'can_request_delete': bool(can_modify)}
