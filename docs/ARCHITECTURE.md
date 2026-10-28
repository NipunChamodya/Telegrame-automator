# Architecture

## Boundaries

```text
Native SwiftUI / AppKit application
          │ owned stdin/stdout pipes
          │ bounded, identified JSON-line requests/responses/events
          ▼
Python IPC adapter (telegram_manager.ipc)
          │ reusable service operations
          ▼
Existing asyncio Telethon service ── macOS Keychain
          │
          └── SQLite metadata, drafts, approvals, cooldowns and delivery ledger
```

The numbered CLI remains a second presentation layer over the same Python modules. It does not run concurrently with the desktop backend against one private directory. Swift implements native presentation, state and process ownership; it does not implement Telegram authentication, MTProto requests or direct SQLite/session editing.

## Python modules

- `application.py`, `bootstrap.py`, `setup_wizard.py`: existing CLI initialization and secure authentication.
- `ipc.py`: strict local request dispatch, account context, safe authentication steps, preview/confirmation, progress, cancellation and process cleanup. See [IPC.md](IPC.md) for exact methods and fields.
- `accounts.py`: bounded private profile registry, stable identity bindings, isolated paths, archive/restore and separately confirmed local removal.
- `chat_features.py`, `chat_store.py`: cached conversation pages, explicit bounded history/media reads, per-conversation drafts, local labels and confirmed personal text/reply delivery.
- `telegram.py`: supported Telethon group discovery, membership/permission analysis, bounded detailed inspection and controlled delivery.
- `storage.py`, `models.py`: account-isolated SQLite records, small typed snapshots, idempotent upgrades and the atomic delivery ledger.
- `cache.py`: independent basic, permission, member-count and optional-metadata freshness policies. A cache does not authorize a send.
- `messaging.py`, `terminal.py`: bounded Unicode validation/import and safe CLI rendering.
- `security.py`, `configuration.py`: private storage, owner lock, native Keychain and non-secret binding/configuration.
- `maintenance.py`, `diagnostics.py`: private SQLite backups and sanitized diagnostics without credential/session export.

The runtime source of truth is Python. GUI state derives from responses rather than hardcoded counts. Switching context, connection recovery and account-profile operations must use the service contract rather than changing active account fields in Swift alone.

## V3 client components

The accepted [architecture decision](CLIENT_ARCHITECTURE_DECISION.md) retains Telethon and existing session files. Swift is still presentation, not a second Telegram implementation.

- `update_pipeline.py`: one current-client event adapter with profile/account/generation and stream identity; serialized bounded projections, gap detection, watch/snapshot/read/typing routes and conservative invalidation.
- `content_policy.py`, `message_projection.py`: verified peer/message scope, protected/unsupported/sponsored-content gates, bounded safe rich metadata and explicit unknowns.
- `conversation_actions.py`: fresh own-plaintext checks, exact one-use previews and additive `conversation_operations` ledger; does not change send reservations.
- `client_features.py`: account-scoped contacts/folder caches and explicit authorized profile reads. No participant enumeration or remote folder mutation.
- `media_preview.py`: explicit JPEG/PNG download, scoped tokens, private bounded files, crash-index ownership and invalidation. Preview bytes are sensitive local plaintext.

The update adapter never fetches full history/participants/media in callbacks. Control-event overflow fails the transport rather than silently losing a deletion. The native projection bounds loaded messages at 200, guards late snapshots against newer events, and clears unsafe content on gaps/disconnect/account changes. A bounded snapshot does not certify complete Telegram synchronization. Read frontiers derive from actual visible incoming messages; typing reflects focused user edits. See [CHAT_API.md](CHAT_API.md).

Original tables remain unchanged. New derived `contact_cache` and `telegram_folder_cache` tables are additive; `conversation_operations` records action digests/status without message bodies. No session conversion, original-ledger reset or account-binding migration occurs.

## Native application

The UI repair uses one root-owned native `HSplitView` for persistent application navigation and content. Chats adapts its conversation list/detail within that content region. One root toolbar belongs to the native unified titlebar; page searches are inline. Group details use a sheet, not an additional adaptive navigation column. SceneStorage restores only the local screen identifier once; no send preview or remote action is restored. See [FULL_UI_AUDIT.md](FULL_UI_AUDIT.md).

