# Native macOS application

The desktop app is SwiftUI/AppKit. It launches the existing Python backend as one managed child process. There is no browser, HTTP listener, Electron, Qt, PySide or independent Telegram implementation. The original `python3 main.py` CLI remains supported.

## Build and launch locally

Requirements: Apple Silicon Mac, macOS 14+, Xcode with macOS SDK; Liquid Glass is selected only on macOS 26+. The current development build uses the checkout's Python 3.13 `.venv` and the same declared Telethon dependency. Complete the CLI's approved virtual-environment setup if the runtime is absent; the desktop app never installs packages globally.

```sh
cd ~/Desktop/TelegramManager
./macos/build.sh
open macos/build/Build/Products/Debug/TelegramManager.app
```

If the build-script name/output changes, use the exact command in the project README. The Xcode project is `macos/TelegramManager.xcodeproj`, scheme `TelegramManager`, configurations Debug and Release. Its bundle identifier is `org.telegram-group-manager.mac`; display name is Unofficial Telegram Manager. The app is arm64. UI materials fall back to standard native controls on earlier supported macOS versions.

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

No session migration, account reset or database replacement is performed. The `drafts`, `approvals` and `delivery_notes` tables remain additive/idempotent. V2 lazily adds `dialog_cache`, `conversation_drafts` and `local_labels`; no original table is replaced. Original delivery IDs, hashes, random IDs, states and unique constraints remain unchanged. Draft bodies and limited delivery previews are sensitive plaintext in this private database; API hashes, verification codes and passwords are never stored there. New deliveries retain at most 160 characters plus an ellipsis as a history preview; historical full bodies are not retained. Old ledger rows display unavailable previews/message IDs honestly.

The same native macOS Keychain service and directory-scoped item naming are reused for the original account. Additional profiles receive their own directory-scoped items, session, SQLite file and desktop settings. The new `account-profiles.json` registry selects an active profile without moving the original files; see [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md). The GUI can collect API credentials, phone, verification code and 2FA password through private IPC; secret fields are cleared after submission and never returned by the backend. A new verified account must be explicitly bound. A different existing account binding is rejected.

SQLite backups use its backup API, include committed WAL contents and pass an integrity check. Backup files are private (0600), must be new filenames, and exclude session/Keychain credentials. They may contain drafts, previews and destination metadata. Restore only with the application stopped and preserve the session and binding separately in a secure full-directory backup. Diagnostic export contains versions, architecture, cache policy and security flags, with no account identifiers, message bodies, group names, credential contents or network traces.

## V3 client boundaries

Chats is now the default workspace. Supported private/group conversations use one bounded event pipeline; gaps clear stale content and require an explicit snapshot repair. Channel/bot identities are visible but content is gated pending sponsored-content integration. Own personal plaintext actions and explicit bounded JPEG/PNG previews are additive. Contacts/profile reads and read-only folder definitions are available; no remote folder modification or avatar downloading is claimed. See [CLIENT_FEATURES.md](CLIENT_FEATURES.md), [MESSAGE_ACTIONS.md](MESSAGE_ACTIONS.md), and [CLIENT_ARCHITECTURE_DECISION.md](CLIENT_ARCHITECTURE_DECISION.md).

## Workflow

- **Dashboard:** live backend/cache statistics, account status, cooldown countdown and bounded recent activity.
- **Groups:** paginated cached table, Unicode search, permission/type filters, name/member/time sort; selecting a row reads cached details only.
- **Inspector:** reasons, membership, slow mode, freshness, visible bots and unknown policies; explicit inspection/refresh and destination approval.
- **Permissions:** bounded user-controlled sequential inspection, optional explicit selected groups, progress, cancel and persisted cooldowns. Default 10, maximum 100; no implicit “all” authorization.
- **Composer:** multiline Unicode editor, UTF-16 limit, explicit draft save/import, approved destination, complete backend preview and fresh permission verification.
- **Destinations:** account-scoped explicit approvals and revocation. Approval never grants standing send authority.
- **History:** search actual ledger outcomes; never automatically retry pending/uncertain deliveries.
- **Accounts:** add/switch isolated profiles; separate disconnect, exact-confirmation remote logout and destructive removal of a selected nonlegacy profile. The original profile cannot be removed through these controls.
- **Chats:** explicit bounded refresh, cached search/type filters, explicit older-dialog continuation, paginated message reads (up to 200 loaded in the UI), Saved Messages, personal text previews/replies, and explicit attachment download up to 64 MiB.
- **Drafts:** 800 ms debounced local saving, per-conversation recovery and deletion; switches flush the original account composition before changing context.
- **Settings:** appearance/launch preferences, account/session/runtime/storage information, cache/batch settings, SQLite backup and sanitized diagnostic export.

