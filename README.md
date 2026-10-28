# Telegram Group Messaging Manager

A Python 3.13+ terminal application for macOS. It restores a personal Telegram session, discovers joined groups, stores permission metadata in SQLite, and sends plain text to one explicitly selected destination after approval. It never automatically sends to joined groups.

## Start

From the project directory:

```sh
python3 main.py
```

The launcher detects the operating system and Python version, checks the constrained runtime dependencies declared in `pyproject.toml`, and opens the terminal dashboard. Python 3.13 or newer is required. macOS is the primary target; Linux can use environment credentials or credentials held only in memory. Windows is not supported.

If dependencies are missing, the launcher looks for the project's `.venv`. If it is ready, it restarts using that interpreter. Otherwise it explains the setup and requests approval **before** creating a virtual environment or installing packages. Installation uses the virtual environment's Python and only the project's declared runtime dependencies. It never installs packages into system Python. Declining or interrupting setup leaves existing application data alone. Package installation requires network access and a working pip index. Development tools are not installed by the startup wizard.

## First-run setup

1. Launch `python3 main.py` in Terminal. Approve virtual environment setup if needed. Existing compatible dependencies are reused.
2. Read the welcome screen and press Enter. Press Ctrl+C at any point to cancel safely.
3. If API credentials are missing, follow the five-step tutorial printed in the terminal:
   - Open the official portal, [my.telegram.org](https://my.telegram.org), and sign in with your phone number.
   - Open **API development tools**. If necessary, register an application using these suggested values: App title **Telegram Group Manager**, Short name **telegramgroupmanager**, Platform **Desktop** if offered, Description **Personal Telegram group management application**. Complete other required portal fields; choose another short name if unavailable.
   - Find the **API ID** (your application's numeric identifier) and **API Hash** (its secret credential).
4. The wizard asks whether to open the portal in your browser, `[Y/n]`. It opens only after you approve; Enter accepts the displayed default. Choosing No lets you open the URL yourself. Browser failure shows the URL without retrying automatically. No portal browser window opens on a normal restored launch or when viewing Help.
5. Enter the API ID, then the API Hash at its hidden prompt. Invalid formats give a specific explanation and re-prompt that field without echoing the hash. These credentials are different from a bot token or a login code.
6. On macOS, approve saving credentials to Keychain if desired. macOS may request Keychain access. The application uses native Security framework calls, not secrets in subprocess arguments. Existing entries are never silently overwritten.
7. Enter your phone number with country code at the hidden prompt. Telegram chooses the code delivery method: check the verified **Telegram** service chat in an already signed-in app first. SMS or another method may be offered, but is not guaranteed. The portal login code is separate from the code for this application. Enter the newest application login code, then your Telegram two-step verification password if enabled. Phone number, code and password prompts hide input.
8. Review the verified Telegram account ID and approve binding this installation to it. The application validates/reuses your database before requesting credentials; it never resets existing records.
9. After successful authentication, a **SETUP COMPLETED** screen shows database ready, session authorized and account connected. Answer **Would you like to discover your joined groups? [Y/n]**. Yes runs the existing discovery operation with progress; No opens the dashboard immediately. A saved Telegram cooldown pauses discovery until the wait expires. Nothing is sent.

The walkthrough follows [Telegram's official credential instructions](https://core.telegram.org/api/obtaining_api_id) and [authorization documentation](https://core.telegram.org/api/auth). Field choices are suggestions; Telegram controls the actual portal form and code delivery methods.

API credentials can instead come from `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. Environment credentials take precedence over Keychain. Set both variables; partial or invalid environment credentials stop setup rather than silently falling back. `.env.example` documents the variables; `.env` is not loaded automatically. Do not put secrets in shell history or source control.

If Keychain access is unsupported, denied, or fails, the wizard offers credentials held only in memory for this launch. It never falls back to storing secrets in plaintext. Existing Keychain items are not overwritten. If you decline saving credentials, or use memory-only mode, supply them again next launch. Login codes, phone numbers and 2FA passwords are not saved in configuration.

## Subsequent launches

Run the same command:

```sh
python3 main.py
```

The application checks the environment, obtains API credentials from the environment or Keychain, opens the original `account.session`, verifies authorization and account identity, validates the database, and loads cached groups. An authorized session does not request another login code. Expired authorization requests login using the same session path. An unexpected account ID blocks the dashboard; it does not silently rebind the installation.

The dashboard displays cached groups immediately. If any snapshot is older than 24 hours, or the cache is empty, it offers a refresh. Discovery is optional and reports progress as groups are inspected. Rate limits stop discovery and persist a cooldown; partial discovery progress remains saved. Snapshots of groups you have left may remain visible, but every send rechecks membership and permissions.

## Dashboard

```text
1. Discover / Refresh Groups
2. View All Groups
3. Search Groups
4. Inspect Group Permissions
5. Compose Message
6. Review Approved Destinations
7. Send to Selected Group
8. View Delivery History
9. View Account Status
10. Settings
11. Help
0. Exit
```

Options 2–4 show/search group metadata: names, marked IDs, type, username, membership count where available, permission verdicts and reasons, slow mode, visible bot IDs, unknown rules and UTC inspection time. Text from Telegram and message files is escaped as JSON to prevent terminal control sequences. Settings shows the configuration location, credential source and safety behavior; it does not display credentials or change them automatically. **11. Help** explains credential setup, login and reconnecting, discovery, allowed/denied/unknown permissions, group restrictions, Telegram rate limits and session-file protection. It is available without making Telegram requests or opening a browser.

Discovery includes joined basic groups and supergroups, including archived dialogs. It excludes broadcast channels and migrated basic groups. Unsupported forum topic contexts can be shown in discovery but are blocked for sending.

- `allowed`: available Telegram membership and text posting permissions permit sending.
- `denied`: a reported restriction prevents sending.
- `unknown`: permission or destination context cannot be verified; sending is blocked.

Account `restricted` flags conservatively block sending. Telegram does not expose every human group rule, bot policy or account-wide spam restriction. Visible bot IDs come from full-chat metadata; their presence does not prove a moderation role or reveal their policies. Missing slow-mode metadata is reported as unknown. Telegram remains authoritative and may reject any request.

## Compose and send safely

Use option **5** to compose plain text or load a UTF-8 file. For interactive input, enter a single `.` on its own line to finish. The preview shows the complete draft. Empty messages and messages over 4096 UTF-16 units are rejected; messages are not automatically split.

Use option **6** to enter a discovered group's exact ID, inspect its fresh permissions, and explicitly select it. “Approved destinations” means one destination selected in memory; it does **not** authorize a send. Replacing the draft clears the destination selection. Drafts and selections are not saved across launches.

Use option **7** to verify account authorization, recheck permissions, and display the exact destination, account ID and complete message. Type the displayed `SEND <destination-id>` phrase to approve. Any other response cancels. The service checks authorization, account identity, permissions and slow mode again immediately before delivery. Selection is cleared before submission so it cannot act as standing approval.

Messages are plain text without Markdown/HTML parsing or link previews. No bulk sending, background scheduler, unattended approval flag, attachments, forwarding, paid messages or forum topic sending is implemented. Review group rules in Telegram before posting.

## Existing CLI compatibility

The original package name and command-line entry point remain available after installation. The original commands use the existing environment credential interface:

```sh
source .venv/bin/activate
# Set TELEGRAM_API_ID and TELEGRAM_API_HASH securely in your environment first.
tgm login
tgm discover
tgm groups --search engineering
tgm inspect -- -1001234567890
tgm send -- -1001234567890
tgm send --file message.txt -- -1001234567890
tgm history
```

Use `--` before negative IDs. The interactive launcher and original CLI share the same application directory, database, ledger, cooldowns and Telethon session. Run one instance at a time. The old CLI can still operate without the launcher's non-secret configuration; it retains its explicit confirmation behavior.

## Local storage and security

The default directory is unchanged:

```text
~/Library/Application Support/TelegramGroupManager/
    account.session      # Telegram authorization credential; keep secret
    manager.sqlite3      # Account-isolated group snapshots, delivery ledger, cooldowns
    manager.lock         # Prevents simultaneous manager instances
    config.json          # Version and bound account ID only; no API secrets
```

`TGM_DATA_DIR` selects a dedicated local directory you own. The application applies directory mode 0700, file mode 0600 and umask 077. It rejects symlinks directly within the directory and rejects files owned by another user or hard linked elsewhere. Do not use a shared or cloud-synced folder. Keychain credentials are scoped to the resolved data directory, so changing it selects a different Keychain item and session.

Keychain contains one generic-password item named `org.telegram-group-manager.credentials.<directory-hash>`, with your macOS user ID as its account field. Native calls are tested with mocked framework functions; actual Keychain access still needs a controlled macOS smoke test.

SQLite is checked for integrity, expected tables/columns and its delivery deduplication index before normal initialization. Existing tables are not dropped, records are not deleted, and incompatible or corrupt databases are rejected instead of reset. If a bound installation loses its database file, startup requires backup recovery rather than creating an empty delivery ledger. The original schema is retained. Initialization is idempotent; it is not a general future schema migration system.

Logging emits sanitized JSON error events with error class names, excluding API hashes, session contents, verification codes, passwords and message bodies. The explicit preview displays your composed message, so avoid screen sharing sensitive content. There is no remote telemetry. FileVault and a locked macOS account protect the session and unencrypted local metadata at rest; filesystem modes alone do not encrypt them. Python cannot guarantee zeroing secrets in process memory.

## Delivery history and duplicate prevention

Option 8 / `tgm history` shows the latest 100 delivery records for the connected account. The ledger stores account, destination, SHA-256 of the exact message, Telegram random ID, timestamps, status and a sanitized result, not the message body.

A unique `(account, destination, message hash)` reservation is committed **before** submission. Exact duplicate text to the same destination is blocked across restarts for every status, including failed attempts. There is no retry/override button. Telegram random IDs provide an additional server deduplication mechanism. A process lock prevents concurrent instances using the same directory.

Statuses: `pending`, `sent`, `blocked`, `rejected`, `uncertain`. `sent` means Telegram acknowledged the request, not that every member read it. A network failure, interruption, server failure or database error after submission can leave `uncertain` or `pending` even if Telegram accepted the message. Inspect Telegram manually before considering another operation. Never delete the ledger or alter text to defeat duplicate protection.

FLOOD_WAIT and slow-mode errors persist the returned wait duration as a conservative account-wide cooldown. Peer spam flood errors block further sending locally for at least 24 hours; that minimum is not evidence Telegram has lifted a restriction. Authentication waits before identity is known use a reserved account-zero cooldown in the same database. No automatic sleeps, uncertain delivery retries, alternate-account tactics or restriction bypasses are implemented.

## Recovery

- **Missing dependencies / failed installation:** check pip output, network/index access, disk space and project permissions. Rerun `python3 main.py` and approve setup when ready. A malformed or old `.venv` is left untouched. Repair/recreate only the project virtual environment with Python 3.13+; never remove the private data directory to fix packages.
- **Interrupted setup:** relaunch. Completed Keychain entries and existing sessions remain available. Incomplete configuration writes are not published; startup releases its process lock when the process exits.
- **Keychain denied or locked:** unlock your login Keychain and relaunch, or explicitly choose credentials in memory. Use macOS Keychain Access to review a saved item. To rotate credentials, explicitly manage that item or use environment overrides. The app never replaces existing secrets automatically.
- **Invalid API ID or Hash format:** follow the field-specific explanation and re-enter that field. The hash stays hidden and is not echoed in validation errors. If Telegram rejects a correctly formatted credential pair, review API development tools, then correct environment values or explicitly manage the saved item using macOS Keychain Access and relaunch.
- **Invalid verification code:** use the newest code for this application, not the developer portal login code or API ID. Relaunch when ready; the app does not retry codes automatically.
- **Expired verification code:** relaunch to explicitly request a new code. Do not reuse the old code.
- **Two-step verification failure:** use the Telegram account password, not the API Hash or macOS password. Check your account in Telegram and relaunch. Password attempts are not automatically retried. The app does not create Telegram accounts.
- **Expired authorization:** relaunch and complete the hidden login prompts. The original session path is reused; session files are not automatically deleted/reset.
- **Unexpected account identity:** restore the matching session from a secure backup or use a separate `TGM_DATA_DIR` for another account. Do not edit the binding just to bypass the mismatch check.
- **Network disconnect:** cached views remain available when an operation returns to the menu. Reconnect/relaunch when ready; uncertain deliveries are never retried automatically.
- **FLOOD_WAIT / slow mode:** wait at least the reported duration. Do not remove cooldowns. For unknown account-wide restrictions, review account status in Telegram; do not probe Telegram limits intentionally.
- **SQLite or permission failure:** stop the app, check free disk space and ownership of the dedicated directory, and restore a known-good backup if necessary. No automatic database repair/reset is performed. Keep the ledger and session together.
- **Compromised session:** revoke it using Telegram Settings → Devices and secure your macOS account. Never share `account.session`, database copies or Keychain exports.

Back up the entire private directory securely with the application stopped. Never publish these backups. Losing the ledger loses its duplicate history. A different data directory has independent local locking and deduplication; do not run multiple copies against one Telegram account to evade limits.

## Architecture

This extends the original `telegram_manager` package rather than replacing it:

- `main.py`, `bootstrap.py`: standard-library environment checks, consented virtual environment setup and interpreter restart.
- `security.py`, `configuration.py`: private storage/lock, native Keychain and non-secret account binding.
- `setup_wizard.py`, `application.py`: credentials, session restoration, first-run authentication and startup cleanup.
- `guidance.py`, `error_messages.py`: terminal tutorial, consented browser opening, Help and safe error explanations.
- `dashboard.py`: terminal menu, cached views, refresh, drafts, single selection and explicit send approval.
- `telegram.py`, `storage.py`, `models.py`: original async Telegram service, SQLite ledger and group models, with startup validation and fresh authorization checks added.
- `cli.py`: existing `tgm` command interface.

## Tests and validation

Install development dependencies only into the project environment:

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py src tests
.venv/bin/python -m ruff check main.py src tests
```

Tests mock all Telegram network operations and Keychain framework calls. They must never send real messages. The suites cover dependency setup and cancellation, first-run/existing configuration, account mismatch, interrupted initialization, permission errors, database creation and preservation, atomic duplicate protection, session restoration and 2FA, dashboard views, explicit approval, permission changes, and rate limits.

Validation in the current environment (Python 3.13.4, Telethon 1.45.0): **70 tests passed**, including mocked Telegram integration tests, with no skipped modules. Syntax compilation passed. The real `python3 main.py` command was launched in a terminal with an isolated temporary data directory: it reused `.venv` without installation and displayed the welcome prompt. Setup was then cancelled before reading credentials or contacting Telegram. The entry-point integration test exercises the complete first-run tutorial/authentication/Help/dashboard flow and a second restored launch using mocked Telegram and Keychain operations; it checks session-path compatibility, metadata, delivery records and cooldown preservation.

Ruff could not be installed from the environment's available package index, so its check remains unverified. Live Telegram authorization, actual Keychain reads/writes, and browser launching remain unverified; browser and Keychain interactions are mocked in tests. No real Telegram messages were sent. Before production use, run Ruff and perform a controlled login/Keychain restoration smoke test. A live send still requires separate explicit approval in the application. The application remains CLI-only, with no GUI dependencies.

## API references

- [Telethon client/authentication API](https://docs.telethon.dev/en/stable/modules/client.html)
- [Telethon session sign-in behavior](https://docs.telethon.dev/en/stable/basic/signing-in.html)
- [Telegram rights model](https://core.telegram.org/api/rights)
- [Telegram text restriction flags](https://core.telegram.org/constructor/chatBannedRights)
- [Telegram sendMessage and random IDs](https://core.telegram.org/method/messages.sendMessage)
