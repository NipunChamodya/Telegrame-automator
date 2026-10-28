"""Beginner-friendly terminal guidance; no network access without browser consent."""
import webbrowser
from .terminal import print, input

PORTAL = "https://my.telegram.org"


def yes(prompt: str, *, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter Y for yes or N for no. Press Ctrl+C to cancel.")


def welcome() -> None:
    print("\n========================================\n"
          "       TELEGRAM GROUP MANAGER\n"
          "========================================\n\nWelcome!\n\n"
          "This application helps you discover and manage\n"
          "Telegram groups using your personal account.\n\n"
          "Before continuing, you need:\n\n"
          "1. Telegram API ID\n2. Telegram API Hash\n3. Your Telegram phone number\n\n"
          "The next steps explain where to find these.\n"
          "Press Ctrl+C at any time to cancel setup safely.")
    input("Press ENTER to begin setup. ")


def api_tutorial(*, offer_browser: bool = False) -> None:
    print("\nTELEGRAM API CREDENTIALS — STEP-BY-STEP\n\n"
          "STEP 1: Open the official Telegram developer portal:\n"
          f"  {PORTAL}\n\n"
          "STEP 2: Sign in there using your Telegram phone number.\n"
          "  Follow the portal's instructions to enter its login code.\n\n"
          'STEP 3: Open "API development tools".\n\n'
          "STEP 4: If required, register your own API application.\n"
          "  Suggested values for the form:\n"
          "  App title: Telegram Group Manager\n"
          "    A readable name for your application.\n"
          "  Short name: telegramgroupmanager\n"
          "    A short identifier; choose another valid name if unavailable.\n"
          "  Platform: Desktop, if offered.\n"
          "  Description: Personal Telegram group management application.\n"
          "  Complete any other fields required by Telegram.\n\n"
          "STEP 5: Find your API ID and API Hash on the application page.\n"
          "  API ID: A numeric identifier for your Telegram API application.\n"
          "  API Hash: A secret credential associated with that application.\n"
          "  These are different from a bot token or a Telegram login code.\n"
          "  Keep your API Hash private. Enter it only at the hidden prompt.\n"
          "  If you already registered an application, reuse its credentials.\n")
    if offer_browser and yes("Would you like to open the official Telegram developer portal in your browser?",
                             default=True):
        try:
            opened = webbrowser.open(PORTAL, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            print(f"The browser could not be opened. Open {PORTAL} manually to continue.")


def setup_completed() -> None:
    print("\n========================================\n"
          "       SETUP COMPLETED\n"
          "========================================\n\n"
          "Telegram connected successfully!\n\n"
          "Application database: Ready\nTelegram session: Authorized\nAccount: Connected")


def show_help() -> None:
    print("\nHELP — TELEGRAM GROUP MANAGER")
    api_tutorial()
    print("TELEGRAM AUTHENTICATION AND RECONNECTING\n"
          "  Enter your phone number with its country code: for Sri Lanka use\n"
          "  +947XXXXXXXX (replace X with digits; omit the domestic leading 0).\n"
          "  Spaces, hyphens and parentheses are accepted; invalid input can be\n"
          "  corrected at the prompt. Telegram chooses how\n"
          "  to deliver the login code; check the verified Telegram service chat\n"
          "  in an already signed-in Telegram app first. SMS or another method\n"
          "  may be offered by Telegram, but is not guaranteed.\n"
          "  If enabled, enter your Telegram two-step verification password.\n"
          "  Codes, API Hash and passwords use hidden prompts and are not logged.\n"
          "  Later launches reuse the session. To reconnect, exit and run\n"
          "  python3 main.py again. Expired authorization requests a new login;\n"
          "  do not delete your session or database to fix a connection problem.\n\n"
          "GROUP DISCOVERY AND POSTING PERMISSIONS\n"
          "  Option 1 performs a lightweight dialog scan without per-group lookups.\n"
          "  Option 12 inspects pending/expired metadata sequentially, skipping fresh\n"
          "  cache entries. Option 3 searches paginated lists; n/p change pages, f\n"
          "  filters status, and s sorts. Option 4 freshly inspects one explicit group.\n"
          "  Metadata has separate freshness periods; stale permissions show Unknown.\n"
          "  Allowed means Telegram reports text posting permission. Denied may\n"
          "  mean an admin muted you, membership ended, or the account is restricted.\n"
          "  Unknown means the app cannot verify permission and will block sending.\n"
          "  Unsupported forum topics are blocked. Human rules and moderation bot\n"
          "  policies may be unknown even when Telegram allows posting. Technical\n"
          "  permission to post is not permission to advertise or send unsolicited content.\n\n"
          "MESSAGES AND TELEGRAM RATE LIMITS\n"
          "  Compose with option 5, select one group with option 6, then use option 7\n"
          "  to preview and confirm the exact message and destination. Nothing sends\n"
          "  automatically. Identical message attempts to the same group are blocked.\n"
          "  FLOOD_WAIT means Telegram requires a pause; slow mode limits how often\n"
          "  you may post in a group. Wait for the stated duration and follow group\n"
          "  rules. Cooldowns survive restarts. There is no bypass or automatic retry.\n"
          "  After an interrupted or uncertain send, inspect history (8) and Telegram\n"
          "  manually. Never delete the ledger to resend.\n\n"
          "PROTECT YOUR SESSION\n"
          "  account.session can authorize access to your Telegram account. Never\n"
          "  share it, put it in Git, or store it in a shared/cloud-synced folder.\n"
          "  Keep API credentials in macOS Keychain or environment variables, not\n"
          "  plaintext configuration. Keychain entries are never silently replaced.\n"
          "  Use a locked macOS account and FileVault. Settings (10) shows the private\n"
          "  data location. Keep secure backups of the session AND database. Revoke\n"
          "  a compromised session using Telegram Settings > Devices.\n")
