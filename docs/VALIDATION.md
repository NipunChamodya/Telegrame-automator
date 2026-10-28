# Telegram Manager V2 — implementation and validation report

Version 0.3.0 development preview, validated 2026-10-28 on macOS 26.6.2 arm64, Python 3.13.4, Telethon 1.45.0, Xcode 27.1 and Swift 6.4. The previous 0.2 baseline was 172 Python tests/54 subtests and 17 Swift tests; current results below supersede those counts.

**This is not a production-readiness claim.** Real graphical launch and screenshots remain blocked in the managed execution context. No live Telegram authentication, discovery, sending, logout or native Keychain modification was performed. Existing personal sessions, database records and credentials were not reset or migrated.

## Implemented features and architecture

| Area | Working implementation |
| --- | --- |
| Accounts | Add/list/switch, restore selected profile on backend restart, separate disconnect/logout/remove, optional archive/restore |
| Isolation | Stable random local profile IDs plus verified numeric Telegram identity; independent session/database/settings/Keychain namespace; original paths preserved |
| Switch safety | Serialized transitions; queued request-generation rejection; preview invalidation; editor draft flush; stale UI response guards |
| Authentication | Existing supported Telethon phone/code/2FA/binding flow, GUI credential tutorial and country-prefix input, secure fields, optional password visibility |
| Groups | Existing lightweight discovery, Unicode cached search/filter/sort/pagination, detailed inspector, bounded inspections, local labels and persistent cooldowns |
| Chats | Explicit bounded dialog refresh/continuation, private/group/channel/Saved Messages browsing, paginated history, available sender/time/unread metadata, explicit remote search |
| Composition | Managed-group and personal text editors, UTF-16 count, preview, per-account/per-conversation drafts, 800 ms local autosave and recovery |
| Sending | One selected destination, exact confirmation, live identity verification, one-use token, persistent atomic deduplication/random IDs/ledger; no automatic replay |
| Media | Explicit known-size attachment download up to 64 MiB, progress/cancellation, private temporary output, no overwrite |
| Native UI | Account switcher/management, Activity, Chats, Drafts, existing screens, native semantic controls/materials, selected Liquid Glass, light/dark/system appearance |
| Compatibility | Original CLI retained; original session/database/binding paths unchanged |

SwiftUI views use the MainActor model and actor-owned process transport. Python remains the Telegram source of truth, with typed bounded JSON-lines IPC and one serialized network/mutation context. Cached reads use the active profile's SQLite file. Account operations never use display names or phone numbers as database identities. See [ARCHITECTURE.md](ARCHITECTURE.md), [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md), [IPC.md](IPC.md) and [CHAT_API.md](CHAT_API.md).

Inactive accounts are disconnected, not continuously polled. Switching does not automatically discover groups or fetch history. The GUI explicitly requests session reconnection after selection; the IPC switch itself is offline. The CLI continues to use its configured original directory unless explicitly pointed elsewhere.

## Bugs and limitations investigated

- **Launch signing defect:** disabling Xcode signing left a linker-only signature. `codesign --verify --deep --strict` failed with “code has no resources but signature indicates they must be present.” Scripts now request proper ad-hoc bundle signing; identifier, Info.plist binding and sealed resources verify.
- **Remaining registration blocker:** corrected signed Debug/Release applications still abort in `_RegisterApplication` / `_NSInitializeAppContext`, before application/Python startup; `open` returns Launch Services -10827. An independent minimal signed SwiftUI APPL bundle reproduces this, while command-line AppKit initialization succeeds. Normal Finder launch outside this execution context is not verified.
- **Wrong-context queued work:** requests now capture generation on protocol acceptance and reject stale mutations after switching/disconnecting/logging out. UI transition tasks cancel and await old queries/autosaves before swapping context.
- **Draft races:** stale asynchronous hydration no longer overwrites new editor text; debounce tasks capture account/destination/text, switches flush the old account, and unchanged-body autosaves no longer invalidate a matching preview.
- **Preview confusion:** personal and managed tokens cannot be interchanged; switching clears both. Personal sends carry an explicit expected account; managed tokens also bind profile/generation.
- **Logout semantics:** the public MTProto logout request is used after fresh live identity verification. It preserves local files rather than calling Telethon's convenience method that deletes the session file. Unknown transport outcomes are not reported as successful logout.
- **Removal scope:** only confirmed nonlegacy profiles can be removed, with private-tree checks and scoped native Keychain removal; original profile removal is blocked. Archive remains a separate reversible action.
- **Screenshot fixtures:** DEBUG-only fixture navigation/read/autosave paths do not replace safe synthetic data with backend errors; the transport independently refuses to start in fixture mode. Fixtures cannot contact Telegram.

