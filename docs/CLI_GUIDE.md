# CLI maintenance guide

The original numbered-menu CLI remains supported. Desktop workflows are documented in [USER_GUIDE.md](USER_GUIDE.md). Current verification results are in [VALIDATION.md](VALIDATION.md).

## Start the CLI

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
7. Enter your phone number with country code at the hidden prompt. For Sri Lanka use `+947XXXXXXXX`, replacing each X with a digit and omitting the domestic leading `0`. Spaces, hyphens and parentheses are accepted, such as `+94 (7X) XXX-XXXX`. Invalid input is explained and can be corrected without restarting; your entered number is never echoed or logged. Telegram chooses the code delivery method: check the verified **Telegram** service chat in an already signed-in app first. SMS or another method may be offered, but is not guaranteed. The portal login code is separate from the code for this application. Enter the newest application login code, then your Telegram two-step verification password if enabled. Phone number, code and password prompts hide input.
8. Review the verified Telegram account ID and approve binding this installation to it. The application validates/reuses your database before requesting credentials; it never resets existing records.
9. After successful authentication, a **SETUP COMPLETED** screen shows database ready, session authorized and account connected. Answer **Would you like to discover your joined groups? [Y/n]**. Yes runs the existing discovery operation with progress; No opens the dashboard immediately. A saved Telegram cooldown pauses discovery until the wait expires. Nothing is sent.

