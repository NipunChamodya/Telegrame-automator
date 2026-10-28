# Contributing

The supplied repository is [NipunChamodya/Telegrame-automator](https://github.com/NipunChamodya/Telegrame-automator). This identifies the repository namespace only; it does not establish a legal name, organization, contact address, or project license. These documents do not assign licensing terms.

## Before changing code

Read [the architecture](docs/ARCHITECTURE.md), [IPC contract](docs/IPC.md), [security model](SECURITY.md), and [validation report](docs/VALIDATION.md). Preserve the existing CLI and Python service. SwiftUI is the native presentation layer; it must not implement a second Telegram client or directly manipulate Telegram session tables.

Keep changes focused. Include a concrete trigger and expected behavior, explain whether database state changes, and add a regression test at the boundary where the defect occurred. Optional Telegram metadata must remain unknown when unavailable. Never treat a visible conversation or technical posting permission as approval to send promotional content.

## Local setup

Use Python 3.13 or newer and the project's virtual environment. The guided CLI can create the environment with explicit approval:

```sh
python3 main.py
```

Development dependencies can be installed into that environment:

```sh
.venv/bin/python -m pip install -e '.[dev]'
```

Do not install into system Python. API credentials, phone numbers, verification codes, passwords and session files are not development fixtures. Use synthetic data and mock Telethon network calls.

## Python validation

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m compileall -q main.py src tests
.venv/bin/python -m ruff check main.py src tests
```

Report unavailable tools and skipped tests explicitly. Do not turn skipped integration tests into passing feature claims. Tests that create subprocesses must use temporary `TGM_DATA_DIR` storage, bounded timeouts, explicit cleanup and no `connect`/authentication operations against Telegram.

## Native development

On a Mac with an appropriate Xcode/macOS SDK:

```sh
./macos/build.sh Debug
./macos/test.sh
./macos/build.sh Release
```

The Xcode project is `macos/TelegramManager.xcodeproj`, scheme `TelegramManager`. The development app starts its own Python subprocess; do not manually launch a second backend for the same data directory. Use `TGM_NO_AUTO_CONNECT=1` and isolated storage for offline native checks. See [desktop build notes](docs/DESKTOP.md) for runtime lookup and distribution boundaries.

A successful compile is not evidence that a window launched, that a screenshot was captured, or that live authentication works. Record actual build/test commands and distinguish mocked operations, real local-process checks, graphical tests, and live Telegram acceptance tests. Genuine UI screenshots must come from the running application with synthetic or explicitly approved data, never fabricated mockups or a desktop containing private information.

## Safety requirements for changes

- Preserve account isolation for metadata, drafts, approvals, cooldowns and delivery records.
- Clear or invalidate account-bound previews and in-memory selections when account context changes.
- Preserve exact destination confirmation, fresh permission checks, atomic deduplication, random IDs and uncertain-outcome handling.
- Serialize Telegram mutations and keep queues, requests, result pages and inspection batches bounded.
- Never replay a send after timeout, cancellation, process death or a closed pipe.
- Keep stdout exclusive to framed IPC data; route sanitized diagnostics to stderr.
- Additive database upgrades must be idempotent and tested against prior schemas. Never silently reset or replace a database.
- Never commit `.env`, `*.session*`, `*.sqlite3*`, private backups, Keychain exports or diagnostic files containing secrets.

## Reporting defects

Use a minimal reproduction with synthetic account/group/message data and safe error codes. For ordinary defects, use the supplied repository's issue tracker if available. For security-sensitive reports, follow [SECURITY.md](SECURITY.md); do not publish credentials, message bodies, session files, or exploitable private data in a public issue.
