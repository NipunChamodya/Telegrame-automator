# Full UI audit and repair — V3

Date: 2026-10-28. This report distinguishes source inspection, executed offline tests, builds, graphical assertions and live Telegram acceptance. **No visual acceptance is inferred from compilation.** Existing accounts, session paths, databases, Keychain namespaces, preferences and backend safety contracts were retained.

## Scope and confirmed structural causes

Every SwiftUI view under `macos/TelegramManager/Views/`, the application scene, AppModel navigation/loading/account state, existing fixtures, tests and backend contracts were inspected. The starting version already had a full-height Chats layout, but the shared window architecture still had avoidable sources of layout variability:

1. The root `NavigationSplitView` left visibility to automatic adaptation. It had no explicit persistent-sidebar policy. A custom sidebar header/account panel lived in that adaptive column. Pages did not independently create sidebars; the issue was the shared adaptive container and its page-dependent inputs.
2. Groups and Destinations used page-level `.searchable`. Search therefore contributed to native navigation/toolbar placement while the detail title and toolbar also changed with the selected page. This coupled content search to window chrome.
3. Group details used `.inspector`, introducing another adaptive column into that layout. Closing/opening pages changed the window's column configuration as well as its content.
4. The selected-conversation task sequenced previous draft save → new draft read → history inside one `do/catch`. A failed draft operation aborted the task before any history request. This is a concrete, reproduced non-graphical cause of a blank conversation.
5. History errors were only transient alerts; contact and several cached-page read errors were silently discarded through `try?`. Stale history failures lacked the successful-response scope checks. Empty states could therefore conceal a real read failure.
6. Delayed draft hydration could replace a deliberately emptied editor. The wide managed composer had nonscrolling panes whose content could exceed available height. Page headers had no explicit intrinsic vertical sizing policy.

Items 1–3 are confirmed source/configuration risks, **not a claim to have reproduced the user's exact pixel-level transition**. The managed host cannot currently launch/test the graphical application. The old BrokenPipeError and real-world competing lock owner are not newly attributed by this audit.

## Shared-shell repair

`RootView` now owns one native `HSplitView`: a persistent sidebar constrained to 220–280 points and one expanding content region. macOS no longer automatically collapses the application navigation column. Chats retains adaptive list/detail presentation inside that content region; it does not create another application sidebar. Advanced tools remain selected through the same AppModel and have a shared Back to Advanced Workspace action.

The application uses an explicit native titlebar/unified toolbar. One root toolbar owns section context and connection diagnostics/connect actions. Page search controls stay inside page content. No `ignoresSafeArea`, traffic-light offsets, transparent-titlebar hacks, arbitrary top clearance padding or competing page toolbars were added. Group details use a native sheet instead of changing the application column configuration.

Navigation restoration uses SceneStorage for the screen identifier only and runs once per root lifetime. It restores local state/filter scope without connecting, discovering, inspecting, approving or sending. Unknown stored identifiers fall back to the default screen. The shared AppModel/backend process ownership remains unchanged; opening preferences does not create another backend.

## Screen-by-screen source audit

All rows below mean source and relevant mocked/native state inspection. **Actual screenshots and graphical interaction results remain blocked for every screen.**