Earlier CLI selection, direct-text/file ambiguity, Unicode spacing, permission cache and FloodWait fixes remain. The historical BrokenPipeError cannot be attributed to an exact original line without its traceback. Current code/tests distinguish closed IPC pipes, network transport, cancellation and partial persistence rather than assuming every pipe failure is a rate limit.

## Actual quality-gate results

| Gate | Status and evidence |
| --- | --- |
| Full Python suite | **PASSED: 216 tests, 59 subtests**, 4.31 seconds; zero failures |
| Python syntax | **PASSED:** `compileall` for main/src/tests/scripts |
| Whitespace | **PASSED:** `git diff --check` |
| IPC/account/auth/Unicode/security regressions | **PASSED:** included in the full Python suite, using mocks and real offline subprocesses |
| Native unit/integration suite | **PASSED: 34 XCTest tests**, zero failures; latest rerun completed in 7.682 seconds |
| Native UI-test target compilation | **PASSED:** expanded 20-state screenshot workflow builds |
| Actual XCUITest execution | **BLOCKED:** testmanagerd/control lookup error 159; no graphical assertions reported as passed |
| Debug / Release builds | **PASSED:** real arm64 `.app` bundles produced with ad-hoc signatures |
| Strict bundle signatures | **PASSED:** `codesign --verify --deep --strict` for both products |
| Actual graphical launch | **BLOCKED / NOT VERIFIED:** registration abort / Launch Services -10827 in this context |
| Screenshots / recordings | **NOT CAPTURED:** zero genuine images/recordings; no fabricated substitutes |
| Live Telegram / Keychain acceptance | **NOT RUN:** mocked APIs only; no live sends |
| Ruff | **NOT RUN:** unavailable in the project venv and shell; no packages installed |
| GitHub Markdown / Mermaid visual rendering | **NOT VERIFIED:** no GitHub-compatible renderer/browser available here; static checks only |
| Distribution | **INCOMPLETE:** checkout venv required; no signed/notarized portable installer |

Python regressions cover original onboarding/authentication/restoration, groups/permissions/caches/rate limits, Unicode and terminal sanitization, duplicate reservation and uncertain outcomes, strict IPC/concurrency/cancellation/progress/EOF, profile registry/path/link protection, duplicate-account prevention, selected logout/removal, Keychain-denial preservation, conversation pages/drafts/labels/personal sends/replies/media bounds and partial recovery. A real offline subprocess test restarts into the selected profile, switches back, and verifies the original ledger/draft/session bytes remain intact.

Swift tests cover typed data, validation, previews and exact confirmation, stale state/backend death, cached filtering/selection/approvals, actor transport/concurrency/timeouts/cancellation, account isolation, switch ordering and Unicode autosave. These do not replace mouse/keyboard/VoiceOver acceptance.

## Graphical and interaction evidence

[UI_VALIDATION.md](UI_VALIDATION.md) lists all 20 fixture states and expected attachments, currently BLOCKED, plus compact/standard/large light/dark procedures. [ui-testing/ATTEMPTS.md](ui-testing/ATTEMPTS.md) preserves a sanitized attempt ledger. The failed runner result is retained under ignored `macos/build/UI-light-20261028-171712.xcresult`.

| Workflow | Verification boundary |
| --- | --- |
| Launch → Dashboard | Model/startup mocks pass; actual window blocked |
| Add/authenticate → Dashboard | Auth/profile mocks pass; real login not performed |
| Switch → correct data | Mocked model tests and real offline process restart pass |
| Disconnect/reconnect | Mocked lifecycle/restoration passes; server reconnect unverified |
| Logout selected account | Fresh-identity/public-request mocks pass; remote revocation unverified |
| Group search/select/inspect | Python/native fixtures pass; graphical clicks blocked |
| Compose/preview/cancel | Validation/preview mocks pass; graphical interaction blocked |
| Chats/conversation read | Bounded API mocks pass; live history not read |
| Draft/restart/recover | SQLite/process persistence passes; graphical restart blocked |
| Close/relaunch/restore session | Process/session preservation and restoration mocks pass; live authorization unverified |
| Backend crash/recovery | Native transport/state tests pass; recovery window unverified |
| FloodWait countdown | Persistence and status-refresh mocks pass; visual countdown unverified |
| Switch while composing | Native ordering/autosave and storage isolation tests pass |
| Switch while send queued | Generation/token isolation tests pass; no live sends |
| Logout one, preserve others | Profile isolation fixtures pass; actual remote logout not performed |