`BackendClient` is an actor managing one `Process`, bounded framing, request continuations, deadlines, cancellation and process-generation checks. Backend stderr is drained without retaining arbitrary library logs. SIGPIPE/EOF/termination paths are treated as process/transport failures, never as permission to replay an operation.

`AppModel` lives on the main actor. It maps protocol results to observable screen state and clears/invalidate previews as their inputs change. `LiveProjection`, `MessagePresentation`, `ClientFeatures` and `ImagePreviewReader` separate bounded client state and off-main image validation from screen presentation. `Views` use native navigation, tables, text editors, sheets and semantic status labels. Expensive I/O stays outside the UI actor. Liquid Glass is availability-gated and applied selectively; tables and long text retain readable native surfaces.

The source tree separates `App`, `Models`, `Services`, `ViewModels`, `Views` and `Resources`. Runtime lookup prefers a bundled runtime when genuinely present, then the explicitly configured development checkout. A venv elsewhere on disk is not a portable distribution runtime.

## Discovery and inspection

Lightweight discovery streams dialogs, identifies supported basic groups/supergroups, includes archives and excludes broadcast-only/migrated duplicates. It saves basic records incrementally without a per-row detailed lookup. Cache visibility does not mean posting is allowed.

Detailed inspection is explicit, sequential and batch-limited. It uses supported membership/rights types, optional metadata and separate timestamps. Missing information remains unknown. Basic-chat full metadata is reused for membership; supergroup checks use a single-member request, not participant enumeration to find bots. A FloodWait stores a persistent deadline and stops; continuation requires an explicit user action after expiry.

## Storage and account isolation

Original group, delivery and cooldown tables remain authoritative. Additive tables support sync progress, saved drafts, explicit approvals and bounded delivery previews. SQL values are parameterized; group pages and recent history are bounded. Schema upgrades must remain idempotent and preserve old IDs, hashes, random IDs, cooldowns and uniqueness constraints.

Account identity is verified against the session/binding before enabling a service. Every cached query and state mutation must use the active verified account context. Any profile implementation must preserve the legacy installation and keep account-specific session/Keychain/state references separate. `account-profiles.json` records stable local profile IDs and verified Telegram identities. The `legacy` profile keeps the original root; new `profile_<32 hex>` profiles store isolated `account.session`, `manager.sqlite3` and preferences under `profiles/<id>/`, with a directory-derived Keychain namespace. Duplicate retained Telegram identities are rejected. Profile switching runs under the mutation lock, increments a generation and invalidates preview/auth/chat context. Requests capture the generation when accepted and reject stale mutations. Archive is reversible; removal separately confirms deletion of one new profile only.

## Delivery transaction

1. Compose/save a draft without sending.
2. Explicitly approve/select one destination.
3. Request a complete preview and fresh eligibility check.
4. Confirm the exact destination phrase shown by the backend.
5. Consume the account/message/destination-bound preview token once.
6. Recheck account identity, membership, restrictions and slow mode.
7. Commit the deduplication reservation before the MTProto submission.
8. Record acknowledgement/rejection or retain `pending`/`uncertain` on interruption.

There is no bulk confirmation, automatic replay, anti-spam bypass or cross-account reuse of a preview. Cancellation before submission is distinct from an unknown outcome after submission.

## Validation layers

Python unit tests cover service/storage/security behavior with mocked Telegram. Real subprocess tests cover strict Unicode framing, malformed requests, concurrent cached reads, exclusive ownership, EOF and shutdown using temporary storage. Swift tests cover models, validation, state and fixture-process transport. Builds, actual window launch, graphical accessibility tests and live Telegram acceptance are separate claims recorded in [VALIDATION.md](VALIDATION.md).

See [DESKTOP.md](DESKTOP.md) for build/runtime boundaries and [SECURITY.md](../SECURITY.md) for the threat model. No production memory, throughput, distribution or live-authentication guarantee is inferred from these layers.
