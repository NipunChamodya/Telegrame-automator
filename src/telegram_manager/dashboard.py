"""Small terminal dashboard. Drafts and destination selection live only in memory."""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import errors

from .cli import compose
from .error_messages import telegram_error_message
from .guidance import show_help
from .setup_wizard import authenticate, yes


def display(value) -> None:
    # Escaping prevents Telegram-controlled names or file text from injecting terminal controls.
    print(json.dumps(value, ensure_ascii=True, indent=2))


class Dashboard:
    def __init__(self, service, root: Path, source: str):
        self.service, self.root, self.source = service, root, source
        self.message: str | None = None
        self.destination: int | None = None

    def require_ready(self) -> None:
        if self.service.store.cooldown(self.service.me.id) > time.time():
            raise ValueError("Account cooldown is active. Wait before further Telegram operations.")

    async def refresh(self) -> None:
        self.require_ready()
        def progress(count: int) -> None:
            print(f"Inspected {count} groups…", flush=True)
        count = await self.service.discover(progress=progress)
        print(f"Saved {count} group snapshots.")

    async def offer_refresh(self, *, first_run: bool = False) -> None:
        groups = self.service.store.groups(self.service.me.id)
        stale = not groups
        try:
            stale = stale or any(datetime.fromisoformat(g["checked_at"]) <
                                 datetime.now(timezone.utc) - timedelta(hours=24) for g in groups)
        except (ValueError, KeyError, TypeError):
            stale = True
        print(f"Loaded {len(groups)} cached groups.")
        if self.service.store.cooldown(self.service.me.id) > time.time():
            print("A saved Telegram cooldown is active. Discovery can resume after the required wait.")
        elif first_run:
            if yes("Would you like to discover your joined groups?", default=True):
                await self.perform("1")
        elif stale:
            if yes("Group cache is empty or older than 24 hours. Discover/refresh now?"):
                await self.perform("1")

    def header(self) -> None:
        groups = self.service.store.groups(self.service.me.id)
        print("\n========================================\n     TELEGRAM GROUP MANAGER\n========================================")
        print(f"Account: Connected ({self.service.me.id})\nGroups discovered: {len(groups)}")
        for state in ("allowed", "denied", "unknown"):
            print(f"Posting {state}: {sum(g['permission'] == state for g in groups)}")
        print("----------------------------------------\n"
              "1. Discover / Refresh Groups\n2. View All Groups\n3. Search Groups\n"
              "4. Inspect Group Permissions\n5. Compose Message\n6. Review Approved Destinations\n"
              "7. Send to Selected Group\n8. View Delivery History\n9. View Account Status\n"
              "10. Settings\n11. Help\n0. Exit\n----------------------------------------")

    async def select(self) -> None:
        self.require_ready()
        destination = int(input("Exact group ID to select: ").strip())
        if destination not in {g["id"] for g in self.service.store.groups(self.service.me.id)}:
            raise ValueError("Select a discovered group; refresh the dashboard first.")
        group = await self.service.inspect(destination)
        display(group.data())
        if group.permission != "allowed":
            raise ValueError("Destination selection blocked: posting permission is not allowed.")
        if yes("Select this one destination for a later message confirmation?"):
            self.destination = destination
        print("Destination selection does not authorize a send.")

    async def send(self) -> None:
        if self.message is None or self.destination is None:
            raise ValueError("Compose a message (5) and select a destination (6) first.")
        self.require_ready()
        me = await authenticate(self.service.client)
        if me.id != self.service.me.id:
            self.destination = None
            raise ValueError("Account identity changed; restart with the matching session.")
        self.service.me = me
        group = await self.service.inspect(self.destination)
        if group.permission != "allowed":
            raise ValueError("Fresh permissions block sending.")
        message, destination = self.message, self.destination
        display({"account_id": me.id, "destination": destination, "name": group.name,
                 "message": message, "unknown_rules": group.unknown_rules})
        expected = f"SEND {destination}"
        if input(f"Type {expected!r} to approve this exact message and destination: ") != expected:
            print("Cancelled. Nothing sent.")
            return
        # Clear approval state before the network operation, including on interruption.
        self.destination = None
        print(await self.service.send(destination, message))

    async def perform(self, choice: str) -> None:
        try:
            store, account = self.service.store, self.service.me.id
            if choice == "1":
                await self.refresh()
            elif choice in {"2", "3"}:
                query = input("Search: ") if choice == "3" else ""
                display(store.groups(account, query))
            elif choice == "4":
                self.require_ready()
                destination = int(input("Group ID: "))
                if destination not in {g["id"] for g in store.groups(account)}:
                    raise ValueError("Choose a discovered group.")
                display((await self.service.inspect(destination)).data())
            elif choice == "5":
                path = input("UTF-8 message file path, or Enter to compose: ").strip()
                message = compose(Path(path).expanduser() if path else None)
                self.message, self.destination = message, None
                display({"message": message, "utf16_units": len(message.encode('utf-16-le')) // 2})
                print("Draft replaced; select a destination with option 6.")
            elif choice == "6":
                display({"selected_destination": self.destination, "send_approval": "required for each send"})
                if yes("Select or change the destination?"):
                    await self.select()
            elif choice == "7":
                await self.send()
            elif choice == "8":
                display(store.history(account))
            elif choice == "9":
                display({"account_id": account, "restricted": bool(getattr(self.service.me, "restricted", False)),
                         "cooldown_until_epoch": store.cooldown(account),
                         "unknown": "Telegram does not expose all account-wide spam restrictions."})
            elif choice == "10":
                display({"data_directory": str(self.root), "credentials": self.source,
                         "cache_stale_after_hours": 24, "automatic_send": False,
                         "credential_changes": "Use environment overrides or macOS Keychain Access; no automatic overwrites.",
                         "drafts": "Memory only; replacing a draft clears destination selection."})
            elif choice == "11":
                show_help()
            else:
                print("Choose one of the displayed menu numbers.")
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            self.service.store.set_cooldown(self.service.me.id, time.time() + exc.seconds)
            print(f"Telegram requires a wait of {exc.seconds} seconds. No retry attempted.")
        except errors.UnauthorizedError as exc:
            self.destination = None
            print(telegram_error_message(exc))
            raise
        except errors.RPCError as exc:
            print(telegram_error_message(exc))
        except sqlite3.Error:
            print("Database failure. Stop and check disk space, permissions and backups. No records were reset.")
            raise
        except UnicodeError:
            print("Message file must be valid UTF-8 text. Its contents were not logged.")
        except ValueError as exc:
            print(str(exc))
        except OSError as exc:
            print(f"Operation failed ({type(exc).__name__}); check network/file access. No automatic retry.")

    async def run(self, *, first_run: bool = False) -> None:
        await self.offer_refresh(first_run=first_run)
        while True:
            self.header()
            choice = input("Select: ").strip()
            if choice == "0":
                print("Goodbye. Session, metadata and delivery history preserved.")
                return
            await self.perform(choice)
