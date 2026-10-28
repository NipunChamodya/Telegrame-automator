import getpass
import json
import platform
import sys
import warnings
from pathlib import Path

from telethon import errors

from .configuration import Credentials, keychain_service, resolve_credentials
from .guidance import api_tutorial, yes
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


def credential_wizard(root: Path) -> tuple[Credentials, str]:
    keychain_available = True
    try:
        credentials, source = resolve_credentials(root)
        if credentials:
            return credentials, source
    except (KeychainError, OSError):
        keychain_available = False
        print("Keychain is unavailable or access was declined. No saved credentials were changed.")
        if not yes("Use credentials only in memory for this launch?"):
            raise ValueError("Unlock Keychain or supply environment credentials, then relaunch.") from None
    api_tutorial(offer_browser=True)
    while True:
        try:
            api_id = Credentials.validate_id(input("Enter Telegram API ID: ").strip())
            break
        except ValueError as exc:
            print(str(exc))
    while True:
        value = hidden("Enter Telegram API Hash (hidden): ").strip()
        try:
            api_hash = Credentials.validate_hash(value)
            break
        except ValueError as exc:
            print(str(exc))
    credentials = Credentials(api_id, api_hash)
    if keychain_available and platform.system() == "Darwin" and yes("Save API credentials in macOS Keychain for future launches?"):
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
        print("\nTelegram account authentication — your existing session file will be reused.\n"
              "1. Enter your phone number with its country code (for example + followed by digits).\n"
              "2. Telegram will choose where to send the login code. Check the verified\n"
              "   Telegram service chat in a signed-in Telegram app first. SMS or another\n"
              "   delivery method may be offered by Telegram, but is not guaranteed.\n"
              "   The developer portal login code is separate from this app's login code.\n"
              "3. If enabled, enter your Telegram two-step verification password.\n"
              "Phone number, code and password prompts are hidden. Nothing will be posted.")
        phone = hidden("Phone number with country code (hidden): ").strip()
        if not phone.startswith("+") or not phone[1:].isdigit():
            raise ValueError("Enter a phone number with a country code; bot tokens are not supported.")
        sent = await client.send_code_request(phone)
        try:
            await client.sign_in(phone=phone, code=hidden("Telegram verification code (hidden): "),
                                 phone_code_hash=sent.phone_code_hash)
        except errors.SessionPasswordNeededError:
            print("Two-step verification is enabled. Enter your Telegram account password,\n"
                  "not your API Hash, macOS password, or login code.")
            await client.sign_in(password=hidden("Telegram 2FA password (hidden): "))
    me = await client.get_me()
    if me is None or getattr(me, "bot", False) or getattr(me, "deleted", False):
        raise ValueError("An active personal Telegram account is required.")
    return me
