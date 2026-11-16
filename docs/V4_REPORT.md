# V4 implementation and UX audit — 2026-11-16

V4 extends the existing architecture rather than replacing it. The implemented
scope and exact limits are in [V4_MEDIA.md](V4_MEDIA.md). This is a development
implementation, not a live-Telegram or standalone-distribution certification.

## Delivered changes

Python adds media policy, transfer orchestration and optional local voice decoding.
Transfers release the shared network/mutation lock while moving chunks, so deletion
updates can invalidate them. Account transitions drain old work before swapping
clients/stores. Scoped IPC includes metadata/open/release/progress/pause/resume and
retains legacy download/cancellation compatibility.

The existing viewer now presents centered zoomable photos, bounded animation,
AVKit `AVPlayerView` playback and Quick Look PDF/plain text. Supported disappearing
photos/MP4s expose viewing-only capabilities, correct timer categories and durable
consumption markers. Ordinary exports remain explicit and private until atomic
publication. No messaging/group ledger or Keychain/session architecture was reset.

The existing design system was reused and extended with an attachment row rather
than introducing another visual framework. Existing PageHeader, EmptyStateView,
SectionCard and status components continue to serve other screens. No automatic
media fetch, automatic send, placeholder action or unrelated screen redesign was
added. Message rows use type icons until a user explicitly opens an attachment;
there is no automatic thumbnail-download pipeline.

## Screen-by-screen UX audit

| Screen | Finding and change | Evidence / remaining boundary |
| --- | --- | --- |
| Sidebar / root | Messaging and advanced tools remain separated. Clicking the selected Advanced Workspace shortcut from a tool previously did nothing. It is now an accessible button that returns to the hub. | Real navigation test traversed everyday pages and every advanced tool; passed after repair |
| Chats / conversation list | Existing search, pagination, bounded rows, Unicode names, selected conversation and composer layout retained. New reusable attachment rows show name, type, size and only backend-authorized actions. | Real Chats capture inspected; attachment capability policy tested with mocked Telegram |
| Message bubbles / composer | Existing semantic incoming/outgoing presentation, drafts, reply and confirmation remain. No automatic media fetching or sending introduced. | Existing native/backend regression suites; no live send |
| Photo viewer | Initial capture exposed bottom-left placement and excessive blank space around a tiny fixture. Scroll-view layout now centers/fits the image; zoom/reset/pan, Escape, save shortcut and full-screen action added. | Revised real photo capture inspected; zoom/reset/dismiss exercised graphically; full-screen interaction still needs manual acceptance |
| Timed viewer | Finite countdown is prominent; view-once uses a close-consumes label instead of a fabricated countdown. Save As absent for timed content. | Real timed-photo capture inspected; absent save, zoom/reset and dismissal asserted; backend expiration/reintroduction tests |
| Video / audio viewer | SwiftUI VideoPlayer caused a runtime metadata crash despite playability tests. Replaced with native AVPlayerView; sharing controls disabled; playback resources cleared on dismissal. | Synthetic H.264 asset verified; real native controls checked in UI retest. Ogg uses optional bounded FFmpeg; no audible listening acceptance |
| GIF viewer | Bounded frame/pixel validation before animated AppKit display; Reduce Motion disables animation. Zoom uses the same image surface. | Synthetic GIF validation XCTest; no separate GIF graphical capture |
| Document viewer | Quick Look previews ordinary PDF/plain text; unsupported formats retain Save As. Timed documents cannot enter Quick Look. | Built and policy gated; no separate document graphical acceptance |
| Transfer feedback | Byte progress, pause/resume and cancel appear while a transfer runs. Two backend transfers allowed; native operation flow remains deliberately conservative. | Mocked success/failure, pause/resume, concurrency, deletion, switch, timeout and cleanup tests; no live transfer UI claim |
| Settings | Native account-specific download-folder chooser and explanatory row added; native Save As remains the final destination choice. | Real Settings capture inspected; preferences keyed by stable profile identity |
| Onboarding | Numbered stages, native default buttons, shorter readable introduction, secure fields and field clearing on dismissal. Original credential guidance/code/2FA/account confirmation preserved. | Five real fixture stages captured; header truncation found and repaired; API setup capture inspected; no live login |
| Accounts | Existing account identities and distinct lifecycle actions retained; transfer drain added below the UI before switching. | Real Accounts capture inspected; mocked switch-during-transfer test and existing account regressions |
| Advanced Workspace | Existing task cards and progressive disclosure retained. Return navigation repaired without moving advanced controls into Chats. | Real hub capture inspected and all tool destinations exercised |
| Group Management / Permissions | Existing explicit discovery/inspection workflow preserved. | Navigation/capture test and Python permission regressions; no live permission lookup |
| Composer / Drafts / Destinations | Existing explicit approvals and exact send confirmation retained. | Navigation and original regression suites; no messages sent |
| History / Activity / Message Actions | Existing outcomes, uncertainty handling and local activity remain. A timing-dependent native action test now waits for a bounded observable result rather than assuming 100 ms completion. | Existing action/native regressions; navigation test reached each page |
| Contacts / profile / folders | No redesign. Existing native metadata surfaces remain accessible. | Real fixture UI test passed; no claim of added folder synchronization/avatar support |

