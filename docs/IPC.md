# Native application IPC, protocol version 1

Launch `python -u -m telegram_manager.ipc` with `PYTHONPATH` pointing to the checkout's `src`. The Swift process owns stdin/stdout pipes, with no listener or HTTP service. The Python process holds the same private-directory application lock as the CLI and opens the existing `manager.sqlite3` and `account.session` paths. Cached reads work immediately using the bound account ID; connecting restores authorization and never automatically discovers, inspects or sends.

Each UTF-8 newline-delimited request must have exactly:

```json
{"id":"a-unique-UUID","method":"status","params":{}}
```

IDs are unique for the entire backend process, 1–64 ASCII letters/digits/underscore/hyphen. At most 64 requests are active/queued. Frames are limited to 1 MiB; duplicate JSON keys and nonfinite numbers are rejected. At 100,000 used request IDs, the backend requires a new process request session. Methods have exact key/type/range validation. No shell commands, expressions or arbitrary Python code are accepted.

Success: `{"id":"...","ok":true,"result":{...}}`.
Error: `{"id":"...","ok":false,"error":{"code":"...","message":"safe explanation"}}`.
Errors never include exception args, request reprs, phone numbers, codes, passwords, API hashes or session bytes. Unknown startup/framing errors may have `id:null`.

Progress: `{"event":"progress","request_id":"...","data":{"phase":"discovery|inspection","index":1,"skipped":false,"group":{...}}}`. Progress is bounded and intermediate events may be dropped under output backpressure; final results and SQLite counters are authoritative. No terminal banners or diagnostic logs appear on stdout. Diagnostic events go to stderr.

## Methods

- `health {}` → protocol/version/Python status.
- `status {}` → `connected`, `auth_stage`, safe `account:{id,display_name}|null`, `bound_account_id`, account-scoped `overview`, `scan`, `cooldown_until`, `remaining_seconds`, `session_present`.
- `connect {}` → status. Reads existing environment/Keychain credentials, restores the existing session, or requests the next auth step. No credential entry is overwritten.
- `auth.credentials {api_id:string,api_hash:string,save?:bool}` → status. Saving uses macOS Keychain's non-overwriting native API; no plaintext fallback.
- `auth.phone {phone:string}`, `auth.code {code:string}`, `auth.password {password:string}` → status. All sensitive values travel only through the owned process pipe and never return in responses. App forms must clear these fields after submission.
- `auth.bind {account_id:int,confirm:true}` → status. Only the verified account can be explicitly bound. A different existing binding is rejected.
- `groups {query?:string,permission?:all|allowed|denied|unknown,sort?:name|id|checked_at|members,kind?:all|group|supergroup,page?:int,size?:int}` → `groups`, `total`, `page`, `size`. Page starts at zero; size 1–100. Rows add `effective_permission` and `metadata_fresh` to stored metadata.
- `detail {destination:int}` → cached `group`; no network lookup.
- `inspect {destination:int}` → freshly inspected `group`.
- `discover {}` → `processed`, persisted `scan`; lightweight dialogs only.
- `inspect_pending {limit:int,destinations?:[int],force?:bool}` → `inspected`, `scan`; bounded sequential inspection, maximum 100.
- `draft.get {}`, `draft.save {message:string}` → draft `message`, `updated_at`. Empty drafts can be saved; sending requires 1–4096 UTF-16 units. Drafts are sensitive private SQLite content, not credentials.
- `approvals {query?:string}` → approved `groups`. `approval.set {destination:int,approved:bool}` explicitly approves/revokes an existing group. Technical posting permission never implies approval.
- `preview {destination:int,message:string}` → one-use `token`, `expires_at`, destination, exact message, fresh group metadata, `confirmation:"SEND <id>"`, UTF-16 count. Requires existing approval and current posting permission.
- `send {token:string,confirmation:string}` → result `message`, latest `delivery`. Token expires in 120 seconds and is consumed even on incorrect confirmation. Token binds account, destination and exact message. Approval is checked again; existing TelegramService performs fresh authorization/identity/permission checks and atomic deduplication before sending. Never retry a timeout or uncertain result.
- `history {query?:string}` → up to 100 account-scoped `deliveries`.
- `settings.update {cache_policy?:{basic?:int,permissions?:int,members?:int,metadata?:int},inspection_limit?:int}` → full settings. Cache TTLs are 0–31536000 seconds; limit 1–100. Explicit changes persist atomically in private `desktop-settings.json`, never in the account-binding configuration, and trigger no requests. Environment values supply initial defaults; saved GUI preferences then take precedence for this GUI backend only. CLI environment behavior is unchanged.
- `settings {}` → storage location, version, Python, cache policy, inspection limit, session flag, binding, credential-source label and security flags. No secrets.
- `storage.backup {destination:string}` → verified SQLite-only backup; existing files are not overwritten. Session/Keychain are not exported.
- `diagnostics.export {destination:string}` → sanitized diagnostic file; no credentials or group/message content.
- `cancel {request_id:string}` → cancellation requested. Original request receives `cancelled`; already committed progress remains. Cancellation after submission can leave an uncertain ledger entry.
- `shutdown {}` → shutdown acknowledged, active tasks cancelled, Telegram disconnected, SQLite closed. EOF has the same cleanup effect. Closing stdout cancels work; it does not trigger reconnect/retry. Production writes use nonblocking OS pipe readiness, not a blocking worker thread. Task cancellation and output draining have bounded shutdown waits; cancellation responses may be dropped during shutdown or backpressure.