No critical/major *visual* defect is claimed fixed through screenshots, because none were captured. Fullscreen, high contrast, reduced motion, larger text, VoiceOver, keyboard-only navigation and layout clipping require local graphical acceptance.

## Measured performance and bounded operations

`scripts/benchmark_cache.py` used 1000 synthetic Unicode dialogs, 100 page queries of 50 records and Python allocation tracing. One actual run measured median **8.469 ms**, p95 **12.558 ms**, peak Python-traced allocations **74,688 bytes**, with **zero Telegram calls**. This describes only that local SQLite workload with tracing overhead; it is not application RSS, startup latency, live network throughput or a general M2 benchmark.

Default group discovery retains the prior explained reduction from per-group detail requests to lightweight dialog collection. Cached rows do not trigger inspection; history is paginated and capped at 200 UI rows; batches, media size, activity, frames and queues are bounded. No idle CPU/RAM claim is made. Profile switching still validates SQLite and may take longer with large real databases; it has not been benchmarked with personal data.

## Security review and remaining work

Session/credential paths and binding are preserved. Additive chat tables do not replace original schema/data. Drafts, dialog previews and delivery notes are sensitive plaintext under private file permissions; they are not encrypted databases. Profile removal is explicit and destructive, and filesystem/Keychain deletion cannot be atomically rolled back together. Legacy removal is intentionally refused. A new local ledger after explicitly deleting history cannot remember deleted deduplication entries.

The final filename audit found zero tracked private-artifact candidates and zero session/database/environment/configuration artifact candidates in either bundle. Bundled Python source hashes match the current backend in both builds. This is a scoped filename/resource audit, not a claim that automated scanning can prove all secrets absent. Ignore rules include per-account registry/settings artifacts; dependencies/runtime remain external in development. No session export, arbitrary-code IPC, bulk send, automatic forwarding, spam bypass or uncertain-delivery retry was added.

Incomplete features: Telegram edit/delete/forward actions; uploads and rendered media previews; real cached avatars; complete per-account notification/quiet-mode behavior; comprehensive graphical/accessibility acceptance; live account acceptance; portable embedded runtime; Developer ID signing/notarization/DMG/update/rollback and clean-Mac tests. Local ad-hoc signing is not release trust or notarization. No license file or verified private security contact exists; neither is invented.

## Documentation deliverables

README was redesigned with an original accessible SVG logo, factual platform/status badges, quick start, feature boundaries, account walkthrough, Mermaid architecture, stack, security, test status, troubleshooting and roadmap. No fake hero screenshot, gallery, animation, CI badge, download link or license claim was added. The CLI's detailed reference was preserved in [CLI_GUIDE.md](CLI_GUIDE.md).

Created/updated: README, CONTRIBUTING, SECURITY, DESKTOP, IPC, MULTI_ACCOUNT, USER_GUIDE, ARCHITECTURE, CHAT_API, UI_VALIDATION and this report; screenshot/demo directories exist for future genuine captures. Static documentation checks passed for local links/images and HTML image alt text; missing CHAT_API/account/UI links encountered during implementation were resolved. GitHub rendering, remote badges/profile metadata, Mermaid layout and mobile visual inspection remain unverified. Repository identity matches the supplied Git remote; no email, legal identity or license is inferred.

Principal code additions: `accounts.py`, `chat_features.py`, `chat_store.py`, `WorkspaceViews.swift`, native screenshot test target/control probe, profile/chat/security/subprocess tests, screenshot/build/documentation/benchmark scripts. Existing IPC, model, views, build settings, dependency metadata and docs were extended rather than replacing the backend/CLI.

## Launch and reproduce

Quit the CLI first:

```sh
cd ~/Desktop/TelegramManager
./macos/build.sh Debug
open macos/build/Build/Products/Debug/TelegramManager.app
```

Release build: `./macos/build.sh Release`; product at `macos/build/Build/Products/Release/TelegramManager.app`. CLI remains `python3 main.py`.

