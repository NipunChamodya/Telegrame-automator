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
from .error_messages import telegram_error_message
from .guidance import setup_completed, welcome
from .security import application_lock, private_directory
from .setup_wizard import (
    AUTH_CONNECTION_RETRIES, AUTH_REQUEST_RETRIES, authenticate, credential_wizard, yes,
)
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
        first_run = config["account_id"] is None
        if first_run:
            welcome()
        print("Existing Telegram session found." if (root / "account.session").exists()
              else "No saved Telegram session found; authentication will be requested.")
        if config["account_id"] is not None and not (root / "manager.sqlite3").is_file():
            raise ValueError("The bound installation's database is missing. Restore its backup before "
                             "continuing; an empty delivery ledger was not created.")
        store = Store(root / "manager.sqlite3")
        client = None
        me = None
        try:
            if store.cooldown(0) > time.time():
                raise ValueError("Authentication cooldown is active; wait before relaunching.")
            credentials, source = credential_wizard(root)
            client = TelegramClient(str(root / "account"), credentials.api_id, credentials.api_hash,
                                    flood_sleep_threshold=0, request_retries=AUTH_REQUEST_RETRIES,
                                    connection_retries=AUTH_CONNECTION_RETRIES, auto_reconnect=False,
                                    receive_updates=False,
                                    raise_last_call_error=True)
            await client.connect()
            me = await authenticate(client)
            if config["account_id"] is None:
                print(f"Telegram verified account ID: {me.id}")
                if not yes("Bind this installation to this account?"):
                    print("Setup cancelled. Existing data was preserved.")
                    return
            bind_account(root, config, me.id)
            # Retry budgets are constructor options. Reopen the SAME saved session
            # sequentially with zero request retries before any group or send work.
            # No private Telethon attributes or session database edits are needed.
            await client.disconnect()
            client = None
            client = TelegramClient(str(root / "account"), credentials.api_id, credentials.api_hash,
                                    flood_sleep_threshold=0, request_retries=0,
                                    connection_retries=0, auto_reconnect=False,
                                    raise_last_call_error=True)
            await client.connect()
            restored = await authenticate(client, allow_login=False)
            if restored.id != me.id:
                raise ValueError("Account identity changed while restoring the authenticated session. "
                                 "No dashboard or message operation was started.")
            me = restored
            if first_run:
                setup_completed()
            else:
                print("Session authorized. Database ready; cached groups and delivery history preserved.")
            await Dashboard(TelegramService(client, store, me), root, source).run(first_run=first_run)
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
    auth_log = logging.getLogger("telegram_manager.authentication")
    auth_log.handlers.clear()
    auth_log.addHandler(handler)
    auth_log.setLevel(logging.INFO)
    auth_log.propagate = False
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
        print(telegram_error_message(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        LOG.error("PermissionError")
        print("The app cannot access its private files. Check ownership and permissions of TGM_DATA_DIR "
              "or the default application directory. No files were reset.", file=sys.stderr)
        raise SystemExit(1) from None
    except (ConnectionError, TimeoutError):
        LOG.error("ConnectionFailure")
        print("Connection to Telegram was lost or timed out. Check your internet connection, then relaunch "
              "with python3 main.py. Check delivery history before another send; no retry was attempted.",
              file=sys.stderr)
        raise SystemExit(1) from None
    except OSError:
        LOG.error("OSError")
        print("The app could not access a file or connect to Telegram. Check your internet connection, "
              "disk space and private directory access, then relaunch. Existing data was not reset.", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        LOG.error(type(exc).__name__)
        print(f"Startup/operation failed ({type(exc).__name__}). Check network, file permissions and "
              "Keychain access, then relaunch. No application data was reset.", file=sys.stderr)
        raise SystemExit(1) from None
