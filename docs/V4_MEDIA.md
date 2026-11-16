# V4 native media system

The existing SwiftUI/AppKit → owned JSON-lines subprocess → Telethon architecture
is retained. No additional Telegram session or HTTP server is introduced.
Live Telegram compatibility has not been tested.

## Implemented behavior

- Classification distinguishes photos, video, animated documents/MP4 GIFs, GIF,
  voice, audio, documents, ordinary attachments, auto-deleting messages,
  view-once, self-destructing media, and unsupported secret-chat envelopes.
- Ordinary attachments with a known positive size up to 512 MiB support explicit
  Save As. Native suggested names discard remote path components, replace unsafe
  extensions, and choose an available numbered filename. Publication never
  overwrites an existing file, including a raced filename.
- Two transfers may run concurrently through the existing authenticated client.
  Authorization and final message revalidation hold the existing shared lock;
  chunk transfer does not. Account transitions cancel and drain transfers before
  disconnecting/swapping stores. Edits, deletions and synchronization gaps cancel
  affected work. Cancellation closes the Telethon iterator and removes partials.
- Pause/resume keeps a transfer in this process; process restart cancels it.
  ConnectionError/TimeoutError retries are limited to two, with 1/2-second
  backoff and completed-byte offsets. Timed media never retries. FloodWait and
  other RPC failures are not retried by this manager.
- SHA-256 records downloaded ordinary bytes, and exact declared length is checked.
  This is a local digest, not proof against a Telegram-provided checksum.
- The viewer supports JPEG/PNG with off-main ImageIO validation/downsampling,
  bounded animated GIFs, AVKit-compatible video/audio, and Quick Look PDF/plain
  text. Other attachments offer saving rather than a nonfunctional Open action.
- Static images retain the 8 MiB/16-megapixel/1600-pixel decode bounds. GIFs are
  limited to 8 MiB, 200 frames, 16 million pixels per frame and 32 million total
  pixels. The native viewer supports zoom, scroll/pan, keyboard zoom/reset,
  Escape, Command-S for ordinary files and a full-screen action.
- Ordinary Ogg/Opus voice previews use optional FFmpeg from
  `/opt/homebrew/bin/ffmpeg` or `/usr/local/bin/ffmpeg`. There is no shell command
  or network input. Input demuxing is forced to Ogg; decoding is limited to one
  thread, 30 seconds of wall time, 10 minutes of audio, 64 MiB of output and a
  64 MiB individual allocation limit. Missing FFmpeg leaves Save As available.
  FFmpeg is not bundled or installed automatically; the development app still
  depends on its checkout runtime. The decoder is killed/reaped on cancellation.
- Download folder preferences are local UserDefaults values keyed by stable
  profile ID. Every save still presents a native Save As panel. Automatic
  download is not enabled or exposed as an unfinished setting.

## Time-limited content

| Category | V4 behavior |
| --- | --- |
| Ordinary | View supported formats and save explicitly |
| Auto-deleting chat message | Supported JPEG/PNG/MP4 view only; absolute deadline is message date plus `ttl_period`; no media-read timer acknowledgement |
| View-once | Supported incoming non-secret JPEG/PNG/MP4 only; content-read acknowledgement after private preparation on explicit open; no countdown; close consumes local content |
| Self-destructing | Supported incoming non-secret JPEG/PNG/MP4, finite 1–86400-second timer; acknowledgement and conservative timer start immediately before viewer exposure on explicit open; visible countdown |
| Secret chat | Unsupported; no second encrypted session or secret-chat implementation |

No timed category can use export or audio conversion. Protected/no-forward,
restricted and unsupported peers remain blocked. Timed voice, GIF, documents,
outgoing self-destruct/view-once and unknown constructors remain unavailable.
The dedicated media scope validator does not relax text/reply/action policy.
Timed history retains hidden bodies, exposing only supported attachment metadata.

A new additive SQLite `media_consumed(account, peer, message)` primary key records
view-once/self-destruct consumption **before** acknowledgement. An uncertain or
interrupted open stays consumed, even if this sacrifices availability. An
in-flight deadline task cancels stalled transfer; viewer deadlines and reliable
`media.expired` control events close native content. Re-fetching cannot restore
consumed media. Auto-delete deadlines are independently rechecked before exposure.

Private cache files use mode 0600 in a 0700 profile directory. An atomic ownership
index reserves pending files before content is written and records device/inode.
Startup/profile activation recovers indexed files conservatively. Unknown files,
links and substituted inodes are preserved and disable cache viewing, while
ordinary saving and other application features remain available. Four completed
viewers, two transfers and a 512 MiB source-byte cache budget bound storage;
conversion has additional bounded input/output reservations. Ordinary cache
leases last 15 minutes. Timed content follows its own earlier deadline or closes
with the viewer; view-once also has a conservative 15-minute safety cap.

Filesystem deletion is not forensic erasure on APFS/SSDs. OS force-kill can leave
private indexed files until the next backend startup. Cleanup permission failures
retain ownership evidence for recovery and log only exception type. No hidden
retention, export bypass, automatic message sending or expiration suppression is
implemented.

## Additive IPC, envelope version 1

All results retain `profile_id` and `account_generation`.

| Method | Exact parameters | Result |
| --- | --- | --- |
| `media.get_metadata` | `account_id,destination,message_id` | Bounded kind/name/size/MIME/duration/category/capability descriptor |
| `media.open` | `account_id,destination,message_id` | Descriptor plus token, generated private path, bytes and expires_at |
| `media.download` | `destination,message_id,path`, optional `account_id` for legacy compatibility | saved, bytes, SHA-256 |
| `media.release` | `account_id,token` | released |
| `media.get_progress` | `account_id,request_id` | bytes, total, paused; active transfers only |
| `media.pause`, `media.resume` | `account_id,request_id` | Same progress snapshot |
| Existing `cancel` | `request_id` | Propagates task cancellation |

IDs, integer bounds, exact field allowlists, framing limits and the 64-request
process cap remain enforced. `media.preview.get/release` remain compatible legacy
JPEG/PNG routes; the native viewer uses the new media routes. Legacy direct
`ChatFeatures` helper tests retain their old 64 MiB behavior; the public router
routes `media.download` through V4. Progress events carry byte count, total and
scope; intermediate progress may be dropped under backpressure. Expiration uses
the control-event path. Errors are structured and omit raw exceptions and paths.

## Validation

See [V4 implementation and UX report](V4_REPORT.md) for executed checks, real
synthetic-data screenshots, source-level audit findings and acceptance limits.
Telegram timer semantics were checked against
[official viewing rules](https://core.telegram.org/api/views); offset downloads
follow [Telethon's documented iterator](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.downloads.DownloadMethods.iter_download).
