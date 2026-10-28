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
