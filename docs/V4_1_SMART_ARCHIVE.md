# V4.1 Smart Media Archive

Smart Media Archive adds a conversation-aware **Save Media** wizard and a
**Media Archives** dashboard to the existing native client. No chat IDs,
usernames or links need to be entered. Existing account sessions, Keychain
credentials, messaging, group permissions, V4 viewers and JSON-lines IPC remain.

This is a development implementation tested with mocked Telegram and real native
UI fixtures. **Live Telegram compatibility is unverified. Channel support is
conditional, not universal:** unsupported sponsored-message formats remain gated.
See [the UX audit and evidence](V4_1_UX_AUDIT.md).

## Use it on your MacBook

1. Quit the other running app/CLI instance normally. Do not remove lock/session
   files to work around another instance.
2. In this checkout, build and open the app:

   ```sh
   ./macos/build.sh Debug
   open macos/build/Build/Products/Debug/TelegramManager.app
   ```

   The project still requires its Python 3.13+ `.venv`. For a new checkout, follow
   the [README setup](../README.md). Archiving adds no external dependency and does
   not need the optional FFmpeg decoder used by V4 voice previews.
3. Connect the intended account, refresh conversations if necessary, and open an
   accessible private chat, group, supergroup, Saved Messages or supported channel.
4. Choose **Save Media** in that conversation's header.
5. Choose media, dates, an existing writable folder, and folder organization.
   Review the conversation/account/dates/destination and choose **Start Saving**.
6. Open **Media Archives** to pause, resume, cancel, retry failed files or open
   the destination in Finder. Switching accounts pauses the old account's job.
   Return to the original account and reconnect before resuming it.
7. After a successful run, **Check for New Media** creates a new immutable job
   using the same conversation and archive folder. Previously saved files are
   verified rather than blindly skipped.

Start manual acceptance with one small ordinary photo/document conversation and
a short custom date range. Confirm filenames and original dates, run it twice,
then test pause/resume, restart and account switching. Use only conversations you
are authorized to export. No messages need to be sent to test archiving.

## Guided workflow

The five steps select Photos, Videos, GIFs (including Telegram MP4 animations),
Documents, Audio/voice, or all supported ordinary attachments; all history, last
30 days, last year or custom dates; destination; daily/monthly/type organization;
and final review. Unknown totals say **Calculated while finding media**.

Date boundaries are saved as UTC instants. Custom dates include the entire final
day in the Mac's selected timezone, including daylight-saving transitions. The
job freezes that timezone and organizes by the original Telegram message date,
not file creation/download time. Future unavailable history is not requested.
An incremental job retains the original lower date boundary and advances its
upper boundary only within the approved range (or to now for rolling ranges).

## Folder and duplicate behavior

```text
Chosen Folder/
  Telegram Archives/
    Conversation Name — stable-account-and-conversation-suffix/
      YYYY-MM-DD/
        photo_123_original-name.jpg
        document_456_receipt.pdf
```

Monthly and media-type folders are optional. Folder identities include stable
profile, verified account and conversation identity. Same-named conversations
cannot share a folder accidentally; later renames reuse that conversation's
existing folder for the same destination. Unicode components are bounded by
UTF-8 byte length. Media names discard traversal components and unsafe extensions;
unknown file types use `.bin`, without altering their bytes.

Duplicate records bind account, conversation, message, media fingerprint and
archive folder. The current file must be an owned regular single-link file with
the expected size and SHA-256, and the message must still permit export. Modified
or unrecognized files are preserved; a numbered filename avoids overwriting them.
A local checksum verifies the saved copy, not an independently supplied Telegram
server checksum. Caption edits alone do not require another media copy.

## Engine, persistence and lifecycle

- `archive_store.py`: additive `archive_jobs`, `archive_items`, `archive_files`
  and `archive_stats` SQLite tables. Triggers maintain dashboard counters without
  recounting an entire archive for each file. Original delivery ledgers remain.
- `archive_policy.py`: ordinary-export classification, dates, fingerprints,
  bounded names, no-follow directory traversal and cancellable file verification.
- `archive_jobs.py`: serialized job commands, one active archive worker, bounded
  50-message pages, a persisted cursor, bounded retries and incremental recovery.
- Existing `MediaTransfers`: shared two-transfer ceiling. One archive worker uses
  at most one slot, leaving interactive capacity. Scan requests do not hold the
  shared mutation lock. Existing short authorization/publication boundaries remain.
- `file_publication.py`: publication through retained directory descriptors,
  without replacement. macOS exclusive rename is used when hard links are not
  supported; unsupported destination semantics fail safely.
- `ArchiveViews.swift` and `AppModel`: native wizard, lazy dashboard, contextual
  action, scoped events and local progress refresh while the dashboard is visible.

Only one history page and one archive item are active in memory. The ledger grows
on disk with discovered items; the dashboard returns at most 100 jobs and item
inspection pages at most 50 rows. The scanner sleeps between pages and stops after
reaching the requested lower range. It does not index message bodies or download
whole histories into RAM. No numerical live throughput/RSS/FPS claim is made.

A publication journal reserves a private temporary file's relative name and
filesystem identity before writing. It records final size/digest before atomic
publication. On resume, matching owned partials are cleaned, and a final file
published before a crash can be verified and completed without redownloading.
Unknown or replaced objects are preserved. Directory/file handles are closed on
failure; active file writes and verification readers are drained on cancellation.
New directories use 0700 and temporary/output files 0600.

