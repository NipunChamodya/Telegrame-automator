# V3 conversations and client feature API

All methods use the [strict JSON-line IPC envelope](IPC.md). Results add active `profile_id` and `account_generation`; live-update and selected feature results also carry the fields listed below. Explicit account IDs must match the bound, authorized account. Network/mutation routes serialize with account switching and managed sending. Cached reads do not connect to Telegram.

## Supported content boundary

Cached channel/bot titles can be listed as metadata, but **channel and bot message content is unavailable** until official sponsored-message support is implemented. Unknown, restricted or protected peers are blocked. Legacy cached rows without verified support metadata return an empty preview. Protected/no-forward, TTL/disappearing, restricted, service and unsupported message/media constructors return an unavailable placeholder or are refused by the requested action. These checks occur in Python, including history, events, replies, downloads and previews; hiding a Swift control is not the protection.

This is a limited client, not full Telegram parity. Missing fields remain unknown. No full participant list, arbitrary raw Telegram object or avatar is returned. Phone numbers, access hashes, authentication/session values and media file references are excluded from client DTOs.

## Cached dialogs and explicit refresh

| Method and exact parameters | Result / behavior |
|---|---|
| `chats.list {query?:string,kind?:string,page?:int,size?:int,sort?:string}` | `chats,total,page,size`. Kinds: `all,private,saved,groups,group,supergroup,channel`; `groups` combines basic/supergroups. Sort: `name` (default) or `recent`. Page is zero-based, size 1–100 (default 50); search uses cached Unicode name/username/ID metadata. |
| `chats.refresh {limit?:int,after?:int}` | Explicitly retrieves up to 100 dialogs (default 100), including archived dialogs and excluding migrated duplicates; saves incrementally. Returns `processed,limit,possibly_more,next_cursor`. Continue with a separate `after:next_cursor` request; this account's cursor must have a cached last-message ID/date. Old cached records are not automatically deleted. |
| `chats.saved {}` | Verifies current identity and returns its Saved Messages cache entry as `chat`; does not read history or send. |

Dialog rows include `id,name,kind`, available username/unread/last-message/date/archive/cache metadata and `content_known,content_available,content_reason,is_bot`. Only supported message previews enter new cache writes. A refresh count describes processed rows, not a certified complete Telegram total. Detailed managed-group inspection is a separate workflow.

## Message pages and presentation metadata

`messages.list {destination:int,limit?:int,offset_id?:int,search?:string}` requires a cached conversation, live authorized identity and freshly resolved supported peer. It returns `messages,next_offset_id,has_more`. Limit is 1–100 (default 50), offset 0–2147483647 (default 0); search is at most 256 characters. Search is an explicit remote request. Pass returned offsets on separate older-page actions. Returned messages must belong to the selected peer.

Available fields include `id,text,sender_name,sender_id,date,outgoing,media,edit_date,reply_to_id,reply_to_peer_id,grouped_id,views,forwards,reactions,entities,forward,pinned,content_available,content_reason,can_request_edit,can_request_delete`. Media is metadata (`kind,name,size,mime_type`), not an automatic download. Unavailable placeholders contain no body/media. Sender names use already available metadata; no per-row sender fetch loop occurs.

Projection preserves a bounded safe subset of entities: bold, italic, code/pre and HTTP(S) links without embedded credentials. Entity ranges use UTF-16, invalid/surrogate-splitting offsets are dropped, and changed/sanitized text does not reuse shifted ranges. At most 32 entities and 32 reaction summaries are projected. Reaction counts/selection, forward attribution and pinned state are display metadata; no reaction/forward/pin mutation is implied. Full message pages are not persisted to SQLite; the native window holds at most 200 rows.

## Scoped live updates, repair, read and typing

| Method and exact parameters | Behavior |
|---|---|
| `updates.watch {account_id:int,peer_id?:int}` | Watches the active account projection, optionally selecting a verified supported peer. Returns scope, `stream_id,watching,sequence,dirty,peer_id,freshness_scope,history_complete:false`. Changing peer clears the eligible read frontier and cancels previous typing. |
| `updates.unwatch {account_id:int}` | Stops publishing, clears selected peer/read eligibility and cancels typing. Runtime handlers remain owned by the current connection until teardown. |
| `sync.snapshot {account_id:int,peer_id?:int,limit?:int}` | Requires the watch selection to match. Limit 1–100 (default 50). With a peer, retrieves a bounded current message page; without a peer, refreshes a bounded dialog page. Returns watch state plus `chats,messages`. A dirty result requires another explicit repair; it does not certify every cached dialog fresh. |
| `messages.read {account_id:int,peer_id:int,max_id:int}` | Requires a watched supported peer and an incoming supported ID actually returned for that peer. Calls the supported acknowledgement API and returns `acknowledged:true,max_id` only on confirmation. UI must additionally establish actual foreground viewport visibility; fetching a page alone is not reading every row. |
| `messages.typing {account_id:int,peer_id:int,active:bool}` | Requires the current watched supported peer. Sends typing or cancellation; active requests are conservatively throttled to one per four seconds. Returns `accepted`; false is not confirmation. UI invokes this only for actual focused editing, not draft hydration. |

