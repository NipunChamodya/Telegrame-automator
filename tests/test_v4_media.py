"""Synthetic V4 transfers; no Telegram network, credentials, or user storage."""

import asyncio
from datetime import UTC
from unittest.mock import Mock

from telethon import types
from test_v3_media_security import PNG, TemporaryBackendTests, image_message

from telegram_manager.ipc import IPCError
from telegram_manager.media_policy import describe


class Chunks:
    def __init__(self, payload=PNG, wait=None):
        self.payload = payload
        self.wait = wait
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.wait:
            await self.wait.wait()
        if not self.payload:
            raise StopAsyncIteration
        value, self.payload = self.payload, b""
        return value

    async def close(self):
        self.closed = True


class MediaV4Tests(TemporaryBackendTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.message = image_message()
        self.client.get_messages.return_value = self.message
        self.stream = Chunks()
        self.client.iter_download = Mock(return_value=self.stream)

    async def call(self, method="media.download", request="transfer", **changes):
        params = {"account_id": 11, "destination": 22, "message_id": 7}
        if method == "media.download":
            params["path"] = str(self.root / "export.png")
        return await self.backend.dispatch(request, method, params | changes)

    async def test_success_private_atomic_and_no_overwrite(self):
        result = await self.call()
        output = self.root / "export.png"
        self.assertEqual(output.read_bytes(), PNG)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result["bytes"], len(PNG))
        self.assertEqual(len(result["sha256"]), 64)
        self.assertTrue(self.stream.closed)
        with self.assertRaises(IPCError):
            await self.call(request="duplicate")
        self.assertEqual(output.read_bytes(), PNG)

    async def test_lock_remains_available_and_deletion_cancels_transfer(self):
        self.stream.wait = asyncio.Event()
        task = asyncio.create_task(self.call())
        for _ in range(20):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        async with asyncio.timeout(1):
            async with self.backend.lock:
                self.backend.transfers.invalidate(22, [7])
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.stream.closed)
        self.assertFalse((self.root / "export.png").exists())
        self.assertEqual(list(self.root.glob(".telegram-media-*")), [])

    async def test_wrong_account_invalid_params_and_size_fail_before_stream(self):
        for changes in (
            {"account_id": 12},
            {"message_id": True},
            {"unexpected": "value"},
        ):
            with self.subTest(changes=changes), self.assertRaises(IPCError):
                await self.call(**changes)
        self.client.get_messages.return_value = image_message(size=600 * 1024 * 1024)
        with self.assertRaises(IPCError):
            await self.call()
        self.client.iter_download.assert_not_called()

    async def test_truncated_and_oversized_leave_no_partial_files(self):
        for payload in (PNG[:8], PNG + b"extra"):
            self.client.iter_download.return_value = Chunks(payload)
            with self.assertRaises(IPCError):
                await self.call()
            self.assertEqual(list(self.root.glob(".telegram-media-*")), [])
            self.assertFalse((self.root / "export.png").exists())

    async def test_context_shutdown_cancels_and_drains_transfer(self):
        self.stream.wait = asyncio.Event()
        task = asyncio.create_task(self.call())
        for _ in range(20):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        await self.backend.transfers.stop()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.backend.transfers.active, {})
        self.assertEqual(list(self.root.glob(".telegram-media-*")), [])

    async def test_two_transfer_limit_and_pause_resume(self):
        self.stream.wait = asyncio.Event()
        one = asyncio.create_task(self.call(request="one"))
        two = asyncio.create_task(
            self.call(request="two", path=str(self.root / "two.png"))
        )
        for _ in range(20):
            await asyncio.sleep(0)
        with self.assertRaises(IPCError) as caught:
            await self.call(request="three")
        self.assertEqual(caught.exception.code, "transfer_limit")
        paused = await self.backend.dispatch(
            "pause", "media.pause", {"account_id": 11, "request_id": "one"}
        )
        self.assertTrue(paused["paused"])
        resumed = await self.backend.dispatch(
            "resume", "media.resume", {"account_id": 11, "request_id": "one"}
        )
        self.assertFalse(resumed["paused"])
        one.cancel()
        two.cancel()
        await asyncio.gather(one, two, return_exceptions=True)

    async def test_open_release_private_cache_and_crash_recovery(self):
        opened = await self.call("media.open")
        from pathlib import Path

        path = Path(opened["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        from telegram_manager.media_transfers import TransferCache

        cache = TransferCache(self.backend)
        cache.recover_index(path.parent)
        self.assertFalse(path.exists())
        await self.backend.dispatch(
            "release", "media.release", {"account_id": 11, "token": opened["token"]}
        )

    def test_classification_distinguishes_timers_and_animated_documents(self):
        ordinary = image_message()
        self.assertEqual(describe(ordinary)["category"], "ordinary")
        self.assertTrue(describe(ordinary)["can_download"])
        auto = image_message(ttl_period=20)
        self.assertEqual(describe(auto)["category"], "auto_delete")
        once = image_message()
        once.media.ttl_seconds = 2147483647
        self.assertEqual(describe(once)["category"], "view_once")
        self.assertFalse(describe(once)["can_download"])
        once.media.ttl_seconds = 8
        self.assertEqual(describe(once)["category"], "self_destructing")
        once.media.ttl_seconds = None
        once.media.document.attributes.append(types.DocumentAttributeAnimated())
        self.assertEqual(describe(once)["kind"], "animation")
        once.media.document.attributes = [
            types.DocumentAttributeAudio(duration=1, voice=True)
        ]
        self.assertEqual(describe(once)["kind"], "voice")

    async def test_view_once_acknowledges_and_cannot_reopen_or_export(self):
        self.message.media.ttl_seconds = 2147483647
        with self.assertRaises(IPCError):
            await self.call()
        opened = await self.call("media.open")
        self.assertFalse(opened["can_download"])
        self.assertEqual(opened["category"], "view_once")
        from telethon import functions

        self.assertIsInstance(
            self.client.call_args.args[0], functions.messages.ReadMessageContentsRequest
        )
        await self.backend.dispatch(
            "release", "media.release", {"account_id": 11, "token": opened["token"]}
        )
        with self.assertRaises(IPCError) as caught:
            await self.call("media.open", request="reopen")
        self.assertEqual(caught.exception.code, "media_expired")
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM media_consumed").fetchone()[0],
            1,
        )

    async def test_expired_auto_delete_fails_before_file_creation(self):
        self.message.ttl_period = 5
        with self.assertRaises(IPCError):
            await self.call("media.open")
        self.client.iter_download.assert_not_called()

    async def test_auto_delete_open_countdown_no_export(self):
        import time
        from datetime import datetime

        self.message.date = datetime.now(UTC)
        self.message.ttl_period = 60
        opened = await self.call("media.open")
        self.assertFalse(opened["can_download"])
        self.assertGreater(opened["expires_at"], time.time())
        self.assertLessEqual(opened["expires_at"], time.time() + 60)
        self.client.assert_not_awaited()  # auto-delete is not a media-read timer
        with self.assertRaises(IPCError):
            await self.call()

    async def test_auto_delete_active_transfer_expires_without_waiting_for_network(
        self,
    ):
        from datetime import UTC, datetime

        self.message.date = datetime.now(UTC)
        self.message.ttl_period = 1
        self.stream.wait = asyncio.Event()
        task = asyncio.create_task(self.call("media.open"))
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        self.assertEqual(
            list((self.root / "media-cache").glob(".telegram-media-*")), []
        )

    async def test_filesystem_error_closes_iterator_and_removes_partial(self):
        from unittest.mock import patch

        with (
            patch(
                "telegram_manager.media_transfers.os.fsync",
                side_effect=PermissionError("synthetic"),
            ),
            self.assertRaises(PermissionError),
        ):
            await self.call()
        self.assertTrue(self.stream.closed)
        self.assertEqual(list(self.root.glob(".telegram-media-*")), [])

    async def test_retry_is_bounded_and_uses_completed_offset(self):
        class Interrupted(Chunks):
            async def __anext__(self):
                raise ConnectionError("synthetic")

        streams = [Interrupted(), Interrupted(), Interrupted()]
        self.client.iter_download.side_effect = streams
        from unittest.mock import AsyncMock, patch

        with (
            patch("telegram_manager.media_transfers.asyncio.sleep", new=AsyncMock()),
            self.assertRaises(IPCError),
        ):
            await self.call()
        self.assertEqual(self.client.iter_download.call_count, 3)
        self.assertTrue(all(s.closed for s in streams))
        self.assertFalse((self.root / "export.png").exists())

    async def test_ordinary_voice_decoding_uses_private_cache_and_preserves_original_export(
        self,
    ):
        from unittest.mock import patch

        self.message.media.document.mime_type = "audio/ogg"
        self.message.media.document.attributes = [
            types.DocumentAttributeAudio(duration=1, voice=True)
        ]

        async def decode(source, stream):
            self.assertEqual(source.read_bytes(), PNG)
            stream.write(b"RIFF" + b"\0" * 40)
            return 44

        with (
            patch(
                "telegram_manager.media_audio.converter",
                return_value="/synthetic/ffmpeg",
            ),
            patch("telegram_manager.media_audio.decode_voice", side_effect=decode),
        ):
            opened = await self.call("media.open")
        self.assertEqual(opened["mime_type"], "audio/wav")
        self.assertEqual(opened["bytes"], 44)
        from pathlib import Path

        path = Path(opened["path"])
        self.assertEqual(path.suffix, ".wav")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(list(path.parent.glob(".telegram-media-*"))), 1)

    async def test_account_transition_cancels_transfer_before_swapping_store(self):
        self.stream.wait = asyncio.Event()
        task = asyncio.create_task(self.call())
        for _ in range(20):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        added = await self.backend.dispatch(
            "switch",
            "accounts.add",
            {"confirm": True, "label": "Synthetic second account"},
        )
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertNotEqual(added["active_profile_id"], "legacy")
        self.assertFalse((self.root / "export.png").exists())
        self.assertEqual(list(self.root.glob(".telegram-media-*")), [])

    async def test_real_synthetic_ogg_decodes_without_telegram(self):
        from pathlib import Path

        from telegram_manager.media_audio import converter, decode_voice

        if converter() is None:
            self.skipTest("Optional local FFmpeg decoder is not installed")
        source = Path(__file__).parent / "fixtures/media/synthetic-voice.ogg"
        output = self.root / "voice.wav"
        with output.open("wb") as stream:
            length = await decode_voice(source, stream)
        self.assertGreater(length, 44)
        self.assertEqual(output.read_bytes()[:4], b"RIFF")
        self.client.assert_not_awaited()

    async def test_expired_viewer_event_cleans_file_and_consumed_marker_survives(self):
        self.message.media.ttl_seconds = 1
        events = []
        self.backend.emit_control = events.append
        opened = await self.call("media.open")
        from pathlib import Path

        path = Path(opened["path"])
        self.assertTrue(path.exists())
        await asyncio.sleep(1.1)
        self.assertFalse(path.exists())
        self.assertTrue(
            any(
                e["event"] == "media.expired" and e["data"]["token"] == opened["token"]
                for e in events
            )
        )
        with self.assertRaises(IPCError):
            await self.call("media.open", request="reintroduce")

    async def test_gap_reset_drains_old_manager_before_new_cache_ownership(self):
        self.stream.wait = asyncio.Event()
        task = asyncio.create_task(self.call("media.open"))
        for _ in range(20):
            if self.client.iter_download.called:
                break
            await asyncio.sleep(0)
        old = self.backend.transfers
        self.backend._close_media()
        descriptor = await self.call("media.get_metadata", request="after-gap")
        self.assertEqual(descriptor["category"], "ordinary")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNot(old, self.backend.transfers)
        self.assertFalse(old.active)

    def test_secret_chat_is_a_separate_unsupported_category(self):
        from datetime import UTC, datetime

        secret = types.EncryptedMessageService(
            random_id=1,
            chat_id=1,
            date=datetime.now(UTC),
            bytes=b"not-real-secret-content",
        )
        metadata = describe(secret)
        self.assertEqual(metadata["category"], "secret_chat")
        self.assertFalse(metadata["can_open"])
        self.assertFalse(metadata["can_download"])
