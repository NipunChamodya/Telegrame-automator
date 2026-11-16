# V4.1 UX audit and implementation evidence

2026-11-16. This extends the existing native application rather than replacing its
architecture. [Smart Archive implementation and MacBook testing guide](V4_1_SMART_ARCHIVE.md).

## Delivered behavior

Save Media follows the selected account/conversation. The native five-step sheet
selects media, dates, destination, organization and review. Running jobs retain
immutable identities even when the user navigates elsewhere. Media Archives is
separate from Advanced Workspace, and archive work does not set the application's
global busy state or prevent ordinary chat navigation.

The implementation adds durable jobs, 50-message scanning, incremental archives,
verified duplicates, owned partial-file recovery, one archive worker under the
existing two-transfer ceiling, account-switch cancellation, wait deadlines and
safe non-overwriting publication. It adds no server or external dependency.

Channel support is **conditional**: actual empty or supported plain-text sponsored
responses unlock a session-scoped capability. Unsupported sponsored variants keep
channel content unavailable. This is not complete sponsored-message parity or a
live Telegram compliance certification. The limitations are detailed in the
[implementation contract](V4_1_SMART_ARCHIVE.md).

## Application-wide audit

| Area | Finding / implemented change | Evidence and acceptance boundary |
| --- | --- | --- |
| First launch / authentication | Existing guided credentials, phone, code, 2FA and account confirmation retained. No archive action before an eligible account/conversation. | Original authentication regressions remain in the executed suite; no live login |
| Accounts | Verified account/profile identities retained. Switching drains archive work and leaves its job attached to the original account. | Mocked switch-during-transfer test; original profile/lifecycle regressions |
| Sidebar | Media Archives added under App; messaging and Advanced Workspace remain separate. | Real navigation test reached everyday screens and advanced tools |
| Conversation navigation | Save Media appears beside familiar profile/refresh actions. Numeric Telegram/account IDs removed from the ordinary header; unavailable-conversation IDs moved under Conversation details. | Real conversation capture and toolbar assertion; no manual-ID entry |
| Search / pagination | Existing bounded list/search behavior retained. Footer now says conversations rather than cached; loading labels use simple language. | Real geometry/search/pagination scenario; updated label assertions |
| Composer | Text/replies/drafts/explicit send confirmations preserved. Archive creation does not send messages or occupy the global operation task. | Existing Python/native send/draft/action regressions; no real sends |
| V4 media viewer | Existing photo/GIF/AVKit/audio/Quick Look paths and timed viewing retained. Archive never reuses timed caches or starts media-read timers. Channel video preview stays gated pending its separate sponsored lifecycle. | V4 private-image/GIF/video/policy tests execute in the full suites; no new live playback claim |
| Single downloads | Existing progress/cancellation retained. Retained destination descriptors and exclusive publication strengthen race safety; tests cover permission failure and native rename fallback. | Mocked transfers plus actual temporary-file publication tests; external volumes still need manual acceptance |
| Archive wizard | Clear numbered steps, native controls, no technical identifiers, native folder picker, restrained defaults. Final review now repeats dates and organization. | Real steps 1–5; Return advances the default action; review/cancel/start controls asserted |
| Archive dashboard | Simple states, discovered/saved/verified-existing/skipped/failed counts, bytes and explanatory notes. Pause/resume/cancel/retry/open-folder controls; no invented ETA. Lazy rendering and bounded snapshots. | Real light/dark state captures and working fixture pause/resume/cancel flow; actual job logic separately tested in Python |
| Wait recovery | Countdown and explicit resume after Telegram's deadline. Resume and Retry Failed disabled while waiting; backend independently enforces the deadline. | Mocked FloodWait/deadline test and real waiting-state capture |
| Restart / offline recovery | Interrupted jobs reopen Paused without network activity. Dashboard loads saved progress offline; resume requires the original connected account. | Persistence/publication-recovery tests; offline UI context uses bound account rather than live scope |
| Settings | Ordinary Account label replaces Account binding/numeric ID; session-file terminology replaced with private-account explanation. Advanced runtime details remain under Advanced. | Real settings navigation/capture; no settings architecture replacement |
| Advanced Workspace | Group management, permissions, approvals, composition, history and actions remain separate and intact. | Real navigation through every tool; original backend/native regressions |
| Error recovery | Ordinary startup text now says connection and drafts/saved files rather than Python child/backend terminology. Filesystem/low-space failures retain saved files and become Needs attention. | Recovery/native tests and injected storage failures; not a real disk-fill experiment |
| Sponsored presentation | Supported text is labelled Sponsored/Recommended with sponsor information and official report choices. External website action confirms first. Full visible text/title geometry drives impressions, never fetching alone. | Mocked request/cache/view/click/report tests and real text-card/confirmation/report-choice UI scenario; no live ads |

## Validation record

Final automated totals:

- **Python:** 354 tests + 148 subtests passed.
- **New archive/sponsored tests with warnings treated as errors:** 33 tests +
  12 subtests passed. Account-switch fixture teardown also closes the active store.
- **Native XCTest:** 96 tests passed, including the new date/DST, immutable target,
  state-label, wizard validation and channel-capability tests.
