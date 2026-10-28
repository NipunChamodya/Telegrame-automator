# Native upgrade implementation and validation

Validated on 2026-10-28 with Python 3.13.4, Telethon 1.45.0, Swift 6.4, Xcode 27.1, macOS 26.6.2 arm64. No live Telegram authentication, discovery or sending was performed. Existing user credentials, sessions and databases were not reset or migrated.

## Implemented functionality

The existing backend and numbered CLI remain. The new SwiftUI/AppKit target implements dashboard/navigation, cached group table/search/filter/sort/pagination, group inspector, bounded permission inspection/progress/cancellation, account connection and guided authentication, Unicode message editor/import/draft persistence, explicit destination approvals/revocation, server preview and exact send confirmation, history, settings, backup and sanitized diagnostic export. Appearance follows system/light/dark; native Liquid Glass is availability-gated to macOS 26. Notifications are opt-in.

The GUI launches one managed Python subprocess. Strict typed JSON-lines requests have unique IDs, bounded frames/queues, typed errors, progress and cancellation. Stdout is protocol only; stderr carries sanitized diagnostics. There is no HTTP server, web UI, shell-command endpoint or second Telegram implementation. Cached reads do not perform Telegram metadata calls; Telegram operations/mutations serialize. EOF, closed pipes, timeout and shutdown invalidate requests without replaying sends.

## Root causes and changes

- CLI selection converted arbitrary text directly to `int`, so `all` leaked a conversion error. Selection now validates exact IDs, visible indices and search, and rejects implicit all/empty/unavailable destinations before API work.
- Composition treated the first answer as a filename. It now has explicit compose/import/cancel modes. Imports require bounded regular UTF-8 files and reject symlinks/devices/FIFOs.
- Fixed-width columns created large gaps and mishandled Unicode display widths. Compact terminal-width-aware columns preserve Sinhala/Tamil, emoji joiners and combining marks while removing unsafe controls.
- Lightweight discovery intentionally leaves permissions unknown. Explicit pending/expired inspection now uses validated bounded batches (default 10, maximum 100), updates cache/counts, and preserves partial progress. Viewing a row never triggers inspection.
- FloodWait state was persisted by the backend but a failing GUI operation skipped its success-path status reload. Typed cooldown errors now reload cached status immediately without retrying the operation. The countdown does not poll Telegram; resumption remains explicit.
- BrokenPipeError has several possible sources. IPC now distinguishes closed output/input, process death and transport failures; shutdown/backpressure are bounded. The historical user-reported BrokenPipeError cannot be attributed to an exact original line without its traceback; no claim is made that it was necessarily a Telegram transport error.
- Unicode JSON uses Unicode-preserving serialization; display sanitization retains original stored names. IPC/UI preserve Unicode without double decoding.

Earlier backend fixes retained in this checkout include supported Telethon permission inspection, supported authentication migration retry behavior, two-phase lightweight discovery, separate freshness policies, persisted cooldowns and incremental saves. The old permission access and zero-retry authentication issues are covered with mocks; live migration was not reproduced here.

## Database and security

Original group, delivery, cooldown and sync records and account-scoped constraints remain. Additive, idempotent `drafts`, `approvals` and `delivery_notes` tables retain account isolation; no original table is replaced or records deleted. Delivery notes contain a bounded new-delivery preview and available Telegram message ID; legacy rows honestly lack these details. Drafts/previews are sensitive plaintext protected by the existing private directory/database permissions.

Existing session filename, Keychain service, configuration binding and exclusive lock are reused. Backups use SQLite's backup API and integrity verification, private non-overwriting output, cancellation cleanup and no session/Keychain export. Diagnostic export omits secrets, account/group identifiers and message bodies.

Sending requires explicit stored approval, a short-lived single-use server preview token bound to the exact account/destination/message, exact `SEND <id>` confirmation, fresh identity/permission/slow-mode checks and the original atomic deduplication reservation. Random message IDs and persistent ledger/cooldowns remain. Pending/uncertain deliveries are never replayed automatically. Text-posting permission does not establish permission for advertising or unsolicited content.

