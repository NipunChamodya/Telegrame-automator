# Client architecture decision — V3 planning gate

Status: accepted for V3 milestones M1–M4, 2026-10-28. The decision retains the existing engine and sessions. The bounded update, message-action and client-feature implementations are now present and tested with mocks; no TDLib migration or live Telegram acceptance was performed. The observations below describe the pre-V3 baseline, followed by the accepted runtime contract.

## Decision

Retain the existing SwiftUI → private JSONL subprocess → Python/Telethon service
for the next implementation increment. Add a bounded application update adapter,
not another Telegram client. Keep existing account databases, session paths,
Keychain scopes, approvals, ledger, cooldowns and explicit send previews unchanged.
Reconsider TDLib only after a separately authorized prototype and measured
requirements demonstrate that maintaining client features in Telethon is unsuitable.

| Criterion | Telethon retained | TDLib replacement | Hybrid client engines |
|---|---|---|---|
| Public integration | Existing Python async API and generated MTProto methods | Async JSON/C interface with its own updates and authorization state | Two distinct API and lifecycle models |
| Session preservation | Existing `account.session` reused | No supported drop-in compatibility established; assume fresh authorization and separate storage | Must retain old session plus new authorization; never share engine databases |
| Update consistency | Delegate protocol sequence/gap handling to Telethon; add app projection and recovery | Library supplies ordered updates and manages local consistency | Reconcile two event streams and account bindings |
| Media | Existing explicit bounded downloads; implement missing features deliberately | Broader client primitives, still needs native renderer and lifecycle integration | Duplicate media caching/ownership decisions |
| Security | Known private SQLite/Keychain model; add bounded content cache intentionally | Requires handling TDLib encryption key and new local data lifecycle | Larger secret and state surface |
| Build/release risk | Existing Python runtime packaging remains unfinished | Add native TDLib build, dependencies, signing and arm64 integration | Carry both packaging stacks |
| License | MIT, retain required notices | Boost Software License 1.0; review distribution notice requirements | Satisfy both; Telegram API terms apply regardless |

