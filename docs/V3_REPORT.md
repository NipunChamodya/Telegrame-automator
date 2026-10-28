# V3 feature-milestone delivery report — 0.4.0 development preview

Follow-up: [FULL_UI_AUDIT.md](FULL_UI_AUDIT.md) documents the subsequent shared-shell repair and latest validation (86 native tests). Counts below describe the earlier feature milestone.

This upgrade implements independently testable client milestones on the existing backend. It **does not complete every feature in the V3 vision**. See the [current capability matrix](TELEGRAM_REFERENCE_STUDY.md) for supported, partial and unsupported features, and [validation](VALIDATION.md) for actual evidence.

## What changed

| Area | Implementation |
| --- | --- |
| Product/navigation | Unofficial Telegram Manager; Chats first; Contacts, group conversations, channel identities, Saved Messages, Advanced Workspace, Accounts and Settings |
| Messaging layout | Existing adaptive full-height list/detail retained; message presentation now supports verified formatting, replies, edited/forwarded/reaction/pin metadata, scope-specific controls and recovery states |
| Connected updates | One coordinated account/generation-scoped Telethon adapter; bounded queue/projection, stream sequence checks, duplicate/stale event guards and explicit bounded snapshot recovery |
| Normal read/typing | Viewport/focus-based incoming read acknowledgement; focused user edits produce throttled typing; no hidden-read or fabricated presence feature |
| Actions | Own personal plaintext edit and Delete for Me, exact one-use confirmation, fresh message/peer/ownership/version checks, separate durable action ledger |
| Client reads | Cached contacts with explicit refresh, verified profile metadata, read-only folder definitions; no implied folder membership synchronization |
| Media | Explicit JPEG/PNG preview, four private files × at most 8 MiB, bounded off-main ImageIO thumbnail, invalidation/release/owned-index recovery |
| Security | Fail-closed protected/TTL/unknown message handling; channels/bots gated pending sponsored-message integration; wrong-peer returned message checks; strict additive IPC |
| Compatibility | Original CLI, legacy data/session paths, account bindings, locks, Keychain namespaces, existing ledgers/cooldowns/drafts/approvals retained |

The architecture remains SwiftUI → actor-owned local stdio transport → existing Python/Telethon service. No second Telegram implementation, HTTP listener, Electron wrapper or automatic TDLib migration was introduced. [Architecture decision](CLIENT_ARCHITECTURE_DECISION.md).

## Defects and gaps established by inspection/tests

- Receiving Telethon transport updates alone did not update native conversation state. There was no application-level event projection; explicit history refresh was required. The new scoped adapter/native projection bridges that gap.
- Channel/bot content could previously be returned without a complete sponsored-message flow. Current content routes and previews fail closed instead of claiming an incomplete fetch is compliant.
- Non-channel message-ID lookup can return a different peer's message. New content helpers verify actual peer and message ID before reply/action/media access, including direct IPC calls.
- Protected/expiring/unknown message types needed consistent boundaries across history, live updates, media and previews. One shared policy now applies; accepted edits/deletions/gaps invalidate projected and cached content, including pending downloads.
- Late snapshots, deleted targets and account changes can race in-flight requests. Stream/revision/context guards prevent stale content or confirmation reuse. Pending action/send outcomes are durable and never replayed automatically.
- Contact/folder caches require strict DTO allowlists and independent account keys; unknown cached nested data cannot become a credential leak.

The previous Chats compression/layout repair and lifecycle locking fixes predate this milestone; they were retained rather than rebuilt. The exact original real-world BrokenPipeError and competing-process owner remain historically unproven without the original traceback/process access. This report does not invent a new attribution.

## Storage changes

Only additive tables: `conversation_operations`, `contact_cache`, `telegram_folder_cache`. Original group/delivery/cooldown uniqueness and records remain authoritative. The action ledger stores hashes/status/context rather than full action bodies. Image previews use a separate private account directory and a validated ownership index; unknown files are preserved. No user session or database was reset, replaced, converted or bundled.

## Files

