from dataclasses import asdict, dataclass, field
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

    def data(self) -> dict:
        return asdict(self)
