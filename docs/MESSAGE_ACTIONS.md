# Confirmed personal-message actions

V3 adds a narrow edit/delete operation path separate from managed sending. API
construction was audited against installed Telethon 1.45, layer 229. Tests use
synthetic Telegram objects; no real message was edited or deleted.

## Scope

Only an existing cached personal/Saved Messages conversation and a freshly
verified own plain-text message are eligible. The backend checks the active
account, resolves a supported peer, validates the returned peer/message ID,
requires the actual sender ID to match the account, and rejects media, entities,
forwarded, inline-bot, channel/group, protected, disappearing and unsupported
content. `outgoing=True` alone is insufficient. Final Telegram edit-age and server
restrictions remain authoritative; no edit-time allowance is invented.

Delete is **for the current account only**, using `revoke=False`. It does not
remove the other participant's copy. There is no delete-for-everyone or bulk
operation parameter. The UI must use that wording even though its exact typed
phrase identifies the message and conversation.

## IPC

`message.action.preview` accepts:

```json
{"account_id":101,"destination":202,"message_id":7,"action":"edit","message":"Replacement text"}
```

For `action:"delete"`, omit `message`. The response includes an opaque one-use
120-second token, account/destination/message ID, original text, proposed text,
`delete_for_everyone:false` and an exact `confirmation` phrase. These are explicit
preview responses over the owned local pipe, not diagnostic exports.

`message.action.commit {account_id,token,confirmation}` consumes the token even on
incorrect confirmation. It checks profile/generation/account binding, refetches
the exact message, compares its original version and commits a reservation before
one raw edit/delete request. A stale preview must be prepared again. No automatic
retry is performed after timeout, cancellation or an uncertain response.

`message.operations {}` reads the selected account's latest 100 operation records.
This is not the send-delivery ledger.

## Persistence and uncertainty

The additive `conversation_operations` table has a validated unique key over
account, destination, message ID, action and digest. It stores no original or
replacement bodies. Acknowledged, rejected, pending and uncertain states are
preserved. Duplicate protection applies across backend/database restart; it is
not erased to offer a retry button. An unknown outcome requires manual inspection
in Telegram. Rejected actions also retain their duplicate reservation; a later
explicitly different edit has a different digest.

Original SQLite tables/records, send hashes/random IDs, approvals and cooldowns
remain unchanged. Telegram FloodWait persists its real duration before returning
an error. Database-only backup includes the new table automatically. Removing a
nonlegacy account profile remains a separately confirmed destructive operation;
this feature never deletes account/session files.

## Limits

Editing/deleting formatted/media/group/channel/forwarded/bot messages and deleting
for both participants are not implemented. Server behavior and live authorization
are not established by mocks. Fresh version checking reduces stale-preview risk;
Telegram's edit API does not provide this application an atomic compare-and-swap
across another device's concurrent mutation. The UI must not claim such a guarantee.
