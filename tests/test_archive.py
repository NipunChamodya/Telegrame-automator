"""Synthetic archive histories and temporary destinations; never contacts Telegram."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from telethon import types
from test_v3_media_security import PNG, TemporaryBackendTests, image_message
from test_v4_media import Chunks

from telegram_manager.archive_jobs import ArchiveJobs
from telegram_manager.archive_policy import conversation_folder
from telegram_manager.ipc import IPCError


class ArchiveTests(TemporaryBackendTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.backend.archives.PAGE_DELAY = 0
        self.messages = [image_message(identity=i) for i in range(1, 4)]
        self.calls = []

        async def history(peer, **options):
            self.calls.append(options)
            rows = [
                m
                for m in self.messages
                if not options["offset_id"] or m.id < options["offset_id"]
            ]
            for message in sorted(rows, key=lambda m: m.id, reverse=True)[
                : options["limit"]
            ]:
                yield message

        self.client.iter_messages = history

        async def get(peer, ids):
            return next((m for m in self.messages if m.id == ids), None)

        self.client.get_messages.side_effect = get
        self.client.iter_download = Mock(side_effect=lambda *args, **kwargs: Chunks())
        self.params = {
            "account_id": 11,
            "destination": 22,
            "types": ["photo", "video", "animation", "document", "audio"],
            "start": 0,
            "end": int(datetime.now(UTC).timestamp()) + 10,
            "timezone": "Asia/Colombo",
            "organization": "daily",
            "folder": str(self.root),
        }

    async def create(self, **changes):
        result = await self.backend.dispatch(
            "create", "archive.create", self.params | changes
        )
        await asyncio.wait_for(self.backend.archives.task, 5)
        return result["job"]["id"]

    def job(self, identity):
        return self.backend.archives.store.snapshot(
            self.backend.archives.store.job(identity, 11)
        )

    async def control(self, method, identity):
        return await self.backend.dispatch(
            "control", method, {"account_id": 11, "job_id": identity}
        )

    async def test_ordinary_files_daily_folders_and_integrity(self):
        identity = await self.create()
        job = self.job(identity)
        self.assertEqual(job["state"], "finished")
        self.assertEqual(job["completed"], 3)
        files = list(Path(job["folder"]).rglob("*.png"))
        self.assertEqual(len(files), 3)
        self.assertTrue(
            all(
                p.parent.name == "2026-10-28"
                and p.read_bytes() == PNG
                and p.stat().st_mode & 0o777 == 0o600
                for p in files
            )
        )
        self.assertEqual(job["bytes"], 3 * len(PNG))

    async def test_restricted_and_timed_never_download(self):
        self.messages[0].noforwards = True
        self.messages[1].media.ttl_seconds = 2147483647
        self.messages[2].ttl_period = 60
        identity = await self.create()
        self.assertEqual(self.job(identity)["restricted"], 3)
        self.assertEqual(self.job(identity)["completed"], 0)
        self.client.iter_download.assert_not_called()
        self.client.assert_not_awaited()  # no media-read acknowledgements

    async def test_repeat_archive_verifies_duplicates_without_redownload(self):
        await self.create()
        self.client.iter_download.reset_mock()
        second = await self.create()
        self.assertEqual(self.job(second)["duplicates"], 3)
        self.client.iter_download.assert_not_called()

    async def test_modified_user_file_is_preserved_and_collision_is_numbered(self):
        first = await self.create()
        path = next(Path(self.job(first)["folder"]).rglob("*.png"))
        path.write_bytes(b"user edit")
        second = await self.create()
        self.assertEqual(path.read_bytes(), b"user edit")
        self.assertEqual(self.job(second)["completed"], 1)
        self.assertEqual(self.job(second)["duplicates"], 2)
        self.assertEqual(len(list(path.parent.glob("*.png"))), 4)

    async def test_date_end_is_exclusive_and_types_filter(self):
        stamp = int(self.messages[0].date.timestamp())
        identity = await self.create(start=stamp, end=stamp + 1, types=["photo"])
        self.assertEqual(self.job(identity)["completed"], 3)
        second = await self.create(start=stamp - 1, end=stamp)
        self.assertEqual(self.job(second)["discovered"], 0)

    async def test_thousand_message_history_uses_bounded_pages(self):
        date = self.messages[0].date
        self.messages = [
            types.Message(
                id=i, peer_id=types.PeerUser(22), date=date, message="synthetic"
            )
            for i in range(1, 1002)
        ]
        identity = await self.create()
        self.assertEqual(self.job(identity)["examined"], 1001)
        self.assertTrue(all(c["limit"] == 50 for c in self.calls))
        self.assertLessEqual(len(self.calls), 22)

    async def test_pause_and_resume_preserve_original_context(self):
        wait = asyncio.Event()
        self.client.iter_download = Mock(side_effect=lambda *a, **k: Chunks(wait=wait))
        result = await self.backend.dispatch("create", "archive.create", self.params)
        identity = result["job"]["id"]
        for _ in range(30):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        await self.control("archive.pause", identity)
        self.assertEqual(self.job(identity)["state"], "paused")
        wait.set()
        await self.control("archive.resume", identity)
        await self.backend.archives.task
        self.assertEqual(self.job(identity)["completed"], 3)
        self.assertEqual(self.job(identity)["destination"], 22)

    async def test_restart_recovery_does_not_start_network(self):
        identity = await self.create()
        self.backend.archives.store.update(identity, state="saving")
        self.client.reset_mock()
        replacement = ArchiveJobs(self.backend)
        self.assertEqual(replacement.store.job(identity, 11)["state"], "paused")
        self.assertIsNone(replacement.task)
        self.client.assert_not_awaited()

    async def test_recover_published_file_before_ledger_completion(self):
        identity = await self.create()
        db = self.store.db
        db.execute("DELETE FROM archive_files")
        db.execute("UPDATE archive_items SET state='pending' WHERE job=?", (identity,))
        db.commit()
        self.client.iter_download.reset_mock()
        await self.control("archive.resume", identity)
        await self.backend.archives.task
        self.assertEqual(self.job(identity)["completed"], 3)
        self.client.iter_download.assert_not_called()

    async def test_low_space_stops_without_success(self):
        with patch(
            "telegram_manager.archive_jobs.shutil.disk_usage",
            return_value=type("Disk", (), {"free": 0})(),
        ):
            identity = await self.create()
        self.assertEqual(self.job(identity)["state"], "attention")
        self.assertEqual(self.job(identity)["completed"], 0)
        self.client.iter_download.assert_not_called()

    async def test_symlink_in_daily_tree_never_receives_files(self):
        first = await self.create()
        folder = Path(self.job(first)["folder"])
        daily = folder / "2026-10-28"
        for file in daily.iterdir():
            file.unlink()
        daily.rmdir()
        daily.symlink_to(self.root, target_is_directory=True)
        second = await self.create()
        self.assertEqual(self.job(second)["state"], "attention")
        self.assertEqual(list(self.root.glob("photo_*.png")), [])

    async def test_wrong_account_and_invalid_options_rejected(self):
        for changes in (
            {"account_id": 12},
            {"types": []},
            {"types": ["unknown"]},
            {"start": 10, "end": 9},
            {"timezone": "../invalid"},
            {"organization": "../escape"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises((IPCError, ValueError)),
            ):
                await self.create(**changes)

    def test_same_named_conversations_and_accounts_have_distinct_folders(self):
        names = {
            conversation_folder(profile, account, peer, "../same/name")
            for profile, account, peer in [
                ("one", 11, 22),
                ("one", 11, 23),
                ("two", 11, 22),
                ("one", 12, 22),
            ]
        }
        self.assertEqual(len(names), 4)
        self.assertTrue(all("/" not in name and "\\" not in name for name in names))

    async def test_incremental_run_is_new_immutable_job_and_only_saves_new_files(self):
        first = await self.create()
        original = dict(self.backend.archives.store.job(first, 11))
        self.messages.append(image_message(identity=4))
        result = await self.control("archive.incremental", first)
        second = result["job"]["id"]
        await self.backend.archives.task
        self.assertNotEqual(first, second)
        self.assertEqual(
            self.backend.archives.store.job(first, 11)["config"], original["config"]
        )
        self.assertEqual(self.job(second)["completed"], 1)
        self.assertEqual(self.job(second)["duplicates"], 3)

    async def test_conversation_rename_retains_stable_folder(self):
        first = await self.create()
        row = self.cache.get(11, 22)
        row["name"] = "Renamed conversation"
        self.cache.save(11, row)
        second = await self.create()
        self.assertEqual(self.job(first)["folder"], self.job(second)["folder"])
        self.assertEqual(self.job(second)["duplicates"], 3)

    async def test_retry_failed_revalidates_and_saves_only_failed_items(self):
        self.client.iter_download = Mock(
            side_effect=lambda *a, **k: Chunks(b"oversized" * 100)
        )
        identity = await self.create()
        self.assertEqual(self.job(identity)["failed"], 3)
        self.client.iter_download = Mock(side_effect=lambda *a, **k: Chunks())
        await self.control("archive.retry_failed", identity)
        await self.backend.archives.task
        self.assertEqual(self.job(identity)["completed"], 3)
        self.assertEqual(self.job(identity)["failed"], 0)

    async def test_floodwait_is_persisted_and_resume_cannot_evade_deadline(self):
        from telethon import errors

        async def flooded(*args, **kwargs):
            raise errors.FloodWaitError(request=None, capture=5)
            yield

        self.client.iter_messages = flooded
        identity = await self.create()
        self.assertEqual(self.job(identity)["state"], "waiting")
        self.assertGreater(
            self.job(identity)["wait_until"], datetime.now(UTC).timestamp()
        )
        with self.assertRaises(IPCError):
            await self.control("archive.resume", identity)
        self.client.iter_download.assert_not_called()

    async def test_account_switch_drains_job_and_does_not_publish_old_file(self):
        wait = asyncio.Event()
        self.client.iter_download = Mock(side_effect=lambda *a, **k: Chunks(wait=wait))
        result = await self.backend.dispatch("create", "archive.create", self.params)
        folder = Path(result["job"]["folder"])
        old = self.backend.archives
        for _ in range(30):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        task = old.task
        await self.backend.dispatch(
            "switch", "accounts.add", {"confirm": True, "label": "Synthetic account"}
        )
        self.assertTrue(task.done())
        self.assertEqual(list(folder.rglob("*.png")), [])
        self.assertNotEqual(self.backend.profile_id, "legacy")

    async def test_owned_partial_is_cleaned_and_published_file_recovered(self):
        identity = await self.create()
        db = self.store.db
        item = dict(
            db.execute(
                "SELECT * FROM archive_items WHERE job=? LIMIT 1", (identity,)
            ).fetchone()
        )
        folder = Path(self.job(identity)["folder"])
        partial = (
            folder / Path(item["relative"]).parent / ".telegram-media-synthetic.png"
        )
        partial.write_bytes(b"partial")
        partial.chmod(0o600)
        info = partial.stat()
        db.execute("DELETE FROM archive_files")
        db.execute(
            "UPDATE archive_items SET state='pending',partial=? WHERE job=? AND message=?",
            (
                json.dumps(
                    {
                        "relative": str(partial.relative_to(folder)),
                        "identity": [info.st_dev, info.st_ino],
                    }
                ),
                identity,
                item["message"],
            ),
        )
        db.commit()
        self.client.iter_download.reset_mock()
        await self.control("archive.resume", identity)
        await self.backend.archives.task
        self.assertFalse(partial.exists())
        self.client.iter_download.assert_not_called()

    async def test_malformed_metadata_and_wrong_peer_never_export(self):
        self.messages = [
            image_message(size=True),
            image_message(size=600 * 1024 * 1024, identity=2),
        ]
        identity = await self.create()
        self.assertEqual(self.job(identity)["unsupported"], 2)
        self.client.iter_download.assert_not_called()
        self.messages = [image_message(peer=23)]
        identity = await self.create()
        self.assertEqual(self.job(identity)["state"], "attention")
        self.client.iter_download.assert_not_called()

    async def test_two_simultaneous_starts_cannot_orphan_a_second_worker(self):
        wait = asyncio.Event()
        self.client.iter_download = Mock(side_effect=lambda *a, **k: Chunks(wait=wait))
        results = await asyncio.gather(
            self.backend.dispatch("one", "archive.create", self.params),
            self.backend.dispatch("two", "archive.create", self.params),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(isinstance(r, IPCError) for r in results), 1)
        await self.backend.archives.stop()

    def test_unicode_folder_components_fit_filesystem_byte_limits(self):
        name = conversation_folder("profile", 11, 22, "👩🏽‍💻 தமிழ் සිංහල " * 80)
        self.assertLessEqual(len(name.encode("utf-8")), 255)
        self.assertNotIn("/", name)

    async def test_daily_folders_use_original_timestamp_in_selected_timezone(self):
        self.messages = [image_message()]
        self.messages[0].date = datetime(2026, 10, 28, 23, 30, tzinfo=UTC)
        identity = await self.create()
        self.assertEqual(self.job(identity)["completed"], 1)
        self.assertTrue((Path(self.job(identity)["folder"]) / "2026-10-29").is_dir())

    async def test_basic_groups_and_supergroups_archive_through_same_policy(self):
        for peer, entity, kind, peer_id in [
            (
                -22,
                types.Chat(
                    22, "Group", types.ChatPhotoEmpty(), 3, datetime.now(UTC), 1
                ),
                "group",
                types.PeerChat(22),
            ),
            (
                -1000000000033,
                types.Channel(
                    33,
                    "Supergroup",
                    types.ChatPhotoEmpty(),
                    datetime.now(UTC),
                    megagroup=True,
                ),
                "supergroup",
                types.PeerChannel(33),
            ),
        ]:
            with self.subTest(kind=kind):
                self.client.get_entity.return_value = entity
                self.cache.save(
                    11,
                    {
                        "id": peer,
                        "name": kind,
                        "kind": kind,
                        "content_known": True,
                        "content_available": True,
                    },
                )
                self.messages = [image_message()]
                self.messages[0].peer_id = peer_id
                identity = await self.create(destination=peer)
                self.assertEqual(self.job(identity)["completed"], 1)
