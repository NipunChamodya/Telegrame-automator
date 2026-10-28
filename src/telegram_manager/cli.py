import argparse
import asyncio
import fcntl
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from telethon import TelegramClient, errors

from .security import private_directory
from .error_messages import telegram_error_message
from .setup_wizard import AUTH_CONNECTION_RETRIES, AUTH_REQUEST_RETRIES, authenticate
from .storage import Store
from .telegram import TelegramService, discover_with_output
from .diagnostics import report_programming_error

LOG = logging.getLogger("telegram_manager")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "event": record.getMessage()})


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Permission-aware Telegram group manager")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Authenticate interactively (phone, code, optional 2FA)")
    sub.add_parser("discover", help="Refresh joined group metadata")
    listing = sub.add_parser("groups", help="Search the local group dashboard")
    listing.add_argument("--search", default="")
    inspect = sub.add_parser("inspect", help="Refresh and display one group's metadata")
    inspect.add_argument("destination", type=int)
    send = sub.add_parser("send", help="Compose and confirm a message to one explicit group")
    send.add_argument("destination", type=int)
    send.add_argument("--file", type=Path, help="UTF-8 plain text message file")
    sub.add_parser("history", help="Show the latest 100 delivery records")
    return result


def compose(path: Path | None) -> str:
    if path:
        message = path.read_text(encoding="utf-8")
    else:
        print("Compose plain text. Enter a single '.' on a line to finish:")
        lines = []
        while (line := input()) != ".":
            lines.append(line)
        message = "\n".join(lines)
    if not message.strip():
        raise ValueError("Message must not be empty.")
    if len(message.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("Message exceeds 4096 UTF-16 units; automatic splitting is disabled.")
    return message


async def run(args: argparse.Namespace) -> None:
    os.umask(0o077)
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID", ""), os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id.isdecimal() or int(api_id) <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
        raise ValueError("Set valid TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables.")
    root = private_directory(Path(os.environ.get("TGM_DATA_DIR", str(
        Path.home() / "Library/Application Support/TelegramGroupManager"))))
    lock = (root / "manager.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("Another manager process is running; close it first.") from None
    store = Store(root / "manager.sqlite3")
    client = TelegramClient(str(root / "account"), int(api_id), api_hash,
                            flood_sleep_threshold=0,
                            request_retries=AUTH_REQUEST_RETRIES if args.command == "login" else 0,
                            connection_retries=AUTH_CONNECTION_RETRIES if args.command == "login" else 0,
                            auto_reconnect=False,
                            raise_last_call_error=True)
    me = None
    try:
        if args.command == "login" and store.cooldown(0) > time.time():
            raise ValueError("Authentication cooldown is active; wait before requesting another login code.")
        await client.connect()
        if args.command == "login":
            if not sys.stdin.isatty():
                raise ValueError("Login requires an interactive terminal.")
            me = await authenticate(client)
            print("Authenticated. Session saved in the private application directory.")
            return
        if not await client.is_user_authorized():
            raise ValueError("Run 'tgm login' first.")
        me = await client.get_me()
        if me.bot:
            raise ValueError("This application requires a personal user account.")
        service = TelegramService(client, store, me)
        if args.command in {"discover", "inspect", "send"} and store.cooldown(me.id) > time.time():
            raise ValueError("Account cooldown is active; wait before further Telegram operations.")
        if args.command == "discover":
            await discover_with_output(service)
        elif args.command == "groups":
            for group in store.groups(me.id, args.search):
                print(json.dumps(group, ensure_ascii=True))
        elif args.command == "inspect":
            print(json.dumps((await service.inspect(args.destination)).data(), indent=2, ensure_ascii=True))
        elif args.command == "history":
            for row in store.history(me.id):
                print(json.dumps(row))
        elif args.command == "send":
            if not sys.stdin.isatty():
                raise ValueError("Sending requires an interactive terminal and explicit confirmation.")
            known = {g["id"] for g in store.groups(me.id)}
            if args.destination not in known:
                raise ValueError("Destination must first be found with 'tgm discover'.")
            group = await service.inspect(args.destination)
            if group.permission != "allowed":
                raise ValueError("Sending blocked: " + "; ".join(group.reasons))
            message = compose(args.file)
            print(json.dumps({"destination": group.id, "name": group.name, "message": message,
                              "unknown_rules": group.unknown_rules}, indent=2, ensure_ascii=True))
            expected = f"SEND {args.destination}"
            if input(f"Type {expected!r} to approve this exact destination and message: ") != expected:
                print("Cancelled. Nothing sent.")
                return
            print(await service.send(args.destination, message))
    except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
        store.set_cooldown(me.id if me else 0, time.time() + exc.seconds)
        raise ValueError(f"Telegram requires a wait of {exc.seconds} seconds. No retry attempted.") from None
    finally:
        await client.disconnect()
        store.close()
        lock.close()


def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    # Third-party exception messages may contain private request data.
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    try:
        asyncio.run(run(parser().parse_args()))
    except (ValueError, OSError, EOFError) as exc:
        # Log only the event type; never message text, credentials or session data.
        LOG.error(type(exc).__name__)
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except sqlite3.Error as exc:
        LOG.error(type(exc).__name__)
        print("Database operation failed. Check disk space, permissions and backups; records were not reset.",
              file=sys.stderr)
        raise SystemExit(1) from None
    except errors.RPCError as exc:
        LOG.error(type(exc).__name__)
        print(telegram_error_message(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        report_programming_error(LOG, exc)
        print("A programming error stopped this operation. Set TGM_DEV_MODE=1 for sanitized file/line "
              "diagnostics. Check history before attempting another delivery.",
              file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Cancelled; inspect delivery history before attempting another send.", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
