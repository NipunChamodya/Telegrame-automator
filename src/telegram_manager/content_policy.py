"""Fail-closed content support boundaries, shared by history, updates and media."""
from telethon import types

SPONSORED = 'Channel and bot content is unavailable until official sponsored-message support is implemented.'
UNKNOWN = 'Content support could not be verified. Refresh the conversation metadata.'
PROTECTED = 'Protected, restricted, or disappearing content is not supported by this client.'


def classify_entity(entity, account: int) -> dict:
    kind = None
    if isinstance(entity, types.User):
        kind = 'saved' if entity.id == account else 'private'
    elif isinstance(entity, types.Chat):
        kind = 'group'
    elif isinstance(entity, types.Channel):
        kind = 'supergroup' if entity.megagroup and not entity.broadcast else 'channel'
    reason = None
    if kind is None:
        reason = UNKNOWN
    elif kind == 'channel' or (isinstance(entity, types.User) and entity.bot):
        reason = SPONSORED
    elif (getattr(entity, 'restricted', False) or getattr(entity, 'restriction_reason', None)
          or getattr(entity, 'noforwards', False) or getattr(entity, 'deleted', False)
          or getattr(entity, 'deactivated', False) or getattr(entity, 'left', False)
          or getattr(entity, 'kicked', False)):
        reason = PROTECTED
    return {'kind': kind, 'content_known': kind is not None,
            'content_available': reason is None, 'content_reason': reason,
            'is_bot': bool(getattr(entity, 'bot', False))}


def project_dialog(row: dict) -> dict:
    result = dict(row)
    available = (row.get('content_known') is True and row.get('content_available') is True
                 and row.get('kind') in {'private', 'saved', 'group', 'supergroup'}
                 and not row.get('is_bot'))
    result['content_available'] = available
    if not available:
        result['content_reason'] = row.get('content_reason') or (SPONSORED if row.get('kind') == 'channel' or row.get('is_bot') else UNKNOWN)
        result['last_message'] = ''
    return result


async def require_content_peer(client, account: int, destination: int):
    from .ipc import IPCError
    from telethon import utils
    entity = await client.get_entity(destination)
    if utils.get_peer_id(entity) != destination:
        raise IPCError('destination_unavailable', 'The resolved conversation does not match the selection.')
    policy = classify_entity(entity, account)
    if not policy['content_available']:
        raise IPCError('content_unavailable', policy['content_reason'])
    return entity


def message_supported(message) -> bool:
    if not isinstance(message, types.Message):
        return False
    media = getattr(message, 'media', None)
    supported_media = (type(None), types.MessageMediaEmpty, types.MessageMediaPhoto,
                       types.MessageMediaDocument, types.MessageMediaWebPage)
    return (isinstance(media, supported_media)
            and not (getattr(message, 'noforwards', False) or getattr(message, 'ttl_period', None)
                     or getattr(message, 'restriction_reason', None) or getattr(message, 'action', None)
                     or getattr(media, 'ttl_seconds', None)))


def require_message_scope(message, destination: int, message_id: int | None = None):
    from .ipc import IPCError
    from telethon import utils
    if (not isinstance(message, types.Message) or getattr(message, 'peer_id', None) is None
            or utils.get_peer_id(message.peer_id) != destination
            or (message_id is not None and message.id != message_id)):
        raise IPCError('message_unavailable', 'The returned message does not match the selected conversation and message.')
    if not message_supported(message):
        raise IPCError('content_unavailable', PROTECTED)
    return message


async def fetch_scoped_message(client, account: int, destination: int, message_id: int):
    await require_content_peer(client, account, destination)
    message = await client.get_messages(destination, ids=message_id)
    return require_message_scope(message, destination, message_id)
