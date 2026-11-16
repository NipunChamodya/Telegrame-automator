"""Private, additive archive ledger; no Telegram objects or session material."""

import json


class ArchiveStore:
    def __init__(self, store):
        self.db = store.db
        existing_stats = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='archive_stats'"
        ).fetchone()
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS archive_jobs (
            id TEXT PRIMARY KEY, account INTEGER NOT NULL, peer INTEGER NOT NULL,
            config TEXT NOT NULL, state TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
            scan_done INTEGER NOT NULL DEFAULT 0, examined INTEGER NOT NULL DEFAULT 0,
            wait_until REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS archive_items (
            job TEXT NOT NULL, message INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            metadata TEXT NOT NULL, relative TEXT NOT NULL, state TEXT NOT NULL,
            bytes INTEGER NOT NULL DEFAULT 0, digest TEXT, note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(job,message));
          CREATE INDEX IF NOT EXISTS archive_pending ON archive_items(job,state,message);
          CREATE TABLE IF NOT EXISTS archive_files (
            account INTEGER NOT NULL, peer INTEGER NOT NULL, message INTEGER NOT NULL,
            fingerprint TEXT NOT NULL, folder TEXT NOT NULL, relative TEXT NOT NULL,
            bytes INTEGER NOT NULL, digest TEXT NOT NULL,
            PRIMARY KEY(account,peer,message,fingerprint,folder));
          CREATE TABLE IF NOT EXISTS archive_stats (job TEXT, state TEXT, n INTEGER NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job,state));
          CREATE TRIGGER IF NOT EXISTS archive_insert AFTER INSERT ON archive_items BEGIN
            INSERT INTO archive_stats VALUES (NEW.job,NEW.state,1,NEW.bytes) ON CONFLICT(job,state) DO UPDATE SET n=n+1,size=size+NEW.bytes;
          END;
          CREATE TRIGGER IF NOT EXISTS archive_update AFTER UPDATE OF state,bytes ON archive_items BEGIN
            UPDATE archive_stats SET n=n-1,size=size-OLD.bytes WHERE job=OLD.job AND state=OLD.state;
            INSERT INTO archive_stats VALUES (NEW.job,NEW.state,1,NEW.bytes) ON CONFLICT(job,state) DO UPDATE SET n=n+1,size=size+NEW.bytes;
          END;
          CREATE TRIGGER IF NOT EXISTS archive_delete AFTER DELETE ON archive_items BEGIN
            UPDATE archive_stats SET n=n-1,size=size-OLD.bytes WHERE job=OLD.job AND state=OLD.state;
          END;
        """)
        if not existing_stats:
            self.db.execute(
                "INSERT OR REPLACE INTO archive_stats SELECT job,state,COUNT(*),SUM(bytes) FROM archive_items GROUP BY job,state"
            )
        if "partial" not in {
            r[1] for r in self.db.execute("PRAGMA table_info(archive_items)")
        }:
            self.db.execute("ALTER TABLE archive_items ADD COLUMN partial TEXT")
        self.db.commit()

    def recover(self):
        self.db.execute(
            "UPDATE archive_jobs SET state='paused', note='Ready to resume after interruption.' WHERE state IN ('finding','saving','waiting')"
        )
        self.db.commit()

    def job(self, identity, account):
        row = self.db.execute(
            "SELECT * FROM archive_jobs WHERE id=? AND account=?", (identity, account)
        ).fetchone()
        return dict(row) if row else None

    def update(self, identity, **values):
        allowed = {"state", "cursor", "scan_done", "examined", "wait_until", "note"}
        assert set(values) <= allowed
        self.db.execute(
            "UPDATE archive_jobs SET "
            + ",".join(key + "=?" for key in values)
            + " WHERE id=?",
            (*values.values(), identity),
        )
        self.db.commit()

    def snapshot(self, row):
        config = json.loads(row["config"])
        stats = {
            r["state"]: (r["n"], r["size"])
            for r in self.db.execute(
                "SELECT state,n,size FROM archive_stats WHERE job=?", (row["id"],)
            )
        }
        count = lambda key: stats.get(key, (0, 0))[0]
        return {
            "id": row["id"],
            "account_id": row["account"],
            "destination": row["peer"],
            "conversation": config["conversation"],
            "folder": config["folder"],
            "state": row["state"],
            "examined": row["examined"],
            "discovered": sum(v[0] for v in stats.values()),
            "completed": count("completed"),
            "duplicates": count("duplicate"),
            "restricted": count("restricted"),
            "unsupported": count("unsupported"),
            "deleted": count("deleted"),
            "failed": count("failed"),
            "bytes": stats.get("completed", (0, 0))[1],
            "known_bytes": sum(v[1] for v in stats.values()),
            "scan_done": bool(row["scan_done"]),
            "wait_until": row["wait_until"],
            "note": row["note"],
            "created": row["created"],
            "organization": config["organization"],
            "types": config["types"],
            "start": config["start"],
            "end": config["end"],
            "timezone": config["timezone"],
        }

    def list(self, account):
        return [
            self.snapshot(dict(row))
            for row in self.db.execute(
                "SELECT * FROM archive_jobs WHERE account=? ORDER BY created DESC LIMIT 100",
                (account,),
            )
        ]
