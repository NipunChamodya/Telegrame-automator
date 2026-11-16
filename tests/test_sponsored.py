"""Channel content remains gated unless the exact sponsored response is supported."""

from datetime import UTC, datetime

from telethon import functions, types
from test_v3_media_security import TemporaryBackendTests

from telegram_manager.content_policy import require_content_peer
from telegram_manager.ipc import IPCError


class SponsoredTests(TemporaryBackendTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.peer = -1000000000033
        self.client.get_entity.return_value = types.Channel(
            33,
            "Synthetic channel",
            types.ChatPhotoEmpty(),
            datetime.now(UTC),
            broadcast=True,
        )
        self.client.get_input_entity.return_value = types.InputPeerChannel(33, 9876)
        self.cache.save(
            11,
            {
                "id": self.peer,
                "name": "Synthetic channel",
                "kind": "channel",
                "content_known": True,
                "content_available": False,
            },
        )

    async def open(self):
        return await self.backend.dispatch(
            "sponsor", "sponsored.open", {"account_id": 11, "destination": self.peer}
        )

    async def test_channel_stays_blocked_before_prerequisite(self):
        with self.assertRaises(IPCError):
            await require_content_peer(self.client, 11, self.peer)

    async def test_real_empty_response_unlocks_only_current_client_and_peer(self):
        self.client.return_value = types.messages.SponsoredMessagesEmpty()
        result = await self.open()
        self.assertEqual(result["ads"], [])
        await require_content_peer(self.client, 11, self.peer)
        self.client._tgm_sponsored_grants = {}
        with self.assertRaises(IPCError):
            await require_content_peer(self.client, 11, self.peer)

    async def test_supported_text_exposes_scoped_tokens_and_actual_view_click(self):
        ad = types.SponsoredMessage(
            url="https://example.com/sponsor",
            title="Sponsor",
            message="Synthetic ad",
            button_text="Learn more",
            random_id=b"opaque",
            can_report=True,
        )
        self.client.return_value = types.messages.SponsoredMessages([ad], [], [])
        result = await self.open()
        token = result["ads"][0]["token"]
        self.assertNotIn("opaque", str(result))
        self.client.assert_awaited_once()  # fetching is not an impression
        self.client.reset_mock()
        self.client.return_value = True
        await self.backend.dispatch(
            "view", "sponsored.view", {"account_id": 11, "token": token}
        )
        self.assertIsInstance(
            self.client.call_args.args[0],
            functions.messages.ViewSponsoredMessageRequest,
        )
        await self.backend.dispatch(
            "click", "sponsored.click", {"account_id": 11, "token": token}
        )
        self.assertIsInstance(
            self.client.call_args.args[0],
            functions.messages.ClickSponsoredMessageRequest,
        )

    async def test_rich_media_deep_links_and_malformed_responses_fail_closed(self):
        for changes in (
            {"media": types.MessageMediaPhoto(types.PhotoEmpty(1))},
            {"url": "https://t.me/example"},
            {"entities": [types.MessageEntityBold(0, 1)]},
            {"url": "javascript:alert(1)"},
        ):
            ad = types.SponsoredMessage(
                **(
                    {
                        "url": "https://example.com",
                        "title": "Ad",
                        "message": "Text",
                        "button_text": "Open",
                        "random_id": b"opaque",
                    }
                    | changes
                )
            )
            self.client.return_value = types.messages.SponsoredMessages([ad], [], [])
            with self.subTest(changes=changes), self.assertRaises(IPCError):
                await self.open()
            with self.assertRaises(IPCError):
                await require_content_peer(self.client, 11, self.peer)

    async def test_no_forward_channel_never_requests_sponsored_or_history(self):
        self.client.get_entity.return_value.noforwards = True
        with self.assertRaises(IPCError):
            await self.open()
        self.client.assert_not_awaited()

    async def test_five_minute_cache_reuses_response_without_fabricating_views(self):
        self.client.return_value = types.messages.SponsoredMessagesEmpty()
        await self.open()
        await self.open()
        self.client.assert_awaited_once()

    async def test_cross_account_report_and_view_are_rejected(self):
        with self.assertRaises(IPCError):
            await self.backend.dispatch(
                "bad", "sponsored.view", {"account_id": 12, "token": "anything"}
            )
        self.client.assert_not_awaited()

    async def test_channel_archive_requires_successful_prerequisite_end_to_end(self):
        from unittest.mock import Mock

        from test_v3_media_security import image_message
        from test_v4_media import Chunks

        self.client.return_value = types.messages.SponsoredMessagesEmpty()
        message = image_message()
        message.peer_id = types.PeerChannel(33)

        async def history(peer, **options):
            if not options["offset_id"]:
                yield message

        self.client.iter_messages = history
        self.client.get_messages.return_value = message
        self.client.iter_download = Mock(side_effect=lambda *a, **k: Chunks())
        self.backend.archives.PAGE_DELAY = 0
        params = {
            "account_id": 11,
            "destination": self.peer,
            "types": ["photo"],
            "start": 0,
            "end": int(datetime.now(UTC).timestamp()) + 1,
            "timezone": "UTC",
            "organization": "daily",
            "folder": str(self.root),
        }
        with self.assertRaises(IPCError):
            await self.backend.dispatch("blocked", "archive.create", params)
        await self.open()
        result = await self.backend.dispatch("allowed", "archive.create", params)
        await self.backend.archives.task
        job = self.backend.archives.store.snapshot(
            self.backend.archives.store.job(result["job"]["id"], 11)
        )
        self.assertEqual(job["completed"], 1)
        self.client.assert_awaited_once()  # no fabricated sponsored impression

    async def test_report_options_are_bound_to_the_ad_token(self):
        ad = types.SponsoredMessage(
            url="https://example.com/sponsor",
            title="Sponsor",
            message="Synthetic",
            button_text="Open",
            random_id=b"opaque",
            can_report=True,
        )
        self.client.return_value = types.messages.SponsoredMessages([ad], [], [])
        token = (await self.open())["ads"][0]["token"]
        self.client.return_value = (
            types.channels.SponsoredMessageReportResultChooseOption(
                "Why report?",
                [types.SponsoredMessageReportOption("Spam", b"server-option")],
            )
        )
        options = await self.backend.dispatch(
            "report", "sponsored.report", {"account_id": 11, "token": token}
        )
        key = options["options"][0]["id"]
        self.assertNotIn("server-option", str(options))
        self.client.return_value = types.channels.SponsoredMessageReportResultReported()
        result = await self.backend.dispatch(
            "reason",
            "sponsored.report",
            {"account_id": 11, "token": token, "option": key},
        )
        self.assertTrue(result["reported"])
        self.assertEqual(self.client.call_args.args[0].option, b"server-option")
