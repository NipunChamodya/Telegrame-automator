"""Independent cache lifetimes; none authorizes sending."""
import os
from dataclasses import dataclass
from datetime import datetime, timezone


def fresh(timestamp: str | None, ttl: int) -> bool:
    if not timestamp:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()
        return 0 <= age < ttl
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class CachePolicy:
    basic: int = 86400
    permissions: int = 900
    members: int = 3600
    metadata: int = 21600

    @classmethod
    def from_environment(cls) -> 'CachePolicy':
        values = {}
        for key in ('basic', 'permissions', 'members', 'metadata'):
            raw = os.environ.get(f'TGM_{key.upper()}_TTL_SECONDS')
            if raw is not None:
                if not raw.isascii() or not raw.isdecimal() or not 0 <= int(raw) <= 31536000:
                    raise ValueError(f'TGM_{key.upper()}_TTL_SECONDS must be 0–31536000 seconds.')
                values[key] = int(raw)
        return cls(**values)

    def details_fresh(self, group: dict) -> bool:
        return group.get('metadata_status') == 'complete' and all((
            fresh(group.get('permissions_checked_at'), self.permissions),
            fresh(group.get('members_checked_at'), self.members),
            fresh(group.get('metadata_checked_at'), self.metadata)))

    def inspection_due(self, group: dict) -> bool:
        if group.get('metadata_status') == 'complete':
            return not self.details_fresh(group)
        # Cache a confirmed unavailable/unknown result briefly too, rather than
        # hammering the same hidden metadata on each explicit pending refresh.
        return not fresh(group.get('inspection_attempted_at'), min(self.permissions, self.members, self.metadata))

    def permission(self, group: dict) -> str:
        permission = group.get('permission', 'unknown')
        return permission if permission in {'allowed', 'denied'} and fresh(group.get('permissions_checked_at'), self.permissions) else 'unknown'
