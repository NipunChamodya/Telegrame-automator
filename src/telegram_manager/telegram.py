import asyncio
import logging
import math
import os
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from telethon import TelegramClient, errors, functions, types, utils
from telethon.tl.custom import ParticipantPermissions

from .cache import CachePolicy, fresh
from .diagnostics import report_io_error, report_programming_error
from .models import Group, ScanReport, now
from .storage import Store
from .terminal import TerminalOutputError, clean_text, print


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
        self.policy = CachePolicy.from_environment()
        self.operation = "idle"
        self.report: ScanReport | None = None
        try:
            self.request_interval = float(os.environ.get("TGM_REQUEST_INTERVAL_SECONDS", "0.5"))
        except ValueError:
            raise ValueError("TGM_REQUEST_INTERVAL_SECONDS must be between 0 and 5.") from None
        if not math.isfinite(self.request_interval) or not 0 <= self.request_interval <= 5:
            raise ValueError("TGM_REQUEST_INTERVAL_SECONDS must be between 0 and 5.")
        self._last_request = 0.0

    def require_ready(self) -> None:
        remaining = max(0, math.ceil(self.store.cooldown(self.me.id) - time.time()))
        if remaining:
            raise ValueError(f"Telegram cooldown: {remaining} seconds remaining. Resume explicitly after it expires.")

    async def _request(self, operation: str, callback):
        self.require_ready()
        self.operation = operation
        delay = self.request_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_request = time.monotonic()
        return await callback()

    async def inspect(self, entity: Any, *, force: bool = True) -> Group:
        self.require_ready()
        destination = utils.get_peer_id(entity) if not isinstance(entity, int) else entity
        cached = self.store.get_group(self.me.id, destination)
        if not force and cached and not self.policy.inspection_due(cached):
            return Group.from_data(cached)
        # Never replace a valid cached record with a pending write before doing I/O.
        if cached is None and isinstance(entity, (types.Chat, types.Channel, types.ChatForbidden, types.ChannelForbidden)):
            self.store.save_group(self.me.id, basic_group(entity))
        try:
            group = await self._inspect_remote(entity, cached=cached, force=force)
            group.inspection_attempted_at = now()
            group.unknown_rules = list(dict.fromkeys(group.unknown_rules))
            if cached:
                group.archived = cached.get('archived')
                group.discovered_at = cached.get('discovered_at')
            self.store.save_group(self.me.id, group)
            return group
        except WAITS as exc:
            self.store.set_cooldown(self.me.id, time.time() + exc.seconds)
            raise
        except OSError as exc:
            report_io_error(LOG, exc, operation=self.operation,
                            database_writes_completed=self.store.contains_group(self.me.id, destination))
            raise

    async def _inspect_remote(self, entity: Any, *, cached: dict | None = None, force: bool = True) -> Group:
        known = isinstance(entity, (types.Chat, types.Channel, types.ChatForbidden, types.ChannelForbidden))
        group = basic_group(entity) if known else Group.from_data(cached) if cached else None
        if group is not None:
            group.permission = "unknown"
            group.permissions_checked_at = None
            group.metadata_status = "partial"
        if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
            group.permission, group.reasons = analyze(entity, None, self.me)
            group.membership = "inaccessible"
            group.permissions_checked_at = now()
            return group
        try:
            entity = await self._request("entity_lookup", lambda: self.client.get_entity(entity))
        except (errors.UnauthorizedError, *WAITS):
            raise
        except ACCESS_DENIED:
            if group is None:
                raise
            group.permission, group.reasons = "denied", ["Telegram reports group access is restricted."]
            group.permissions_checked_at = now()
            group.membership = "inaccessible"
            return group
        except (errors.RPCError, ValueError):
            if group is None:
                raise
            group.reasons = ["Fresh group information unavailable; posting permission is unknown."]
            return group
        basic = basic_group(entity)
        group = Group.from_data(cached) if cached and not force else basic
        for key in ('name', 'kind', 'username'):
            setattr(group, key, getattr(basic, key))
        if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
            group.permission, group.reasons = analyze(entity, None, self.me)
            group.membership = "inaccessible"
            group.permissions_checked_at = now()
            return group
        group.membership = "active"
        need_permissions = force or not cached or not fresh(cached.get('permissions_checked_at'), self.policy.permissions)
        need_full = (force or not cached or cached.get('metadata_status') != 'complete'
                     or not fresh(cached.get('members_checked_at'), self.policy.members)
                     or not fresh(cached.get('metadata_checked_at'), self.policy.metadata)
                     or isinstance(entity, types.Chat) and need_permissions)
        full = None
        if need_full:
            group.unknown_rules = basic.unknown_rules.copy()
            try:
                request = (functions.channels.GetFullChannelRequest(entity) if isinstance(entity, types.Channel)
                           else functions.messages.GetFullChatRequest(entity.id))
                full = await self._request("full_chat_metadata", lambda: self.client(request))
            except (errors.UnauthorizedError, *WAITS):
                raise
            except errors.RPCError:
                group.unknown_rules.append("Full-chat metadata is unavailable.")
        info = getattr(full, "full_chat", None)
        permissions = None
        if need_permissions:
            group.permission, group.permissions_checked_at = "unknown", None
            group.reasons = ["Posting permissions could not be verified."]
        try:
            if isinstance(entity, types.Chat) and need_permissions:
                # Basic-chat GetFullChat already contains membership. Reuse it;
                # get_permissions would fetch the same full chat again.
                participants = getattr(getattr(info, "participants", None), "participants", None)
                if isinstance(participants, list):
                    member = next((p for p in participants if getattr(p, "user_id", None) == self.me.id), None)
                    if member is not None:
                        permissions = ParticipantPermissions(member, chat=True)
                    else:
                        group.permission = "denied"
                        group.reasons = ["Telegram's complete participant list does not include this account."]
            elif need_permissions:
                result = await self._request("participant_permissions", lambda: self.client(
                    functions.channels.GetParticipantRequest(entity, self.me)))
                member = getattr(result, "participant", None)
                if member is not None:
                    permissions = ParticipantPermissions(member, chat=False)
        except (errors.UnauthorizedError, *WAITS):
            raise
        except ACCESS_DENIED:
            group.permission, group.reasons = "denied", ["Telegram reports membership or posting access is restricted."]
        except errors.RPCError:
            group.reasons = ["Posting permissions could not be verified."]
        if permissions is not None:
            group.permission, group.reasons = analyze(entity, permissions, self.me)
        if need_permissions:
            if permissions is None and group.permission != "denied":
                group.permission = "unknown"
            group.permissions_checked_at = now() if group.permission != "unknown" else None
        if need_full:
            group.metadata_status = "partial"
            group.visible_bots = []
            group.metadata_checked_at = None
            group.members_checked_at = None
            group.slowmode_seconds = None
            group.slowmode_next_send = None
        if info is not None:
            group.metadata_checked_at = now()
            count = getattr(info, "participants_count", None)
            participants = getattr(getattr(info, "participants", None), "participants", None)
            if isinstance(count, int):
                group.members = count
            elif isinstance(participants, list):
                group.members = len(participants)
            group.members_checked_at = now() if group.members is not None else None
            group.slowmode_seconds = getattr(info, "slowmode_seconds", None)
            if group.slowmode_seconds is None and not getattr(entity, "slowmode_enabled", False):
                group.slowmode_seconds = 0
            next_send = getattr(info, "slowmode_next_send_date", None)
            group.slowmode_next_send = int(next_send.timestamp()) if hasattr(next_send, "timestamp") else None
            bots = getattr(info, "bot_info", None)
            if bots is not None:
                for bot in bots:
                    user_id = getattr(bot, "user_id", None)
                    if isinstance(user_id, int):
                        group.visible_bots.append(str(user_id))
                    else:
                        group.unknown_rules.append("Some visible bot identifiers are unavailable.")
            else:
                group.unknown_rules.append("Visible bot metadata is unavailable.")
            if group.permission != "unknown" and group.members is not None and group.slowmode_seconds is not None and bots is not None:
                group.metadata_status = "complete"
            group.unknown_rules.append("Bot presence does not establish a moderation role or reveal its policies.")
        elif need_full:
            group.unknown_rules.append("Full-chat metadata was missing; detailed fields are unknown.")
        if group.permission == "unknown":
            group.metadata_status = "partial"
        group.checked_at = now()
        return group

    async def discover(self, progress: Callable[[int], None] | None = None, *,
                       on_group: Callable[[int, Group], None] | None = None,
                       detailed: bool = False, force: bool = False,
                       on_inspected: Callable[[int, Group, bool], None] | None = None) -> int:
        self.require_ready()
        report = self.report = ScanReport()
        self.store.save_scan(self.me.id, report.data())
        seen: set[int] = set()
        try:
            self.operation = "dialog_iteration"
            async for dialog in self.client.iter_dialogs(ignore_migrated=True):
                entity = getattr(dialog, "entity", None)
                if not is_group(entity):
                    continue
                try:
                    basic = basic_group(entity)
                    if basic.id in seen:
                        continue
                    seen.add(basic.id)
                    old = self.store.get_group(self.me.id, basic.id)
                    group = Group.from_data(old) if old else basic
                    changes = any(getattr(group, key) != getattr(basic, key) for key in ('name', 'kind', 'username'))
                    archived = getattr(dialog, "archived", None)
                    if archived is None:
                        archived = group.archived
                    membership = "inaccessible" if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)) else "active"
                    changes = changes or group.archived != archived or group.membership != membership
                    for key in ('name', 'kind', 'username'):
                        setattr(group, key, getattr(basic, key))
                    group.archived = archived
                    group.discovered_at = report.started_at
                    if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden)):
                        group.membership = "inaccessible"
                        group.permission, group.reasons = analyze(entity, None, self.me)
                        group.permissions_checked_at = now()
                    else:
                        if group.membership == "inaccessible":
                            group.permission, group.permissions_checked_at = "unknown", None
                            group.metadata_status = "partial"
                            changes = True
                        group.membership = "active"
                    next_state = report.data()
                    if not detailed and not self.policy.inspection_due(group.data()):
                        next_state['cache_skipped'] += 1
                    next_state['processed'] += 1
                    next_state['new' if old is None else 'updated' if changes else 'unchanged'] += 1
                    self.store.save_group(self.me.id, group, scan=next_state)
                    # Advance counters only after the group and progress transaction commits.
                    for key in ('processed', 'new', 'updated', 'unchanged', 'cache_skipped'):
                        setattr(report, key, next_state[key])
                except (sqlite3.Error, OSError):
                    raise
                except Exception as exc:
                    report_programming_error(LOG, exc)
                    continue
                if progress:
                    progress(report.processed)
                if on_group:
                    on_group(report.processed, group)
                self.operation = "dialog_iteration"
            if detailed:
                await self._inspect_pending(report, force=force, current_scan=True, on_inspected=on_inspected)
            report.state = "completed"
        except WAITS as exc:
            report.state = "cooldown"
            self.store.set_cooldown(self.me.id, time.time() + exc.seconds)
            raise
        except sqlite3.Error:
            report.state = "database_error"
            raise
        except TerminalOutputError as exc:
            report.state = "output_unavailable"
            report_io_error(LOG, exc, operation="terminal_output", database_writes_completed=report.processed > 0)
            raise
        except OSError as exc:
            report.state = "network_interrupted"
            report_io_error(LOG, exc, operation=self.operation, database_writes_completed=report.processed > 0)
            raise
        except BaseException:
            report.state = "interrupted"
            raise
        finally:
            report.finished_at = now()
            self.store.save_scan(self.me.id, report.data())
        return report.processed

    async def _inspect_pending(self, report: ScanReport, *, force: bool, current_scan: bool = False,
                               on_inspected: Callable[[int, Group, bool], None] | None = None) -> None:
        report.phase = "details"
        # Cursor iteration is bounded in Python memory. Each group is committed
        # independently; cached records not seen in this scan are never deleted.
        for index, data in enumerate(self.store.iter_groups(self.me.id), 1):
            if current_scan and data.get("discovered_at") != report.started_at:
                continue
            if not force and (not self.policy.inspection_due(data) or data.get('membership') == 'inaccessible'
                              and fresh(data.get('permissions_checked_at'), self.policy.permissions)):
                report.cache_skipped += 1
                if on_inspected:
                    on_inspected(index, Group.from_data(data), True)
                continue
            try:
                group = await self.inspect(data['id'], force=force)
                report.inspected += 1
            except (errors.UnauthorizedError, *WAITS, OSError, sqlite3.Error):
                raise
            except errors.RPCError:
                continue
            except Exception as exc:
                report_programming_error(LOG, exc)
                group = Group.from_data(data)
                group.permission, group.metadata_status = "unknown", "error"
                group.permissions_checked_at = None
                self.store.save_group(self.me.id, group)
            self.store.save_scan(self.me.id, report.data())
            if on_inspected:
                on_inspected(index, group, False)

    async def inspect_pending(self, *, force: bool = False,
                              on_inspected: Callable[[int, Group, bool], None] | None = None) -> int:
        self.require_ready()
        prior = self.store.scan(self.me.id)
        last_basic = prior if prior.get('kind', 'discovery') == 'discovery' else prior.get('last_basic')
        report = self.report = ScanReport(phase="details", kind="details", last_basic=last_basic)
        self.store.save_scan(self.me.id, report.data())
        try:
            await self._inspect_pending(report, force=force, on_inspected=on_inspected)
            report.state = "completed"
        except WAITS:
            report.state = "cooldown"
            raise
        except sqlite3.Error:
            report.state = "database_error"
            raise
        except TerminalOutputError as exc:
            report.state = "output_unavailable"
            report_io_error(LOG, exc, operation="terminal_output", database_writes_completed=report.inspected > 0)
            raise
        except OSError:
            report.state = "network_interrupted"
            raise
        except BaseException:
            report.state = "interrupted"
            raise
        finally:
            report.finished_at = now()
            self.store.save_scan(self.me.id, report.data())
        return report.inspected

    async def send(self, destination: int, message: str) -> str:
        if not message.strip() or len(message.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("Message must contain 1–4096 UTF-16 units of text.")
        if not self.store.contains_group(self.me.id, destination):
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


async def discover_with_output(service: TelegramService, *, detailed: bool = False, force: bool = False) -> int:
    print("Discovering Telegram groups (lightweight scan)...", flush=True)

    def on_group(count: int, group: Group) -> None:
        print(f"[{count}] {clean_text(group.name)} — Basic metadata saved", flush=True)

    try:
        count = await service.discover(on_group=on_group, detailed=detailed, force=force, on_inspected=inspection_progress)
    except TerminalOutputError:
        raise  # Repeating output to a closed pipe cannot recover it.
    except WAITS as exc:
        report = service.store.scan(service.me.id)
        print(f"Telegram requested a {exc.seconds}-second cooldown.\nDiscovery paused safely. "
              f"{report.get('processed', 0)} groups processed. Progress saved.\n"
              "Resume explicitly after the cooldown expires.")
        raise
    except BaseException:
        print("Discovery interrupted. Saved records were retained.")
        raise
    report = service.store.scan(service.me.id)
    overview = service.store.overview(service.me.id, getattr(service, "policy", CachePolicy()))
    print(f"Discovery completed.\nTotal groups: {count} (current scan)\n"
          f"New: {report.get('new', 0)}; updated: {report.get('updated', 0)}; "
          f"unchanged: {report.get('unchanged', 0)}; fresh detail cache skipped: {report.get('cache_skipped', 0)}\n"
          f"Total cached groups: {overview['total']}; metadata complete: {overview['complete']}; "
          f"incomplete: {overview['incomplete']}; awaiting permission inspection: {overview['pending']}")
    for state in ("allowed", "denied", "unknown"):
        print(f"Posting {state}: {overview[state]}")
    return count


def inspection_progress(index: int, group: Group, skipped: bool) -> None:
    status = "Cache fresh — skipped" if skipped else f"{group.permission.capitalize()} / metadata {group.metadata_status}"
    print(f"[Details {index}] {clean_text(group.name)} — {status}", flush=True)


async def inspect_pending_with_output(service: TelegramService, *, force: bool = False) -> int:
    print("Inspecting metadata sequentially...", flush=True)
    try:
        count = await service.inspect_pending(force=force, on_inspected=inspection_progress)
    except WAITS as exc:
        report = service.store.scan(service.me.id)
        print(f"Telegram requested a {exc.seconds}-second cooldown. Metadata inspection paused safely; "
              f"{report.get('inspected', 0)} groups inspected. Resume explicitly after the cooldown expires.")
        raise
    print(f"Metadata inspection completed: {count} groups refreshed; "
          f"{service.store.scan(service.me.id).get('cache_skipped', 0)} cached inspections skipped.")
    return count
