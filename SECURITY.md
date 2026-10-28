# Security policy and operating model

This application controls a personal Telegram account. The Python service, its SQLite database, macOS Keychain access and native IPC transport are security-sensitive. A native UI does not remove the need for explicit authorization.

The supplied project repository is [NipunChamodya/Telegrame-automator](https://github.com/NipunChamodya/Telegrame-automator). No maintainer email, legal identity, private reporting channel or project license is invented here. If the repository offers GitHub private vulnerability reporting, use that enabled feature. Otherwise request a private reporting channel with a high-level, non-exploitable description; never post secret material publicly.

## Protected information

Treat these as sensitive:

- Telegram API hashes, login codes, two-step verification passwords and phone numbers.
- Telegram `.session` files and related journal/WAL files. A copied authorized session may permit account access.
- Saved drafts, cached messages, destination approvals, group metadata, cooldowns and delivery records.
- Database backups and message previews. Filesystem modes protect access but do not encrypt their contents.

API credentials belong in the existing macOS Keychain integration, environment variables or short-lived process memory. They must not be saved in plaintext configuration, returned in IPC responses or embedded in application bundles. Python cannot guarantee erasing immutable secret strings from memory.

## Local storage and process ownership

The application uses its existing per-user Application Support directory, private directory/file permissions and exclusive owner lock. The CLI and GUI must not own the same session/database concurrently. SQLite uses short transactions, parameterized values, WAL and additive, idempotent schema upgrades. An incompatible or corrupt database is rejected rather than reset.

Account data must remain isolated by the verified account identity and, where account profiles are enabled, the active profile context. Do not infer identity from a display name. A session/account mismatch must block operations. Selecting a different account must never grant access to another account's drafts, approvals, history, previews or pending sends.

## Authentication and account lifecycle

Only Python/Telethon performs Telegram authentication. Supported bounded authentication retries permit Telegram data-center migration; normal delivery clients retain zero request retries. The application must not hardcode migration destinations or edit session database tables manually.

Disconnecting, Telegram logout, and local removal are distinct actions:

- Disconnect closes the current connection without revoking Telegram authorization or deleting saved data.
- A supported explicit Telegram logout may revoke authorization and alter the corresponding session through Telethon. It requires clear, account-specific confirmation and must not be applied to another account.
- Any local removal of credentials, sessions, account records or private files is destructive. It must be separately labeled and confirmed, with its exact scope stated. It must not be disguised as a reconnect/reset fix.

Do not remove sessions or databases just to troubleshoot network failures. Preserve data unless the user explicitly authorizes a supported destructive action. Documentation of a lifecycle concept is not a claim that every action is implemented; use the current [IPC contract](docs/IPC.md) and [user guide](docs/USER_GUIDE.md) for available controls.

## Sending trust boundary

A cached permission result is never the sole authority for delivery. A send requires an explicit selected destination, current account/identity verification, fresh technical permission and slow-mode checks, a complete message preview, and exact account/destination confirmation. Persistent destination approval expresses user intent but is not standing send authority.

The GUI obtains a short-lived, single-use backend preview token tied to the account, destination and exact message. Changing message, destination or account must invalidate the applicable preview. Revoking approval must prevent future use. The atomic delivery reservation commits before submission, preserving the original `(account, destination, exact-message hash)` duplicate protection and random request ID.

After a network failure, timeout, cancellation or backend exit during submission, delivery may be uncertain even when Telegram accepted it. Never automatically retry. Inspect the ledger and Telegram manually. Rate-limit waits persist and resume only after expiry and explicit user action. Account/proxy rotation, spam-limit probing and moderation bypasses are not supported.

## IPC and untrusted content

The native process owns stdin/stdout pipes to one backend child. There is no unauthenticated HTTP listener. Requests are bounded newline-delimited JSON with strict method/parameter validation, unique identifiers, typed errors and cancellation. Arbitrary shell/code execution is not an IPC operation.

Backend stdout contains protocol frames only. Logs go to stderr without raw request objects, exception payloads, locals or secrets. Development diagnostics report limited source locations and safe attribute names; they are not raw tracebacks. Exported diagnostic snapshots omit message bodies, account identifiers, group names, credential contents and session data.

Group names and message files are untrusted text. Preserve Unicode while preventing executable terminal controls. File imports must be bounded regular UTF-8 files, not symlinks, FIFOs or devices. Native UI display must not execute markup or shell content. Database/diagnostic exports use explicit output paths, private non-overwriting publication and safe backup methods; no generic credential export is offered.

## Packaging and validation limits

The development build is not represented as a distributable, notarized, App-Sandbox-contained product. Packaging requires a verified relocatable Python runtime/dependencies, correct nested signing, resource verification, notarization/stapling and testing on a clean Mac. Never include sessions, databases, `.env`, private configuration or Keychain material in a bundle.

Automated tests use synthetic records and mocked Telegram requests. Real local subprocess tests verify framing and lifecycle without contacting Telegram. See [the validation report](docs/VALIDATION.md) for actual results and launch restrictions. Do not treat a mock, successful build or screenshot as proof of live account security or server authorization behavior.

## If a secret or session is exposed

Stop sharing the affected files/logs, revoke compromised Telegram sessions through Telegram Settings → Devices, and secure the local macOS account. Use the official Telegram account controls to review access. Do not upload the session for debugging or delete the delivery ledger to work around duplicate protection. Preserve a private incident record without reproducing secret contents in public reports.

## Supported versions

Version 0.3.0 is a development preview on the currently tested branch. Security fixes target that branch; no long-term maintenance or security guarantee is offered. Earlier 0.2 releases have not been independently reassessed here and should not be assumed to receive ongoing fixes. Build/test results are recorded separately from live Telegram acceptance and distribution readiness.

Managed-group sends require fresh Telegram posting-permission inspection and explicit destination approval. Personal-chat and Saved Messages sends instead require a cached personal destination, a fresh verified account identity and fresh peer validation, plus an exact single-use preview/confirmation. They cannot route managed-group destinations around the group workflow. A technical capability to send never establishes consent to unsolicited messages.
