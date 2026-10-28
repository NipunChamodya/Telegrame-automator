# V3 incremental client plan

This is an upgrade of the existing application, not a new Telegram engine. The baseline is Python 216 tests/59 subtests and native 44 tests from V2. Official interface research and the Telethon/TDLib decision precede implementation. Existing session paths, account bindings, private locks, Keychain scopes, CLI and delivery records stay unchanged.

## Acceptance gates

| Milestone | Scope | Gate before proceeding |
| --- | --- | --- |
| M0 reference and architecture | Official sources, parity matrix, licensing/terms, existing-code audit, retain Telethon decision | Documents reviewed; limitations/source access recorded |
| M1 messaging shell | Chats default; native conversation first, Advanced Workspace retains tools; unofficial visible branding, original icon | Native build/state tests; no storage identifier changes |
| M2 live conversation foundation | One bounded account/generation-scoped update adapter, rich safe message serialization, update-loss recovery, sponsored-content/protected-media gates | Python mocked ordering/overflow/isolation tests and native projection tests |
| M3 conversation actions | Personal text reply/edit/delete with exact scoped confirmation and persistent uncertain-outcome protection; managed groups remain stricter | Mocked permission/account/duplicate/cancellation/security tests; no live mutation |
| M4 people, organization and media | Explicit contacts/profile reads, clearly local views, safe explicit static-image preview; disclose unsupported remote folder/media features | Bounded/private storage tests and native model/build tests |
| M5 validation and documentation | Complete regression suites, native Debug/Release, real graphical attempt, truthful parity/README/release boundaries | Record actual passes/failures/blocked checks; no fabricated screenshots |

Only completed, tested increments may be described as implemented. Later milestones may be split or deferred if the preceding security/consistency gate cannot be met. This plan does not authorize a TDLib migration, arbitrary session conversion, remote account changes or live message sends.

## Messaging boundary

Ordinary personal/Saved Messages composition remains inline in the conversation. Existing explicit message preview/account/destination confirmation and deduplication remain. Managed group destinations still require approval and fresh technical permission checks; normal visibility never authorizes a send. Editing/deleting messages requires a separate exact-account and message confirmation, not standing approval. The existing send ledger is not repurposed to invent new sends for edits/deletes.

## Content and terms boundary

Visible naming becomes Unofficial Telegram Manager; product/bundle/storage/Keychain IDs remain stable. No official logo/source assets are copied. The existing independent bubble/check logo provides a distinct direction.

Channel/bot reading is not compliant merely because a generated sponsored-message fetch exists. Until native presentation/reporting is implemented, unsupported content must be gated at backend routes and removed from returned previews/events, preserving stored legacy rows. Expiring/protected/view-once content must not enter general downloads or preview caches. Unknown semantics are unavailable rather than guessed safe.

No hidden read/typing mode is planned. Visible read acknowledgements and actual focused-composer typing must be explicit supported UI/backend interactions, not a background poll or fabricated presence. Incoming indicators derive only from Telegram events.

## Explicitly not a parity promise

Calls, secret chats, stories, payments/Premium/Business, video/audio/sticker rendering, uploads, synchronized folder mutation and sponsored-content playback need separate working implementations and tests. TDLib evaluation is documented, not a migration. Distribution remains a separate embedded-runtime/signing/notarization/clean-Mac acceptance task.


## Execution outcome (2026-10-28)

M0 through M4 were implemented incrementally. M1 gate: 217 Python tests/59 subtests and 49 native tests. M2 gate: 248/87 and 63 native. M3 gate: 270/118 and 69 native. M4 backend gate: 299/133. Final native/build/graphical results are recorded in [VALIDATION.md](VALIDATION.md), superseding intermediate counts.

These completed milestones are a bounded V3 foundation, **not completion of every feature in the vision**. Sponsored channel/bot content, calling, secret chats, stories, full rich media, uploads, forwarding controls, cloud drafts and folder mutation remain incomplete. Full graphical acceptance, live Telegram validation and portable distribution remain separate gates. The implementation does not silently downgrade those requirements to compile-only success.