Pause, cancel, disconnect, profile switching and orderly shutdown cancel/drain the
archive worker. Completed files remain. An interrupted file restarts from zero;
this is **job-level recovery, not persistent byte-level resume**. Startup marks
interrupted work Paused; it never silently resumes network activity. External
archive folders are checked/cleaned when a job resumes, rather than scanned during
startup. A force-kill can therefore leave an owned ordinary partial until resume.
Protected media is never staged by this engine.

## Restrictions and failure states

| Item | Behavior |
| --- | --- |
| Authorized ordinary photo/video/GIF/audio/document | Export through the V4 transfer manager, up to its existing 512 MiB limit |
| No-forward/protected/restricted message or peer | Refuse export; individual restricted items are counted, never counted as saved |
| Auto-delete, view-once, self-destruct or secret chat | No archive download, no read-to-start-timer acknowledgement, no cache fallback |
| Unsupported/unknown-size/oversized attachment | Count unsupported and continue |
| Deleted/expired attachment | Count unavailable/deleted as applicable; no successful-file record |
| Temporary network failure | At most two scan/transfer retries with bounded backoff; otherwise explicit resume/retry |
| FloodWait / existing account cooldown | Persist deadline; Waiting for Telegram; no resume or retry before expiry |
| Low space, denied access, changed directory or unavailable account | Stop safely as Needs attention; preserve completed files |

Dashboard states are Finding media, Saving, Paused, Waiting for Telegram,
Needs attention, Finished and Cancelled. Counts separate saved, verified existing,
restricted, unsupported, deleted/expired and failed items. Bytes include active
transfer progress while available. The full-history duration is unknown, so no
completion ETA is invented. Retry Failed only requeues failures and revalidates
policy; it cannot force a restricted download.

## Broadcast-channel prerequisite: implemented subset and gate

Every production channel opening goes through `sponsored.open`, including channels
previously listed as available. It calls the official sponsored-message API and
caches the result for five minutes. The current client/account may access the
channel only after the actual response is recognized and presentable. A real
empty response is accepted; an error or unknown result is never treated as empty.
The session-scoped capability supports a long-running explicitly started archive;
reopening/refreshing the channel rechecks its sponsored response and can revoke it.
Disconnect/profile changes clear sponsored state.

Supported plain-text sponsored messages appear after channel posts, with the
Sponsored/Recommended label, title, text, action, sponsor information and report
flow. Impressions originate from full text/title visibility in a focused window,
not from fetching the ad. External HTTPS actions require confirmation and report
clicks. Report choices use opaque ad-bound tokens; report options are not invented.

**Rich/formatted ads, photos, media, special colors, timed/video ads and Telegram
deep-link actions are not yet implemented. If any are returned, channel content
and its archive action remain unavailable.** Bot content remains gated. Channel
video/animation preview also remains unavailable because its full-screen sponsored
lifecycle is not implemented; permitted original files can be archived/saved from
an otherwise supported channel. This is deliberately not a claim of complete
Telegram channel/sponsored parity or live API compliance certification.

Reference: [official sponsored-message specification](https://core.telegram.org/api/sponsored-messages)
and [Telegram API terms](https://core.telegram.org/api/terms).

## Additive IPC, envelope version 1

All archive methods require `account_id`; results retain profile/generation scope.
The existing 1 MiB frames, exact-key/type validation, request limits and subprocess
ownership remain. No HTTP server, second session or automatic message sending.

| Method | Parameters beyond account_id | Purpose |
| --- | --- | --- |
| `archive.capabilities` | destination | Fresh export eligibility for a cached conversation |
| `archive.create` | destination, types, start, end, timezone, folder, organization | Freeze settings and start one job |
| `archive.list` | none | Up to 100 account-scoped snapshots, including offline progress |
| `archive.get` | job_id | Snapshot for one job |
| `archive.items` | job_id, optional page | Bounded skipped/failed item inspection |
| `archive.pause`, `archive.resume`, `archive.cancel` | job_id | Control the immutable job |
| `archive.retry_failed` | job_id | Revalidate and retry failed items |
| `archive.incremental` | job_id | New immutable incremental job, same account/conversation/folder |
| `sponsored.open` | destination | Fetch/validate channel sponsored presentation |
| `sponsored.view`, `sponsored.click` | token | Actual visibility/click reporting |
| `sponsored.report` | token, optional option | Official report-choice flow |

`types` is a nonempty unique subset of photo/video/animation/document/audio;
`organization` is daily/monthly/type. Dates are bounded integer epoch seconds,
with an exclusive end. `archive.changed` events are replaceable; SQLite snapshots
remain authoritative. Sensitive raw exceptions, credentials and file references
are not logged. Ledgers contain private ordinary filenames/paths and must be
protected along with existing database backups.

## Validation and remaining manual acceptance

Actual final test/build results and screenshots are recorded in
[V4_1_UX_AUDIT.md](V4_1_UX_AUDIT.md). Automated Telegram responses are mocked;
UI counters and conversations are synthetic. Tests never authenticate or send.

On the MacBook, additionally verify native folder selection/permissions, real
permitted media, original timestamp grouping, duplicate checks, network loss,
actual disk-full/external-volume behavior, restart and account switching. Verify
VoiceOver, keyboard-only operation, contrast, Reduce Motion, compact layouts and
sustained scrolling manually. Record these separately from the automated results.
Unsupported sponsored variants, the 512 MiB file limit, interrupted-file restart,
100-job dashboard page, no installer/embedded runtime and unverified live Telegram
behavior remain material limitations.
