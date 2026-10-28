# V3 validation plan

This plan follows the accepted [reference study](TELEGRAM_REFERENCE_STUDY.md). Cases below are requirements and future acceptance checks, not passing-test claims. M0 research is complete; M1 native-shell work precedes M2 client synchronization/actions. Runtime tests for unimplemented features must wait until the corresponding milestone lands. No live Telegram account, send, edit, delete, reaction or private-media download is authorized by this plan.

## Evidence rules

Use synthetic fixtures, temporary per-account directories, mocked Telethon calls and bounded subprocess timeouts. Verify behavior at the Python service boundary and strict IPC route, rather than testing only helper implementations. Record exact commands/counts. Distinguish unit/mocked integration, actual local subprocess, native model, graphical UI and separately authorized live acceptance. A compiled UI target is not a passing graphical test. Preserve the existing CLI, database/session format, account ledger and credentials.

Naming/branding checks establish only the checked facts: the visible application title must meet Telegram's unofficial-client naming requirement, the intro must disclose Telegram API use, and the artwork must have original provenance rather than reuse Telegram's official logo. This does not establish complete compliance with all platform terms. See the [API Terms](https://core.telegram.org/api/terms) and the reference study's concise summary.

## Milestone gates

| Milestone | Acceptance gate | Test boundary | Block further rollout when |
|---|---|---|---|
| M1 native shell | Stable navigation/selection; cached list from correct account; readable compact layout; no accidental networking from row rendering | Swift fixture/state, read-only Python queries, genuine fixture-only UI capture | Wrong account data, broken selection, inaccessible controls, fabricated screenshot evidence |
| M2 synchronization | Typed bounded events, authoritative update order, resync after overflow/gap, peer/account lifecycle | Mocked Telethon events + actual IPC subprocess | Lost/deleted message resurrected, unbounded queue, stale-account update accepted |
| M3 read/typing/content | Normal visibility/read semantics; typing lifecycle; explicit protected/ephemeral/sponsored-content gates | Mocked service/IPC + native visibility state | Hidden-read behavior, expired media export, channel posts shown through an ungated route |
| M4 message actions | One deliberate action at one exact account/peer/message scope; durable uncertainty; current capabilities | Adversarial service/IPC + native confirmation state | Wrong-peer action, stale preview, duplicate uncertain action, bulk mutation by implicit selection |
| M5 media/profile | Bounded file/decoder/cache behavior; verified peer identity; privacy-preserving cleanup | Temporary files, fake streams, cached fixtures | Path escape, expiry leakage, arbitrary URL/code execution, cross-account cache exposure |
| Release acceptance | CLI tests, native tests, Debug/Release builds, real graphical/keyboard/accessibility and separate installation checks | Actual tools with reported limitations | Untested embedded runtime, false live/performance/distribution claims |

## M1: navigation and cached state

- Every sidebar destination has a stable identifier and correct title. Selection remains stable across search/page changes where the selected record still exists; disappearing rows have a clear deselection state.
- Cached dialog/group queries distinguish basic groups, supergroups, personal chats, Saved Messages and broadcast channels. The managed-group list excludes unsupported destinations. Union queries do not duplicate the same ID.
- Account switch clears old selected peer, inspector, preview token, history window and transient action context. Draft preservation happens before switching, and cancelled pending tasks cannot submit a stale draft into the new account.
- Compact, standard and large fixture windows exercise long Sinhala/Tamil titles, emoji sequences, empty lists, offline states, real loading states and inline recoverable errors. Native list/history regions fill available height; composer and pagination controls remain reachable.
- Use 198 synthetic cached conversations for search/pagination/selection assertions, not hardcoded production counts. No test should authenticate or request Telegram just to display rows.
- Native account-menu Disconnect/Logout/Remove must route into the account-specific confirmation flow. No menu item may silently invoke logout or delete a profile.

## M2: ordered and bounded updates

| Case | Injected fixture | Required result |
|---|---|---|
| New/edit/delete ordering | Same peer, IDs and revision/timestamp metadata; edits arrive around page response | One current message model per ID; edit applied once; deleted record does not reappear from an older response |
| Duplicate events | Repeated identical update and repeated page boundary | Stable list/draft/selection, no extra ledger entry or repeated notification |
| Different peers | Same numeric message ID in two conversations | Events affect only their exact account/peer/message tuple |
| Account generation | Update queued before switch; delivered after switch | Rejected/ignored with no mutation of the new account's visible data |
| Disconnect/reconnect | Socket loss, cancellation, restored session and update gap | No automatic message replay; library-supported recovery; explicit stale/resync indication |
| Overflow | Producer exceeds bounded queue while consumer is slow | Bounded memory; coalescing or explicit resync-needed signal; no silent claim of fully synchronized state |
| Large history | Many bounded pages and live updates | Documented in-memory cap; no full-history fetch; keep scroll anchor and selected message where possible |
| Shutdown | EOF/closed pipe during event emission | Backend exits without orphaned work; no stdout contamination or unbounded drain |

Do not reimplement MTProto sequence recovery by guessing timestamps. Exercise supported Telethon lifecycle/events; let the client library own protocol state. An event acknowledged over IPC is not proof that the GUI applied it; test both transport and model application.

## M3: read, typing and restricted content

- **Read visibility:** only actually displayed active conversation content advances the read boundary. Search previews, background windows and cached lists must not masquerade as viewed history. Track maximum visible message ID per peer; use the proper public API for peer kind. A failed read request must not permanently fabricate server read state.
- **No hidden-read product mode:** no ghost-mode toggle, read-suppression advertising or claim of preserving unread status while browsing messages. Normal Telegram read semantics require a clear user-facing explanation.
- **Typing lifecycle:** send appropriate supported typing state only for current editing context, conservatively throttle and stop on blur/send/cancel/disconnect/switch. Ignore stale typing events after peer changes; no polling loop or background typing.
- **Presence:** distinguish last-known metadata from fresh status. Do not invent online state or suppress required status behavior. Privacy-restricted status remains unknown where appropriate.
- **Disappearing content:** inject TTL, expired, view-once and unknown ephemeral constructors. Ordinary text rendering, media download, search results, copy/export and caches must not retain or expose content beyond its permitted lifetime. Unsupported content needs a clear placeholder and no unsafe action button.
- **Protected content:** no-forward/no-save restrictions must survive serialization. Forward, copy/export and download routes must check actual relevant protection rather than relying on a hidden button in Swift.
- **Channel sponsorship:** until the complete official sponsored-message flow is supported, reject channel-content access at the backend. Exercise messages.list/search/media routes, aliases, stale cached kinds and direct IPC calls. Listing a cached channel title must not become a bypass for reading its posts. Do not claim complete platform compliance from a single gate.
- **Bots:** bot peers must not accidentally use a personal-only send route. A bot command, inline callback or external Mini App is a separate deliberate action; never execute untrusted URL, shell text or JavaScript from metadata.

## M4: message action safety

Test every action against wrong account, wrong peer, wrong message, expired/stale preview, malformed IDs, bool-as-int, extra/unknown parameters, duplicate frame IDs, missing confirmation, cancellation and active cooldown.

| Action | Required preconditions | Durable result and uncertainty checks |
|---|---|---|
| Text/reply | Exact preview body/destination/account, live identity, current allowed destination; reply target bound to peer/thread | Existing atomic deduplication/random IDs retained; transport failure after reservation remains pending/uncertain; no retry |
| Edit | Fresh target/capability/ownership; exact replacement preview and confirmation | Original target immutable in token; stale edit rejected or re-reviewed; success means server acknowledgement, not a guessed UI update |
| Delete | Exact selected IDs, correct peer-specific API, explicit local/all-participants scope | Declining confirmation performs no call; partial/uncertain outcome recorded; no whole-history fallback |
| Forward | Explicit source IDs and one destination; content protection respected; correct attribution | No implicit fan-out; per-message request identity; server/transport errors do not trigger copy-and-send fallback |
| Reaction | Allowed reaction/capability, exact peer/message, fresh account | Standard vs paid reaction distinct; no implicit spending; failed action restores honest current state |
| Pin | Current rights and exact target; notification semantics shown | No hidden bulk pin/unpin; administrator changes or deleted targets produce clear rejection |
| Upload/media send | Stable bounded selected file, exact destination/caption preview and explicit consent | Upload completion is not message delivery; interrupted submission uncertain; no automatic retry |

For each route, assert that an invalid request fails before the network mutation and before inappropriate ledger reservation. For uncertainty tests, deliberately raise after the durable reservation and assert that a second attempt cannot bypass the first outcome. Changing a draft must invalidate the relevant preview without invalidating unrelated account context.

## M5: files, caches and profiles

- Reject symlinks, FIFOs/devices, hard-link/foreign-owner surprises where relevant, missing parents, traversal and existing output destinations. Tests must not hang opening nonregular files.
- Enforce stream limits even if metadata lies, disappears or the producer writes a huge block. Check reported byte counts, temporary-file mode, cancellation cleanup and no-overwrite publication. Never pass untrusted attachment names as commands or unrestricted relative paths.
- Avoid unbounded decoded images: test large dimensions/pixel counts as well as compressed byte size. Unknown codecs/types show safe placeholders. Do not automatically open downloaded binaries or active documents.
- Keep avatar/media caches bounded and isolated by account/peer/resource identity. An avatar is not proof of account identity. Switching, logout and removal must not reveal another profile's cached content.
- Profile changes require live verified account identity and explicit exact changes. Reject attempted API hash/session export and arbitrary Keychain service selection. Account identity mismatch must block remote logout before any revocation request.
- A declined Keychain removal must preserve local profile files. Archive retains data; destructive removal affects only the confirmed new profile; the original legacy root remains protected.

## Regression and reporting checklist

Run the existing Python suite before and after each milestone. Add adversarial cases in `tests/test_v3_security.py` only after the relevant runtime contract exists. Use mocks for Telegram and Keychain; synthetic session bytes must never be handed to a real client. Preserve existing subprocess ownership/EOF, cooldown persistence, database upgrade and delivery-safety tests.

Run Python syntax checks, Ruff when available, Swift model/transport tests, and Debug/Release builds. Document unavailable tools. Graphical tests must run the real native app in DEBUG fixture mode with the backend process disabled; no replacement artwork counts as UI evidence. Current managed-host error 159 remains a known blocker until a genuine rerun establishes otherwise.

For every completed matrix item, report: implementing files; API/schema actually checked; unit/mock/subprocess/native/graphical/live evidence; failed/skipped checks; data/schema changes; remaining limitations. Never collapse these evidence types into a single “works” statement.
