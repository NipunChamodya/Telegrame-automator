import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

from .models import Group, now
from .cache import CachePolicy, fresh


class DuplicateMessage(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.validate()
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def validate(self) -> None:
        if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("Database integrity check failed.")
        expected = {
            "groups": {"account", "id", "name", "metadata"},
            "deliveries": {"id", "account", "destination", "digest", "random_id", "status",
                           "created_at", "updated_at", "detail"},
            "cooldowns": {"account", "until_epoch"},
        }
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and not set(expected).issubset(tables):
            raise sqlite3.DatabaseError("Incomplete or incompatible database; no reset was performed.")
        for table, columns in expected.items():
            if table in tables:
                actual = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
                if not columns.issubset(actual):
                    raise sqlite3.DatabaseError("Incompatible database schema.")
        if "sync_runs" in tables:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(sync_runs)")}
            if not {"account", "data"}.issubset(columns):
                raise sqlite3.DatabaseError("Incompatible synchronization metadata table.")
        if "deliveries" in tables:
            unique_columns = []
            for index in self.db.execute("PRAGMA index_list(deliveries)"):
                if index[2] and not index[4]:
                    name = index[1].replace('"', '""')
                    unique_columns.append([row[2] for row in self.db.execute(f'PRAGMA index_info("{name}")')])
            if ["account", "destination", "digest"] not in unique_columns:
                raise sqlite3.DatabaseError("Delivery duplicate protection is missing.")

    def _initialize(self) -> None:
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS groups (
                account INTEGER NOT NULL, id INTEGER NOT NULL, name TEXT NOT NULL,
                metadata TEXT NOT NULL, PRIMARY KEY(account,id));
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, account INTEGER NOT NULL, destination INTEGER NOT NULL,
                digest TEXT NOT NULL, random_id INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, detail TEXT,
                UNIQUE(account,destination,digest));
            CREATE TABLE IF NOT EXISTS cooldowns (
                account INTEGER PRIMARY KEY, until_epoch REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sync_runs (
                account INTEGER PRIMARY KEY, data TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    def _save_scan(self, account: int, scan: dict) -> None:
        self.db.execute("INSERT INTO sync_runs VALUES (?,?) ON CONFLICT(account) DO UPDATE SET data=excluded.data",
                        (account, json.dumps(scan, ensure_ascii=False)))

    def save_scan(self, account: int, scan: dict) -> None:
        with self.db:
            self._save_scan(account, scan)

    def scan(self, account: int) -> dict:
        row = self.db.execute("SELECT data FROM sync_runs WHERE account=?", (account,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_group(self, account: int, group: Group, *, scan: dict | None = None) -> None:
        metadata = json.dumps(group.data(), ensure_ascii=False)
        with self.db:
            self.db.execute("INSERT INTO groups VALUES (?,?,?,?) ON CONFLICT(account,id) DO UPDATE "
                            "SET name=excluded.name,metadata=excluded.metadata "
                            "WHERE groups.name != excluded.name OR groups.metadata != excluded.metadata",
                            (account, group.id, group.name, metadata))
            if scan is not None:
                self._save_scan(account, scan)

    def get_group(self, account: int, destination: int) -> dict | None:
        row = self.db.execute("SELECT metadata FROM groups WHERE account=? AND id=?", (account, destination)).fetchone()
        return json.loads(row[0]) if row else None

    def contains_group(self, account: int, destination: int) -> bool:
        return self.db.execute("SELECT 1 FROM groups WHERE account=? AND id=?", (account, destination)).fetchone() is not None

    def iter_groups(self, account: int, query: str = ""):
        cursor = self.db.execute("SELECT metadata FROM groups WHERE account=? ORDER BY name", (account,))
        try:
            for row in cursor:
                group = json.loads(row[0])
                if query.casefold() in str(group).casefold():
                    yield group
        finally:
            cursor.close()

    def groups(self, account: int, query: str = "") -> list[dict]:
        return list(self.iter_groups(account, query))  # Legacy CLI compatibility.

    def page(self, account: int, *, query: str = "", permission: str = "all", sort: str = "name",
             page: int = 0, size: int = 15, policy: CachePolicy | None = None) -> tuple[list[dict], int]:
        if permission not in {'all', 'allowed', 'denied', 'unknown'} or sort not in {'name', 'id', 'checked_at'}:
            raise ValueError("Unsupported list filter or sort order.")
        if not 1 <= size <= 100 or page < 0:
            raise ValueError("Invalid page size or offset.")
        policy = policy or CachePolicy()
        # Evaluate freshness in SQL via a deterministic-size Python callback,
        # and decode only the returned page into application memory.
        self.db.create_function('effective_permission', 1, lambda value: policy.permission(json.loads(value)))
        self.db.create_function('unicode_fold', 1, lambda value: str(value).casefold(), deterministic=True)
        condition = "account=? AND (instr(unicode_fold(name),?)>0 OR instr(unicode_fold(metadata),?)>0)"
        params: list = [account, query.casefold(), query.casefold()]
        if permission != 'all':
            condition += " AND effective_permission(metadata)=?"
            params.append(permission)
        order = {'name': 'unicode_fold(name),id', 'id': 'id',
                 'checked_at': "json_extract(metadata,'$.checked_at') DESC,id"}[sort]
        total = self.db.execute(f"SELECT COUNT(*) FROM groups WHERE {condition}", params).fetchone()[0]
        rows = self.db.execute(f"SELECT metadata FROM groups WHERE {condition} ORDER BY {order} LIMIT ? OFFSET ?",
                               (*params, size, page * size))
        return [json.loads(r[0]) for r in rows], total

    def overview(self, account: int, policy: CachePolicy | None = None) -> dict:
        policy = policy or CachePolicy()
        result = dict(total=0, allowed=0, denied=0, unknown=0, complete=0, incomplete=0, pending=0, fresh=0, last_seen=None)
        for group in self.iter_groups(account):
            result['total'] += 1
            stamp = group.get('discovered_at')
            if stamp and (result['last_seen'] is None or stamp > result['last_seen']):
                result['last_seen'] = stamp
            result[policy.permission(group)] += 1
            result['complete' if group.get('metadata_status') == 'complete' else 'incomplete'] += 1
            result['fresh'] += int(policy.details_fresh(group))
            if not fresh(group.get('permissions_checked_at'), policy.permissions):
                result['pending'] += 1
        return result

    def reserve(self, account: int, destination: int, message: str) -> tuple[int, int]:
        digest = hashlib.sha256(message.encode()).hexdigest()
        random_id = secrets.randbits(63) or 1
        try:
            with self.db:
                cursor = self.db.execute(
                    "INSERT INTO deliveries(account,destination,digest,random_id,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,'pending',?,?)",
                    (account, destination, digest, random_id, now(), now()))
            return int(cursor.lastrowid), random_id
        except sqlite3.IntegrityError as exc:
            raise DuplicateMessage("This exact message already has a delivery record for this group. "
                                   "Inspect history; automatic retries are disabled.") from exc

    def finish(self, delivery: int, status: str, detail: str) -> None:
        with self.db:
            self.db.execute("UPDATE deliveries SET status=?,detail=?,updated_at=? WHERE id=?",
                            (status, detail, now(), delivery))

    def history(self, account: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM deliveries WHERE account=? ORDER BY id DESC LIMIT 100", (account,))]

    def cooldown(self, account: int) -> float:
        row = self.db.execute("SELECT until_epoch FROM cooldowns WHERE account=?", (account,)).fetchone()
        return float(row[0]) if row else 0

    def set_cooldown(self, account: int, until: float) -> None:
        with self.db:
            self.db.execute("INSERT INTO cooldowns VALUES (?,?) ON CONFLICT(account) DO UPDATE "
                            "SET until_epoch=MAX(until_epoch,excluded.until_epoch)", (account, until))
