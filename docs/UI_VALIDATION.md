# Native UI validation

The native application is a SwiftUI macOS application, with an AppKit subprocess and file-panel integration. Debug and Release builds use a real Xcode application target. `macos/screenshots.sh` drives the real application with XCUITest; it does not draw replacement screenshots.

## Reproduce

From an unlocked graphical macOS login session with Xcode installed:

```sh
./macos/test.sh
./macos/build.sh Debug
./macos/build.sh Release
./macos/screenshots.sh light
./macos/screenshots.sh dark
```

Grant the test runner any macOS Automation/Accessibility permissions requested by the OS. UI tests use synthetic account, Unicode group, conversation, and draft data. They set `TGM_TEST_MODE=1`, `TGM_UI_FIXTURE=1`, and `TGM_NO_AUTO_CONNECT=1`, and an isolated temporary storage path. The DEBUG backend transport explicitly refuses to launch in fixture mode. Navigation tests cannot authenticate, read the real session, or send a message. Fixtures are not evidence of live Telegram functionality.

The test visits Dashboard, Chats, Groups, Permissions, Composer, Drafts, Destinations, History, Activity, Accounts, and Settings, attaching actual window screenshots to the `.xcresult`. The script exports successful attachments into `docs/assets/screenshots/light` or `dark`. The application opens at 1260 × 820 points (minimum 980 × 640); tests fix English locale. Inspect narrow-window layout and accessibility manually as a separate check. Screenshot mode must be run in Debug; it is excluded from Release.

## Evidence and launch diagnosis

The earlier build scripts disabled code signing, leaving a linker-only signature without an Info.plist binding or sealed resources. This caused strict code-signature verification to fail. Build and test scripts now request Xcode ad-hoc signing. Verify each artifact with:

```sh
codesign --verify --deep --strict --verbose=2 macos/build/Build/Products/Debug/TelegramManager.app
```

In the managed development environment, direct application launch aborted in macOS `_RegisterApplication` / `_NSInitializeAppContext` before application views or Python startup. LaunchServices returned -10827. A separately compiled, ad-hoc signed minimal SwiftUI WindowGroup application also aborted; a command-line `NSApplication.shared` probe initialized successfully. Therefore this is specifically a graphical application-registration limitation observed in this execution context, rather than evidence of a successful visual launch. No screenshots have been fabricated. An interactive login-session run is still required to validate appearance, input, window resizing, and VoiceOver.

Direct XCTest executes the model and IPC tests without the graphical test manager; `macos/test.sh` documents that fallback. XCUITest requires the OS test-manager service and a graphical session. If those services reject the runner, retain the result/log as a failed validation attempt and do not populate screenshot directories with illustrative artwork.

## Manual safety checks

1. Confirm account identity in Accounts before switching. Confirm managed and conversation drafts remain isolated.
2. Disconnect preserves local records. Logout revokes only the selected session; local history remains. Removing a nonlegacy profile permanently removes that profile’s local records after the exact typed phrase; it does not perform server logout. Original installation removal is blocked.
3. Select one personal conversation and verify a preview contains the exact account/destination/text. Change text or account and confirm the preview disappears. Never send in screenshot or automated tests.
4. Managed group sending still requires explicit approval and fresh permissions through the existing Composer.
5. Confirm cooldown cancellation, backend termination, empty lists, Unicode titles, dark mode, and native file-panel failures produce understandable states.

A sealed ad-hoc development application is not a distributable release: it still uses the checkout virtual environment when a packaged Python runtime is absent. Developer ID signing, notarization, a relocatable embedded runtime, and installation tests on another Mac remain outstanding.

## V2 screenshot matrix

`./macos/screenshots.sh light standard` supports `light|dark` and `compact|standard|large`. Sizes are 980×640, 1260×820, and 1500×960 points. Run the six combinations explicitly; the default avoids an unbounded screenshot matrix. Export folders include appearance and size. Authentication and error states are separate launches, still fixture-only.

The following expected attachment names are **BLOCKED / not captured** in this managed environment. The XCUITest target compiled, but execution failed at `com.apple.testmanagerd.control` lookup with error 159 (sandbox restriction). The initial failed result is `macos/build/UI-light-20261028-171712.xcresult`. An interactive user-session run must supply actual evidence.

