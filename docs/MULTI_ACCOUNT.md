# Multiple accounts and local profile isolation

The native app uses one Python subprocess and one active Telegram connection. It does not rotate accounts to evade restrictions. Switching profiles is an explicit user operation, serialized with all network/mutating work. Finish or cancel an active operation before switching; a switch queued behind work waits for that work to finish safely. No background discovery, permission inspection, message-history fetch or send is triggered by an account switch.

## Existing account compatibility

The original account is registered under local ID `legacy`. Its paths remain exactly:

```text
~/Library/Application Support/TelegramGroupManager/
    account.session
    manager.sqlite3
    config.json
    desktop-settings.json
    account-profiles.json       # New private registry
    profiles/
        profile_<32 hex digits>/
            account.session
            manager.sqlite3
            config.json
            desktop-settings.json
            manager.lock
```

`TGM_DATA_DIR` overrides the outer root as before. Registering the original installation does not move, rename, copy, reset or delete its session/database/binding. A CLI launched with the original data directory continues to use the original account. The native backend holds the original root lock for the whole process and also holds the active new profile's lock, preventing simultaneous CLI access to an active profile.

The registry contains version, active local profile ID, labels, verified Telegram account IDs, safe display names and lifecycle flags. It contains no API hashes, phone numbers, login codes, passwords or session keys. Local IDs are random and remain unchanged after verification; they never derive from a phone number or filesystem path supplied through IPC. New profiles use their own Keychain service derived from their own root. Existing environment API credentials may provide explicitly configured application-level defaults; they are not copied into plaintext files.

Every profile's SQLite database contains its own account-scoped groups, delivery ledger, cooldowns, drafts, approvals, dialog cache, local labels and conversation drafts. Switching closes the old connection/database, discards in-memory authentication/preview state, and opens the selected profile's database. It does not carry draft text, approvals or send tokens across profiles. Save an unsaved editor draft before switching; saved drafts are restored from the selected profile only.

A verified Telegram ID cannot be bound to another retained profile, including an archived one. Use the original profile or restore its archived entry. This prevents accidental duplicate ledgers for the same account. After explicitly deleting that profile's local data, registering that account again necessarily begins a new local ledger; the deletion confirmation warns about losing its prior history/deduplication records.

## User operations

- **Add Account**: explicitly creates an isolated local profile and activates it offline. Use Connect to restore any authorization or complete the existing credential/phone/code/2FA/binding workflow. Nothing is messaged automatically.
- **Switch Account**: explicitly activates the chosen profile offline. Existing session restoration is available through Connect. Known cached data can load without any Telegram request.
- **Disconnect**: closes the selected active connection locally. It preserves server authorization, local session, Keychain credentials, database and drafts. Reconnect can reuse the session.
- **Log Out**: requires the exact `LOG OUT <profile_id>` phrase. The backend checks the current connection and freshly verifies the live Telegram ID against the selected profile before issuing the public MTProto `auth.LogOutRequest`. It then disconnects. Unlike `TelegramClient.log_out()`, the adapter does not delete the session file. Telegram revokes that authorization, so preserved local session information will require login again. The API app credentials and SQLite records remain. A network interruption is marked `logout_unknown`; review Telegram Settings → Devices instead of blindly repeating logout.
- **Archive**: optional reversible removal from the normal account list, requiring explicit confirmation. Local files and Keychain remain. Restore makes the same stable profile visible again.
- **Remove Local Account Data**: requires exact `REMOVE <profile_id>` confirmation. This is different from Archive and Log Out. For a selected **non-legacy** profile, it disconnects/closes that profile, switches to the protected original profile if necessary, acquires its lock, validates the owned tree without following symlinks/hard links, removes its scoped Keychain item through native APIs, and deletes only its private directory. Existing files belonging to other profiles remain untouched. It does not revoke a remote Telegram authorization; use Log Out separately first if desired. This operation deletes that profile's local ledger/drafts/approvals/cooldowns. Make a secure backup if you may need them. The registry retains a tombstone without private session data. Restore cannot recreate deleted data.

The original `legacy` profile cannot be archived or removed through this API. Disconnect and explicit Log Out are available; both preserve its local files and original binding. Removing a profile with a linked, foreign-owned, missing or actively locked directory fails rather than broadening the deletion scope. Keychain access denial prevents local file removal. An I/O failure during deletion can leave the selected profile partially removed; no filesystem/Keychain deletion can be rolled back atomically across both systems. Other profiles remain outside the operation's scope. Restore that selected profile from a secure backup or inspect it manually before retrying.

## Request generations and delivery safety

Every status/result includes `profile_id` and `account_generation`; progress events include them in their data. The protocol captures the generation when a request is **accepted**, before it can wait behind another operation. Queued mutations from an old generation are rejected as `account_changed` after a switch/disconnect/logout. Cached account reads also reject old accepted generations. The UI clears account-bound state and ignores stale results/events across profile switches.

Switching/disconnecting/logging out clears every managed-group and personal-chat preview token. Managed-group tokens additionally bind the local profile, generation, verified Telegram ID, destination and exact message; personal previews bind the verified account and destination, and share the same global invalidation. Managed tokens cannot be used on personal-send routes or vice versa. Idempotent autosaving of an unchanged draft keeps its matching preview; changing the body invalidates the relevant token. Every send still requires a fresh preview, the exact `SEND <destination>` confirmation, fresh Telegram checks and the persistent unique delivery reservation. No uncertain message is retried automatically, including after a profile switch.

## Recovery and security limits

- Missing/corrupt registry or a missing bound profile database is never silently reset. Restore a valid backup; no empty replacement ledger is created.
- API credentials remain in the existing native Keychain namespace for each profile, or in memory/environment when explicitly chosen. No credential export exists.
- `account.session` can authorize account access. Files stay mode 0600 and profile directories mode 0700. Disk/FileVault and macOS account security still matter; these are not database encryption.
- Database-only backups include private draft and message-preview data but omit session/Keychain authorization. Treat backups as sensitive.
- Registry changes are atomic, idempotent and refuse conflicting external edits. Filesystem deletion is explicit and limited to validated random-ID profile directories.
- Current verification uses isolated fixtures and mocked Telegram/Keychain calls. No live account addition, switch, logout or removal was executed during development. Actual server logout and native Keychain removal still need a controlled, explicitly approved account smoke test.
