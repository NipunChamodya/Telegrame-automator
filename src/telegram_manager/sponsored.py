"""Fail-closed channel prerequisite. Unsupported sponsored variants never unlock content."""

import secrets
import time
from urllib.parse import urlsplit

from telethon import functions, types, utils

from .terminal import clean_text


def granted(client, peer):
    grants = getattr(client, "_tgm_sponsored_grants", None)
    return isinstance(grants, dict) and grants.get(peer) is True


class SponsoredMessages:
    METHODS = frozenset(
        {"sponsored.open", "sponsored.view", "sponsored.click", "sponsored.report"}
    )

    def __init__(self, backend):
        self.backend = backend
        self.cache = {}
        self.tokens = {}
        self.options = {}

    async def dispatch(self, method, p, generation):
        from .ipc import IPCError, fields, integer, string

        fields(
            p,
            {"account_id", "destination"}
            if method == "sponsored.open"
            else {"account_id", "token", "option"}
            if method == "sponsored.report"
            else {"account_id", "token"},
            {"account_id", "destination"}
            if method == "sponsored.open"
            else {"account_id", "token"},
        )
        b = self.backend
        account = integer(p, "account_id", minimum=1)
        if generation != b.account_generation or account != b.account():
            raise IPCError("account_changed", "The selected account changed.")
        await b.chats.identity(account)
        if method == "sponsored.open":
            peer = integer(p, "destination")
            entity = await b.client.get_entity(peer)
            if (
                not isinstance(entity, types.Channel)
                or not entity.broadcast
                or entity.megagroup
                or utils.get_peer_id(entity) != peer
                or any(
                    getattr(entity, k, False)
                    for k in (
                        "restricted",
                        "restriction_reason",
                        "noforwards",
                        "left",
                        "kicked",
                        "deactivated",
                    )
                )
            ):
                raise IPCError(
                    "content_unavailable",
                    "This channel is unavailable or does not permit media export.",
                )
            cached = self.cache.get(peer)
            if cached and cached["expires"] > time.monotonic():
                return {**cached["result"], **b.scope()}
            grants = getattr(b.client, "_tgm_sponsored_grants", None)
            if not isinstance(grants, dict):
                grants = {}
                b.client._tgm_sponsored_grants = grants
            grants.pop(peer, None)
            result = await b.client(
                functions.messages.GetSponsoredMessagesRequest(
                    await b.client.get_input_entity(peer)
                )
            )
            if not isinstance(
                result,
                (
                    types.messages.SponsoredMessages,
                    types.messages.SponsoredMessagesEmpty,
                ),
            ):
                raise IPCError(
                    "sponsored_unavailable",
                    "This channel cannot be opened safely right now. Try again later.",
                )
            ads = []
            for ad in getattr(result, "messages", []):
                # Rich media, Telegram deep-links, timed ads and unknown fields need their complete
                # presentation lifecycle. Never drop these ads while exposing the channel.
                if not isinstance(ad, types.SponsoredMessage) or not isinstance(
                    ad.url, str
                ):
                    raise IPCError(
                        "sponsored_unsupported",
                        "This sponsored format is unavailable. Channel content stays blocked.",
                    )
                try:
                    url = urlsplit(ad.url)
                except ValueError:
                    raise IPCError(
                        "sponsored_unsupported",
                        "This sponsored link is unavailable. Channel content stays blocked.",
                    ) from None
                if (
                    len(ads) >= 10
                    or not isinstance(ad, types.SponsoredMessage)
                    or not isinstance(ad.random_id, bytes)
                    or not 0 < len(ad.random_id) <= 256
                    or any(
                        getattr(ad, key, None)
                        for key in (
                            "media",
                            "photo",
                            "color",
                            "min_display_duration",
                            "max_display_duration",
                        )
                    )
                    or ad.entities
                    or url.scheme != "https"
                    or not url.hostname
                    or url.username
                    or url.password
                    or any(
                        url.hostname == host or url.hostname.endswith("." + host)
                        for host in (
                            "t.me",
                            "telegram.me",
                            "telegram.org",
                            "telegram.dog",
                            "telegra.ph",
                            "te.legra.ph",
                            "graph.org",
                            "fragment.com",
                            "telesco.pe",
                        )
                    )
                    or any(
                        not isinstance(value, str) or len(value) > maximum
                        for value, maximum in (
                            (ad.url, 2048),
                            (ad.title, 256),
                            (ad.message, 4096),
                            (ad.button_text, 128),
                        )
                    )
                ):
                    raise IPCError(
                        "sponsored_unsupported",
                        "This channel uses a sponsored format this version cannot display yet. Its content stays unavailable.",
                    )
                token = secrets.token_urlsafe(24)
                self.tokens[token] = {
                    "peer": peer,
                    "ad": ad,
                    "expires": time.monotonic() + 300,
                    "viewed": False,
                }
                ads.append(
                    {
                        "token": token,
                        "title": clean_text(ad.title),
                        "text": clean_text(ad.message),
                        "button": clean_text(ad.button_text),
                        "label": "Recommended" if ad.recommended else "Sponsored",
                        "can_report": bool(ad.can_report),
                        "info": clean_text(
                            (ad.sponsor_info or "") + "\n" + (ad.additional_info or "")
                        )[:4096],
                    }
                )
            if any(getattr(result, k, None) for k in ("start_delay", "between_delay")):
                raise IPCError(
                    "sponsored_unsupported",
                    "This channel needs a presentation mode this version does not support yet.",
                )
            # Bound ephemeral token storage independently of conversation navigation.
            self.tokens = {
                token: value
                for token, value in self.tokens.items()
                if value["expires"] > time.monotonic()
            }
            if len(self.tokens) > 200:
                self.tokens = {
                    token: self.tokens[token] for token in [ad["token"] for ad in ads]
                }
            self.cache = {
                key: value
                for key, value in self.cache.items()
                if value["expires"] > time.monotonic()
            }
            if len(self.cache) >= 20:
                self.cache.clear()
                grants.clear()
            grants[peer] = True
            row = b.chats.store().get(account, peer)
            if row is None:
                raise IPCError(
                    "destination_unavailable",
                    "Refresh conversations and select the channel again.",
                )
            row.update(
                content_available=True,
                content_known=True,
                content_reason=None,
                sponsored_ready=True,
            )
            b.chats.store().save(account, row)
            reply = {"ads": ads, "chat": row, "expires_at": time.time() + 300}
            self.cache[peer] = {"expires": time.monotonic() + 300, "result": reply}
            return {**reply, **b.scope()}
        token = string(p, "token", maximum=128)
        item = self.tokens.get(token)
        if item is None or item["expires"] <= time.monotonic():
            raise IPCError(
                "sponsored_expired", "Refresh this channel before continuing."
            )
        ad = item["ad"]
        if method == "sponsored.view":
            if not item["viewed"]:
                await b.client(
                    functions.messages.ViewSponsoredMessageRequest(ad.random_id)
                )
                item["viewed"] = True
            return {"accepted": True, **b.scope()}
        if method == "sponsored.click":
            await b.client(
                functions.messages.ClickSponsoredMessageRequest(random_id=ad.random_id)
            )
            return {"url": ad.url, **b.scope()}
        if not ad.can_report:
            raise IPCError(
                "report_unavailable", "This sponsored message cannot be reported."
            )
        if not p.get("option"):
            self.options = {
                key: value
                for key, value in self.options.items()
                if key[0] != token and key[0] in self.tokens
            }
        option = string(p, "option", default="", maximum=128)
        raw = self.options.get((token, option)) if option else b""
        if raw is None:
            raise IPCError(
                "invalid_params", "Choose one of the available report options."
            )
        report = await b.client(
            functions.messages.ReportSponsoredMessageRequest(
                option=raw, random_id=ad.random_id
            )
        )
        if isinstance(report, types.channels.SponsoredMessageReportResultChooseOption):
            choices = []
            for entry in report.options[:20]:
                key = secrets.token_urlsafe(16)
                self.options[(token, key)] = entry.option
                choices.append({"id": key, "title": clean_text(entry.text)[:256]})
            return {
                "title": clean_text(report.title)[:256],
                "options": choices,
                **b.scope(),
            }
        if not isinstance(
            report,
            (
                types.channels.SponsoredMessageReportResultReported,
                types.channels.SponsoredMessageReportResultAdsHidden,
            ),
        ):
            raise IPCError("report_unavailable", "The report could not be completed.")
        self.cache.pop(item["peer"], None)
        return {"reported": True, **b.scope()}
