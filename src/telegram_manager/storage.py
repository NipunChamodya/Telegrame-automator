import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

from .models import Group, now


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
        """)

    def close(self) -> None:
        self.db.close()

    def save_group(self, account: int, group: Group) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO groups VALUES (?,?,?,?)",
                            (account, group.id, group.name, json.dumps(group.data())))

    def groups(self, account: int, query: str = "") -> list[dict]:
        rows = self.db.execute("SELECT metadata FROM groups WHERE account=? ORDER BY name", (account,))
        return [g for row in rows if query.casefold() in
                str(g := json.loads(row[0])).casefold()]

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
