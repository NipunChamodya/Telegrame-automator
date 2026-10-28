# User guide

Telegram Group Manager is a native macOS interface over the existing Python/Telethon application. It uses your personal account. Nothing discovers, inspects, approves destinations or sends messages merely because you open a screen.

## Launch the development app

From the checkout:

```sh
./macos/build.sh Debug
open macos/build/Build/Products/Debug/TelegramManager.app
```

The app starts its own backend; do not start another CLI/backend for the same data directory. The CLI remains available as `python3 main.py` when the desktop app is closed. If Python dependencies are missing, the CLI offers approved virtual-environment setup; the app does not install packages globally.

This build is a local development application. Follow [DESKTOP.md](DESKTOP.md) and [VALIDATION.md](VALIDATION.md) for its actual runtime/signing/launch status. Successful compilation alone does not verify graphical launch or live Telegram access. A relocatable embedded runtime and distribution acceptance testing are separate work.

## First connection

1. Open the app and choose Connect if a session was not restored.
2. If credentials are required, obtain your API ID/API Hash at [my.telegram.org](https://my.telegram.org), then **API development tools**. These are application credentials, not a bot token or login code.
3. Use the hidden fields for secrets. Save credentials to macOS Keychain only when you approve that choice. Existing credentials are not silently replaced.
4. Enter your phone number with its country code. For Sri Lanka, use `+947XXXXXXXX`, replacing X with digits and omitting the domestic leading `0`. Spaces, hyphens and parentheses are accepted.
5. Check the verified Telegram service chat in an already signed-in Telegram app for the code. Telegram controls delivery; SMS or another method is not guaranteed. The developer portal's login code is different from this application's code.
6. Enter the Telegram two-step verification password if requested.
7. Confirm the verified account identity before binding a new installation/profile. A session that does not match the expected account is blocked rather than silently rebound.

Do not share an API Hash, code, password or session file with anyone helping debug the application. Subsequent launches reuse saved authorization where available; they do not deliberately delete the session to force another login.

## Dashboard and cached groups

The dashboard shows actual backend statistics and cache state, not sample values. The first group scan is deliberately lightweight: it discovers supported dialogs and saves names, IDs and basic metadata. Therefore many new groups initially show **Unknown**. This is expected until an explicit permission inspection finishes.

- **Allowed:** a recent technical permission snapshot says text posting is permitted.
- **Denied:** Telegram reported a restriction or inaccessible membership.
- **Unknown:** the application cannot reliably verify permission, or the permission snapshot expired.

Allowed does not mean permission to advertise or send unsolicited messages. Human rules and moderation-bot policies may remain unknown. A row becoming visible never triggers a detailed Telegram request.

## Group browser and inspection

Search by group name, username or Telegram ID. Filter by permission/type and sort using the available native table controls. Select a row to read cached details; copy the actual Telegram ID when needed. Sinhala, Tamil, English, combining characters and emoji remain Unicode; unsafe display controls are sanitized without changing the stored name.

Use Discover to refresh basic dialogs. Use the explicit inspection action for one selected group or a bounded pending/expired batch. Choose the batch limit deliberately; the backend enforces 1–100 and defaults to 10. It does not interpret `all` as authority to inspect or send to every group. Completed results persist if a later group fails.

Inspection is sequential. Member counts, permissions and optional metadata have different cache lifetimes. A fresh cache is reused for non-forced inspection, while selected send destinations always receive fresh checks. Some metadata is simply unavailable through Telegram and remains unknown.

## Compose and confirm one message

1. Write plain text in the multiline editor or explicitly import a regular UTF-8 file.
2. Check the UTF-16 count and validation message. Telegram text is limited to 4096 units; emoji may use multiple units.
3. Save the draft when you want it retained. Drafts are private account data stored in plaintext in the protected database; destination selection and a send confirmation are separate.
4. Explicitly approve one destination. Approval is not inferred from an Allowed permission label.
5. Choose that approved destination and request Preview/Verify. Review the complete message, exact account/destination and current restriction information.
6. Type the exact confirmation phrase shown by the backend and choose the single-send action.
7. Review the delivery result and history. Do not repeat an uncertain send automatically.

Changing the account, message or destination must invalidate the applicable preview. Previews expire and are single use, including failed confirmation attempts. The backend checks identity, permission, slow mode and approval again before submission, then reserves the exact message/destination in its deduplication ledger. There is no bulk-send confirmation.

Imports are size-bounded, regular UTF-8 files; symlinks, devices, FIFOs and malformed text are rejected. A typed message is never implicitly treated as a filename: the CLI likewise separates direct composition, file import and cancellation.

## Accounts and lifecycle safety

Choose an account explicitly in Accounts and verify its displayed identity before working. The original `legacy` profile retains its existing directory, session and database. New profiles have stable random local IDs and private directories under `profiles/`, with separate session, database and Keychain namespaces. Switching clears connection/authentication state and preview tokens; queued requests from the previous account generation are rejected. A Telegram identity already bound to a retained profile cannot be bound again to evade its delivery ledger.

These actions have different meanings:

| Action | Meaning |
| --- | --- |
| Disconnect | Close the active connection while keeping local state and Telegram authorization available for later restoration. |
| Switch account | Change the active account context; clear account-bound previews/selections and restore only that profile's state. |
| Telegram logout | Explicitly revoke the selected account's Telegram authorization using the supported backend operation. Local history is not automatically deleted. |
| Archive profile | Hide a new profile reversibly, retaining its database, session and credentials. |
| Remove local profile | Permanently delete only the selected new profile directory and its Keychain entry after the exact `REMOVE <profile_id>` confirmation. This cannot remove the original legacy profile. |
| Restore archived profile | Make a retained profile available again through an explicit supported action. |

Read each account-specific confirmation. Telegram logout requires `LOG OUT <profile_id>` and preserves the local session file and delivery history while revoking server authorization. Archive and permanent removal are separate operations; back up before removal. Do not use account switching to circumvent Telegram cooldowns or restrictions. See [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md) and [IPC.md](IPC.md) for the contract.

## Chats, drafts and history

Chats loads the cached conversation list first. Explicit refresh reads a bounded dialog page (up to 100), and selecting a conversation reads a bounded message page. Search/filter the cached list by conversation type or title. No detailed group permission requests happen merely because rows become visible.

Personal chats and Saved Messages support text preview, exact confirmation, and optional reply-to message ID through the same persistent delivery ledger. Managed groups retain the approved-destination composer and fresh permission checks; personal-chat sending cannot bypass that workflow. Explicit media download accepts a selected message, a new destination filename and known files up to 64 MiB, without overwriting existing files. Edit, delete, forward, upload and avatar caching are not implemented.

Saved drafts and send previews are different. A draft can be restored for composition; it never carries standing send permission. Conversation drafts support save, restore, list and delete, scoped to both the account and conversation. Local group labels are application metadata and do not modify Telegram. Switching either must not submit the previous conversation's text.

History records acknowledged, rejected, blocked or uncertain delivery attempts using the existing ledger. Older records may have no message preview or Telegram message ID. `Sent` means acknowledgement, not that every recipient read it. A timeout, cancellation, process exit or network failure after submission may leave `pending`/`uncertain` even when Telegram accepted the message. Inspect Telegram manually before considering another action. Never delete ledger records to defeat duplicate prevention.

## Cooldowns, cancellation and connection failures

A FloodWait is a server instruction to wait. The deadline persists and the UI shows remaining time. There is no automatic resume, aggressive retry, proxy/account rotation or restriction bypass. After expiry, explicitly continue the desired operation. Partial scans and completed inspections remain saved.

Cancel stops pending work where possible, not an already accepted Telegram operation. Cancelling a send cannot prove it was not delivered. Check history before another attempt.

A closed backend pipe, process failure and Telegram transport failure are different conditions. Use the typed error and safe diagnostic location. Reconnect explicitly if the backend permits it, or quit/relaunch to restore the existing session. The app must not replay a send on recovery. If the output pipe itself is closed, a CLI cannot keep rendering; restore output and relaunch.

## Settings, backups and diagnostics

Use Settings for appearance, launch preferences, cache/batch controls, account/session status and storage information. Backups use SQLite's backup API and include committed database content, not Keychain credentials or a session export. Backups can contain private drafts, cached content, previews and destination metadata: keep them private.

Diagnostics export contains safe version/platform/schema/security information, not API hashes, session contents, phone numbers, group names or message bodies. Do not replace it with raw exception dumps. `TGM_DEV_MODE=1` enables limited sanitized development source locations for the CLI; it is not permission to share private files.

For incident handling and data protection, read [SECURITY.md](../SECURITY.md). For actual tested/unverified features and known launch limits, read [VALIDATION.md](VALIDATION.md).

## Connection recovery panel

When disconnected, use the displayed explanation to distinguish backend startup failure, disconnected Telegram, expired authorization, or required setup. **Retry Connection** restores the service or continues the secure authentication flow; it does not delete sessions or databases. Retry is disabled while a connection or another operation is in progress. **Manage Accounts** opens the isolated account list. **Connection Diagnostics** shows a selectable sanitized local summary and recovery instructions; it does not export credentials or initiate Telegram requests.

Cached groups, drafts and delivery records remain available offline. Live discovery, permission checks and sending require a connected account. If the backend exits during a send, inspect the delivery ledger and Telegram before taking another action: reconnecting does not retry that message.


## Backend unavailable or another instance running

The new connection panel explains the current state. Choose **View Diagnostics** to inspect local process readiness and a safe failure category; this does not start Python or expose Telegram secrets. Choose **Retry Connection** for one explicit attempt. Choose **Manage Accounts** to view the account screen; account-changing actions require the backend to be ready.

For an instance conflict, quit other CLI terminals or other Debug/Release copies normally before retrying. A previous version may have left an old backend; inspect the exact file user with the safe procedure in [BACKEND_LIFECYCLE.md](BACKEND_LIFECYCLE.md). Never delete a lock file while a process may own it, never reset your database/session, and never end all Python processes. A leftover file alone is harmless.

Closing the app waits for its own child to exit. Opening Settings shares the same backend; additional workspace windows are not created. Disconnect and logout preserve cached records and do not terminate the backend process. If Telegram requires a cooldown, wait for its deadline before explicitly resuming. Uncertain messages are never replayed by recovery.

The sidebar groups screens by purpose. The account menu shows the actual selected profile and connection state; its Disconnect and Logout entries open Accounts so you can review the selected account and confirm the correct operation. Delivery History can search, filter by status and sort the latest loaded 100 records locally; the count describes loaded records, not the entire ledger. Refresh reloads that bounded page without messaging Telegram. Activity records the latest 100 typed operations from the current app session and resets on relaunch; persistent delivery outcomes remain in History.


## Chats and the responsive workspace

Use the search field at the top of Chats to search cached names, usernames or IDs. The type menu narrows results locally. Use the arrows at the bottom of the list to page through cached conversations. The actions menu contains explicit Telegram refresh and Saved Messages; navigation does not refresh Telegram automatically.

On a wide window, the list and conversation appear side by side. On a narrow window, choose a row to open it and use Back to return to the list without discarding the selected conversation’s draft. Recent history loads only on explicit conversation selection/refresh; older pages remain bounded. Full names are available through row help and the selected conversation header.

Activity is a searchable timeline of the latest 100 operations in this app session, with timestamps, account context and statuses. It clears when the app exits and is separate from saved Delivery History. Processing counts appear only when actually returned; an uncertain/blocked delivery is not shown as a successful send.

History search/status/sort work on the latest 100 loaded ledger records; Refresh reloads those records. Select a row for message ID/error details. Unknown or pending outcomes are never automatically retried. Destinations shows only explicitly approved groups; Browse Groups is available inside its empty state. The account menu opens account management for confirmed disconnect/logout actions.
