# Conversations, drafts, labels and personal sends

These methods use the existing [strict IPC envelope](IPC.md). Results add the active profile ID/generation. Network and mutation methods use the same operation lock as discovery, account switching and managed sending. Cached reads do not connect to Telegram.

## Dialog cache

- `chats.list {query?:string,kind?:all|private|group|supergroup|channel|saved,page?:int,size?:int}` returns `chats`, `total`, `page`, `size`. Size is 1–100; search includes cached Unicode name/username/ID metadata. Rows contain `id`, `name`, `kind`, optional `username`, unread count, bounded last-message preview, timestamp, archive flag and cache time.
- `chats.refresh {limit?:int,after?:int}` explicitly retrieves at most 100 dialogs using supported `iter_dialogs`, includes archived dialogs, skips migrated duplicates, and saves rows incrementally. It returns `processed`, `limit`, `possibly_more`, `next_cursor`. Pass the returned last-dialog ID as `after` only on a separate user-requested continuation. Cursor state must exist in this account's cache and contain a last-message ID/date. Refresh without a cursor starts at recent dialogs. This is not a complete-count guarantee and does not delete old cached rows.
- `chats.saved {}` explicitly verifies the current identity and creates/returns its own `saved` cache entry as `chat`. It does not load message history or send anything.

Unlike managed-group discovery, chat browsing includes broadcast channels for **reading**, not managed sending. No full participant list or avatar is downloaded by these methods. Last-message previews are sensitive plaintext in the private SQLite cache.

## Message pages

`messages.list {destination:int,limit?:int,offset_id?:int,search?:string}` requires a cached destination and a freshly verified authorized identity. It returns at most 100 messages, `next_offset_id` and `has_more`; the desktop requests 50 and retains at most 200 loaded rows. `search` is an explicit remote Telegram search, not an automatic background operation. Empty search reads recent history. Pass the returned offset on a separate older-page request.

Rows contain `id`, Unicode `text`, available `sender_name`/`sender_id`, `date`, `outgoing`, and optional media description (`kind`, available `name`, `size`). Missing sender metadata remains unknown; there is no per-message sender lookup loop. Recent message pages are not persisted to SQLite. Telegram controls access and may return restricted/inaccessible/network/rate-limit errors. Completed dialog cache writes survive partial refresh failures.

## Conversation drafts and local labels

- `chatdraft.get {destination:int}` returns destination/message/updated_at; missing drafts return an empty body.
- `chatdraft.save {destination:int,message:string}` saves at most 4096 UTF-16 units locally, including whitespace while composing. Empty input deletes the conversation draft. An unchanged-body save preserves matching preview tokens; an edited body invalidates relevant personal previews.
- `chatdraft.delete {destination:int}` explicitly deletes that account/conversation draft.
- `chatdraft.list {}` returns the 100 most recently saved conversation drafts, with available cached titles.
- `labels {}` returns up to 1000 account-scoped destination/label rows.
- `label.set {destination:int,label:string,enabled:bool}` applies/removes a local label (1–40 safe characters) on an already discovered managed group. It does not change Telegram settings or send a request.

All tables are additive: `dialog_cache`, `conversation_drafts`, `local_labels`. Values are SQL parameters; original group and delivery tables are untouched. The GUI debounces local draft saving by 800 ms and flushes account compositions before switching. This cannot guarantee recovery of unsaved keystrokes if the entire process crashes before persistence.

## Personal text preview and send

`chat.preview {account_id:int,destination:int,message:string,reply_to?:int}` verifies the selected account and cached personal/Saved Messages destination, resolves the current user entity, validates the message and returns:

- One-use opaque token and 120-second expiry.
- Exact verified account ID, destination, text and optional reply-message ID.
- Exact confirmation phrase `SEND <destination>`.

`chat.send {account_id:int,token:string,confirmation:string}` consumes the token even on a bad confirmation. It rejects expired or wrong-account tokens, freshly checks identity/destination, commits the original `(account,destination,message hash)` duplicate reservation and submits one raw supported `messages.SendMessageRequest` with the persisted random ID. Optional reply uses `InputReplyToMessage`. Telegram rejections, cooldowns and uncertain transport outcomes are recorded. It never automatically retries.

These routes only accept private-user/Saved Messages destinations. Groups/supergroups/channels cannot bypass managed approvals through them. Managed groups use the existing `preview`/`send` workflow with fresh permission inspection. Token types cannot be interchanged. A personal chat being visible does not prove that Telegram will accept delivery; server restrictions are final.

## Explicit attachment download

`media.download {destination:int,message_id:int,path:string}` verifies identity, requires a cached conversation and retrieves the selected message's attachment only. Known declared size must be 1–64 MiB. Streaming writes enforce that size; inaccurate/unknown/oversized attachments are rejected. It emits bounded download progress events with current byte count and total.

The user chooses a new local output filename. The backend creates a private temporary file in that folder, verifies complete length, fsyncs and atomically publishes without overwriting an existing file. Cancellation/failure removes temporary content. No untrusted remote filename becomes a filesystem path. There is no automatic download, unbounded media cache, upload endpoint or automatic file execution. Downloaded files are not scanned for malicious content; opening them remains a separate user action.

## Current limits

Copying text and personal replies are implemented. Editing, deleting and forwarding Telegram messages, document/image upload, rendered media previews and avatar downloading are not implemented. Notifications are opt-in generic operation notifications; per-account quiet mode and incoming-message notification delivery are not complete. All development verification uses mocks, never live sends.