TDLib's documented JSON interface correlates async requests using `@extra`; it
owns networking/storage and produces ordered updates. These are valuable client
primitives, but do not remove UI, policy, migration, or packaging work. Storage
encryption also needs a correctly protected application-provided key.
[TDLib overview](https://core.telegram.org/tdlib),
[TDLib interface](https://core.telegram.org/tdlib/getting-started).
License references: [Telethon MIT](https://raw.githubusercontent.com/LonamiWebs/Telethon/v1/LICENSE),
[TDLib Boost](https://raw.githubusercontent.com/tdlib/td/master/LICENSE_1_0.txt).
The session incompatibility assessment is a conservative integration decision,
not a claim that arbitrary extraction/conversion of auth keys is supported.

## Observed repository behavior before V3

`ipc.Backend._new_client` creates authentication clients with bounded retries and
`receive_updates=False`. `_authorized` verifies identity, disconnects that client,
then sequentially reopens the **same session** with runtime request/connection
retries zero, `auto_reconnect=False`, `flood_sleep_threshold=0`, and
`receive_updates=True`. It verifies identity again before creating TelegramService.
There is currently no application event handler registration, catch-up integration,
or message projection. Receiving transport updates alone does not update SwiftUI.
Disconnect/switch clears previews and increases account generation; all new event
work must follow that same boundary. Existing process ownership and private locks
remain mandatory.

`ChatFeatures.messages.list` fetches bounded pages on explicit requests. It does
not mark history read. Chat refresh saves dialog previews/unread counts to
`ChatStore.dialog_cache`; full history is not persisted. `media.download` explicitly
imports a known-size attachment up to 64 MiB. There is no typing action, sponsored
message workflow, or automatic reconnect/catch-up UI. Existing class docstrings
accurately say there is no application live subscription.

Telethon exposes public event handlers, `catch_up`, read acknowledgements and chat
actions. Its constructor documents retry, update ordering and cache controls.
Do not switch all runtime RPC retries on to obtain update recovery: delivery
uncertainty protections are independent and must stay intact.
[Telethon client API](https://docs.telethon.dev/en/stable/modules/client.html).
Event properties can lack sender/chat data; resolving them through async getters
can cause additional network requests. Handlers must avoid per-update entity
fetches and render unknown names until a bounded refresh resolves them.
[Telethon event guidance](https://docs.telethon.dev/en/stable/concepts/updates.html).
Session files contain authentication material and entity caches; preserve their
path and never export them through IPC or diagnostics.
[Telethon sessions](https://docs.telethon.dev/en/stable/concepts/sessions.html).

## Proposed minimal real-time increment

1. After runtime identity verification, create one update adapter capturing
   `(profile_id, account_id, account_generation, client_instance)`. Register public
   NewMessage, MessageEdited, MessageDeleted, MessageRead and UserUpdate/ChatAction
   handlers as needed. Call public catch-up only after handlers are installed.
   Let Telethon manage Telegram `pts/seq` and gap recovery; never edit session
   tables or implement competing protocol cursors. In installed 1.45, public
   `catch_up()` queues an update-gap signal and returns; its return is not an
   acknowledgement that replay finished. Do not label the app fully synchronized
   on that return. Establish displayed-data freshness through bounded snapshot
   recovery, without reading Telethon private internals. Telegram specifies ordered
   sequence tracking and differences for gaps.
   [Telegram updates](https://core.telegram.org/api/updates).
2. Handlers normalize only already-present data, perform no entity/media/history
   fetch, and enqueue lightweight immutable records into an application queue
   capped at 256. One worker projects updates in short transactions and emits
   scoped UI events. Coalesce repeated edits/read counts by peer/message; message
   identity is `(account, peer, message_id)`, never message ID alone.
3. Queue overflow must set a durable-or-session dirty marker and emit one
   `sync.required` control event. Never silently claim cache completeness. Cap
   pending invalidation peers; if that cap is exceeded mark the whole profile
   dirty. UI then requests bounded recovery for its visible chat and dialog page.
   Catch-up cannot repair application events already consumed and discarded by
   the projection, so recovery must refetch affected snapshots.
4. Initially persist only existing dialog cache fields plus necessary monotonic
   read/last-message metadata. Keep message bodies for the active conversation in
   bounded memory (suggest 200 rows), no automatic attachment downloads. A later
   persistent message cache requires explicit TTL/deletion support and additive,
   transactional, idempotent schema tests before approval.
5. Stop intake, remove registered handlers, cancel/await worker and clear volatile
   content before disconnect/switch/removal. Check captured scope both before
   enqueue and before commit/emission. Cancel stale queued UI requests via existing
   generation checks. Never mutate the newly selected profile through an old task.
6. Reconnect must be one coalesced lifecycle operation. Start with explicit user
   Retry; after successful reconnect emit `sync.required`, fetch visible bounded
   data once and resume handlers. A future automatic policy may retry only
   connection/update recovery with bounded backoff and cooldown checks, never
   message delivery. Expose offline/catching-up/ready/dirty states honestly.

Proposed JSONL contracts, to implement only after the planning gate:

- `updates.watch {account_id}` / `updates.unwatch {account_id}` enables scoped
  native consumption; no arbitrary user-specified subscription callbacks.
- Events `{event:"chat.changed"|"message.changed"|"message.deleted"|"read.changed"|
  "typing.changed"|"sync.required", data:{profile_id,account_id,account_generation,
  sequence,peer_id,...}}`. Application `sequence` detects IPC projection loss;
  it is **not** Telegram `pts`. Edited messages replace matching cached rows;
  deletes invalidate preview/content even when not currently visible.
- `sync.snapshot {account_id,peer_id?,limit:1..100}` gives scoped authoritative
  bounded projection and dirty state. Do not promise completeness beyond that page.
- Terminal/control events must survive the lossy progress path. Bound writer queue;
  if control cannot be delivered, close transport and force explicit resync rather
  than block forever or silently lose a deletion.

Tests must cover duplicate/edit/delete ordering, missing optional entity fields,
queue overflow with snapshot repair, offline/catch-up transitions, stale generation
at every await, disconnect under backpressure, profile-specific SQLite writes,
read/typing semantics, and unchanged uncertain-delivery reservations. Use mocks
and fixture-owned subprocesses; no real sends.

## Read, typing and content compliance

Normal client presentation must not offer a stealth/ghost mode. Announce during
onboarding that viewing a focused conversation marks displayed messages read and
active composition sends typing status. Selection in a sidebar, background sync,
previews and draft restoration are not evidence that messages were viewed.

Propose `messages.read {account_id,peer_id,max_id}` only after visible incoming
rows are rendered while the conversation/window is active. Validate the frontier
against the displayed page; debounce/coalesce to its maximum, never acknowledge
unseen history. Use Telethon's supported read acknowledgement, accounting for
channel-specific behavior. Incoming read updates update local delivery indicators.
[Read-history semantics](https://core.telegram.org/method/messages.readHistory).

Propose `messages.typing {account_id,peer_id,active}` from actual user editing in
a focused composer. Throttle active indications, expire promptly, send cancellation
on blur/switch/idle, and never derive typing from restored drafts or background
work. Display incoming typing with a short expiry and no persistence. These
requests have no message body and never grant send approval.
[Typing semantics](https://core.telegram.org/method/messages.setTyping).

Telegram's client terms disallow interfering with ordinary read/typing behavior;
name transparency also requires **Unofficial** before Telegram in an app title,
and the official logo must not be used. Rename visible product metadata and
review icon provenance separately; do not rename session/storage paths.
[Telegram API terms](https://core.telegram.org/api/terms).

## Sponsored content: release blocker, not an optional enhancement

Official guidance requires requesting sponsored messages when opening a channel
**or bot conversation**, caching the response for five minutes, and honoring
presentation, impression, click and reporting behavior. Global peer search has
additional sponsored-peer requirements; cached local search is different. Video
ads add timed visibility rules. Treat implementing a bare fetch as insufficient.
[Sponsored-message specification](https://core.telegram.org/api/sponsored-messages).

Installed Telethon 1.45.0 was inspected locally without network calls:
`messages.GetSponsoredMessagesRequest(peer,msg_id=None)`,
`ViewSponsoredMessageRequest(random_id=...)`, and
`ClickSponsoredMessageRequest(media=None,fullscreen=None,random_id=...)` exist.
SponsoredMessage includes text/entities, title/URL/button, sponsor/additional info,
optional photo/media/color, reporting capability and duration bounds. The result
includes posts-between and video-delay fields. Supported generated constructors
therefore exist; a compliant renderer and view/click/report lifecycle do not.

**Smallest safe interim scope:** block opening channel and bot content until that
workflow is implemented. Enforce backend checks before history/media APIs, not
just disabled native controls. Suppress their message previews in cached dialog
responses/events; preserve old records on disk rather than destructively migrate.
Retain channel/bot identity metadata to explain the limitation. Validate actual
entity bot/channel flags before content retrieval; old cached private records may
not distinguish bots. Prevent bypass through channel/bot media downloads, selected-history, and
future direct content routes. Forwarded messages shown in otherwise supported
conversations need a separate semantics review; do not invent API requirements.
Treat unsupported/unknown entity classification conservatively.

A later supported-content implementation needs server-issued scoped ad handles
(random IDs remain backend-owned), five-minute per-peer cache, native labeled
cards with original entities and sponsor info, visibility-triggered view reports,
user-click reports, reporting UI, and mock tests for every path including empty
results/premium behavior. Do not fabricate ads, report invisible impressions, or
silently ignore ad errors and continue reading. No claim of client-terms compliance
or distributability follows from this design document alone.

## M2 contract/test specification (implementation gate still closed)

The following shapes are proposals for the next milestone, not routes that exist
in the current build. M1 native-shell validation must pass before implementation.

All event `data` carries `{profile_id:string,account_id:int,
account_generation:int,sequence:int}`. Sequence starts at one for each adapter
instance and strictly increases for published updates. The GUI clears volatile
message/typing state on scope change and ignores mismatched events. It treats a
sequence gap as dirty, requests a bounded snapshot, and never merges across
accounts. Account ID is mandatory on new mutation/watch/snapshot requests.

Request responses:

| Request | Required / bounded parameters | Result |
|---|---|---|
| `updates.watch` | `account_id` | scope, `watching:true`, `sequence`, `dirty` |
| `updates.unwatch` | `account_id` | scope, `watching:false` |
| `sync.snapshot` | `account_id`; optional `peer_id`, `limit` 1–100 | scope, `sequence`, `dirty`, bounded `chats`; if peer selected, bounded `messages` |
| `messages.read` | `account_id,peer_id,max_id`; `max_id` positive Telegram message ID previously returned as visible | scope, `peer_id,max_id`, `acknowledged:true` only on API success |
| `messages.typing` | `account_id,peer_id,active:bool` | scope, `peer_id`, `accepted:bool` (false when coalesced/throttled) |

Candidate normalized message shape extends existing `messages.list` rows without
removing fields: `{id,text,sender_name,sender_id,date,outgoing,media,edit_date,
reply_to_id,reply_to_peer_id,grouped_id,views,forwards,reactions,read_outbox_max_id}`.
`reactions` is a bounded list `{emoji:string?,custom_emoji_id:int?,count:int,
chosen:bool}`; unsupported/unknown reactions remain absent rather than invented.
Message-level read state is unknown until an actual read frontier is known.
`media` remains metadata only, with `{kind,name,size,mime_type}` where available;
no bytes, local paths, access hashes, file references or download tokens in events.
Reply IDs are scoped by peer. Cross-peer reply availability must not trigger an
implicit history fetch. Unsupported/empty optional fields use null or empty lists.

Event-specific additions:

- `message.changed`: `{peer_id,message,change:"new"|"edit"}`.
- `message.deleted`: `{peer_id:int|null,message_ids:[int]}`. Telegram can omit the
  peer for a private/basic-chat deletion. Do not guess a peer or delete every row
  sharing an ID across unrelated scopes. Invalidate the current profile's affected
  projection conservatively and require snapshot recovery if ambiguous.
- `chat.changed`: `{peer_id,chat}` with the existing sanitized dialog row.
- `read.changed`: `{peer_id,max_id,outbox:bool}`.
- `typing.changed`: `{peer_id,user_id,active,expires_at}`; no persistence.
- `sync.required`: `{reason:"overflow"|"reconnect"|"ambiguous_delete"|"gap"}`;
  no raw Telegram exception or private request representation.

`content_policy.py` should expose pure `classify_entity(entity,account)` and
`project_dialog(row)` plus async `require_content_peer(client,account,destination)`.
Known ordinary users, Saved Messages, basic groups and supergroups are eligible
for supported content. Broadcast channels and bot users return a fixed
`content_unavailable` error explaining sponsored support is pending. Unknown peer
classification returns the same conservative gate. Identity listing remains
possible; old cached rows lacking explicit bot classification suppress previews
until a supported classification is verified. Expose `content_available` and
`content_reason` so the native app explains a disabled row. The shared async guard
must be callable by future media/client-action modules before content retrieval.

Test matrix for M2 acceptance:

1. New/edit/delete, Unicode and combining sequences; missing sender/entity/media;
   reactions/replies/read-frontiers normalized without triggering network getters.
2. Known channel/bot/unknown content blocked before `iter_messages`, `get_messages`
   or download invocation; legacy cached previews hidden without modifying records;
   ordinary users/groups/saved remain usable; identity-only rows retained.
3. Handlers registered once on the runtime client and removed on every disconnect;
   authentication client never subscribes; catch-up called after registration;
   catch-up return alone does not set synchronized state.
4. Queue at capacity, repeated edit coalescing, dirty marker, control backpressure,
   closed stdout, and snapshot recovery; deletions are never silently discarded.
5. Switch before handler entry, during worker await, before SQLite commit and
   before IPC emission; stale adapter cannot touch the new store or emit new scope.
6. Duplicate IDs across peers/accounts, ambiguous deletes, dirty startup snapshots,
   cancellation, cooldown persistence and reconnect all preserve existing ledgers.
7. Read only returned visible frontiers for the active scope; reject future/foreign
   IDs, no read effects from list/search/background refresh. Typing requires an
   explicit true boolean, actual foreground request, per-peer throttle, expiry and
   cancellation, with no message content or automatic send attached.
8. IPC malformed/unknown fields, strict booleans/integers/limits, concurrent watch
   and switch, bounded stdout and parent-exit cleanup continue to pass existing
   process tests. All cases use mock network and isolated storage.
