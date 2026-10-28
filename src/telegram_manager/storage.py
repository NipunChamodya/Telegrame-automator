import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

from .models import Group, now
from .cache import CachePolicy, fresh
from .messaging import message_units


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
        optional_tables = {
            'sync_runs': {'account', 'data'},
            'drafts': {'account', 'message', 'updated_at'},
            'approvals': {'account', 'destination', 'approved_at'},
            'delivery_notes': {'delivery_id', 'account', 'preview', 'telegram_message_id'},
        }
        for table, required in optional_tables.items():
            if table in tables:
                columns = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
                if not required.issubset(columns):
                    raise sqlite3.DatabaseError("Incompatible optional application table; nothing was reset.")
        for table, required in {'drafts': {'account', 'message', 'updated_at'},
                                'approvals': {'account', 'destination', 'approved_at'}}.items():
            if table in tables and not required.issubset({r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}):
                raise sqlite3.DatabaseError("Incompatible application state table.")
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
            CREATE TABLE IF NOT EXISTS drafts (
                account INTEGER PRIMARY KEY, message TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals (
                account INTEGER NOT NULL, destination INTEGER NOT NULL, approved_at TEXT NOT NULL,
                PRIMARY KEY(account,destination));
            CREATE TABLE IF NOT EXISTS delivery_notes (
                delivery_id INTEGER PRIMARY KEY, account INTEGER NOT NULL, preview TEXT NOT NULL,
                telegram_message_id INTEGER);
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
             page: int = 0, size: int = 15, policy: CachePolicy | None = None, group_type: str = 'all') -> tuple[list[dict], int]:
        if permission not in {'all', 'allowed', 'denied', 'unknown'} or sort not in {'name', 'id', 'checked_at', 'members'} or group_type not in {'all', 'group', 'supergroup'}:
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
        if group_type != 'all':
            condition += " AND json_extract(metadata,'$.kind')=?"
            params.append(group_type)
        order = {'name': 'unicode_fold(name),id', 'members': "COALESCE(json_extract(metadata,'$.members'),-1) DESC,id", 'id': 'id',
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

    def delivery_note(self, account: int, delivery: int, preview: str,
                      telegram_message_id: int | None = None) -> None:
        if not self.db.execute("SELECT 1 FROM deliveries WHERE account=? AND id=?", (account, delivery)).fetchone():
            raise ValueError('Delivery record is not available for this account.')
        if len(preview) > 161:
            raise ValueError('Delivery preview is too long.')
        with self.db:
            self.db.execute("INSERT INTO delivery_notes VALUES (?,?,?,?) ON CONFLICT(delivery_id) DO UPDATE "
                            "SET telegram_message_id=COALESCE(excluded.telegram_message_id,delivery_notes.telegram_message_id)",
                            (delivery, account, preview, telegram_message_id))

    def history(self, account: int, query: str = "") -> list[dict]:
        self.db.create_function('unicode_fold', 1, lambda value: str(value or '').casefold(), deterministic=True)
        rows = self.db.execute("SELECT d.*,g.name AS destination_name,n.preview AS message_preview,"
                               "n.telegram_message_id FROM deliveries d LEFT JOIN groups g "
                               "ON d.account=g.account AND d.destination=g.id LEFT JOIN delivery_notes n "
                               "ON n.account=d.account AND n.delivery_id=d.id WHERE d.account=? AND "
                               "(instr(unicode_fold(g.name),?)>0 OR instr(unicode_fold(n.preview),?)>0 OR "
                               "instr(CAST(d.destination AS TEXT),?)>0 OR instr(unicode_fold(d.status),?)>0) "
                               "ORDER BY d.id DESC LIMIT 100", (account, *([query.casefold()] * 4)))
        return [dict(row) for row in rows]

    def draft(self, account: int) -> dict:
        row = self.db.execute("SELECT message,updated_at FROM drafts WHERE account=?", (account,)).fetchone()
        return dict(row) if row else {'message': '', 'updated_at': None}

    def save_draft(self, account: int, message: str) -> None:
        if message_units(message) > 16384:
            raise ValueError('Draft exceeds the 16384 UTF-16 unit storage limit.')
        with self.db:
            self.db.execute("INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(account) DO UPDATE "
                            "SET message=excluded.message,updated_at=excluded.updated_at",
                            (account, message, now()))

    def is_approved(self, account: int, destination: int) -> bool:
        return self.db.execute("SELECT 1 FROM approvals WHERE account=? AND destination=?",
                               (account, destination)).fetchone() is not None

    def set_approval(self, account: int, destination: int, approved: bool) -> None:
        if type(approved) is not bool:
            raise ValueError('Approval must be explicitly true or false.')
        if approved and not self.contains_group(account, destination):
            raise ValueError('Only a discovered group can be approved.')
        with self.db:
            if approved:
                self.db.execute("INSERT INTO approvals VALUES (?,?,?) ON CONFLICT(account,destination) DO NOTHING",
                                (account, destination, now()))
            else:
                self.db.execute("DELETE FROM approvals WHERE account=? AND destination=?", (account, destination))

    def approvals(self, account: int, query: str = "") -> list[dict]:
        rows = self.db.execute("SELECT g.metadata,a.approved_at FROM approvals a JOIN groups g "
                               "ON a.account=g.account AND a.destination=g.id WHERE a.account=? ORDER BY g.name",
                               (account,))
        result = []
        for row in rows:
            group = json.loads(row[0])
            if query.casefold() in str(group).casefold():
                result.append(group | {'approved_at': row[1]})
        return result

    def cooldown(self, account: int) -> float:
        row = self.db.execute("SELECT until_epoch FROM cooldowns WHERE account=?", (account,)).fetchone()
        return float(row[0]) if row else 0

    def set_cooldown(self, account: int, until: float) -> None:
        with self.db:
            self.db.execute("INSERT INTO cooldowns VALUES (?,?) ON CONFLICT(account) DO UPDATE "
                            "SET until_epoch=MAX(until_epoch,excluded.until_epoch)", (account, until))