The walkthrough follows [Telegram's official credential instructions](https://core.telegram.org/api/obtaining_api_id) and [authorization documentation](https://core.telegram.org/api/auth). Field choices are suggestions; Telegram controls the actual portal form and code delivery methods.

API credentials can instead come from `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. Environment credentials take precedence over Keychain. Set both variables; partial or invalid environment credentials stop setup rather than silently falling back. `.env.example` documents the variables; `.env` is not loaded automatically. Do not put secrets in shell history or source control.

If Keychain access is unsupported, denied, or fails, the wizard offers credentials held only in memory for this launch. It never falls back to storing secrets in plaintext. Existing Keychain items are not overwritten. If you decline saving credentials, or use memory-only mode, supply them again next launch. Login codes, phone numbers and 2FA passwords are not saved in configuration.

## Authentication migration fix

The previous authentication failure was caused by configuring the login client with `request_retries=0`. In Telethon 1.45, `send_code_request()` issues `auth.SendCodeRequest`; Telethon's request loop catches `PhoneMigrateError`, looks up the DC supplied by Telegram, updates/saves its session and reconnects. With no retry iteration left, it then re-raises the migration exception instead of resubmitting the authentication request. App-level error handling displayed that exception; it did not itself prevent the initial switch. The prior phone check separately raised `ValueError` immediately for empty or formatted input.

Startup now uses Telethon's documented constructor options with three request retries and two connection retries **only during authentication**, with flood sleeping disabled and no automatic background reconnection. This bounded auth budget also permits Telethon's normal retries for transient internal RPC failures. Exhausted migration, network errors and Telegram waits stop with a safe explanation; the app does not run an outer migration retry loop. No DC IDs or addresses are hardcoded in the application, no private Telethon migration methods are called, and no session tables are edited by application code.

Once authorized, the app disconnects that client and opens a second client **sequentially against the same `account.session` file** with zero request/connection retries before opening the dashboard. It verifies the restored identity matches the authenticated account. This changes client instances, not the saved session location, credentials or SQLite records. Message delivery retains its existing zero-retry policy. If authorization expires during dashboard use, sending stops and asks you to relaunch for authentication; it does not start login inside a send operation. The original `tgm login` also uses the supported authentication retry budget and corrected phone prompts; its other commands retain zero retries.

Phone normalization accepts `+` followed by a nonzero international prefix and 7–15 ASCII digits in total, with optional spaces, hyphens and parentheses. It does not guess a country code or convert domestic numbers. Both local validation failures and a confirmed Telegram `PhoneNumberInvalidError` allow explicit correction at the hidden prompt. Invalid/expired codes and incorrect 2FA passwords are not retried automatically. Existing authorized sessions skip phone/code/password prompts.

## Subsequent launches

Run the same command:

```sh
python3 main.py
```

The application checks the environment, obtains API credentials from the environment or Keychain, opens the original `account.session`, verifies authorization and account identity, validates the database, and loads cached groups. An authorized session does not request another login code. Expired authorization requests login using the same session path. An unexpected account ID blocks the dashboard; it does not silently rebind the installation.

The dashboard displays cached groups immediately, without scanning Telegram or inspecting groups. If the last basic observation is older than the configured basic cache lifetime (default 24 hours), or the cache is empty, it offers a lightweight refresh. Discovery and detailed inspection are separate, explicit operations. Rate limits pause work and persist a cooldown; saved records remain available. Snapshots of groups you have left may remain visible, but every send rechecks membership and permissions.

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
12. Inspect Pending / Expired Metadata
0. Exit
```

Options **2** and **3** show ten groups per page with Unicode names, actual Telegram IDs, effective permission status and permission timestamps. Use `n`/`p` for pages, `f` to filter allowed/denied/unknown/all, `s` to sort by name/ID/inspection time, and Enter or `q` to return. Search is case-insensitive, including Unicode. On narrow terminals, names are conservatively truncated for layout; the original value remains unchanged in SQLite and detailed JSON. Always select a destination by its **actual Telegram ID**, not its page position.

Option **4** always performs a fresh inspection of one explicit group. Option **12** sequentially inspects missing or expired metadata and skips reusable cache entries. Option **10** shows cache settings and credential source without secrets. Option **11** explains setup, permissions, reconnecting and session protection without making requests.
Discovery includes joined basic groups and supergroups, including archived dialogs. It excludes broadcast channels and migrated basic groups. Unsupported forum topic contexts can be shown in discovery but are blocked for sending.

- `allowed`: available Telegram membership and text posting permissions permit sending.
- `denied`: a reported restriction prevents sending.
- `unknown`: permission or destination context cannot be verified; sending is blocked.

Account `restricted` flags conservatively block sending. Telegram does not expose every human group rule, bot policy or account-wide spam restriction. Visible bot IDs come from full-chat metadata; their presence does not prove a moderation role or reveal their policies. Missing slow-mode metadata is reported as unknown. Telegram remains authoritative and may reject any request.

## Discovery compatibility and partial results

The discovery crash was reproduced offline with installed Telethon **1.45.0**. The original `analyze()` function in `telegram.py` (line 35 before the fix) read `permissions.send_messages`. `get_permissions(entity, me)` returns `ParticipantPermissions`, which has no such property. The old test fixture incorrectly invented it. The fixed code uses the real participant type to establish membership/admin status and the entity/participant `ChatBannedRights` (`view_messages`, `send_messages`, `send_plain`) to check text restrictions. Tests now use actual Telethon permission objects. An unverifiable participant remains **unknown**, never implicitly allowed.

### Phase 1: lightweight synchronization

Option **1** / `tgm discover` streams joined dialogs through `iter_dialogs(ignore_migrated=True)` with folder/archive filters unset. It includes archived groups and collects ID, title, type, username, available archive/membership state and observation time. It excludes broadcast channels, left/deactivated groups and migrated basic-group duplicates. Repeated IDs are processed once per scan. Inaccessible group entries are retained as restricted reference records, not authorized destinations.

This phase makes **no per-group entity, permission or full-chat requests**. Dialog paging itself still uses Telegram's API and may encounter a rate limit. Each basic record and its scan counters commit together. New groups start with unknown permissions. Existing inspected metadata and timestamps survive basic title/archive updates; visibility alone never grants posting permission. Records absent from a later scan are retained rather than deleted.

Counters distinguish current-scan groups, new records, basic fields updated, unchanged basic fields and fresh inspection caches skipped. `updated` refers to title/type/username/archive/membership changes, not merely a new observation timestamp. The dashboard separately shows total cached records, complete/incomplete metadata, fresh complete caches and groups awaiting permission verification. Unknown/expired permission snapshots display **Unknown**, even if an older raw JSON record said Allowed. Last basic scan state is retained when you run a separate detail inspection. An unfinished previous run is identified rather than presented as completed.

### Phase 2: detailed inspection and cache policy

Detailed inspection occurs only for an explicit single-group inspection, option **12**, `tgm inspect-pending`, or `tgm discover --details`. It is sequential, with a default minimum 0.5 seconds between detailed-request starts and no concurrent metadata workers. Basic groups reuse the full-chat response to verify membership, avoiding a second full-chat request. Supergroups use the supported single-member `GetParticipantRequest`. No `GetParticipantsRequest` enumeration is used to find bots. Telegram's full basic-chat response inherently includes its participant list; the app uses it for account membership, not a separate bot scan.

Available fields include membership, text restrictions, slow mode, member counts and visible bot IDs. Missing fields remain unknown. Optional metadata failures do not by themselves deny posting. Human rules and hidden moderation policies are never inferred. **Allowed is technical text permission, not permission to advertise or send unsolicited messages.**

Configure cache lifetimes through exported environment variables; `.env` is not auto-loaded:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `TGM_BASIC_TTL_SECONDS` | 86400 | When startup offers a basic refresh |
| `TGM_PERMISSIONS_TTL_SECONDS` | 900 | Permission snapshot freshness |
| `TGM_MEMBERS_TTL_SECONDS` | 3600 | Member-count freshness |
| `TGM_METADATA_TTL_SECONDS` | 21600 | Slow-mode/bot metadata freshness |
| `TGM_REQUEST_INTERVAL_SECONDS` | 0.5 | Minimum spacing of detail-request starts; 0–5 seconds |

TTL values accept 0–31536000 seconds; zero disables that cache. Different timestamps are stored inside the existing group metadata JSON. Legacy records without these timestamps need an explicit inspection before being considered fresh. A supergroup with expired permissions but fresh counts/bot metadata refreshes its entity and participant only, reusing the other cached fields. Basic-chat membership and member counts share a full-chat endpoint, so those fields refresh together. A confirmed partial/unknown result is briefly cached for the shortest detail TTL to avoid hammering unavailable data; it remains unknown/incomplete and never becomes authorization to send. Network failures are not cached as successful inspections.

Manual commands:

```sh
tgm discover                         # Basic dialogs only
tgm discover --details               # Basic scan, then missing/expired details
tgm inspect-pending                  # Resume missing/expired details; skip fresh results
tgm inspect-pending --force          # Explicitly bypass detail cache once
tgm discover --details --force       # Basic scan plus forced detail refresh
tgm inspect -- -1001234567890         # Fresh inspection of one chosen group
tgm groups --search 'ශ්‍රී' --permission unknown --sort name --page 1 --page-size 10
```

Standalone `tgm groups` keeps stdout as Unicode JSON lines; its page summary goes to stderr for pipe/script compatibility.

`--force` does not bypass Telegram cooldowns or restrictions. Sending always forces fresh authorization, identity, membership, text-permission and slow-mode checks after confirmation; caches are never the sole sending authority.

### Cooldowns, interruption and BrokenPipeError

FLOOD_WAIT records the actual Telegram wait duration as an absolute epoch deadline. The dashboard displays remaining seconds. Completed work is committed; further requests are blocked until expiry. There is no automatic wake-up/resume or immediate retry. After waiting, explicitly select option **1** or **12** / the corresponding CLI command. A resumed basic scan streams dialogs again with idempotent upserts; a resumed metadata pass skips completed fresh results. Unknown/optional API metadata errors remain group-local; network, authorization and database failures stop safely with the correct category.

The historical `BrokenPipeError` message lacked a traceback, so its actual origin cannot be established retrospectively. New sanitized I/O diagnostics always identify the boundary (`dialog_iteration`, `entity_lookup`, `full_chat_metadata`, `participant_permissions`, or `terminal_output`), exception class, relevant module/line and whether a record had committed. They exclude exception messages, request objects, credentials and absolute user paths. A request boundary identifies where an error surfaced; its included safe frames distinguish Telethon/asyncio internals when available. No assumption is made that BrokenPipeError means FloodWait.

Expected network failures preserve partial progress and return to the dashboard, where cached views remain available. If the connection is lost, exit/relaunch to restore the session before explicitly continuing. A closed stdout pipe or failed prompt flush cannot support a dashboard: the app stops the operation, preserves committed work and exits with a short stderr explanation. It does not keep requesting Telegram data into a broken output stream. Delivery errors remain uncertain/rejected according to the existing ledger and are never retried automatically.

### Unicode and terminal safety

Sinhala, Tamil, English, combining marks and emoji/ZWJ sequences remain unchanged in storage. New metadata JSON uses UTF-8-preserving serialization; old ASCII-escaped JSON decodes normally without re-encoding migrations. Human-readable JSON uses `ensure_ascii=False`. Terminal rendering removes executable ANSI/control sequences and bidi display controls while preserving combining marks, ZWJ/ZWNJ and variation selectors. JSON previews represent unsafe controls as visible escapes, preserving the exact message value rather than silently changing its body. Unsupported terminal encodings use explicit backslash escapes instead of crashing; use a UTF-8 terminal for readable Sinhala/Tamil. Column widths are conservative standard-library estimates: complex emoji/Indic fonts may not align identically in every terminal.

### SQLite preservation and measured operation counts

Original `groups`, `deliveries`, and `cooldowns` definitions and records remain unchanged. One additive `sync_runs(account PRIMARY KEY, data TEXT)` table stores account-isolated scan counters/state and the previous basic scan. `CREATE TABLE IF NOT EXISTS` is an atomic, idempotent additive upgrade; it never rebuilds the database or deletes records. WAL remains enabled. Basic group upsert and scan progress share one short transaction. UPSERT replaces `INSERT OR REPLACE`, avoids delete/insert semantics and skips identical payload updates. Primary-key lookups replace loading all groups to check a destination. Lists decode a bounded page; aggregates and pending inspections stream records. Python retains only compact seen IDs for scan deduplication, not all dialog/metadata objects. Existing account indexes are sufficient; no speculative indexes were added.

An offline 32-basic-group comparison against repository baseline `9917c95` measured **96 → 0 mocked per-group API-boundary calls** for the default scan (`get_entity`, `get_permissions`, raw full-chat calls; dialog paging excluded). SQLite commits were **64 → 34**, including new persisted progress. The prior benchmark’s explicit 32-group detail pass made 64 boundary calls (entity + full-chat per basic group), and a second fresh-cache pass made **0**. These are operation counts, not live network throughput, memory-use or elapsed-time claims. No M2/8 GB performance benchmark or live Telegram load test was performed.

## Sanitized development diagnostics

For file/line diagnostics on programming errors:

```sh
TGM_DEV_MODE=1 python3 main.py
```

Normal mode reports only the error class. Development mode adds package-relative filenames, line numbers, function names and a statically referenced missing attribute where available. It excludes exception messages, request representations, source lines, frame locals, exception chains and absolute user paths. Do not replace this with raw traceback/exception logging, which can expose Telegram request data. Telegram RPC errors, confirmed permission restrictions, network failures and SQLite failures have separate handling; unexpected programming errors are no longer described as generic network/Keychain troubleshooting.

## Compose and send safely

Use option **5** to compose plain text or load a UTF-8 file. Choose **1. Compose directly**, **2. Import UTF-8 file**, or **0. Cancel**. Typed message text is never interpreted as a filename. For direct multiline input, enter a single `.` on its own line to finish. The preview shows the complete draft. Empty messages and messages over 4096 UTF-16 units are rejected; messages are not automatically split.

Use option **6** to select a discovered group by exact ID, a visible page index, or search, inspect its fresh permissions, and explicitly select it. The current CLI send destination is selected in memory; persistent destination approval does **not** authorize a send. Replacing the draft clears the destination selection. Drafts and explicit destination approvals are account-isolated in the private database. A message's exact send confirmation is never persistent or standing approval. GUI preview tokens are short-lived and single use.

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

SQLite is checked for integrity, expected tables/columns and its delivery deduplication index before normal initialization. Existing tables are not dropped, records are not deleted, and incompatible or corrupt databases are rejected instead of reset. If a bound installation loses its database file, startup requires backup recovery rather than creating an empty delivery ledger. The original tables are retained; additive `sync_runs`, `drafts`, `approvals` and `delivery_notes` tables are initialized idempotently. The upgrade is idempotent and tested against the prior schema. It is not a general future schema migration framework.

Logging emits sanitized JSON error events with error class names, excluding API hashes, session contents, verification codes, passwords and message bodies. The explicit preview displays your composed message, so avoid screen sharing sensitive content. There is no remote telemetry. FileVault and a locked macOS account protect the session and unencrypted local metadata at rest; filesystem modes alone do not encrypt them. Python cannot guarantee zeroing secrets in process memory.

## Delivery history and duplicate prevention

Option 8 / `tgm history` shows the latest 100 delivery records for the connected account. The ledger stores account, destination, SHA-256 of the exact message, Telegram random ID, timestamps, status and a sanitized result, not a full historical message body. New desktop-era deliveries also retain a sanitized prefix (up to 160 characters plus an ellipsis) in a separate private table for history; drafts persist their full text when explicitly saved. These fields are sensitive plaintext in the private database. Legacy records remain unchanged and may have no preview or Telegram message ID.

A unique `(account, destination, message hash)` reservation is committed **before** submission. Exact duplicate text to the same destination is blocked across restarts for every status, including failed attempts. There is no retry/override button. Telegram random IDs provide an additional server deduplication mechanism. A process lock prevents concurrent instances using the same directory.

Statuses: `pending`, `sent`, `blocked`, `rejected`, `uncertain`. `sent` means Telegram acknowledged the request, not that every member read it. A network failure, interruption, server failure or database error after submission can leave `uncertain` or `pending` even if Telegram accepted the message. Inspect Telegram manually before considering another operation. Never delete the ledger or alter text to defeat duplicate protection.

FLOOD_WAIT and slow-mode errors persist the returned wait duration as a conservative account-wide cooldown. Peer spam flood errors block further sending locally for at least 24 hours; that minimum is not evidence Telegram has lifted a restriction. Authentication waits before identity is known use a reserved account-zero cooldown in the same database. No automatic flood-wait sleeps, uncertain delivery retries, alternate-account tactics or restriction bypasses are implemented. Bounded authentication connection/request retries are described above.

## Recovery

- **Missing dependencies / failed installation:** check pip output, network/index access, disk space and project permissions. Rerun `python3 main.py` and approve setup when ready. A malformed or old `.venv` is left untouched. Repair/recreate only the project virtual environment with Python 3.13+; never remove the private data directory to fix packages.
- **Interrupted setup:** relaunch. Completed Keychain entries and existing sessions remain available. Incomplete configuration writes are not published; startup releases its process lock when the process exits.
- **Keychain denied or locked:** unlock your login Keychain and relaunch, or explicitly choose credentials in memory. Use macOS Keychain Access to review a saved item. To rotate credentials, explicitly manage that item or use environment overrides. The app never replaces existing secrets automatically.
- **Invalid API ID or Hash format:** follow the field-specific explanation and re-enter that field. The hash stays hidden and is not echoed in validation errors. If Telegram rejects a correctly formatted credential pair, review API development tools, then correct environment values or explicitly manage the saved item using macOS Keychain Access and relaunch.
- **Invalid phone number:** use `+` and the country code; for Sri Lanka, `+947XXXXXXXX`, replacing X with digits. Omit the domestic leading `0`. You can correct local validation failures or a confirmed Telegram rejection at the same prompt. Input stays hidden.
- **Data-center migration:** Telethon handles normal migration within the bounded authentication retry budget. If migration still fails, check network access and relaunch using the saved session. Never delete or manually edit the session to change data centers.
- **Invalid verification code:** use the newest code for this application, not the developer portal login code or API ID. Relaunch when ready; the app does not retry codes automatically.
- **Expired verification code:** relaunch to explicitly request a new code. Do not reuse the old code.
- **Two-step verification failure:** use the Telegram account password, not the API Hash or macOS password. Check your account in Telegram and relaunch. Password attempts are not automatically retried. The app does not create Telegram accounts.
- **Expired authorization:** relaunch and complete the hidden login prompts. The original session path is reused; session files are not automatically deleted/reset.
- **Unexpected account identity:** restore the matching session from a secure backup or use a separate `TGM_DATA_DIR` for another account. Do not edit the binding just to bypass the mismatch check.
- **Network disconnect / request BrokenPipeError:** read the sanitized operation/module/line diagnostic, use cached views, and exit/relaunch to restore the connection. Explicitly resume discovery or pending inspection when ready. Never automatically retry an uncertain delivery.
- **Closed output pipe:** restore terminal/stdout access and relaunch. The app exits rather than repeatedly writing/requesting into a closed pipe. Previously committed group records and counters remain available.
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
- `telegram.py`, `storage.py`, `models.py`: original async service/ledger extended with two-phase sync, streaming queries and scan status.
- `cache.py`, `terminal.py`: lightweight freshness policies and Unicode-safe terminal output; standard library only.
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

Current Python, native, IPC and graphical validation results are maintained in [VALIDATION.md](VALIDATION.md) and [UI_VALIDATION.md](UI_VALIDATION.md). All automated Telegram operations use mocks; no live send is authorized by running tests.

## API references

- [Telethon client/authentication API and retry options](https://docs.telethon.dev/en/stable/modules/client.html)
- [Telegram migration error meanings](https://core.telegram.org/api/errors)
- [Telethon request/migration implementation](https://github.com/LonamiWebs/Telethon/blob/v1/telethon/client/users.py)
- [Telethon session sign-in behavior](https://docs.telethon.dev/en/stable/basic/signing-in.html)
- [Telegram rights model](https://core.telegram.org/api/rights)
- [Telegram text restriction flags](https://core.telegram.org/constructor/chatBannedRights)
- [Telethon ParticipantPermissions implementation](https://github.com/LonamiWebs/Telethon/blob/v1/telethon/tl/custom/participantpermissions.py)
- [Telegram sendMessage and random IDs](https://core.telegram.org/method/messages.sendMessage)
