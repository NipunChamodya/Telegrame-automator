from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Literal


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Group:
    id: int
    name: str
    kind: str
    permission: Literal["allowed", "denied", "unknown"] = "unknown"
    reasons: list[str] = field(default_factory=list)
    username: str | None = None
    members: int | None = None
    slowmode_seconds: int | None = None
    slowmode_next_send: int | None = None
    visible_bots: list[str] = field(default_factory=list)
    unknown_rules: list[str] = field(default_factory=lambda: [
        "Human rules, bot enforcement and account-wide spam limits cannot be fully determined."
    ])
    checked_at: str = field(default_factory=now)
    archived: bool | None = None
    membership: str = "active"
    discovered_at: str | None = None
    permissions_checked_at: str | None = None
    members_checked_at: str | None = None
    metadata_checked_at: str | None = None
    inspection_attempted_at: str | None = None
    metadata_status: Literal["complete", "partial", "unavailable", "error"] = "unavailable"

    def data(self) -> dict:
        return asdict(self)

    @classmethod
    def from_data(cls, data: dict) -> "Group":
        names = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})


@dataclass
class ScanReport:
    started_at: str = field(default_factory=now)
    finished_at: str | None = None
    state: str = "running"
    phase: str = "basic"
    kind: str = "discovery"
    last_basic: dict | None = None
    processed: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    inspected: int = 0
    cache_skipped: int = 0

    def data(self) -> dict:
        return asdict(self)
