"""Small terminal dashboard. Drafts and destination selection live only in memory."""
import logging
import sqlite3
import time
from pathlib import Path

from telethon import errors

from .cache import CachePolicy, fresh
from .cli import compose
from .diagnostics import report_io_error, report_programming_error
from .error_messages import telegram_error_message
from .guidance import show_help
from .setup_wizard import authenticate, yes
from .telegram import discover_with_output, inspect_pending_with_output
from .terminal import TerminalOutputError, cell, clean_text, input, json_text, print, width


def display(value) -> None:
    # Escaping prevents Telegram-controlled names or file text from injecting terminal controls.
    print(json_text(value))


class Dashboard:
    def __init__(self, service, root: Path, source: str):
        self.service, self.root, self.source = service, root, source
        self.message: str | None = None
        self.destination: int | None = None

    def require_ready(self) -> None:
        remaining = max(0, int(self.service.store.cooldown(self.service.me.id) - time.time() + 0.999))
        if remaining:
            raise ValueError(f"Telegram cooldown: {remaining} seconds remaining. Resume explicitly after it expires.")

    async def refresh(self) -> None:
        self.require_ready()
        await discover_with_output(self.service)

    async def offer_refresh(self, *, first_run: bool = False) -> None:
        policy = getattr(self.service, 'policy', CachePolicy())
        overview = self.service.store.overview(self.service.me.id, policy)
        stale = not fresh(overview['last_seen'], policy.basic)
        print(f"Loaded {overview['total']} cached groups.")
        if self.service.store.cooldown(self.service.me.id) > time.time():
            print(f"Telegram cooldown: {max(0, int(self.service.store.cooldown(self.service.me.id) - time.time() + 0.999))} seconds remaining. "
                  "Resume explicitly after the required wait.")
        elif first_run:
            if yes("Would you like to discover your joined groups?", default=True):
                await self.perform("1")
        elif stale:
            if yes(f"Basic cache is empty or older than {policy.basic} seconds. Discover/refresh now?"):
                await self.perform("1")

    def header(self) -> None:
        policy = getattr(self.service, 'policy', CachePolicy())
        stats = self.service.store.overview(self.service.me.id, policy)
        scan = self.service.store.scan(self.service.me.id)
        last_basic = scan.get('last_basic') if scan.get('kind') == 'details' else scan
        last_basic = last_basic or {}
        remaining = max(0, int(self.service.store.cooldown(self.service.me.id) - time.time() + 0.999))
        print("\n========================================\n     TELEGRAM GROUP MANAGER\n========================================")
        print(f"Account: Connected ({self.service.me.id})\n\nGROUP OVERVIEW\n"
              f"Groups discovered: {stats['total']} (total cached)")
        for state in ('allowed', 'denied', 'unknown'):
            print(f"Posting {state}: {stats[state]}")
        print(f"\nDISCOVERY STATUS\nLast scan: {last_basic.get('started_at', 'Never')} "
              f"({last_basic.get('state', 'not run') if last_basic.get('state') != 'running' else 'unfinished'})\nMetadata complete: {stats['complete']}\n"
              f"Metadata incomplete: {stats['incomplete']}\nAwaiting permission inspection: {stats['pending']}\n"
              f"Current/last scan groups: {last_basic.get('processed', 0)}; new: {last_basic.get('new', 0)}; "
              f"updated: {last_basic.get('updated', 0)}; unchanged: {last_basic.get('unchanged', 0)}\n"
              f"Fresh detail cache: {stats['fresh']}; skipped: {scan.get('cache_skipped', 0)}\n"
              f"Telegram cooldown: {str(remaining) + ' seconds' if remaining else 'None'}")
        print("----------------------------------------\n"
              "1. Discover / Refresh Groups\n2. View All Groups\n3. Search Groups\n"
              "4. Inspect Group Permissions\n5. Compose Message\n6. Review Approved Destinations\n"
              "7. Send to Selected Group\n8. View Delivery History\n9. View Account Status\n"
              "10. Settings\n11. Help\n12. Inspect Pending / Expired Metadata\n0. Exit\n----------------------------------------")

    def view_groups(self, query: str = "") -> None:
        page, permission, sort = 0, 'all', 'name'
        policy = getattr(self.service, 'policy', CachePolicy())
        while True:
            rows, total = self.service.store.page(self.service.me.id, query=query, permission=permission,
                                                  sort=sort, page=page, size=10, policy=policy)
            columns = width()
            print(f"Groups — page {page + 1}/{max(1, (total + 9) // 10)}; matches: {total}; filter: {permission}")
            print('GROUP / TELEGRAM ID / POSTING STATUS')
            for group in rows:
                status = policy.permission(group).capitalize()
                print(cell(clean_text(group['name']), max(6, columns - 12)) + ' ' + status)
                print(f"  ID: {group['id']}")
                stamp = group.get('permissions_checked_at') or 'not inspected'
                print(cell(f"  Permissions checked: {stamp}", columns))
            command = input('[n] next [p] previous [f] filter [s] sort [q/Enter] return: ').strip().lower()
            if command == 'n' and (page + 1) * 10 < total:
                page += 1
            elif command == 'p' and page:
                page -= 1
            elif command == 'f':
                selected = input('all / allowed / denied / unknown: ').strip().lower()
                if selected in {'all', 'allowed', 'denied', 'unknown'}:
                    permission, page = selected, 0
            elif command == 's':
                selected = input('name / id / checked_at: ').strip().lower()
                if selected in {'name', 'id', 'checked_at'}:
                    sort, page = selected, 0
            else:
                return

    async def select(self) -> None:
        self.require_ready()
        destination = int(input("Exact group ID to select: ").strip())
        if not self.service.store.contains_group(self.service.me.id, destination):
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
        me = await authenticate(self.service.client, allow_login=False)
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
                self.view_groups(query)
            elif choice == "4":
                self.require_ready()
                destination = int(input("Group ID: "))
                if not store.contains_group(account, destination):
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
                         "cache_policy_seconds": vars(getattr(self.service, 'policy', CachePolicy())), "automatic_send": False,
                         "credential_changes": "Use environment overrides or macOS Keychain Access; no automatic overwrites.",
                         "drafts": "Memory only; replacing a draft clears destination selection."})
            elif choice == "11":
                show_help()
            elif choice == "12":
                self.require_ready()
                await inspect_pending_with_output(self.service)
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
        except TerminalOutputError as exc:
            report_io_error(logging.getLogger('telegram_manager.dashboard'), exc,
                            operation='terminal_output', database_writes_completed=bool(getattr(self.service, 'report', None) and self.service.report.processed))
            raise
        except OSError as exc:
            print(f"Telegram/network or file I/O failed ({type(exc).__name__}). "
                  "See sanitized I/O diagnostics for the operation and location. Saved progress was retained. "
                  "No retry attempted; cached views remain available. Relaunch to restore a lost connection.")
        except Exception as exc:
            report_programming_error(logging.getLogger("telegram_manager.dashboard"), exc)
            print("A programming error interrupted this operation. Set TGM_DEV_MODE=1 for sanitized "
                  "file/line diagnostics. Saved records were retained.")

    async def run(self, *, first_run: bool = False) -> None:
        await self.offer_refresh(first_run=first_run)
        while True:
            self.header()
            choice = input("Select: ").strip()
            if choice == "0":
                print("Goodbye. Session, metadata and delivery history preserved.")
                return
            await self.perform(choice)