A managed-group send requires a backend-issued one-use preview token bound to account/destination/exact message, valid for 120 seconds; explicit stored destination approval; the exact `SEND <id>` confirmation; and fresh identity, permission and slow-mode checks. The existing atomic deduplication reservation is committed before submission. Cancellation or a lost process/pipe after submission can leave `uncertain`/`pending`; check history and Telegram manually. The UI never replays send requests automatically.

## IPC and lifecycle

See [IPC.md](IPC.md) for the versioned newline-delimited JSON protocol. Every request has a unique ID, strictly validated method/parameters and a typed success/error response. Progress has the originating request ID. Stdout is protocol only; diagnostics go to stderr without secrets. There is no shell-command endpoint or unauthenticated local listener.

Telegram and mutation work serialize. Local cached reads can proceed while network calls await results. Queues, page sizes, outstanding requests, frame size, activity and inspection batches are bounded. EOF, shutdown, cancellation and output backpressure cancel work and close the session/database safely. The GUI monitors termination, fails outstanding continuations, clears standing previews, and never duplicates an uncertain operation. Process reattachment requires explicit restoration rather than replaying a failed send.

## Launch diagnostics and UI evidence

Build scripts now use Xcode ad-hoc signing instead of disabling signing. Both the Info.plist binding and resource seal must verify:

```sh
codesign --verify --deep --strict --verbose=2 macos/build/Build/Products/Debug/TelegramManager.app
```

An earlier artifact failed this check. The corrected signed artifact verifies, but graphical execution in the managed environment still aborts in macOS application registration before app/backend initialization. An independently signed minimal SwiftUI APPL bundle reproduces the abort; ordinary command-line AppKit initialization succeeds. Launch Services also returns -10827 here. Do not treat this as a verified window launch or recommend deleting user data. Reproduce from an unlocked Terminal/Finder session on the Mac.

Run `./macos/screenshots.sh light` and `./macos/screenshots.sh dark` for fixture-only XCUITest capture. See [UI_VALIDATION.md](UI_VALIDATION.md) for actual blocked test-runner results and the remaining visual matrix. No genuine screenshots or recordings were captured in this environment.

## Packaging boundary

The produced app is a **local development build**, not yet a distributable release. It depends on this checkout's runtime. Copying `.venv` to another Mac is not a valid distribution strategy: it can contain symlinks, absolute interpreter paths and external framework dependencies.

A distribution build should embed a verified relocatable arm64 Python 3.13 runtime (for example a pinned, checksum-verified python-build-standalone release) under `Contents/Resources/Python`, install only the declared dependencies into that runtime, retain their licenses, and use bundled backend source. The client has a bundled-runtime lookup path. Runtime/source resources must never include `account.session`, SQLite files, `.env`, Keychain exports or user configuration. The package then needs nested Mach-O/library signing, hardened-runtime review, Developer ID signing/notarization/stapling, and clean-Mac tests including no external Python installed, Unicode, Keychain ACL prompts, first login, update/rollback, quarantine, reconnect and cancellation. No archive/runtime was downloaded or represented as verified in this task.

Native subprocess access to the existing Python/Keychain/filesystem is not App-Sandbox-contained in this development configuration. File permissions, exclusive ownership, strict IPC, process management and safe file import remain enforced. A Mac App Store sandbox design would require additional entitlements and data-access work; it is not claimed here. No generic secret/credential export is provided.


## Stability repair: process ownership

See [BACKEND_LIFECYCLE.md](BACKEND_LIFECYCLE.md). Ordinary IPC requests no longer start Python. Startup/retry explicitly owns one child; restart waits for its exit, and repeated Quit waits for cleanup. The app has one workspace window; Settings uses the same model. Python also observes its actual parent's exit on macOS, protecting against inherited writers that would delay EOF.

A live disconnected backend deliberately retains its installation lock to protect cached writes. Telegram disconnect/logout is not application termination. Account switching releases the old additional profile lock, while the installation lock remains owned until the backend exits. A rejected competing process cannot steal it.

Recovery shows a prominent state/explanation, bounded Retry Connection, local diagnostics and Account Manager. Missing runtime or an external owner is not fixed by a restart loop. Local diagnostics include only the managed child PID/state, outstanding request count and withheld-stderr byte count. A lock-owner inventory is not available from the restricted development environment; diagnose persistent external ownership safely from Terminal as documented.