| Screen/state | Expected attachment name | Current evidence |
|---|---|---|
| Dashboard | fixture-dashboard | BLOCKED |
| Conversations and selected history | fixture-chats | BLOCKED |
| Groups | fixture-groups | BLOCKED |
| Permission inspections | fixture-permissions | BLOCKED |
| Managed composer | fixture-composer | BLOCKED |
| Drafts | fixture-drafts | BLOCKED |
| Approved destinations | fixture-destinations | BLOCKED |
| Delivery history | fixture-history | BLOCKED |
| Activity | fixture-activity | BLOCKED |
| Accounts / add-account form | fixture-accounts | BLOCKED |
| Settings | fixture-settings | BLOCKED |
| Welcome / API credential setup | fixture-welcome-api-setup | BLOCKED |
| Country prefix and phone input | fixture-phone-entry | BLOCKED |
| Verification code | fixture-verification-code | BLOCKED |
| Two-step verification | fixture-two-step-verification | BLOCKED |
| Exact account binding | fixture-account-binding | BLOCKED |
| Group detail inspector | fixture-group-inspector | BLOCKED |
| Empty conversation list | fixture-empty-conversations | BLOCKED |
| Backend unavailable error | fixture-backend-error | BLOCKED |
| Account switcher menu | fixture-account-switcher | BLOCKED |

The independent registration control source is retained at `macos/Tools/NativeLaunchProbe.swift`. It contains only a SwiftUI WindowGroup and a Text view; it does not import the application or backend. Compile with a writable module cache, put the executable in a minimal APPL bundle, sign ad hoc, and launch from the same execution context when comparing registration failures. Its failure does not establish whether a normal Finder launch on an unlocked desktop will work.

## Recovery and compact layout checks

The current recovery panel displays the model's actual connection state and explanation, with separate Retry Connection, Manage Accounts, and Connection Diagnostics actions. Diagnostics opens a selectable, sanitized local summary without requiring a Telegram request. Retry is unavailable while connecting or another operation owns the service. Cached browsing remains available when disconnected.

The managed composer uses a side-by-side editor/review at content widths of at least 850 points, and a vertically scrolling layout below that width. This addresses the previous fixed minimum pane widths exceeding the 980-point minimum window once the sidebar was included. The editor has a 200-point minimum height, and the review message has bounded scrolling. Group filters permit horizontal scrolling instead of forcing the window wider. These are code-level layout safeguards; actual visual acceptance remains blocked until graphical tests execute.

Two additional fixture-only UI tests assert recovery/diagnostics navigation and compact composer behavior without an approved destination. They never click Send or connect to Telegram. Compilation and execution results must be reported independently: an unexecuted assertion is not a passing UI test.

Recovery-layout validation rerun: `./macos/build.sh Debug` succeeded with the recovery panel, diagnostics sheet and adaptive composer. `./macos/screenshots.sh light compact` compiled the updated UI test target but failed before executing assertions: `com.apple.testmanagerd.control` lookup error 159, “Sandbox restriction”; xcodebuild exited 133 after reporting TEST FAILED. Evidence is `macos/build/UI-light-20261028-174046.xcresult` and the development log `/private/tmp/tgm-recovery-ui-test.log`. No screenshots or passing graphical assertions were produced. Recovery/diagnostics and compact-composer screenshots remain blocked alongside the matrix above.

## Screen-by-screen source audit (not visual acceptance)

