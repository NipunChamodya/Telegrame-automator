"""Additive, account-scoped conversation cache, drafts and local labels."""
import json
from .models import now
from .storage import Store


class ChatStore:
    def __init__(self, store: Store) -> None:
        self.db = store.db
        self.db.create_function('unicode_fold', 1, lambda value: (value or '').casefold(), deterministic=True)
        if getattr(store, '_chat_tables_ready', False):
            return
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS dialog_cache (
                account INTEGER NOT NULL, destination INTEGER NOT NULL, name TEXT NOT NULL,
                kind TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(account,destination));
            CREATE TABLE IF NOT EXISTS conversation_drafts (
                account INTEGER NOT NULL, destination INTEGER NOT NULL, message TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(account,destination));
            CREATE TABLE IF NOT EXISTS local_labels (
                account INTEGER NOT NULL, destination INTEGER NOT NULL, label TEXT NOT NULL,
                PRIMARY KEY(account,destination,label));
        ''')
        store._chat_tables_ready = True

    def save(self, account: int, data: dict) -> None:
        with self.db:
            self.db.execute('INSERT INTO dialog_cache VALUES (?,?,?,?,?) ON CONFLICT(account,destination) '
                            'DO UPDATE SET name=excluded.name,kind=excluded.kind,data=excluded.data '
                            'WHERE dialog_cache.data != excluded.data',
                            (account, data['id'], data['name'], data['kind'], json.dumps(data, ensure_ascii=False)))

    def get(self, account: int, destination: int) -> dict | None:
        row = self.db.execute('SELECT data FROM dialog_cache WHERE account=? AND destination=?',
                              (account, destination)).fetchone()
        return json.loads(row[0]) if row else None

    def page(self, account: int, query: str = '', kind: str = 'all', page: int = 0, size: int = 50) -> dict:
        # Unicode casefold in Python SQLite's registered function; all inputs stay parameters.
        where = 'account=? AND (?=\'all\' OR kind=?) AND instr(unicode_fold(name || data),?)>0'
        args = (account, kind, kind, query.casefold())
        total = self.db.execute('SELECT count(*) FROM dialog_cache WHERE ' + where, args).fetchone()[0]
        rows = self.db.execute('SELECT data FROM dialog_cache WHERE ' + where +
                               ' ORDER BY unicode_fold(name),destination LIMIT ? OFFSET ?', (*args, size, page*size))
        return {'chats': [json.loads(row[0]) for row in rows], 'total': total, 'page': page, 'size': size}

    def draft(self, account: int, destination: int) -> dict:
        row = self.db.execute('SELECT message,updated_at FROM conversation_drafts WHERE account=? AND destination=?',
                              (account, destination)).fetchone()
        return {'destination': destination, 'message': row[0] if row else '', 'updated_at': row[1] if row else None}

    def save_draft(self, account: int, destination: int, message: str) -> dict:
        with self.db:
            if not message:
                self.db.execute('DELETE FROM conversation_drafts WHERE account=? AND destination=?', (account,destination))
            else:
                self.db.execute('INSERT INTO conversation_drafts VALUES (?,?,?,?) ON CONFLICT(account,destination) '
                                'DO UPDATE SET message=excluded.message,updated_at=excluded.updated_at',
                                (account,destination,message,now()))
        return self.draft(account,destination)

    def drafts(self, account: int) -> dict:
        rows = self.db.execute('SELECT d.destination,d.message,d.updated_at,c.name AS title FROM conversation_drafts d '
                              'LEFT JOIN dialog_cache c ON c.account=d.account AND c.destination=d.destination '
                              'WHERE d.account=? ORDER BY d.updated_at DESC LIMIT 100', (account,))
        return {'drafts': [dict(row) for row in rows]}

    def label(self, account: int, destination: int, label: str, enabled: bool) -> None:
        with self.db:
            if enabled:
                self.db.execute('INSERT OR IGNORE INTO local_labels VALUES (?,?,?)', (account,destination,label))
            else:
                self.db.execute('DELETE FROM local_labels WHERE account=? AND destination=? AND label=?',
                                (account,destination,label))

    def labels(self, account: int) -> dict:
        return {'labels': [dict(row) for row in self.db.execute(
            'SELECT destination,label FROM local_labels WHERE account=? ORDER BY label,destination LIMIT 1000', (account,))]}
