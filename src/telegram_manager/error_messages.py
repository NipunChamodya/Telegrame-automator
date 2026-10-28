"""Safe explanations for Telegram failures; never interpolate request or error text."""
from telethon import errors


def telegram_error_message(exc: errors.RPCError) -> str:
    if isinstance(exc, (errors.PhoneMigrateError, errors.NetworkMigrateError, errors.UserMigrateError)):
        return ("Telegram requested another data center, but authentication could not finish within "
                "the bounded migration attempts. The session was preserved. Check your connection "
                "and relaunch; do not delete the session or change its database manually.")
    if isinstance(exc, errors.SessionPasswordNeededError):
        return ("Telegram requires your two-step verification password to finish signing in. "
                "Use your Telegram account password, not your API Hash or login code.")
    if isinstance(exc, errors.ApiIdInvalidError):
        return ("Telegram did not accept the API ID/API Hash pair. Check both on my.telegram.org "
                "under API development tools. Correct the environment variables or review the saved "
                "item in macOS Keychain Access, then relaunch.")
    if isinstance(exc, errors.PhoneNumberInvalidError):
        return ("Telegram did not accept the phone number. Enter it again with + and its country code. "
                "For Sri Lanka: +947XXXXXXXX, replacing X with digits and omitting the domestic leading 0. "
                "Your input was not displayed or logged.")
    if isinstance(exc, errors.PhoneNumberBannedError):
        return "Telegram reports this phone number is banned. Review the account with Telegram; the app cannot bypass a ban."
    if isinstance(exc, (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError)):
        return ("The verification code was not accepted. Use the newest Telegram login code, "
                "not your API ID or a portal login code. Relaunch when ready; no code was retried automatically.")
    if isinstance(exc, errors.PhoneCodeExpiredError):
        return ("The verification code expired. Relaunch to explicitly request a fresh login code. "
                "Do not reuse the expired code; no new code was requested automatically.")
    if isinstance(exc, errors.PasswordHashInvalidError):
        return ("The two-step verification password was not accepted. This is your Telegram account password, "
                "not your API Hash or login code. Check it in Telegram and relaunch; no password retry was attempted.")
    if isinstance(exc, errors.AuthKeyDuplicatedError):
        return ("Telegram rejected a session used in conflicting locations. Stop other copies and review "
                "Telegram Settings > Devices. No session file was deleted; do not bypass the restriction.")
    if isinstance(exc, errors.UnauthorizedError):
        return ("Telegram authorization expired or was revoked. Exit and run python3 main.py to sign in again. "
                "The existing session path and database will be preserved.")
    if isinstance(exc, (errors.FloodWaitError, errors.SlowModeWaitError)):
        return f"Telegram requires a wait of {exc.seconds} seconds. Wait before continuing; no retry was attempted."
    if isinstance(exc, errors.PeerFloodError):
        return "Telegram has restricted this account's activity. Stop posting and review the account in Telegram; do not retry to evade limits."
    return ("Telegram could not complete this operation. Check account access and group restrictions, "
            "then review delivery history before another attempt. No automatic retry was attempted.")
