# Native application IPC, protocol version 1

Launch `python -u -m telegram_manager.ipc` with `PYTHONPATH` pointing to the checkout's `src`. The Swift process owns stdin/stdout pipes, with no listener or HTTP service. The Python process holds the same private-directory application lock as the CLI and opens the existing `manager.sqlite3` and `account.session` paths. Cached reads work immediately using the bound account ID; connecting restores authorization and never automatically discovers, inspects or sends.

Each UTF-8 newline-delimited request must have exactly:

```json
{"id":"a-unique-UUID","method":"status","params":{}}
```

IDs are unique for the entire backend process, 1–64 ASCII letters/digits/underscore/hyphen. At most 64 requests are active/queued. Frames are limited to 1 MiB; duplicate JSON keys and nonfinite numbers are rejected. Methods have exact key/type/range validation. No shell commands, expressions or arbitrary Python code are accepted.

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

## V2 account profiles and chat integration

The existing envelope remains protocol version 1; methods and optional result fields are additive. All account-bound results add `profile_id` and `account_generation`. Progress data includes the same context. See [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md) for filesystem isolation, legacy compatibility and safety semantics.

- `accounts.list {include_archived?:bool}` → `profiles`, `active_profile_id`, `status`. Each profile includes `profile_id`/`id`, label, display_name, nullable verified `telegram_id`, `legacy`, `archived`, `is_active`, `session_present`, `auth_state`, `logout_confirmation`, `remove_confirmation`.
- `accounts.add {label?:string,confirm:true}` → list/status plus `created_profile_id`; creates and activates an isolated profile **offline**.
- `accounts.switch {profile_id:string,confirm:true}` → list/status; switches offline after serialized work finishes/cancels. Use `connect {}` explicitly to restore the selected session.
- `accounts.disconnect {profile_id:string,confirm:true}` → list/status; selected active connection only, preserving server authorization and local files.
- `accounts.logout {profile_id:string,confirmation:"LOG OUT <profile_id>"}` → list/status; selected active session only, with fresh identity verification before public `auth.LogOutRequest`. Preserves session files, Keychain and database; server authorization is revoked.
- `accounts.archive {profile_id:string,confirm:true}`, `accounts.restore {profile_id:string,confirm:true}` → list/status; reversible local registry visibility. Existing retained Telegram IDs remain unique across archived profiles.
- `accounts.remove {profile_id:string,confirmation:"REMOVE <profile_id>"}` → list/status; deletes only the selected non-legacy profile directory and its Keychain item, after closing/locking/validating that scope. Local ledger/drafts/approvals are deleted by this explicit operation. Original account removal is refused. This is not a server logout. Deleted data cannot be restored through `accounts.restore`.

Local IDs are `legacy` or `profile_<32 random hex digits>`, never paths or phone numbers. Profile identifiers stay stable after Telegram verification. Unknown IDs, traversal-like values, duplicate Telegram identities, incorrect phrases, unsafe linked profile trees and foreign-owned registry files are rejected. The process caps active local profiles at 50. A registry record for removed data cannot be switched to, so no empty bound ledger is recreated.

The backend now registers `ChatFeatures.METHODS` and `ChatFeatures.NETWORK` through the same strict router, serialization lock, cancellation, account-generation guard and framing. Chat APIs are listed below; implementations live in `chat_features.py`/`chat_store.py`. Account switches reconstruct the feature adapter against the new context and clear all chat/managed preview tokens. A same-body managed draft autosave preserves the matching token; editing that body invalidates managed tokens only. Managed sends require token kind `managed` as well as profile/generation/account/destination/message binding.


### V2 chat requests

- `chats.list {query?,kind?,page?,size?}` reads cached dialog summaries; kinds `all|private|saved|group|supergroup|channel`, pages zero-based, size 1–100.
- `chats.refresh {limit?:1..100,after?:int}` explicitly retrieves a bounded dialog page; returns `processed`, `possibly_more`, `next_cursor`. Continue explicitly with `after:next_cursor`. This is separate from managed-group discovery.
- `chats.saved {}` explicitly creates the active account's Saved Messages entry using verified identity; it sends nothing.
- `messages.list {destination:int,limit?:1..100,offset_id?:int,search?:string}` retrieves a bounded page on explicit selection/action. Returns message IDs/text/senders/dates/direction/available media metadata, `next_offset_id`, `has_more`. Full message history is not written to SQLite or automatically subscribed/polled.
- `media.download {destination:int,message_id:int,path:string}` explicitly downloads a known-size attachment of at most 64 MiB into a user-selected new file; uses a bounded temporary file and no-overwrite publication. No automatic attachment downloads or previews occur.
- `chatdraft.get {destination}`, `chatdraft.save {destination,message}`, `chatdraft.delete {destination}`, `chatdraft.list {}` manage per-account/per-conversation private local drafts. Same-body autosave preserves matching personal preview tokens; edits invalidate the corresponding token.
- `labels {}`, `label.set {destination,label,enabled}` manage local labels on discovered managed groups. Labels change no Telegram membership, permissions or administrator settings.
- `chat.preview {account_id:int,destination:int,message:string,reply_to?:int}` prepares a one-use, expiring personal-chat/Saved Messages preview. It validates live account identity and a cached personal destination. Groups/channels are refused and must use managed approvals.
- `chat.send {account_id:int,token:string,confirmation:"SEND <destination>"}` consumes that personal preview and revalidates identity/destination before the existing persistent delivery reservation. Optional reply IDs use public MTProto `InputReplyToMessage` rather than interpreting local UI list indices. Personal and managed preview tokens cannot cross send routes. No uncertain delivery is retried.
