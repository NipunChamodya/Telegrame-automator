import time
from typing import Any
from collections.abc import Callable

from telethon import TelegramClient, errors, functions, types, utils

from .models import Group
from .storage import Store


def analyze(entity: Any, permissions: Any, me: Any) -> tuple[str, list[str]]:
    if getattr(me, "restricted", False) or getattr(me, "deleted", False):
        return "denied", ["Account is restricted or deleted; sending is conservatively blocked."]
    if getattr(entity, "left", False) or getattr(entity, "deactivated", False):
        return "denied", ["Not an active member."]
    if not isinstance(entity, types.Chat) and not (
        isinstance(entity, types.Channel) and entity.megagroup
    ):
        return "denied", ["Destination is not a joined group or supergroup."]
    if getattr(entity, "forum", False):
        return "unknown", ["Forum topic selection is not supported; sending is blocked."]
    if permissions is None:
        return "unknown", ["Membership permissions could not be verified."]
    participant = getattr(permissions, "participant", None)
    if isinstance(participant, (types.ChannelParticipantLeft, types.ChannelParticipantBanned)):
        if isinstance(participant, types.ChannelParticipantLeft) or getattr(participant, "left", False):
            return "denied", ["Membership is not active."]
    privileged = bool(permissions.is_admin or permissions.is_creator)
    rights = [getattr(entity, "banned_rights", None), getattr(participant, "banned_rights", None)]
    if not privileged:
        rights.append(getattr(entity, "default_banned_rights", None))
    for right in rights:
        if right and any(getattr(right, flag, False) for flag in ("view_messages", "send_messages", "send_plain")):
            return "denied", ["Telegram reports a text posting restriction."]
    if not permissions.send_messages:
        return "denied", ["Telegram reports that sending messages is prohibited."]
    return "allowed", ["Telegram membership and text posting permissions verified."]


class TelegramService:
    def __init__(self, client: TelegramClient, store: Store, me: Any):
        self.client, self.store, self.me = client, store, me

    async def inspect(self, entity: Any) -> Group:
        entity = await self.client.get_entity(entity)
        group = Group(utils.get_peer_id(entity), getattr(entity, "title", "Unknown"),
                      "supergroup" if isinstance(entity, types.Channel) else "group",
                      username=getattr(entity, "username", None),
                      members=getattr(entity, "participants_count", None))
        try:
            permissions = await self.client.get_permissions(entity, self.me)
            group.permission, group.reasons = analyze(entity, permissions, self.me)
        except (errors.FloodWaitError, errors.SlowModeWaitError):
            raise
        except (errors.RPCError, ValueError):
            group.reasons = ["Telegram permissions unavailable; sending is blocked."]
        try:
            request = (functions.channels.GetFullChannelRequest(entity) if isinstance(entity, types.Channel)
                       else functions.messages.GetFullChatRequest(entity.id))
            full = await self.client(request)
            info = full.full_chat
            group.members = getattr(info, "participants_count", group.members)
            group.slowmode_seconds = getattr(info, "slowmode_seconds", 0)
            group.slowmode_next_send = getattr(info, "slowmode_next_send_date", None)
            if hasattr(group.slowmode_next_send, "timestamp"):
                group.slowmode_next_send = int(group.slowmode_next_send.timestamp())
            group.visible_bots = [str(b.user_id) for b in (getattr(info, "bot_info", None) or [])]
            group.unknown_rules.append("Visible bots are not necessarily moderation bots; their policies are unknown.")
        except (errors.FloodWaitError, errors.SlowModeWaitError):
            raise
        except (errors.RPCError, ValueError):
            group.unknown_rules.append("Slow mode and visible bot metadata unavailable.")
        self.store.save_group(self.me.id, group)
        return group

    async def discover(self, progress: Callable[[int], None] | None = None) -> int:
        if self.store.cooldown(self.me.id) > time.time():
            raise ValueError("Account cooldown is active; discovery is paused.")
        count = 0
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            entity = dialog.entity
            if isinstance(entity, types.Chat) or isinstance(entity, types.Channel) and entity.megagroup:
                await self.inspect(entity)
                count += 1
                if progress:
                    progress(count)
        return count

    async def send(self, destination: int, message: str) -> str:
        if not message.strip() or len(message.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("Message must contain 1–4096 UTF-16 units of text.")
        if destination not in {g["id"] for g in self.store.groups(self.me.id)}:
            raise ValueError("Destination has not been discovered for this account.")
        if self.store.cooldown(self.me.id) > time.time():
            raise ValueError("Account cooldown is active. Wait before making further requests.")
        if not await self.client.is_user_authorized():
            raise ValueError("Telegram authorization expired; reauthenticate before sending.")
        fresh_me = await self.client.get_me()
        if fresh_me is None or fresh_me.id != self.me.id:
            raise ValueError("Telegram account identity changed; sending blocked.")
        self.me = fresh_me
        # Recheck after user confirmation, immediately before reserving and sending.
        group = await self.inspect(destination)
        if group.permission != "allowed":
            raise ValueError("Sending blocked: " + "; ".join(group.reasons))
        if group.slowmode_next_send and group.slowmode_next_send > time.time():
            raise ValueError("Telegram slow mode is active; wait until the next permitted send.")
        delivery, random_id = self.store.reserve(self.me.id, destination, message)
        try:
            peer = await self.client.get_input_entity(destination)
            await self.client(functions.messages.SendMessageRequest(
                peer=peer, message=message, random_id=random_id, no_webpage=True))
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            self.store.set_cooldown(self.me.id, time.time() + exc.seconds)
            self.store.finish(delivery, "blocked", f"{type(exc).__name__}: wait {exc.seconds} seconds")
            return f"Blocked. Wait {exc.seconds} seconds; no retry was attempted."
        except errors.RPCError as exc:
            if isinstance(exc, errors.PeerFloodError):
                self.store.set_cooldown(self.me.id, time.time() + 86400)
            status = "uncertain" if isinstance(exc, errors.ServerError) else "rejected"
            self.store.finish(delivery, status, type(exc).__name__)
            return f"Telegram result: {status} ({type(exc).__name__}). No retry."
        except BaseException:
            self.store.finish(delivery, "uncertain", "Interrupted or transport failure; inspect Telegram manually.")
            raise
        self.store.finish(delivery, "sent", "Telegram acknowledged the send request.")
        return "Sent; delivery recorded."
