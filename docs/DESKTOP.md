# Native macOS application

The desktop app is SwiftUI/AppKit. It launches the existing Python backend as one managed child process. There is no browser, HTTP listener, Electron, Qt, PySide or independent Telegram implementation. The original `python3 main.py` CLI remains supported.

## Build and launch locally

Requirements: Apple Silicon Mac, macOS 14+, Xcode with macOS SDK; Liquid Glass is selected only on macOS 26+. The current development build uses the checkout's Python 3.13 `.venv` and the same declared Telethon dependency. Complete the CLI's approved virtual-environment setup if the runtime is absent; the desktop app never installs packages globally.

```sh
cd ~/Desktop/TelegramManager
./macos/build.sh
open macos/build/Build/Products/Debug/TelegramManager.app
```

If the build-script name/output changes, use the exact command in the project README. The Xcode project is `macos/TelegramManager.xcodeproj`, scheme `TelegramManager`, configurations Debug and Release. Its bundle identifier is `org.telegram-group-manager.mac`; display name is Telegram Group Manager. The app is arm64. UI materials fall back to standard native controls on earlier supported macOS versions.

The local build locates `.venv/bin/python` through its compiled development-root setting (or an explicit `TGM_PROJECT_ROOT`). Python source is bundled as app resources. The app starts `python -u -m telegram_manager.ipc` with private owned pipes and `PYTHONPATH` pointing at backend resources. It does not require a separately running CLI. Quit the CLI before launching the GUI: the shared exclusive application lock prevents concurrent backend owners of one session/database.

`TGM_NO_AUTO_CONNECT=1` disables the normal startup session-restore attempt for offline UI validation. `TGM_DATA_DIR` can select a dedicated test directory. These are developer controls, not a way to bypass Telegram or sending confirmation. Normal startup restores credentials/session, loads cached groups immediately, and never starts discovery, metadata inspection or messaging automatically.

## Existing installation and data

The existing directory is retained:

```text
~/Library/Application Support/TelegramGroupManager/
  account.session       Telegram authorization; never copied into the app bundle
  manager.sqlite3       Original group/delivery/cooldown records
  config.json           Non-secret account binding
  manager.lock          Single backend owner
  desktop-settings.json Non-secret desktop cache/batch preferences
```

No session migration, account reset or database replacement is performed. New `drafts`, `approvals` and `delivery_notes` tables are additive/idempotent. Original delivery IDs, hashes, random IDs, states and unique constraints remain unchanged. Draft bodies and limited delivery previews are sensitive plaintext in this private database; API hashes, verification codes and passwords are never stored there. New deliveries retain at most 160 characters plus an ellipsis as a history preview; historical full bodies are not retained. Old ledger rows display unavailable previews/message IDs honestly.

The same native macOS Keychain service and directory-scoped item naming are reused. The GUI can collect API credentials, phone, verification code and 2FA password through private IPC; secret fields are cleared after submission and never returned by the backend. A new verified account must be explicitly bound. A different existing account binding is rejected.

SQLite backups use its backup API, include committed WAL contents and pass an integrity check. Backup files are private (0600), must be new filenames, and exclude session/Keychain credentials. They may contain drafts, previews and destination metadata. Restore only with the application stopped and preserve the session and binding separately in a secure full-directory backup. Diagnostic export contains versions, architecture, cache policy and security flags, with no account identifiers, message bodies, group names, credential contents or network traces.

## Workflow

- **Dashboard:** live backend/cache statistics, account status, cooldown countdown and bounded recent activity.
- **Groups:** paginated cached table, Unicode search, permission/type filters, name/member/time sort; selecting a row reads cached details only.
- **Inspector:** reasons, membership, slow mode, freshness, visible bots and unknown policies; explicit inspection/refresh and destination approval.
- **Permissions:** bounded user-controlled sequential inspection, optional explicit selected groups, progress, cancel and persisted cooldowns. Default 10, maximum 100; no implicit “all” authorization.
- **Composer:** multiline Unicode editor, UTF-16 limit, explicit draft save/import, approved destination, complete backend preview and fresh permission verification.
- **Destinations:** account-scoped explicit approvals and revocation. Approval never grants standing send authority.
- **History:** search actual ledger outcomes; never automatically retry pending/uncertain deliveries.
- **Settings:** appearance/launch preferences, account/session/runtime/storage information, cache/batch settings, SQLite backup and sanitized diagnostic export.

A send requires a backend-issued one-use preview token bound to account/destination/exact message, valid for 120 seconds; explicit stored destination approval; the exact `SEND <id>` confirmation; and fresh identity, permission and slow-mode checks. The existing atomic deduplication reservation is committed before submission. Cancellation or a lost process/pipe after submission can leave `uncertain`/`pending`; check history and Telegram manually. The UI never replays send requests automatically.

## IPC and lifecycle

See [IPC.md](IPC.md) for the versioned newline-delimited JSON protocol. Every request has a unique ID, strictly validated method/parameters and a typed success/error response. Progress has the originating request ID. Stdout is protocol only; diagnostics go to stderr without secrets. There is no shell-command endpoint or unauthenticated local listener.

Telegram and mutation work serialize. Local cached reads can proceed while network calls await results. Queues, page sizes, outstanding requests, frame size, activity and inspection batches are bounded. EOF, shutdown, cancellation and output backpressure cancel work and close the session/database safely. The GUI monitors termination, fails outstanding continuations, clears standing previews, and never duplicates an uncertain operation. Process reattachment requires explicit restoration rather than replaying a failed send.

## Packaging boundary

The produced app is a **local development build**, not yet a distributable release. It depends on this checkout's runtime. Copying `.venv` to another Mac is not a valid distribution strategy: it can contain symlinks, absolute interpreter paths and external framework dependencies.

A distribution build should embed a verified relocatable arm64 Python 3.13 runtime (for example a pinned, checksum-verified python-build-standalone release) under `Contents/Resources/Python`, install only the declared dependencies into that runtime, retain their licenses, and use bundled backend source. The client has a bundled-runtime lookup path. Runtime/source resources must never include `account.session`, SQLite files, `.env`, Keychain exports or user configuration. The package then needs nested Mach-O/library signing, hardened-runtime review, Developer ID signing/notarization/stapling, and clean-Mac tests including no external Python installed, Unicode, Keychain ACL prompts, first login, update/rollback, quarantine, reconnect and cancellation. No archive/runtime was downloaded or represented as verified in this task.

Native subprocess access to the existing Python/Keychain/filesystem is not App-Sandbox-contained in this development configuration. File permissions, exclusive ownership, strict IPC, process management and safe file import remain enforced. A Mac App Store sandbox design would require additional entitlements and data-access work; it is not claimed here. No generic secret/credential export is provided.