New Python modules: `content_policy.py`, `message_projection.py`, `update_pipeline.py`, `conversation_actions.py`, `client_features.py`, `media_preview.py` under `src/telegram_manager/`. Existing `ipc.py`, `chat_features.py`, `chat_store.py` integrate these contracts; package metadata moves to 0.4.0.

New native components under `macos/TelegramManager/`: `Models/LiveProjection.swift`, `Models/MessagePresentation.swift`, `Models/ClientFeatures.swift`, `Services/ImagePreviewReader.swift`, `Views/MessageActionsView.swift`, `Views/ClientFeaturesView.swift`, `Views/ImagePreviewView.swift`. Existing app/model/root/workspace/authentication/protocol/project/resources integrate the features and original icon/unofficial naming. No storage/bundle identifier was renamed.

New Python regression files: `test_update_pipeline.py`, `test_message_projection.py`, `test_client_features.py`, `test_v3_security.py`, `test_v3_actions_security.py`, `test_v3_media_security.py`; existing chat tests extended. Native tests add `LiveProjectionTests.swift`, `ClientFeaturesTests.swift`, extend model/presentation tests and XCUITest screenshot scenarios.

Documentation: README, SECURITY, architecture, IPC/chat contracts, desktop/user guide, validation/UI validation; new reference study, feasibility audit, architecture decision, milestone/test plans, message-action/client-feature contracts and this report. Existing contribution instructions remain valid. The README's original SVG logo palette now matches the distinct purple native direction; no fake screenshot assets were added.

## Verification

- **Python:** 299 tests + 133 subtests passed; syntax passed.
- **Native:** 76 XCTest tests passed; nine graphical test methods compiled.
- **Builds:** Debug and Release succeeded; strict signatures passed; all 29 bundled Python modules in each match source; zero private session/database/env filename candidates in bundle Resources.
- **Graphical testing:** blocked by testmanagerd error 159; direct fixture launch exit -6 / Launch Services -10827. Zero captured/inspected screenshots. No visual perfection or launch success claim.
- **Ruff:** unavailable, not run. Static documentation links/alt text and diff whitespace pass. No GitHub/browser rendering claim.
- **Live Telegram:** not run. Tests use mocked network/temporary storage. No live sending, edits, deletion, logout or private media download.

A synthetic 1,000-dialog/100-page SQLite benchmark measured median 9.055 ms, p95 10.512 ms with tracemalloc enabled. This is an isolated cached-read measurement, not a before/after speedup or GUI/live benchmark. Queues, loaded histories and cache bounds reduce unbounded work; no idle-CPU, RAM or launch-time result is invented.

## Not complete

Channel/bot content and sponsored-message workflow; calling; secret chats; stories; full rich media/player/upload support; forwarding/reaction/pin mutations; group/media/formatted-text editing; delete-for-everyone; complete topics; cloud drafts; synchronized folder membership/editing; avatar loading; complete incoming notifications; unified global search; full accessibility/graphical/live acceptance; portable distribution. Detailed API feasibility is in [TELEGRAM_FEATURE_FEASIBILITY.md](TELEGRAM_FEATURE_FEASIBILITY.md).

The build still depends on this checkout's Python venv. It cannot yet be presented as a tested standalone installer for another Mac. An embedded runtime/dependency packaging, project licensing decision/notices, Developer ID/notarization and clean-Mac verification remain.

## Launch locally

```sh
cd ~/Desktop/TelegramManager
./macos/build.sh Debug
open macos/build/Build/Products/Debug/TelegramManager.app
```

Quit a competing CLI/backend normally first; never remove a held lock or delete session/database files. The app owns its backend subprocess. For Release use `./macos/build.sh Release` and the corresponding Release product. For CLI maintenance, close the GUI and run `python3 main.py`.

For genuine screenshot capture on an unlocked graphical Mac, run `./macos/screenshots.sh light standard` and repeat Dark/compact/large using [UI_VALIDATION.md](UI_VALIDATION.md). Review actual images before publication; do not capture personal credentials or private conversations. Live acceptance is a separate explicitly controlled step, never an automatic test send.
