import json
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from telethon import TelegramClient, errors, functions, types, utils

from .diagnostics import report_programming_error
from .models import Group
from .storage import Store


LOG = logging.getLogger("telegram_manager.discovery")
WAITS = (errors.FloodWaitError, errors.SlowModeWaitError)
ACCESS_DENIED = (errors.UserNotParticipantError, errors.ChannelPrivateError,
                 errors.ChatForbiddenError, errors.UserBannedInChannelError)
MEMBERS = (types.ChatParticipant, types.ChatParticipantAdmin, types.ChatParticipantCreator,
           types.ChannelParticipant, types.ChannelParticipantSelf, types.ChannelParticipantAdmin,
           types.ChannelParticipantCreator, types.ChannelParticipantBanned)
ADMINS = (types.ChatParticipantAdmin, types.ChatParticipantCreator,
          types.ChannelParticipantAdmin, types.ChannelParticipantCreator)


def is_group(entity: Any) -> bool:
    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        return not any(getattr(entity, flag, False) for flag in ("left", "deactivated", "migrated_to"))
    return (isinstance(entity, (types.Channel, types.ChannelForbidden))
            and bool(getattr(entity, "megagroup", False))
            and not getattr(entity, "broadcast", False) and not getattr(entity, "left", False))


def basic_group(entity: Any) -> Group:
    return Group(utils.get_peer_id(entity), getattr(entity, "title", None) or "Unnamed group",
                 "supergroup" if isinstance(entity, (types.Channel, types.ChannelForbidden)) else "group",
                 username=getattr(entity, "username", None),
                 members=getattr(entity, "participants_count", None),
                 reasons=["Posting permissions have not been verified; sending is blocked."])


def analyze(entity: Any, permissions: Any, me: Any) -> tuple[str, list[str]]:
    if getattr(me, "restricted", False) or getattr(me, "deleted", False):
        return "denied", ["Account is restricted or deleted; sending is conservatively blocked."]
    if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
        return "denied", ["Telegram reports that this group is inaccessible."]
    if not is_group(entity):
        return "denied", ["Destination is not an active joined group or supergroup."]
    if any(getattr(entity, flag, False) for flag in ("forum", "monoforum")):
        return "unknown", ["Forum topic selection is not supported; sending is blocked."]
    if getattr(entity, "min", False):
        return "unknown", ["Telegram returned an incomplete group entity; permissions are unknown."]
    participant = getattr(permissions, "participant", None)
    if isinstance(participant, types.ChannelParticipantLeft) or getattr(participant, "left", False):
        return "denied", ["Membership is not active."]
    if not isinstance(participant, MEMBERS):
        return "unknown", ["Membership permissions could not be verified."]
    privileged = isinstance(participant, ADMINS)
    rights = [getattr(entity, "banned_rights", None), getattr(participant, "banned_rights", None)]
    if not privileged:
        rights.append(getattr(entity, "default_banned_rights", None))
    for right in rights:
        if right and any(getattr(right, flag, False) for flag in ("view_messages", "send_messages", "send_plain")):
            return "denied", ["Telegram reports a text posting restriction."]
    if getattr(entity, "gigagroup", False) and not privileged:
        return "denied", ["Only administrators can post in this gigagroup."]
    return "allowed", ["Telegram membership and text posting permissions verified."]