| Screen | Source review and implemented safeguards | Actual visual result |
| --- | --- | --- |
| Dashboard | Real account/cache counts, prominent recovery, actual recent activity and explicit quick actions | BLOCKED |
| Chats | Cached search/type filter, bounded pages, explicit refresh, informative empty list | BLOCKED |
| Conversation | Bounded history, empty overlay, Unicode text selection, explicit remote search and busy-safe controls | BLOCKED |
| Groups | Search/filter/sort, dense rows, constrained filter scrolling, pagination, cached details when backend is offline | BLOCKED |
| Group inspector | Real reasons/freshness, explicit approval and inspection; no automatic send | BLOCKED |
| Permissions | Bounded selection, count/progress/cancel, connected/busy gates; no implicit all | BLOCKED |
| Composer | Adaptive stacked/side-by-side layout, useful editor height, account/destination, exact confirmation | BLOCKED |
| Drafts | Account-specific persistence and deletion, useful empty guidance | BLOCKED |
| Destinations | Explicit approval/revocation and actionable empty state | BLOCKED |
| History | Actual ledger table/details, no fabricated records, uncertain-result explanation | BLOCKED |
| Activity | Real in-session activity, empty-list overlay rather than detached filler text | BLOCKED |
| Accounts | Separate lifecycle actions, blank-label validation, offline mutation controls disabled | BLOCKED |
| Settings | Native form/file panels, explicit backup/export, secret-free status | BLOCKED |
| Login | Secret inputs; Telegram delivery explanation and backend format validation | BLOCKED |
| Add Account | Explicit labeled profile creation; no background discovery | BLOCKED |
| Verification code | Hidden entry, explicit submit/cancel; no codes in diagnostics | BLOCKED |
| Two-step verification | Hidden by default, optional visibility, explicit submit/cancel | BLOCKED |
| Disconnect confirmation | Distinct network-disconnect wording, preserved records | BLOCKED |
| Logout confirmation | Exact account-specific phrase and remote-revocation warning | BLOCKED |
| Error/recovery | Typed state, one explicit retry, local diagnostics and Account Manager | BLOCKED |

The app now uses one workspace `Window`; Settings shares its model/transport. Command-N changes composition screen rather than creating another workspace backend. Repeated Quit waits for the initial cleanup. Unit/transport tests verify idempotent start and reconnect; actual menu/window and keyboard navigation still require local UI execution.

Manual follow-up must include long names, Sinhala/Tamil/emoji, populated history, destructive confirmation sheets using disposable profiles, Light/Dark, compact/standard/large/fullscreen, high contrast, reduced motion, text scaling and VoiceOver. Existing fixture screenshot automation does not establish complete coverage of every confirmation/accessibility setting. No screenshot filename is listed as captured when none exists.

## Native presentation repairs

Source inspection found fixed-width split panes and intrinsic-height stacks inside an expanding root frame. The root frame's default centered alignment did not itself make each screen consume the available height. Chats now uses a finite GeometryReader, an explicitly expanding native conversation List and message-history region, with a compact single-pane/back arrangement. The existing split-pane minimum widths and the composer editor/review widths are replaced by width-dependent presentation. These findings explain the constraints changed in code; they are not observations of rendered screenshots in this restricted environment.

The sidebar now groups navigation into Overview, Messaging, Groups, Records and App. Its account menu uses a native account symbol, actual profile identity and connection status; Add, Manage, Disconnect and Logout open Accounts, retaining its separate confirmation workflow. Shared PageHeader, SectionCard, EmptyStateView, AccountIdentityView, SearchToolbar, FilterMenu and StatusBadge components use native semantic styles. Destinations and History fill the detail region from the top leading edge, with empty-state actions inside the corresponding state rather than detached below it.

Delivery History filters and sorts only the latest loaded ledger page (at most 100 records), with a displayed loaded count. Search, status and ordering controls do not send Telegram requests or alter delivery records. Activity is a separate bounded, typed, session-only operation timeline; it is not the persistent delivery ledger and contains no message-body field.

Integrated Debug build succeeded, and `./macos/test.sh` executed **44 native tests with zero failures** after these repairs. These tests include fixture presentation/state, activity models and IPC transport. They do not establish visual appearance. New XCUITest assertions cover conversation-list geometry, cached search/pagination/selection, integrated empty-state actions, history controls and composer confirmation safety using synthetic data only.

The post-repair screenshot run `./macos/screenshots.sh light standard` compiled the expanded UI target but again failed before executing tests with `com.apple.testmanagerd.control` lookup error 159 (“Sandbox restriction”), followed by xcodebuild exit 133. Result: `macos/build/UI-light-20261028-185759.xcresult`; log: `/private/tmp/tgm-presentation-ui-tests.log`. No actual window screenshots or passing graphical geometry assertions were produced. All graphical and accessibility acceptance checks remain to be run in an unlocked interactive macOS session.

## Responsive workspace repair — current evidence

