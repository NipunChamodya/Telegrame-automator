"""Bounded conversation archive jobs on the existing account/client/transfer owner."""

import asyncio
import json
import os
import secrets
import shutil
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telethon import errors

from .archive_policy import (
    conversation_folder,
    inspect_message,
    safe_tree,
    verify_async,
)
from .archive_store import ArchiveStore
from .content_policy import require_content_peer


class ArchiveJobs:
    METHODS = frozenset(
        {
            "archive.capabilities",
            "archive.create",
            "archive.list",
            "archive.get",
            "archive.pause",
            "archive.resume",
            "archive.cancel",
            "archive.retry_failed",
            "archive.incremental",
            "archive.items",
        }
    )
    PAGE_SIZE = 50
    PAGE_DELAY = 1.0

    def __init__(self, backend):
        self.backend = backend
        self.store = ArchiveStore(backend.store)
        self.store.recover()
        self.task = None
        self.current = None
        self.commands = asyncio.Lock()

    def scoped(self, generation, account):
        from .ipc import IPCError

        if (
            generation != self.backend.account_generation
            or account != self.backend.account()
        ):
            raise IPCError(
                "account_changed",
                "Select the original account to continue this archive.",
            )

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None
        self.current = None

    def with_progress(self, snapshot):
        entry = self.backend.transfers.active.get("archive_" + snapshot["id"])
        snapshot["in_progress_bytes"] = entry["bytes"] if entry else 0
        return snapshot

    def emit(self, identity):
        row = self.store.job(identity, self.backend.account())
        if row:
            self.backend.emit(
                {
                    "event": "archive.changed",
                    "data": {
                        **self.backend.scope(),
                        "job": self.with_progress(self.store.snapshot(row)),
                    },
                }
            )

    async def dispatch(self, method, p, generation):
        async with self.commands:
            return await self._dispatch(method, p, generation)

    async def _dispatch(self, method, p, generation):
        from .ipc import IPCError, fields, integer, string

        b = self.backend
        base = {"account_id"}
        if method == "archive.capabilities":
            allowed = base | {"destination"}
            required = allowed
        elif method == "archive.create":
            allowed = base | {
                "destination",
                "types",
                "start",
                "end",
                "timezone",
                "folder",
                "organization",
            }
            required = allowed
        elif method == "archive.list":
            allowed = required = base
        elif method == "archive.items":
            allowed = base | {"job_id", "page"}
            required = base | {"job_id"}
        else:
            allowed = required = base | {"job_id"}
        fields(p, allowed, required)
        account = integer(p, "account_id", minimum=1)
        self.scoped(generation, account)
        if method == "archive.list":
            return {
                "jobs": [self.with_progress(job) for job in self.store.list(account)],
                **b.scope(),
            }
        if method == "archive.capabilities":
            peer = integer(p, "destination")
            row = b.chats.store().get(account, peer)
            available = bool(
                row and row.get("content_available") and not row.get("is_bot")
            )
            if available:
                await b.chats.identity(account)
                await require_content_peer(b.client, account, peer)
                self.scoped(generation, account)
            return {
                "available": available,
                "reason": None
                if available
                else "Media saving is unavailable for this conversation. Open an accessible conversation first.",
                **b.scope(),
            }
        if method == "archive.create":
            if self.task and not self.task.done():
                raise IPCError(
                    "archive_busy", "Pause the current archive before starting another."
                )
            peer = integer(p, "destination")
            await b.chats.identity(account)
            await require_content_peer(b.client, account, peer)
            self.scoped(generation, account)
            row = b.chats.store().get(account, peer)
            if row is None:
                raise IPCError(
                    "destination_unavailable", "Choose a conversation first."
                )
            kinds = p["types"]
            if (
                not isinstance(kinds, list)
                or not 1 <= len(kinds) <= 5
                or any(
                    type(k) is not str
                    or k not in {"photo", "video", "animation", "document", "audio"}
                    for k in kinds
                )
                or len(set(kinds)) != len(kinds)
            ):
                raise IPCError(
                    "invalid_params", "Choose at least one supported media type."
                )
            start = integer(p, "start", minimum=0, maximum=32503680000)
            end = integer(p, "end", minimum=1, maximum=32503680000)
            if min(end, int(time.time()) + 1) <= start:
                raise IPCError(
                    "invalid_params", "The end date must follow the start date."
                )
            timezone = string(p, "timezone", maximum=128)
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise IPCError(
                    "invalid_params", "Choose a supported time zone."
                ) from None
            organization = string(p, "organization", maximum=16)
            if organization not in {"daily", "monthly", "type"}:
                raise IPCError(
                    "invalid_params", "Choose daily, monthly or media-type folders."
                )
            root = (
                Path(string(p, "folder", maximum=4096))
                .expanduser()
                .resolve(strict=True)
            )
            if not root.is_dir():
                raise IPCError("file_access", "Choose an existing folder.")
            leaf = conversation_folder(b.profile_id, account, peer, row["name"])
            for previous in self.store.db.execute(
                "SELECT config FROM archive_jobs WHERE account=? AND peer=? ORDER BY created DESC LIMIT 100",
                (account, peer),
            ):
                previous_config = json.loads(previous["config"])
                if previous_config["root"] == str(root):
                    leaf = Path(previous_config["folder"]).name
                    break
            folder, identity = safe_tree(root, ["Telegram Archives", leaf])
            identifier = secrets.token_hex(16)
            config = {
                "profile": b.profile_id,
                "conversation": row["name"][:256],
                "root": str(root),
                "folder": str(folder),
                "folder_identity": list(identity),
                "types": kinds,
                "start": start,
                "end": min(end, int(time.time()) + 1),
                "timezone": timezone,
                "organization": organization,
                "rolling": abs(end - time.time()) <= 10,
                "requested_end": end,
            }
            self.store.db.execute(
                "INSERT INTO archive_jobs(id,account,peer,config,state,created) VALUES (?,?,?,?,?,?)",
                (identifier, account, peer, json.dumps(config), "paused", time.time()),
            )
            self.store.db.commit()
            self.start(identifier, generation, account)
            return {
                "job": self.store.snapshot(self.store.job(identifier, account)),
                **b.scope(),
            }
        identity = string(p, "job_id", maximum=64)
        row = self.store.job(identity, account)
        if row is None:
            raise IPCError(
                "archive_missing",
                "This archive is unavailable for the selected account.",
            )
        if method == "archive.get":
            return {"job": self.with_progress(self.store.snapshot(row)), **b.scope()}
        if method == "archive.items":
            page = integer(p, "page", default=0, minimum=0, maximum=10000000)
            items = [
                {"message_id": r["message"], "state": r["state"], "note": r["note"]}
                for r in self.store.db.execute(
                    "SELECT message,state,note FROM archive_items WHERE job=? AND state NOT IN ('completed','duplicate','pending') ORDER BY message LIMIT 50 OFFSET ?",
                    (identity, page * 50),
                )
            ]
            return {"items": items, **b.scope()}
        if method in {"archive.pause", "archive.cancel"}:
            if self.current == identity:
                await self.stop()
            self.store.update(
                identity,
                state="cancelled" if method == "archive.cancel" else "paused",
                note="Saved files have been kept.",
            )
        else:
            if self.task and not self.task.done():
                raise IPCError(
                    "archive_busy",
                    "Pause the current archive before continuing another.",
                )
            if row["wait_until"] > time.time():
                raise IPCError(
                    "cooldown",
                    "Telegram asked for a wait. Resume after the displayed time.",
                )
            if method == "archive.retry_failed":
                self.store.db.execute(
                    "UPDATE archive_items SET state='pending',digest=NULL,note='' WHERE job=? AND state='failed'",
                    (identity,),
                )
                self.store.db.commit()
            if method == "archive.incremental":
                config = json.loads(row["config"])
                if config.get("rolling"):
                    config["end"] = int(time.time()) + 1
                else:
                    config["end"] = min(config.get('requested_end', config['end']), int(time.time()) + 1)
                identity = secrets.token_hex(16)
                self.store.db.execute(
                    "INSERT INTO archive_jobs(id,account,peer,config,state,created) VALUES (?,?,?,?,?,?)",
                    (
                        identity,
                        account,
                        row["peer"],
                        json.dumps(config),
                        "paused",
                        time.time(),
                    ),
                )
                self.store.db.commit()
            self.start(identity, generation, account)
        return {
            "job": self.store.snapshot(self.store.job(identity, account)),
            **b.scope(),
        }

    def start(self, identity, generation, account):
        self.current = identity
        self.store.update(identity, state="finding", note="", wait_until=0)
        self.task = asyncio.create_task(self.run(identity, generation, account))

    def destination(self, config, relative):
        folder = Path(config["folder"])
        path, identity = safe_tree(
            config["root"], folder.relative_to(config["root"]).parts
        )
        if list(identity) != config["folder_identity"]:
            raise ValueError("Archive folder changed")
        parts = Path(relative).parts
        if len(parts) != 2:
            raise ValueError("Unsafe archive item")
        directory, _ = safe_tree(path, [parts[0]])
        return directory / parts[1]

    async def save_item(self, job, item, config, generation, account):
        from .ipc import IPCError

        b = self.backend
        self.scoped(generation, account)
        if item.get("partial"):
            reservation = json.loads(item["partial"])
            recorded = self.destination(config, reservation["relative"])
            try:
                info = recorded.lstat()
                if (
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and [info.st_dev, info.st_ino] == reservation["identity"]
                ):
                    recorded.unlink()
            except FileNotFoundError:
                pass
            self.store.db.execute(
                "UPDATE archive_items SET partial=NULL WHERE job=? AND message=?",
                (job["id"], item["message"]),
            )
            self.store.db.commit()
        metadata = json.loads(item["metadata"])
        from .media_policy import fetch_media_message

        def validate_metadata(fresh):
            refreshed = inspect_message(fresh, job["peer"], config)
            if refreshed is None or refreshed[0] != "pending":
                raise IPCError(
                    "media_unavailable", "This item no longer permits export."
                )
            if refreshed[3] != item["fingerprint"]:
                raise IPCError(
                    "media_changed",
                    "This attachment changed. Check for new media after this run.",
                )

        async def validate_source():
            await b.chats.identity(account)
            fresh = await fetch_media_message(
                b.client, account, job["peer"], item["message"]
            )
            self.scoped(generation, account)
            validate_metadata(fresh)

        output = self.destination(config, item["relative"])
        prior = self.store.db.execute(
            "SELECT * FROM archive_files WHERE account=? AND peer=? AND message=? AND fingerprint=? AND folder=?",
            (
                account,
                job["peer"],
                item["message"],
                item["fingerprint"],
                config["folder"],
            ),
        ).fetchone()
        if prior:
            existing = self.destination(config, prior["relative"])
            try:
                valid = await verify_async(existing, prior["bytes"], prior["digest"])
            except OSError:
                valid = False
            self.scoped(generation, account)
            if valid is True:
                await validate_source()
                self.store.db.execute(
                    "UPDATE archive_items SET state='duplicate',note='Already saved and verified.' WHERE job=? AND message=?",
                    (job["id"], item["message"]),
                )
                self.store.db.commit()
                return
        # A crash may publish the final file before completion was recorded.
        if item["digest"]:
            try:
                recovered = await verify_async(output, item["bytes"], item["digest"])
            except OSError:
                recovered = False
            if recovered is True:
                await validate_source()
                self.complete(
                    job, item, config, item["relative"], item["bytes"], item["digest"]
                )
                return
        stem = output.stem
        suffix = output.suffix
        for number in range(10000):
            candidate = (
                output
                if number == 0
                else output.with_name(f"{stem} ({number}){suffix}")
            )
            if not candidate.exists() and not candidate.is_symlink():
                output = candidate
                break
        else:
            raise IPCError(
                "file_access",
                "Too many matching filenames. Choose another destination.",
            )
        if (
            shutil.disk_usage(output.parent).free
            < (metadata["size"] or 0) + 16 * 1024 * 1024
        ):
            raise IPCError(
                "low_storage", "Not enough free space. Free some space, then resume."
            )
        relative = str(output.relative_to(config["folder"]))

        def reserve(path, identity):
            relative = str(path.relative_to(config["folder"]))
            self.destination(config, relative)
            self.store.db.execute(
                "UPDATE archive_items SET partial=? WHERE job=? AND message=?",
                (
                    json.dumps({"relative": relative, "identity": list(identity)}),
                    job["id"],
                    item["message"],
                ),
            )
            self.store.db.commit()

        def journal(size, digest):
            self.scoped(generation, account)
            self.destination(config, relative)
            self.store.db.execute(
                "UPDATE archive_items SET relative=?,bytes=?,digest=? WHERE job=? AND message=?",
                (relative, size, digest, job["id"], item["message"]),
            )
            self.store.db.commit()

        while len(b.transfers.active) >= b.transfers.LIMIT:
            await asyncio.sleep(0.2)
            self.scoped(generation, account)
        result = await b.transfers.dispatch(
            "archive_" + job["id"],
            "media.download",
            {
                "account_id": account,
                "destination": job["peer"],
                "message_id": item["message"],
                "path": str(output),
            },
            generation,
            on_publish=journal,
            on_reserve=reserve,
            on_metadata=validate_metadata,
        )
        self.complete(job, item, config, relative, result["bytes"], result["sha256"])

    def complete(self, job, item, config, relative, size, digest):
        self.store.db.execute(
            "INSERT OR REPLACE INTO archive_files VALUES (?,?,?,?,?,?,?,?)",
            (
                job["account"],
                job["peer"],
                item["message"],
                item["fingerprint"],
                config["folder"],
                relative,
                size,
                digest,
            ),
        )
        self.store.db.execute(
            "UPDATE archive_items SET state='completed',relative=?,bytes=?,digest=?,note='',partial=NULL WHERE job=? AND message=?",
            (relative, size, digest, job["id"], item["message"]),
        )
        self.store.db.commit()

    async def run(self, identity, generation, account):
        from .ipc import IPCError

        b = self.backend
        try:
            while True:
                self.scoped(generation, account)
                job = self.store.job(identity, account)
                config = json.loads(job["config"])
                if config["profile"] != b.profile_id:
                    raise IPCError(
                        "account_changed",
                        "Select the original account to resume this archive.",
                    )
                b.require_cooldown_expired()
                if b.transfers.closed:
                    await b.transfers.stop()
                    from .media_transfers import MediaTransfers

                    b.transfers = MediaTransfers(b)
                pending = self.store.db.execute(
                    "SELECT * FROM archive_items WHERE job=? AND state='pending' ORDER BY message DESC LIMIT 1",
                    (identity,),
                ).fetchone()
                if pending:
                    self.store.update(identity, state="saving")
                    try:
                        await self.save_item(
                            job, dict(pending), config, generation, account
                        )
                    except IPCError as exc:
                        if exc.code in {
                            "low_storage",
                            "file_access",
                            "account_changed",
                            "cooldown",
                            "channel_refresh",
                        }:
                            raise
                        state = (
                            "restricted"
                            if exc.code in {"media_unavailable", "content_unavailable"}
                            else "deleted"
                            if exc.code in {"message_unavailable", "media_expired"}
                            else "failed"
                        )
                        self.store.db.execute(
                            "UPDATE archive_items SET state=?,note=? WHERE job=? AND message=?",
                            (
                                state,
                                "Cannot export this item."
                                if state == "restricted"
                                else "Unavailable. Retry later."
                                if state == "failed"
                                else "Deleted or expired.",
                                identity,
                                pending["message"],
                            ),
                        )
                        self.store.db.commit()
                    self.emit(identity)
                    continue
                if job["scan_done"]:
                    snapshot = self.store.snapshot(job)
                    self.store.update(
                        identity,
                        state="attention" if snapshot["failed"] else "finished",
                        note="Finished. Review skipped items below."
                        if snapshot["restricted"]
                        or snapshot["unsupported"]
                        or snapshot["deleted"]
                        else "All discovered files have been processed.",
                    )
                    break
                self.store.update(identity, state="finding")
                await b.chats.identity(account)
                await require_content_peer(b.client, account, job["peer"])
                self.scoped(generation, account)
                page = []
                for attempt in range(3):
                    try:
                        page = []
                        async for message in b.client.iter_messages(
                            job["peer"],
                            limit=self.PAGE_SIZE,
                            offset_id=job["cursor"],
                            offset_date=datetime.fromtimestamp(config["end"], UTC),
                        ):
                            self.scoped(generation, account)
                            if len(page) >= self.PAGE_SIZE:
                                raise ValueError("Oversized history page")
                            page.append(message)
                        break
                    except (ConnectionError, TimeoutError):
                        if attempt == 2:
                            raise IPCError(
                                "network",
                                "The connection was interrupted. Resume to try again.",
                            ) from None
                        await asyncio.sleep(2**attempt)
                cursor = job["cursor"]
                older = True
                for message in page:
                    mid = getattr(message, "id", None)
                    if type(mid) is not int or mid <= 0 or cursor and mid >= cursor:
                        raise ValueError("Invalid history order")
                    cursor = mid
                    result = inspect_message(message, job["peer"], config)
                    date = getattr(message, "date", None)
                    if (
                        not isinstance(date, datetime)
                        or date.timestamp() >= config["start"]
                    ):
                        older = False
                    if result:
                        state, metadata, relative, fingerprint = result
                        self.store.db.execute(
                            "INSERT INTO archive_items(job,message,fingerprint,metadata,relative,state,bytes) VALUES (?,?,?,?,?,?,?) ON CONFLICT(job,message) DO NOTHING",
                            (
                                identity,
                                mid,
                                fingerprint,
                                json.dumps(metadata),
                                relative,
                                state,
                                metadata.get("size") or 0,
                            ),
                        )
                self.store.update(
                    identity,
                    cursor=cursor,
                    examined=job["examined"] + len(page),
                    scan_done=int(not page or older),
                )
                self.emit(identity)
                await asyncio.sleep(self.PAGE_DELAY)
        except asyncio.CancelledError:
            self.store.update(
                identity, state="paused", note="Paused. Saved files have been kept."
            )
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            until = time.time() + max(1, exc.seconds)
            b.store.set_cooldown(account, until)
            self.store.update(
                identity,
                state="waiting",
                wait_until=until,
                note="Telegram asked for a wait. Resume when the timer ends.",
            )
        except Exception as exc:  # noqa: BLE001 - background job boundary must persist a safe terminal state
            from .ipc import IPCError

            note = (
                exc.message
                if isinstance(exc, IPCError)
                else "Saving stopped safely. Check the connection, folder access and free space, then resume."
            )
            if isinstance(exc, IPCError) and exc.code == "cooldown":
                self.store.update(
                    identity,
                    state="waiting",
                    wait_until=b.store.cooldown(account),
                    note="Telegram asked for a wait. Resume when the timer ends.",
                )
            else:
                self.store.update(identity, state="attention", note=note)
        finally:
            self.emit(identity)
            if self.current == identity:
                self.current = None