Authentication stages are `disconnected`, `credentials`, `phone`, `code`, `password`, `bind_account`, `connected`. Login uses the existing supported bounded migration retries, then sequentially reopens the same session with zero request retries before enabling delivery operations. Network/mutating operations serialize under one lock; cached reads and health/status remain available during discovery. The GUI must never automatically replay failed requests or sends.

Compatibility aliases: `groups.list`, `groups.get`, `destinations.list`, `destinations.approve`, `destinations.revoke` (the last two accept only `destination`).

## Account profiles and current context

The existing envelope remains protocol version 1; methods and optional result fields are additive. All account-bound results add `profile_id` and `account_generation`. Progress data includes the same context. See [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md) for filesystem isolation, legacy compatibility and safety semantics.

- `accounts.list {include_archived?:bool}` → `profiles`, `active_profile_id`, `status`. Each profile includes `profile_id`/`id`, label, display_name, nullable verified `telegram_id`, `legacy`, `archived`, `is_active`, `session_present`, `auth_state`, `logout_confirmation`, `remove_confirmation`.
- `accounts.add {label?:string,confirm:true}` → list/status plus `created_profile_id`; creates and activates an isolated profile **offline**.
- `accounts.switch {profile_id:string,confirm:true}` → list/status; switches offline after serialized work finishes/cancels. Use `connect {}` explicitly to restore the selected session.
- `accounts.disconnect {profile_id:string,confirm:true}` → list/status; selected active connection only, preserving server authorization and local files.
- `accounts.logout {profile_id:string,confirmation:"LOG OUT <profile_id>"}` → list/status; selected active session only, with fresh identity verification before public `auth.LogOutRequest`. Preserves session files, Keychain and database; server authorization is revoked.
- `accounts.archive {profile_id:string,confirm:true}`, `accounts.restore {profile_id:string,confirm:true}` → list/status; reversible local registry visibility. Existing retained Telegram IDs remain unique across archived profiles.
- `accounts.remove {profile_id:string,confirmation:"REMOVE <profile_id>"}` → list/status; deletes only the selected non-legacy profile directory and its Keychain item, after closing/locking/validating that scope. Local ledger/drafts/approvals are deleted by this explicit operation. Original account removal is refused. This is not a server logout. Deleted data cannot be restored through `accounts.restore`.

Local IDs are `legacy` or `profile_<32 random hex digits>`, never paths or phone numbers. Profile identifiers stay stable after Telegram verification. Unknown IDs, traversal-like values, duplicate Telegram identities, incorrect phrases, unsafe linked profile trees and foreign-owned registry files are rejected. The process caps active local profiles at 50. A registry record for removed data cannot be switched to, so no empty bound ledger is recreated.

## V3 conversation/client method families

The envelope remains version 1. `ChatFeatures`, `UpdatePipeline`, `ConversationActions`, `ClientFeatures` and `MediaPreview` register explicit method allowlists in the same router. Network and mutation methods use the shared operation lock and generation check; direct local SQL/session access is not a GUI API. See [CHAT_API.md](CHAT_API.md) for the exact parameters, result fields and limits of every method below.

