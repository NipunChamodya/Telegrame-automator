"""Non-secret configuration and credential resolution."""
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .security import MacKeychain


@dataclass(frozen=True)
class Credentials:
    api_id: int
    api_hash: str = field(repr=False)

    @classmethod
    def parse(cls, api_id: str, api_hash: str) -> "Credentials":
        if (not re.fullmatch(r"[0-9]{1,10}", api_id) or not 0 < int(api_id) <= 2147483647
                or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash)):
            raise ValueError("Invalid API credentials. API ID must be a positive integer; hash must be 32 hex characters.")
        return cls(int(api_id), api_hash)


def data_directory() -> Path:
    # Keep the original location even on Linux to preserve existing installations.
    return Path(os.environ.get("TGM_DATA_DIR", str(
        Path.home() / "Library/Application Support/TelegramGroupManager")))


def keychain_service(root: Path) -> str:
    suffix = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
    return f"org.telegram-group-manager.credentials.{suffix}"


def load_configuration(root: Path) -> dict:
    path = root / "config.json"
    if not path.exists():
        return {"version": 1, "account_id": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("version") != 1
                or type(data.get("account_id")) not in (int, type(None))):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise ValueError("Invalid configuration. It was left untouched; recover config.json from a backup.") from None


def bind_account(root: Path, config: dict, account_id: int) -> None:
    if config["account_id"] is not None and config["account_id"] != account_id:
        raise ValueError("Session account differs from the configured identity. No data was changed. "
                         "Restore the matching session or use a separate data directory.")
    path = root / "config.json"
    if config["account_id"] == account_id and path.exists():
        return
    updated = config | {"account_id": account_id}
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(updated, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # All writers hold the application lock. Never overwrite an existing binding.
        if path.exists():
            if load_configuration(root) != config:
                raise ValueError("Configuration changed during startup; it was not overwritten.")
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic creation; fails if another file appeared.
        config.update(updated)
    finally:
        Path(temporary).unlink(missing_ok=True)


def resolve_credentials(root: Path) -> tuple[Credentials | None, str]:
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if api_id is not None or api_hash is not None:
        return Credentials.parse(api_id or "", api_hash or ""), "environment"
    keychain = MacKeychain(keychain_service(root))
    value = keychain.read()
    if value is None:
        return None, "unset"
    try:
        data = json.loads(value)
        return Credentials.parse(str(data["api_id"]), data["api_hash"]), "macOS Keychain"
    except (ValueError, KeyError, TypeError):
        raise ValueError("Saved Keychain credentials are invalid. They were not overwritten.") from None