class TelegramService:
    def __init__(self, client: TelegramClient, store: Store, me: Any):
        self.client, self.store, self.me = client, store, me

    async def inspect(self, entity: Any) -> Group:
        # Discovery supplies a dialog entity: save its basic record before API work.
        known = isinstance(entity, (types.Chat, types.Channel, types.ChatForbidden, types.ChannelForbidden))
        group = basic_group(entity) if known else None
        if group is not None:
            self.store.save_group(self.me.id, group)
        if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
            group.permission, group.reasons = analyze(entity, None, self.me)
            self.store.save_group(self.me.id, group)
            return group
        try:
            fresh = await self.client.get_entity(entity)
        except (errors.UnauthorizedError, *WAITS):
            raise
        except ACCESS_DENIED:
            if group is None:
                raise
            group.permission = "denied"
            group.reasons = ["Telegram reports this group's access is restricted."]
            self.store.save_group(self.me.id, group)
            return group
        except (errors.RPCError, ValueError):
            if group is None:
                raise
            group.reasons = ["Fresh group information unavailable; posting permission is unknown."]
            self.store.save_group(self.me.id, group)
            return group
        entity = fresh
        group = basic_group(entity)
        if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
            group.permission, group.reasons = analyze(entity, None, self.me)
            self.store.save_group(self.me.id, group)
            return group
        # These calls may return optional/missing metadata independently.
        permission_available = False
        try:
            permissions = await self.client.get_permissions(entity, self.me)
        except (errors.UnauthorizedError, *WAITS):
            raise
        except ACCESS_DENIED:
            group.permission, group.reasons = "denied", ["Telegram reports membership or group access is restricted."]
        except (errors.RPCError, ValueError):
            group.reasons = ["Telegram permissions unavailable; sending is blocked."]
        except AttributeError as exc:
            # Telethon's basic-chat permission helper itself assumes a visible
            # participants list. A forbidden list must not lose the dialog record.
            report_programming_error(LOG, exc)
            group.reasons = ["Permission metadata was incomplete; sending is blocked."]
        else:
            group.permission, group.reasons = analyze(entity, permissions, self.me)
            permission_available = group.permission != "unknown"
        group.metadata_status = "partial"
        try:
            request = (functions.channels.GetFullChannelRequest(entity) if isinstance(entity, types.Channel)
                       else functions.messages.GetFullChatRequest(entity.id))
            full = await self.client(request)
        except (errors.UnauthorizedError, *WAITS):
            raise
        except (errors.RPCError, ValueError):
            group.unknown_rules.append("Slow mode, member count and visible bot metadata may be unavailable.")
        else:
            info = getattr(full, "full_chat", None)
            if info is None:
                group.unknown_rules.append("Full-chat metadata was missing; detailed fields are unknown.")
            else:
                group.metadata_status = "complete" if permission_available else "partial"
                count = getattr(info, "participants_count", None)
                participants = getattr(getattr(info, "participants", None), "participants", None)
                if isinstance(count, int):
                    group.members = count
                elif isinstance(participants, list):
                    group.members = len(participants)
                group.slowmode_seconds = getattr(info, "slowmode_seconds", None)
                if group.slowmode_seconds is None and not getattr(entity, "slowmode_enabled", False):
                    group.slowmode_seconds = 0
                next_send = getattr(info, "slowmode_next_send_date", None)
                group.slowmode_next_send = int(next_send.timestamp()) if hasattr(next_send, "timestamp") else None
                bot_info = getattr(info, "bot_info", None)
                if bot_info is None:
                    group.unknown_rules.append("Visible bot metadata is unavailable.")
                else:
                    for bot in bot_info:
                        user_id = getattr(bot, "user_id", None)
                        if isinstance(user_id, int):
                            group.visible_bots.append(str(user_id))
                        else:
                            group.unknown_rules.append("Some visible bot records have no identifier.")
                if group.members is None or group.slowmode_seconds is None or bot_info is None:
                    group.metadata_status = "partial"
                group.unknown_rules.append("Visible bots are not necessarily moderation bots; their policies are unknown.")
        self.store.save_group(self.me.id, group)
        return group

    async def discover(self, progress: Callable[[int], None] | None = None, *,
                       on_group: Callable[[int, Group], None] | None = None) -> int:
        if self.store.cooldown(self.me.id) > time.time():
            raise ValueError("Account cooldown is active; discovery is paused.")
        count = 0
        seen: set[int] = set()
        try:
            # Leaving folder/archived unset includes archived and unarchived dialogs.
            async for dialog in self.client.iter_dialogs(ignore_migrated=True):
                entity = getattr(dialog, "entity", None)
                if not is_group(entity):
                    continue
                group = None
                try:
                    group = basic_group(entity)
                    if group.id in seen:
                        continue
                    seen.add(group.id)
                    group = await self.inspect(entity)
                except (errors.UnauthorizedError, *WAITS, OSError, sqlite3.Error):
                    raise
                except errors.RPCError:
                    if group is None:
                        continue
                    group.reasons = ["Group information unavailable; posting permissions are unknown."]
                    self.store.save_group(self.me.id, group)
                except Exception as exc:
                    report_programming_error(LOG, exc)
                    if group is None:
                        continue
                    group.permission = "unknown"
                    group.reasons = ["Unexpected group processing error; permission is unknown and sending is blocked."]
                    group.metadata_status = "error"
                    self.store.save_group(self.me.id, group)
                count += 1
                if progress:
                    progress(count)
                if on_group:
                    on_group(count, group)
        except WAITS as exc:
            self.store.set_cooldown(self.me.id, time.time() + exc.seconds)
            raise
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


async def discover_with_output(service: TelegramService) -> int:
    """One progress and summary renderer shared by both CLI entry points."""
    groups: list[Group] = []
    print("Discovering Telegram groups...", flush=True)

    def on_group(count: int, group: Group) -> None:
        groups.append(group)
        if group.metadata_status == "error":
            status = "Processing error (permission unknown)"
        elif group.permission == "denied":
            status = "Restricted"
        elif group.metadata_status != "complete":
            status = "Metadata unavailable"
        elif group.permission == "unknown":
            status = "Unknown permissions"
        else:
            status = "Found"
        print(f"[{count}] {json.dumps(group.name, ensure_ascii=True)} — {status}", flush=True)

    try:
        count = await service.discover(on_group=on_group)
    except BaseException:
        print(f"Discovery interrupted. Completed records reported: {len(groups)}; basic records already saved are retained.")
        raise
    print(f"Discovery completed.\nTotal groups: {count}")
    for state in ("allowed", "denied", "unknown"):
        print(f"Posting {state}: {sum(group.permission == state for group in groups)}")
    return count
