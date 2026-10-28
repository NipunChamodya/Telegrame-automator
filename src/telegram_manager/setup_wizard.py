import getpass
import json
import platform
import sys
import warnings

from telethon import errors

from .configuration import Credentials, keychain_service, resolve_credentials
from .security import KeychainError, MacKeychain


def hidden(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise ValueError("Secure input requires an interactive terminal.")
    # getpass may otherwise fall back to echoed input if /dev/tty is unavailable.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise ValueError("Hidden input is unavailable; use a normal terminal.") from None


def yes(prompt: str) -> bool:
    return input(prompt + " [y/N]: ").strip().lower() == "y"


def credential_wizard(root) -> tuple[Credentials, str]:
    try:
        credentials, source = resolve_credentials(root)
        if credentials:
            return credentials, source
    except (KeychainError, OSError):
        print("Keychain is unavailable or access was declined. No saved credentials were changed.")
        if not yes("Use credentials only in memory for this launch?"):
            raise ValueError("Unlock Keychain or supply environment credentials, then relaunch.") from None
    print("\nTelegram API setup — create your own application at https://my.telegram.org")
    credentials = Credentials.parse(hidden("API ID (hidden): ").strip(), hidden("API hash (hidden): ").strip())
    if platform.system() == "Darwin" and yes("Save API credentials in macOS Keychain for future launches?"):
        try:
            MacKeychain(keychain_service(root)).save_new(json.dumps({
                "api_id": credentials.api_id, "api_hash": credentials.api_hash}))
            return credentials, "macOS Keychain"
        except (KeychainError, OSError):
            print("Keychain storage failed; existing items were preserved.")
            if not yes("Continue with credentials in memory for this launch only?"):
                raise ValueError("Credential setup cancelled.") from None
    print("Credentials will be used in memory only; they will be requested again next launch.")
    return credentials, "memory only"


async def authenticate(client):
    """Restore the original session, or explicitly authenticate without start() output."""
    if not await client.is_user_authorized():
        print("Telegram authentication required. Existing session files will be reused.")
        phone = hidden("Phone number with country code (hidden): ").strip()
        if not phone.startswith("+") or not phone[1:].isdigit():
            raise ValueError("Enter a phone number with a country code; bot tokens are not supported.")
        sent = await client.send_code_request(phone)
        try:
            await client.sign_in(phone=phone, code=hidden("Telegram verification code (hidden): "),
                                 phone_code_hash=sent.phone_code_hash)
        except errors.SessionPasswordNeededError:
            await client.sign_in(password=hidden("Telegram 2FA password (hidden): "))
    me = await client.get_me()
    if me is None or getattr(me, "bot", False) or getattr(me, "deleted", False):
        raise ValueError("An active personal Telegram account is required.")
    return me