- **Graphical:** four selected XCUITest scenarios passed in the final acceptance
  run: archive wizard/dashboard, archive states/conversation action, sponsored
  presentation/confirmation/report flow, and application-wide navigation.
  The three archive/sponsor scenarios passed again with final labels and wait
  controls. Conversation geometry/search/pagination/selection passed separately
  after correcting inherited-identifier queries and deferring the List selection
  update to eliminate a SwiftUI publication-during-update warning. Five distinct
  graphical scenarios passed; this was not the entire historical UI test suite.
- **Debug and Release:** both final builds passed. `codesign --verify --deep
  --strict` passed for each final application bundle (exit 0). Signatures are
  ad-hoc, not notarization/distribution approval.
- **Bundle integrity:** all 37 bundled Python modules in both configurations
  matched source byte-for-byte; neither bundle contained session, SQLite database
  or `.env` files.
- **Static validation:** Python syntax and new-module Ruff checks passed;
  27 documentation files / 174 local links resolved; `git diff --check` passed.

Telegram objects and network responses are mocked. Download success tests use
synthetic PNG bytes and temporary storage. The large-history test scans **1,001
synthetic messages** in bounded pages; it is not a throughput benchmark or a live
channel archive. UI job counts are synthetic presentation fixtures, not measured
Telegram download totals. The UI fixture folder button supplies a temporary demo
location instead of invoking the real picker; native folder permissions remain
part of manual acceptance.

A cancellation refactor briefly returned an unfinished verification operation;
the modified-file regression caught it. It was fixed and rerun with warnings as
errors before delivery. Early graphical failures came from a missing synthetic
account generation and inherited SwiftUI accessibility identifiers; assertions now
use the actual accessible controls. These early runs are not counted as passing. Xcode emitted its usual unused
AppIntents metadata warning and the navigation runner emitted a QoS diagnostic;
these did not fail acceptance. No sustained performance claim is inferred.

Evidence locations for this session:

- `/private/tmp/tgm-v41-python-final.log`
- `/private/tmp/tgm-v41-policy-final.log`
- `/private/tmp/tgm-v41-native-final.log`
- `/private/tmp/tgm-v41-ui-final.xcresult`
- `/private/tmp/tgm-v41-ui-reviewed.xcresult` (archive/sponsor passed; initial navigation query failed)
- `/private/tmp/tgm-v41-ui-navigation3.xcresult` (navigation passed after correction)
- `/private/tmp/tgm-v41-debug.log`
- `/private/tmp/tgm-v41-release.log`
- `/private/tmp/tgm-v41-debug-signature.log` and `/private/tmp/tgm-v41-release-signature.log` (silent successful verification)

## Screenshots

Retained images under `assets/screenshots/v4_1/` are actual XCUITest application
window captures using synthetic data. Selected images were inspected for clipping,
readability, spacing and accidental private content. They are not mockups or live
Telegram evidence. The accompanying evidence JSON records dimensions and hashes,
without hardware identifiers or raw Xcode diagnostic metadata.

| Light appearance | Dark appearance |
| --- | --- |
| [Choose media](assets/screenshots/v4_1/light/choose-media.png) | [Saving](assets/screenshots/v4_1/dark/saving.png) |
| [Review and start](assets/screenshots/v4_1/light/review.png) | [Waiting for Telegram](assets/screenshots/v4_1/dark/waiting.png) |
| [Sponsored text](assets/screenshots/v4_1/light/sponsored-text.png) | [Finished](assets/screenshots/v4_1/dark/finished.png) |

[Offline conversation navigation](assets/screenshots/v4_1/light/offline-conversation-navigation.png)
shows the disconnected recovery banner and second-page selection; Save Media is
correctly disabled until connected.

[Capture hashes and dimensions](assets/screenshots/v4_1/evidence.json).

## Remaining limitations and manual acceptance

- No live Telegram login, history, export, sponsored impression/click/report or
  real-device compatibility verification was performed.
- Rich/formatted/media/photo/timed sponsored messages and Telegram deep-link ads
  are unsupported. Channels returning them stay blocked. Bots remain gated.
- Channel video viewing does not implement its full-screen sponsored-ad lifecycle;
  its original ordinary files may be saved only from an otherwise eligible channel.
- The existing **512 MiB per-file** cap remains. Protected/no-forward/timed/secret
  content is never bulk-exported. This is not a complete Telegram data export.
- Pause/restart preserve completed files and the scan cursor; an interrupted file
  restarts from zero. There is no automatic restart/resume after app launch.
- Local duplicate verification checks the current disk copy; subsequent external
  edits cannot be prevented. Unknown files are never deleted or overwritten.
- Unknown total history duration prevents a reliable full-job ETA; none is shown.
- Only 100 recent jobs are shown in one dashboard response; the durable ledger
  retains older jobs. There is no automatic scheduling or retention policy.
- Actual low-storage, unavailable/network volumes, picker/TCC permissions,
  sustained performance, VoiceOver traversal, high contrast, Reduce Motion,
  keyboard-only folder selection and every compact layout require manual review.
  Native labels/default actions were checked; this is not a complete accessibility
  certification or an FPS/memory measurement.
- Existing checkout Python runtime dependency, optional FFmpeg for voice previews,
  ad-hoc signing and lack of standalone installer/notarization remain unchanged.

Use the [MacBook testing steps](V4_1_SMART_ARCHIVE.md#use-it-on-your-macbook) for
controlled live acceptance. Keep private media and account/session data out of
screenshots, bug reports and repository artifacts.
