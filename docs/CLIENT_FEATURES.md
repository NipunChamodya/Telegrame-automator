# Contacts, profiles, folders and image preview

V3 development preview, 0.4.0. These are real backend/native integrations tested with mocked Telegram responses, not a full Telegram client or live-service acceptance result.

## Explicit people and organization reads

`client_features.py` exposes cached contacts and Telegram folder definitions without connecting on list operations. Refresh/open/profile routes require the exact active numeric Telegram account and serialize with account changes. Derived `contact_cache` and `telegram_folder_cache` tables use account keys and parameterized SQL; original group, draft, approval, delivery and cooldown records remain unchanged.

Contacts refresh uses supported `contacts.GetContactsRequest(hash=0)`. The server response has **no page-limit argument**; the application bounds its stored projection to 1,000 authoritative contact IDs and reports truncation/incomplete responses. Extra users in a response are not automatically classified as contacts. Cached search/page sizes are bounded. Public DTOs allowlist scalar fields: no phone numbers, access hashes or arbitrary cached nested objects return to Swift.

Opening a contact verifies the resolved user ID before adding its identity to the existing dialog cache. Profile lookup accepts the account itself, cached contacts or cached dialogs, verifies the returned peer and full-object identity, and returns available name/username/about/count/verified/photo-availability metadata. It does not download profile photos, enumerate participants, mutate contacts or expose private Telegram objects. Channels/bots can have identity metadata while content remains gated.

Folder refresh uses `messages.GetDialogFiltersRequest`. At most 100 read-only definitions and 1,000 explicit IDs per include/exclude/pinned list are projected. The result explicitly says `membership_supported:false`. No complete membership computation, synchronized folder editing or cloud-label claim is made. Local group labels and conversation-type filters are different features.

## Image-preview contract

Only explicit selected-message JPEG/PNG preview is supported. The backend checks the current identity, cached destination, resolved peer, returned message ID/peer and content policy before downloading. Protected, expiring, restricted, unknown and sponsored-content-gated peers are unavailable.

- Compressed size: known, positive, at most **8 MiB**; streaming enforces declared length.
- Private per-profile cache: at most **four** registered images; no automatic download.
- Native decoder: regular owned 0600 single-link file, no symlink/FIFO following, exact bounded byte count, single image frame, source at most **16 million pixels**, thumbnail at most **1,600 pixels** on its longest edge.
- ImageIO decoding runs off the main actor. One native viewer retains an image; a revision guard discards late download/decode results after invalidation or account change.
- JPEG/PNG signatures and declared types must agree. No document plugin, arbitrary Quick Look handler or shell execution is used.

Files are reserved with exclusive creation and indexed by generated filename/device/inode. Restart cleanup removes only validated indexed files still owned by the app; it preserves unexpected files or substituted inodes and reports a cache error. Symlinks, hard links and unsafe trees fail closed. This is ownership verification, not filesystem encryption.

Tokens bind account, generation, destination and message. Release, accepted edits/deletions, synchronization gaps, disconnect/runtime replacement and shutdown invalidate owned previews. Pending downloads are revision-guarded as well. Backend TTL is **900 seconds, checked lazily on cache access**. The native viewer also closes at its expiry deadline. A crash, OS failure or cleanup error prevents an absolute erasure-time guarantee; sensitive local files can remain until safe recovery. No secure-erasure claim is made.

Explicit Save As uses the existing separate known-size attachment route up to 64 MiB, with no-overwrite output. It does not turn unsupported protected content into a downloadable attachment. Uploads, audio/video players, animated stickers/GIF rendering, automatic avatar fetching and full-screen media collections remain incomplete.

## Evidence

`tests/test_client_features.py`, `tests/test_v3_media_security.py`, native `ClientFeaturesTests.swift` and existing isolation/update tests cover these contracts using temporary files and synthetic data. ImageIO tests decode real test-generated JPEG/PNG bytes; these are decoder fixtures, **not application screenshots**. See [VALIDATION.md](VALIDATION.md) for final counts and [UI_VALIDATION.md](UI_VALIDATION.md) for graphical limitations.