Live events are `chat.changed` (`peer_id,chat`), `message.changed` (`peer_id,message,change`), `message.deleted` (`peer_id,message_ids`), `read.changed` (`peer_id,max_id,outbox`), `typing.changed` (`peer_id,user_id,active,expires_at`) and `sync.required` (`reason,peer_id`). Each event's `data` also includes `profile_id,account_generation,account_id,stream_id,sequence`.

Consumers must reject wrong scope/stream, ignore old/duplicate sequence numbers and treat gaps/`sync.required` as requiring a scoped snapshot. Ambiguous peerless deletion is a repair signal, not authorization to delete the same numeric ID in an arbitrary conversation. The ingress queue is capped at 256 and projected messages/tombstones at 200. Slow-reader control-event overflow fails the IPC transport rather than silently losing a deletion. Telethon owns MTProto update state/catch-up; this projection is not a new protocol engine. Disconnect, account change, EOF and unknown outcomes never replay a send or action.

## Local drafts and labels

- `chatdraft.get {destination:int}` → `destination,message,updated_at`; missing drafts have an empty message.
- `chatdraft.save {destination:int,message:string}` saves at most 4096 UTF-16 units locally. Empty text deletes this conversation draft. Same-body saves preserve matching personal preview tokens; changed bodies invalidate relevant previews.
- `chatdraft.delete {destination:int}` deletes only this account/conversation draft.
- `chatdraft.list {}` returns up to 100 recent `drafts`, with available cached titles.
- `labels {}` returns up to 1000 local account-scoped destination/label rows.
- `label.set {destination:int,label:string,enabled:bool}` applies/removes a safe 1–40 character local label on an existing managed group.

Local drafts are not Telegram cloud-draft synchronization. Labels do not change Telegram folders, permissions or membership. Native autosave is debounced; process failure before persistence can lose the latest keystrokes. Account switches flush drafts and invalidate the previous context.

## Personal text and replies

`chat.preview {account_id:int,destination:int,message:string,reply_to?:int}` checks the cached personal/Saved Messages destination, fresh account/peer identity and 1–4096 UTF-16 units. An optional positive reply target is fetched and checked against the exact peer/message and content policy. Returns a single-use token, 120-second expiry, exact account/destination/body/reply and `confirmation:"SEND <destination>"`.

`chat.send {account_id:int,token:string,confirmation:string}` consumes the token even on an incorrect phrase; verifies kind, account/profile/generation, expiry and exact target again; reserves the original send-ledger entry and persisted random ID before one supported MTProto submission. It re-fetches a reply target before sending. Groups/channels/bots cannot bypass the managed composer through this route. Tokens cannot cross personal, managed and message-action routes. Server restrictions and cooldowns remain authoritative. Acknowledgement is not recipient read status; uncertain results are never retried automatically.

## Own plain-text edit and delete-for-me

| Method | Contract |
|---|---|
| `message.action.preview {account_id:int,destination:int,message_id:int,action:edit|delete,message?:string}` | Only verified own outgoing plain-text personal/Saved Messages messages. Actual sender identity, returned peer/ID and content support are checked. Edit requires valid changed replacement text; delete rejects a `message` field. Rich/formatted/media/forwarded/bot/group/channel targets are unavailable. |
| `message.action.commit {account_id:int,token:string,confirmation:string}` | One-use 120-second token binds account/profile/generation, peer, message, action, replacement and original version. Fresh target/version verification precedes durable reservation. Phrases are `EDIT <message_id> IN <destination>` and `DELETE <message_id> FROM <destination>`. |
| `message.operations {}` | Latest 100 account-scoped `operations` from the separate persistent ledger. No message bodies are stored in it. |

Preview returns `token,action,account_id,destination,message_id,original_text,message,confirmation,expires_at,delete_for_everyone:false`. Delete uses public `DeleteMessagesRequest(revoke=False)` and removes only the current account's copy. Delete-for-everyone is not exposed. Commit returns `operation` with account/destination/message/action/digest, timestamps, detail and status `pending,acknowledged,rejected,uncertain` (pending can remain after a crash).