Verification commands:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py src tests scripts
./macos/test.sh
./macos/screenshots.sh light standard
./macos/screenshots.sh dark compact
.venv/bin/python scripts/check_docs.py
.venv/bin/python scripts/benchmark_cache.py
```

Use an unlocked graphical login session for screenshot tests and normal launch. The development `.app` is not currently a verified distributable package for another Mac. See [DESKTOP.md](DESKTOP.md) for exact remaining packaging work.


## Critical stability repair and current acceptance boundary

The user reports that the native application opens on their Mac. This is user-observed launch evidence, not a graphical launch or screenshot independently observed by this agent.

Controlled investigation established lifecycle defects: requests implicitly called `start()`, shutdown dropped the managed process reference before awaiting exit, unused pipe ends/handle inheritance weakened EOF detection, and termination could outrun a buffered typed startup error. These paths were fixed. A single workspace replaces multi-window workspace creation; the app-scoped model remains shared with Settings. Concurrent start/shutdown and repeated reconnect are covered with synthetic native processes. Only an owned child can be terminated by recovery; unrelated processes are never signaled.

Python parent-exit monitoring is event-driven kqueue on macOS, with a one-second own-PPID fallback if process filters are unavailable. Tests deliberately retained an inherited writer, killed the fixture launcher, and verified its backend stopped/released locks. Real offline tests cover sole/second backends, CLI-style competing ownership, child crash/restart, active-profile collisions and switching without leaking locks. Account session/cache/draft/approval/history/settings isolation remains covered. Startup does not remove any lock/session/database file.

**The exact holder behind the user's reported lock conflict remains unknown.** The environment denied safe PID/PPID/comm-only `ps` inspection. No self-double-lock was reproduced in the Python account-switch path. Genuine CLI ownership, another app build and an old orphan remain possible; the report does not select one without evidence. [BACKEND_LIFECYCLE.md](BACKEND_LIFECYCLE.md) documents safe identification and recovery.

Recovery now has explicit connected/connecting/disconnected/instance-conflict/authentication/interruption/cooldown states, one-shot Retry Connection, local sanitized diagnostics and Account Manager. Diagnostics does not start a process. Validation errors do not become lock errors. Transport errors retain their typed category and do not trigger implicit spawn/retry.

UI source audit fixed a concrete responsive-layout issue: old pane minimum widths plus sidebar exceeded the 980-point minimum window. The composer now stacks under narrower content widths, with useful editor/review bounds. Filter controls scroll when constrained. Recovery is prominent; blank account names cannot be added; offline account mutations are disabled; empty conversation/draft/account/activity/history/destination screens provide guidance rather than invented records. Cached group details remain inspectable locally if the backend fails. No screenshot-based defect fix is claimed.

The real fixture XCUITest attempt compiled but stopped before assertions at testmanagerd/control error 159 (sandbox restriction), exiting 133. Result: `macos/build/UI-light-20261028-174046.xcresult`. No screenshots were captured/inspected, and no graphical tests are reported passed. Native unit/integration and standalone Swift transport smoke tests pass; the latter exercises 12 concurrent requests, Unicode, cancellation/timeouts, malformed frames, closed input/SIGPIPE, output EOF and shutdown. A separate abrupt-parent-exit native probe verified child EOF and exit.

Manual acceptance still required: normal GUI-to-backend connection on the user's installation after the actual owner is closed; window/menu behavior; account switching/reconnect using live authorized sessions; visual light/dark/size matrix; accessibility/keyboard-only workflows; profile logout with explicit authorization. No live authentication, discovery or message sending occurred here. Ruff remains unavailable. Existing code signing configuration was preserved; testmanagerd failure was not treated as a reason to weaken signing.

Principal stability files modified: native `BackendClient.swift`, `TelegramManagerApp.swift`, `AppModel.swift`, Root/Composer/Groups/Workspace views, native tests, UI tests, transport smoke tool, Python `ipc.py`, and required documentation. Added `parent_lifecycle.py`, `test_backend_lifecycle.py`, `ParentDeathProbe.swift`, and `BACKEND_LIFECYCLE.md`. Current test counts above supersede the V2 baseline; final Debug/Release build and signature audits are recorded after source freeze.

Final stability artifacts: Debug and Release builds both succeeded after source freeze; both strict deep signature checks passed. Both bundles contain the current Python source snapshot and zero private-artifact filename candidates. Final native test run: 34 passed, zero failures (7.682 seconds); final Python run: 216 passed, 59 subtests (4.31 seconds). Documentation and shell syntax checks passed. No graphical or live-Telegram claim is inferred from these results.
