"""Interactive startup using the existing database and Telethon session paths."""
import asyncio
import logging
import os
import sqlite3
import sys
import time

from telethon import TelegramClient, errors

from .cli import JsonFormatter
from .configuration import bind_account, data_directory, load_configuration
from .dashboard import Dashboard
from .security import application_lock, private_directory
from .setup_wizard import authenticate, credential_wizard, yes
from .storage import Store
from .telegram import TelegramService

LOG = logging.getLogger("telegram_manager.application")


async def startup() -> None:
    if not sys.stdin.isatty():
        raise ValueError("The dashboard requires an interactive terminal.")
    os.umask(0o077)
    root = private_directory(data_directory())
    with application_lock(root):
        config = load_configuration(root)
        if not (root / "config.json").exists():
            print("\nWelcome to Telegram Group Manager setup.\n"
                  "Existing sessions and database records will be preserved.\n"
                  "Python and runtime dependencies have been checked.")
        print("Existing Telegram session found." if (root / "account.session").exists()
              else "No saved Telegram session found; authentication will be requested.")
        if config["account_id"] is not None and not (root / "manager.sqlite3").is_file():
            raise ValueError("The bound installation's database is missing. Restore its backup before "
                             "continuing; an empty delivery ledger was not created.")
        credentials, source = credential_wizard(root)
        store = Store(root / "manager.sqlite3")
        client = None
        me = None
        try:
            if store.cooldown(0) > time.time():
                raise ValueError("Authentication cooldown is active; wait before relaunching.")
            client = TelegramClient(str(root / "account"), credentials.api_id, credentials.api_hash,
                                    flood_sleep_threshold=0, request_retries=0,
                                    connection_retries=0, auto_reconnect=False,
                                    raise_last_call_error=True)
            await client.connect()
            me = await authenticate(client)
            if config["account_id"] is None:
                print(f"Telegram verified account ID: {me.id}")
                if not yes("Bind this installation to this account?"):
                    print("Setup cancelled. Existing data was preserved.")
                    return
            bind_account(root, config, me.id)
            print("Session authorized. Database validated; cached metadata and delivery records preserved.")
            await Dashboard(TelegramService(client, store, me), root, source).run()
        except (errors.FloodWaitError, errors.SlowModeWaitError) as exc:
            if me is not None:
                store.set_cooldown(me.id, time.time() + exc.seconds)
            else:
                store.set_cooldown(config["account_id"] or 0, time.time() + exc.seconds)
            print(f"Telegram requires waiting {exc.seconds} seconds. No retry attempted.")
        finally:
            try:
                if client is not None:
                    await client.disconnect()
            finally:
                store.close()


def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    try:
        asyncio.run(startup())
    except (KeyboardInterrupt, EOFError):
        print("Interrupted. Data and sessions preserved; check history before another delivery attempt.")
        raise SystemExit(130) from None
    except ValueError as exc:
        LOG.error(type(exc).__name__)
        print(f"Setup/operation stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except sqlite3.Error as exc:
        LOG.error(type(exc).__name__)
        print("Database initialization or operation failed. Check permissions, disk space and backups; "
              "the database was not reset.", file=sys.stderr)
        raise SystemExit(1) from None
    except errors.RPCError as exc:
        LOG.error(type(exc).__name__)
        print(f"Telegram operation failed ({type(exc).__name__}). Check credentials or account authorization "
              "and relaunch. No delivery retry or session deletion was attempted.", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        LOG.error(type(exc).__name__)
        print(f"Startup/operation failed ({type(exc).__name__}). Check network, file permissions and "
              "Keychain access, then relaunch. No application data was reset.", file=sys.stderr)
        raise SystemExit(1) from None