The additive `conversation_operations` table validates its required unique reservation constraint. It does not replace the existing send ledger. A changed original requires a new preview; a duplicate reserved action is refused, including after restart. Cancellation/transport/server uncertainty remains durable. There is no automatic retry or bulk action.

## Explicit attachment save

`media.download {destination:int,message_id:int,path:string}` requires live identity, a cached supported conversation and the exact returned supported message/attachment. Declared size must be known, positive and at most 64 MiB. A bounded sink verifies complete length. Progress reports byte count/total.

The user selects a new filename in an existing directory. A private temporary file is fsynced and published without overwriting another file; failure/cancellation removes it. Remote names are never used as paths. TTL/protected/unsupported content is refused. This is no malware scan or automatic execution; opening a saved file is a separate user action.

## Private static-image preview

- `media.preview.get {account_id:int,destination:int,message_id:int}` verifies identity, cached peer and exact message/content scope; accepts only known-size JPEG/PNG attachments up to 8 MiB with a matching file signature. Returns `token,path,bytes,mime_type,destination,message_id,expires_at`, plus normal profile scope.
- `media.preview.release {account_id:int,token:string}` releases only a token belonging to that account/profile generation, returning `released`. Unknown/stale tokens return false; wrong account is rejected.

Generated cache files are private and limited to four (at most 32 MiB). A private index records only generated basename/device/inode. Crash recovery deletes only matching owned recorded files; unknown/replaced matching filenames are preserved and block more previews. Invalidation removes relevant active/pending previews. Backend expiry is lazy at 900 seconds on cache access, plus release/close cleanup; native viewer expiry/close also requests release. This is not absolute-time secure erasure.

Native ImageIO additionally enforces owned single-link regular private files, exact bounded length, one static PNG/JPEG image, at most 16 million source pixels and 1600-pixel downsampling off the main actor. Python signature tests alone do not verify native decoding or rendered output. No GIF/video/audio playback, upload, album renderer or avatar download is provided.

## Read-only contacts, profiles and Telegram folder definitions

| Method and exact parameters | Result / limits |
|---|---|
| `contacts.list {query?:string,page?:int,size?:int}` | Cached account-scoped `contacts,total,page,size`; page zero-based, size 1–100, default 50. No Telegram connection is made. |
| `contacts.refresh {account_id:int}` | Explicit full-contact RPC; only actual contact-vector members matched to typed users are projected. Returns `processed,cached_count,truncated`; projection/cache is capped at 1000. Telegram has no limit parameter for this RPC, so the server response itself may be larger. An incomplete response preserves the old cache. |
| `contacts.open {account_id:int,user_id:int}` | Requires a cached contact, resolves exact identity and returns a supported/policy-gated `chat` cache entry; sends nothing. |
| `profile.get {account_id:int,peer_id:int}` | Only own account, cached contact or cached conversation. Verifies returned entity and actual full-object type/ID. Returns allowlisted `profile` name/ID/username, policy/status/photo-availability flags, available about/member count and check time. No arbitrary-user lookup or avatar download. |
| `folders.list {}` | Cached `folders,source:"telegram_read_only",membership_supported:false`. |
| `folders.refresh {account_id:int}` | Explicit read-only Telegram folder-definition request. Up to 100 typed definitions; explicit peer ID arrays capped at 1000; returns cached result plus `truncated`. No access hashes/raw peers. |

Derived contact/folder snapshots replace only their own account-scoped cache tables, preserving existing manager/session/delivery data. DTO allowlists are applied again on cached reads. Folder definitions are not full membership filtering or editing, and are not local labels. Missing/unknown member metadata is not fabricated.

## Remaining limits and verification

Unsupported: forwarding/reaction/pin mutations, scheduled sending, delete-for-everyone, media upload/albums/video/audio/GIF rendering, avatar downloads, cloud drafts, remote folder changes, bot/Mini App workflows, sponsored channel content, secret chats/calls/stories/payments. Supported rich presentation is a subset, not a complete Telegram entity renderer.

Tests use mocks/synthetic data and isolated process fixtures. See [reference/evidence study](TELEGRAM_REFERENCE_STUDY.md), [validation](VALIDATION.md) and [native UI attempts](UI_VALIDATION.md). No API contract or passing mock test establishes live Telegram acceptance, actual graphical launch, performance benchmarks or distributability.