| Family | Registered methods |
|---|---|
| Dialogs and bounded history | `chats.list`, `chats.refresh`, `chats.saved`, `messages.list` |
| Local conversation drafts and labels | `chatdraft.get`, `chatdraft.save`, `chatdraft.delete`, `chatdraft.list`, `labels`, `label.set` |
| Personal/Saved Messages text/reply | `chat.preview`, `chat.send` |
| Scoped live state | `updates.watch`, `updates.unwatch`, `sync.snapshot`, `messages.read`, `messages.typing` |
| Confirmed own plain-text edit/delete-for-me | `message.action.preview`, `message.action.commit`, `message.operations` |
| Read-only people and organization | `contacts.list`, `contacts.refresh`, `contacts.open`, `profile.get`, `folders.list`, `folders.refresh` |
| Explicit file save and static image viewer | `media.download`, `media.preview.get`, `media.preview.release` |

A cached channel/bot title does not enable reading its messages: channel/bot content remains unavailable while official sponsored-message support is absent. Restricted/protected/unknown/TTL or unsupported content is refused or represented without body/media. History, reply, mutation and media routes validate the actual returned peer/message ID. A visible group cannot enter the personal-send/action routes; managed groups retain approval and fresh permission checks.

Personal, managed and message-action previews are distinct token kinds. Tokens bind exact account/profile/generation and target/body/action, expire after 120 seconds and are consumed on incorrect confirmation. Draft edits invalidate relevant tokens; same-body autosaves preserve matching previews. Action commit additionally checks the unchanged original and reserves a separate persistent operation-ledger entry. Delete-for-everyone, bulk actions and automatic uncertain retries are not exposed.

Contacts/profile/folder DTOs exclude phone numbers, access hashes, session material and arbitrary raw objects. Contacts require authoritative membership and are projected to at most 1000; profile reads require own/cached identity; Telegram folder definitions are read-only metadata, not implemented membership filtering or editing. JPEG/PNG preview paths are generated private cache files, not arbitrary path-read requests. Upload, avatar download, video/audio playback and complete Telegram parity are not provided.

## Live event contract and backpressure

Example event envelope:

```json
{"event":"message.deleted","data":{"profile_id":"legacy","account_generation":2,"account_id":123,"stream_id":"opaque-runtime-stream","sequence":7,"peer_id":456,"message_ids":[89]}}
```

Runtime event names are `chat.changed`, `message.changed`, `message.deleted`, `read.changed`, `typing.changed`, and `sync.required`. They do not use a request ID. Every live event includes the frozen account/profile/generation, stream ID and strictly increasing projection sequence. Payload fields and watch/snapshot methods are specified in [CHAT_API.md](CHAT_API.md#scoped-live-updates-repair-read-and-typing).

Clients must reject mismatched scope/stream and old sequence numbers. A gap, ambiguous deletion or `sync.required` means the projection is dirty: preserve drafts, clear unsafe active content/confirmations as appropriate, and request a matching snapshot. Snapshot success covers its bounded selected scope, not the freshness of all cached groups/dialogs. There is no busy polling or automatic send replay. Normal visible-read acknowledgements and actual user typing are distinct deliberate client behaviors; fetching/hydrating text alone does not authorize them.

Replaceable progress events may be dropped when the bounded output queue is full. Live control events cannot be silently dropped: a full control queue fails the transport and forces scoped recovery. The update ingress queue is bounded at 256; message/tombstone projection is bounded at 200. Backend teardown removes old handlers and cancels projected work. A new connection has a new stream ID even if it restores the same persistent session.

## Data and lifecycle guarantees

The original database, session paths, account bindings, cooldowns, approvals, send deduplication and delivery ledger remain in use. Additive derived tables cover dialog/contact/folder caches, drafts/local labels and the separate `conversation_operations` ledger. Cached reads stay account-scoped. Account switches clear authentication/preview/projection/image context and reject queued old-generation mutations rather than silently rebinding them.

Image previews enforce known compressed size up to 8 MiB, four cache files, private filesystem permissions and recorded inode ownership for recovery; general explicit attachment saving is bounded at 64 MiB. Backend preview expiry is lazy on cache access, plus release/close/invalidation cleanup, with native viewer expiry handling. No absolute-time secure-erasure guarantee is made. Neither database backup nor diagnostics exports session/Keychain secrets.

See [BACKEND_LIFECYCLE.md](BACKEND_LIFECYCLE.md), [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md), [CHAT_API.md](CHAT_API.md) and [VALIDATION.md](VALIDATION.md) for process ownership, exact methods and actual test evidence. Mocked and native-model tests do not prove live Telegram operations or genuine graphical acceptance.