| Screen | Findings / repair / retained behavior |
| --- | --- |
| Chats | Persistent outer shell; independently expanding list/history; search, scoped type menu, selection, unread/time metadata and anchored paging retained; inline cached-read errors added |
| Selected conversation | Actual supported history no longer depends on successful draft I/O; centered loading/error/empty states; scoped retry and stale-error guards; older-page cap/order retained; active account shown in header |
| Groups conversations | Group/supergroup-only filter options; cached query/selection scope retained; supported history uses the same repaired conversation path |
| Channels | Cached identity list and explicit refresh retained; unsupported sponsored-content flow remains explained/gated, never replaced with fabricated messages |
| Contacts | Prominent identified Refresh Contacts button, inline loader/error/retry, actionable empty state, cached search/paging and profile sheet; no macOS address-book access |
| Saved Messages | Same repaired detail/history; existing account verification and personal-preview workflow retained; fixture route remains offline |
| Advanced Workspace | One shared shell; existing tool cards and shared toolbar breadcrumb/back action; no page-owned application sidebar |
| Dashboard | Native scroll container, real counts, bounded activity and quick actions retained; header/panels remain inside window content |
| Group Management / Discovery | Inline search and explicit Discover button; existing filters, cache pagination and selected-row inspector; scoped stale-query checks and cached loading/error feedback |
| Permissions | Same group layout; bounded inspection selection/limit/cancel/cooldown retained; no automatic inspection or `all` send authorization |
| Group inspector | Scrollable native sheet avoids third-column collapse; current metadata/labels and explicit approval confirmation retained |
| Managed Composer | Wide panes independently scroll; narrow layout has one outer scrolling owner; editor has an explicit usable viewport; full preview and one-send confirmation unchanged |
| Drafts | Shared page header, cached read status, bounded list and account-specific open/delete actions retained |
| Approved Destinations | Search moved below heading inside content; centered empty state with Browse Groups directly beneath explanation; approvals/revocation unchanged; read errors preserve cached rows |
| Delivery History | Header/filters/table and empty state retained inside shell; cached loader/error/retry; no automatic retry of uncertain sends |
| Activity | Shared header/search controls; filters horizontally accessible at constrained widths; bounded session-only timeline and timestamps retained |
| Message Actions | Always inside persistent shell; expanding ledger and actionable Open Chats empty state; actual edit/delete entry points remain conversation context menus |
| Accounts / switcher | Shared header; actual profile identity/status; separately confirmed disconnect/logout/remove retained; fixture-only account switching tests cannot launch Python |
| Settings | Native grouped Form and shared root toolbar; Light/Dark/System preferences and existing backing settings retained |
| Authentication / code / 2FA | Existing secure sheets/validation, bounded fields and cancellation inspected; no authentication backend rewrite or secret logging |
| Profile / folders / image / action sheets | Existing bounded/scrollable native sheets inspected; no unsupported avatar, synchronized-folder or media claims added |
| Recovery / diagnostics / operation progress | Shared process/account status remains visible; bounded explicit retry, sanitized diagnostics and cancellation retained; no endless process restart |

## Async and draft correctness

History and draft failures are independent. A failed previous write retains transient draft recovery keyed by profile, numeric account and conversation; a successful write retires it. The buffer is bounded to 100 entries of at most 4096 UTF-16 units each, refuses further dirty transitions when full, and is **in-memory recovery, not durable crash protection**. Deliberate draft/profile removal retires the matching entries. No failed draft save is reported as persisted.

Draft hydration checks the editor revision, including deliberate deletion to empty text. Pending user edits are autosaved after the cached baseline arrives. Cached reads and history responses/errors are account/revision scoped; stale results do not replace a later selection/query. Existing data remains visible when a refresh fails. No new polling, per-row network requests, media downloads, send retries or background scans were introduced.

## Changed files for this audit

- `macos/TelegramManager/App/TelegramManagerApp.swift`: explicit native titlebar/unified toolbar.
- `Views/RootView.swift`: stable persistent shell, root toolbar, once-only local navigation restoration, accessibility identifiers.
- `Views/DesignSystem.swift`: intrinsic page headers, content controls, loading/error/cached-status components.
- `Views/WorkspaceViews.swift`: account/draft headers, conversation loading/error handling, scoped filters, inline cache status.
- `Views/GroupsView.swift`: inline search/Discover, cached status, native inspector sheet.
- `Views/ComposerView.swift`: scrolling wide panes, bounded editor viewport, inline destination search/status, history cached status.
- `Views/ClientFeaturesView.swift`: visible refresh, actionable contact empty/loading/error states.
- `Views/ActivityTimeline.swift`: shared search/content controls.
- `Views/MessageActionsView.swift`: full-height content, read status and meaningful Chats action.
- `ViewModels/AppModel.swift`: local restoration, independent draft/history paths, scoped cached reads/errors, transient draft recovery and DEBUG-only safe fixtures.
- `TelegramManagerTests/ChatPresentationTests.swift`: regression cases for the above state paths.
- `TelegramManagerUITests/ScreenshotTests.swift`: all-section shell/clearance cycles, resize, minimize/restore, fixture account switch/draft, Contacts refresh and loading/error screenshots.
- README and validation/UI documents; this report. Python backend/runtime and SQLite schema are unchanged in this repair milestone.