Accessibility uses native buttons, file panels, scroll views and player controls,
semantic system colors, font styles and explicit labels. Reduce Motion is observed
for animation. New controls have keyboard equivalents. Full VoiceOver traversal,
high-contrast review, every window size and sustained scrolling performance remain
manual acceptance tasks; no FPS/memory benchmark or complete accessibility claim
is inferred from source inspection.

## Executed validation

- Python: **319 tests + 136 subtests passed**.
- Native XCTest: **91 tests passed** (models, private media decoding, GIF bounds,
  synthetic video playability, transport and existing regressions).
- Graphical: Contacts/profile/folders/photo scenario passed; five onboarding
  stages passed; everyday navigation plus all advanced tools passed after repair;
  timed-photo zoom/reset/dismiss/no-export and AVKit native-control scenario
  passed after the player replacement. Explicit dark appearance was captured and
  visually inspected, rather than inferred from a requested test setting.
- Syntax, new-module Ruff checks, documentation links and diff whitespace passed.
- **Debug and Release builds succeeded; both deep/strict signature checks passed.**
  Bundled Python source was checked against this checkout; no session/database/.env
  filename candidates were found in either bundle Resources directory.

Local evidence: `/private/tmp/tgm-v4-ui-verified.xcresult` (navigation),
`/private/tmp/tgm-v4-ux-final.xcresult` (photo/onboarding scenarios passed; its old
navigation accessibility query failed), `/private/tmp/tgm-v4-dark-reviewed.xcresult`
(explicit dark timed/video scenario), `/private/tmp/tgm-v4-native-final.log`.
AVKit emitted a recoverable internal glass-volume-control constraint warning in
the passing dark run; this remains a platform-specific manual-review item.
All Telegram responses in automated backend tests are mocked. Media fixtures are
locally generated color/silent content. Tests never authenticate Telegram or send
real messages. The optional decoder integration test uses a local silent Ogg file.

Real XCUITest runs exposed and helped repair sidebar navigation, photo placement,
onboarding truncation and a video-player runtime crash. A video capture containing
a macOS Desktop permission prompt and another application window was excluded from
repository artifacts. The movie fixture now runs from temporary storage. Early
failed runs remain local diagnostic evidence and are not described as passing.

## Screenshot evidence

Retained images are genuine application-window XCUITest captures with synthetic
fixtures, not mockups or screenshots of real conversations. Selected captures were
visually inspected. Pixel dimensions are 2520 × 1640 for the standard 1260 × 820
point window at 2× scale.

- [Chats](assets/screenshots/v4/light/chats.png)
- [Accounts](assets/screenshots/v4/light/accounts.png)
- [Advanced Workspace](assets/screenshots/v4/light/advanced-workspace.png)
- [Settings](assets/screenshots/v4/light/settings.png)
- [API onboarding](assets/screenshots/v4/light/welcome-api-setup.png)
- [Photo viewer](assets/screenshots/v4/light/synthetic-image-viewer.png)
- [Timed viewer without export](assets/screenshots/v4/light/timed-photo-viewing-only.png)
- [Dark timed viewer](assets/screenshots/v4/dark/timed-photo-viewing-only.png)
- [Dark native video player](assets/screenshots/v4/dark/native-video-player.png)

[Artifact dimensions and SHA-256](assets/screenshots/v4/evidence.json) are recorded
without machine identifiers or raw Xcode report metadata.

## Remaining limits

- Live account/device Telegram viewing, timer synchronization and export acceptance
  have not been performed; no live compatibility claim.
- Secret chats, restricted/no-forward peers, timed voice/GIF/documents and outgoing
  view-once/self-destruct viewing remain unavailable.
- Common documents beyond PDF/plain text are saved for another application.
  Codecs depend on macOS; Ogg preview additionally needs optional local FFmpeg.
- Pause/resume works within the current process; restart cancels partial transfers.
  Automatic downloads and automatic thumbnail downloads are not implemented.
- Ordinary attachments are capped at 512 MiB; image/animation limits are stricter.
- Forced process death may leave private indexed files until startup recovery;
  filesystem deletion does not guarantee physical erasure. Filesystem permission
  failures can delay cleanup while retaining ownership evidence.
- Complete VoiceOver, contrast, fullscreen, small-window, GIF/document rendering,
  audible playback, performance and clean-Mac distribution acceptance remain.
- The app still needs the checkout Python runtime; FFmpeg is not bundled. No
  installer/notarization/production readiness claim is made.