Source changes now address the reported Chats compression with an explicit full-height finite layout, independent native scrolling and footer pagination. Content at least 800 points wide uses a 300–360 point conversation list and remaining-width detail; narrower content shows one pane with Back navigation. Search/actions no longer occupy several full toolbar rows. Rows have stable IDs, native selection, Unicode titles/previews, timestamps, unread badges and safe SF Symbol placeholders. No fixed large list height is used.

History and Destinations have top-leading full-height pages, shared headers, native local filters and centered empty states with their actions inside the state. The larger account switcher and grouped sidebar retain existing lifecycle confirmations. Activity is a typed, account-context timeline of up to 100 session-only events, with status/type/search, timestamps, expandable details, real available counts and a running indicator. It does not persist message content or replace the delivery ledger.

**Actual results:** 44 native model/transport/presentation tests passed; 216 Python tests and 59 subtests passed. The final expanded XCUITest target compiled, but graphical execution failed before any assertion with testmanagerd/control error 159 (sandbox restriction), exit 133. Result: `macos/build/UI-light-20261028-190305.xcresult`; log `/private/tmp/tgm-responsive-ui-final.log`. A separate direct launch of the safe Chats fixture exited -6 and the own-PID window probe found zero windows. No screenshot was captured, inspected, substituted or overwritten.

The UI target now prepares these **16 real-window capture states**, all currently BLOCKED here:

| Requested state | Expected attachment | Actual capture |
| --- | --- | --- |
| Dashboard | fixture-dashboard | None |
| Chats populated | fixture-chats-populated | None |
| Chats empty | fixture-chats-empty | None |
| Conversation selected | fixture-conversation-selected | None |
| Activity populated | fixture-activity-populated | None |
| Activity empty | fixture-activity-empty | None |
| History populated | fixture-history-populated | None |
| History empty | fixture-history-empty | None |
| Destinations populated | fixture-destinations-populated | None |
| Destinations empty | fixture-destinations-empty | None |
| Groups | fixture-groups | None |
| Permissions | fixture-permissions | None |
| Composer | fixture-composer | None |
| Drafts | fixture-drafts | None |
| Accounts | fixture-accounts | None |
| Settings | fixture-settings | None |

Fixture data includes 198 synthetic conversations (50 per page), Sinhala/Tamil/emoji/long names, explicit fake ledger states and safe timeline events. Fixture filtering/pagination/selection operates locally and cannot launch the Python backend. UI assertions prepare relative list-height/footer geometry, row selection, cached search/pagination and history status sorting; they are compiled **not passed**. Unit tests separately verify cache query semantics, stale-response rejection, search continuation/deduplication and event privacy/bounds.

### Run all available capture combinations locally

From an unlocked graphical Terminal session:

```sh
./macos/build.sh Debug
./macos/test.sh
for appearance in light dark; do
  for size in compact standard large; do
    ./macos/screenshots.sh "$appearance" "$size" || exit 1
  done
done
```

Exports go under `docs/assets/screenshots/<appearance>/<size>/` only after successful tests. Requested sizes are 980×640, 1260×820 and 1500×960 points; macOS may constrain them to the attached display. Keep the `.xcresult` as raw evidence and inspect actual captured dimensions. Before publishing, inspect every image for clipping, overlap, contrast, row visibility, selected state and sensitive content. Fixtures contain no genuine Telegram credentials/messages.

### Manual fallback and fullscreen

If XCUITest is unavailable on the local Mac, open a **Debug fixture-only** instance:

```sh
open -n --env TGM_UI_FIXTURE=1 --env TGM_TEST_MODE=1 \
  --env TGM_NO_AUTO_CONNECT=1 --env TGM_UI_SCREEN=Chats \
  --env TGM_UI_NO_SELECTION=1 --env TGM_DATA_DIR=/private/tmp/tgm-ui-demo \
  macos/build/Build/Products/Debug/TelegramManager.app
```

This instance must show Example Account and synthetic data; never capture a real account window. Navigate the fixture screens manually. Use Control-Command-F to enter/leave fullscreen, and Shift-Command-4 then Space to capture only the selected fixture window. Repeat in Light/Dark, compact/standard/large/fullscreen, then review actual PNGs before placing them in the documentation directory. Fullscreen, high contrast, reduced motion, text scaling, VoiceOver and scrolling/keyboard interactions remain manual acceptance items; no claim is made that compilation validates them.