## Automated validation and graphical evidence

| Final gate | Actual result |
| --- | --- |
| Python / IPC / backend regressions | **299 tests + 133 subtests passed**, 6.67 s; zero failures |
| Native XCTest / navigation-state / async regressions | **86 tests passed**, 13.944 s; zero failures |
| UI-test target | **14 methods compile**; no graphical assertions executed |
| Debug / Release builds | **Both passed on final source**, strict deep signatures passed; 29 bundled Python modules match source in each product |
| Graphical run | **Blocked:** testmanagerd lookup error 159, explicit Sandbox restriction; command exit 133 |
| Fixture direct launch / open | Exit -6 / Launch Services -10827; no window observed |
| Screenshots / visual review | **0 / 0** |
| Python syntax / whitespace / documentation links | Passed; Ruff unavailable, not installed |
| Live Telegram operations | Not run; no sends, edits, logout or destructive real-account tests |

Static documentation check: 23 documents and 121 local links/images resolve; HTML image alt text and diff whitespace pass. This does not validate GitHub rendering or visual layout.

Latest graphical attempt: ignored `macos/build/UI-light-20261028-204439.xcresult`; temporary log `/private/tmp/tgm-full-ui-graphical.log`. It fails during runner bootstrap before any app navigation. Light/Dark, sizes, fullscreen and manual accessibility acceptance remain unverified. Repeating all appearance combinations under the same bootstrap restriction would not produce visual evidence.

Final executed counts/build results are recorded in [VALIDATION.md](VALIDATION.md). Regression tests use synthetic IPC subprocesses and temporary storage; no live Telegram messages or destructive account operations occur. Initial compilation exposed excessive root view type-checking complexity; extracting sidebar/content/toolbar components fixed it without suppressing checks or deleting tests.

Prepared graphical assertions check the sidebar after every primary and Advanced Workspace navigation cycle, traffic-light clearance using native close-button geometry, list/footer dimensions, selection/search/pagination, resizing, minimize/restore, safe mock account switching/draft preservation, Contacts refresh and explicit history loading/error states. The fixture backend transport refuses to start Python. Synthetic images are decoder/viewer fixtures, not screenshots.

**Screenshots captured: 0. Screenshots inspected: 0.** No fake replacement screenshots, fabricated visual comparison or claim that all visual defects are gone is made. On this managed host, graphical acceptance remains separate from native unit execution. [UI_VALIDATION.md](UI_VALIDATION.md) records the latest actual runner/launch attempt and exact local commands.

## Local capture and acceptance

From an unlocked graphical Terminal session, quit the real application before fixture tests:

```sh
cd ~/Desktop/TelegramManager
./macos/test.sh
for appearance in light dark; do
  for size in compact standard large; do
    ./macos/screenshots.sh "$appearance" "$size" || exit 1
  done
done
```

The script launches the actual DEBUG app using only synthetic fixtures, exports real successful XCTest attachments into `docs/assets/screenshots/<appearance>/<size>/`, and preserves `.xcresult` evidence. It does not generate UI artwork. Do not capture real account content. Manually test fullscreen, VoiceOver, high contrast, reduced motion and actual keyboard/scroll feel using the fixture-only launch procedure in [UI_VALIDATION.md](UI_VALIDATION.md).

For every accepted image record actual dimensions/appearance/screen/filename, sidebar/traffic-light/header clearance, clipping, selected state, scrolling, defects and corrected recapture. Screenshot availability alone is not proof of accessibility or live Telegram correctness. A failure must be fixed and recaptured before marking the relevant acceptance item verified.

## Remaining limits

No numerical UI CPU/RAM/FPS/startup improvement is claimed. This repair removes automatic application-sidebar collapse and page-owned window search/inspector coupling, but it cannot certify pixel-level behavior without graphical execution. Live Telegram history, network reconnection and real account switching were not exercised. Existing channel/bot content gates, media/client-feature limitations and development-runtime distribution constraints remain. Original sessions/databases/settings were not reset or converted.