## Actual verification results

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **172 passed, 54 subtests passed**, 2.58 seconds; no failures |
| Python `compileall` for main/src/tests | Passed |
| `git diff --check` | Passed |
| `./macos/test.sh` | **17 Swift/XCTest tests passed**, zero failures, about 3.95 seconds |
| Debug build (including build-for-testing) | **BUILD SUCCEEDED**, arm64 `.app` produced |
| `./macos/build.sh Release` | **BUILD SUCCEEDED**, arm64 `.app` produced |
| Standalone compiled Swift transport harness | Passed Unicode, concurrent requests, progress, timeout, cancellation, malformed response, closed pipe/SIGPIPE, EOF and graceful shutdown scenarios |
| Ruff | Unavailable in the existing venv; lint not verified; no packages installed |
| Standard Xcode test runner | Testmanagerd execution blocked with error 159; direct `xcrun xctest` executes the built suite successfully |
| Interactive window launch | **Not verified**: direct execution aborted in macOS `_RegisterApplication` before application initialization; normal `open` returned Launch Services `-10827` (`kLSNoExecutableErr`) despite the arm64 executable being present/executable |
| Isolated native launch data preservation | Temporary cached Unicode group/draft remained intact; backend lock released; no Telegram connection attempted |
| Live Telegram/session/Keychain behavior | Not exercised; mocked restoration/authentication only |

Python coverage includes authentication/session restoration, discovery types/archived/migrated/broadcast handling, Unicode, missing metadata, classification/freshness, FloodWait/cooldowns, partial failures, SQLite preservation, account isolation, CLI selection/composition, import validation, IPC strict validation/cancellation/concurrency/progress/EOF, real subprocess offline workflows, backups and delivery safeguards. Swift tests cover typed Unicode decoding, freshness, composer limits, exact confirmation, preview invalidation, search/filter/selection/approval state, backend death, concurrent transport, cancellation, errors/timeouts and cooldown status refresh. These are unit/integration tests, not full mouse-driven accessibility/UI automation.

The CLI launcher was exercised in isolated storage and cancelled before authentication; complete startup/dashboard restoration uses mocks. No real sends occurred. Existing live connection/discovery reports are user observations, not newly verified results.

## Performance observations

The earlier documented offline 32-group baseline reduces default scan per-group API-boundary calls from 96 to zero, excluding dialog paging. This upgrade retains that separation: row display is SQLite-only, fresh metadata skips detail requests, inspection is sequential and bounded, queries paginate, activity/queues/frame sizes are bounded, and no constant Telegram polling is introduced. These are explained operation reductions, not measured live throughput.

The final Debug bundle occupies about 4.1 MiB locally, excluding the external Python runtime, dependencies and build caches. No valid M2 RAM/idle-CPU/launch-time benchmark was obtained; process inspection is restricted in this environment. No memory or speed claim is made.

## Files created and modified

Created:

- `src/telegram_manager/ipc.py`, `messaging.py`, `maintenance.py`.
- `tests/test_ipc.py`, `test_cli_stabilization.py`, `test_desktop_integration.py`, `test_maintenance.py`, and `tests/fixtures/ipc_transport_fixture.py`.
- `macos/TelegramManager.xcodeproj` and shared scheme; native `App`, `Models`, `Services`, `ViewModels`, `Views`, `Resources` source directories; `macos/TelegramManagerTests/ModelTests.swift`; `macos/Tools/TransportSmoke.swift`.
- `macos/build.sh`, `macos/test.sh`, `scripts/build_macos.sh`.
- `docs/DESKTOP.md`, `docs/IPC.md`, this report.

Modified:

- `.gitignore`, `README.md`, `pyproject.toml`.
- `src/telegram_manager/__init__.py`, `cli.py`, `dashboard.py`, `security.py`, `storage.py`, `telegram.py`, `terminal.py`.
- `tests/test_application.py`.

## Launch instructions and remaining work

Quit the CLI first, then use the local development build:

```sh
cd ~/Desktop/TelegramManager
./macos/build.sh
open macos/build/Build/Products/Debug/TelegramManager.app
```

Release artifact: `macos/build/Build/Products/Release/TelegramManager.app`. CLI maintenance remains `python3 main.py`.

**This is not yet a verified distributable product.** Normal desktop window launch must be checked outside this managed execution environment; the observed launch failures remain unresolved here. Live authentication/restoration, real Keychain prompts, discovery, cancellation and deliberate single-destination sending require separate user-authorized acceptance testing. Notification permission prompts, visual accessibility/window behavior and clean-Mac testing remain unverified.

Distribution additionally needs a verified relocatable embedded Python runtime and dependencies/licenses, nested-library signing and hardened-runtime review, Developer ID signing/notarization/stapling, quarantine/update/rollback and clean-Mac tests. Local builds use the checkout's venv and are not App-Sandbox-contained. See [DESKTOP.md](DESKTOP.md) for the packaging boundary and [IPC.md](IPC.md) for protocol details. Do not copy private sessions/configuration/databases into the bundle.
