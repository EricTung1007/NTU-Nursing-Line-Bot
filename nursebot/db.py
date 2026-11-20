"""SQLite store: users, messages, settings.

Replaces the per-user .txt memory files. One file, transactional, indexed, safe under
concurrent webhook workers (WAL + per-thread connections).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    g            INTEGER,
    p            INTEGER,
    weeks        INTEGER,
    weeks_set_on TEXT,              -- ISO date `weeks` was recorded; gestational age advances from it
    is_dad       INTEGER,           -- NULL unknown, 0/1
    state        TEXT NOT NULL DEFAULT 'collecting',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    last_seen    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    role    TEXT NOT NULL,          -- 'user' | 'bot'
    text    TEXT NOT NULL,
    flag    TEXT,                   -- user rows: 'no_data' | 'error' when the bot could not answer
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_flag ON messages(flag) WHERE flag IS NOT NULL;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

USER_FIELDS = ("name", "g", "p", "weeks", "weeks_set_on", "is_dad", "state")


class DB:
    def __init__(self, path: Path):
        self.path = str(path)
        self._local = threading.local()
        with self.conn() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.c = c
        return c

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn().execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        r = self.conn().execute(sql, params).fetchone()
        return dict(r) if r else None

    def run(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        c = self.conn()
        with c:
            return c.execute(sql, params)

    # ---- users -------------------------------------------------------------
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.one("SELECT * FROM users WHERE user_id=?", (user_id,))

    def ensure_user(self, user_id: str) -> Dict[str, Any]:
        now = time.time()
        self.run(
            "INSERT OR IGNORE INTO users(user_id, created_at, updated_at, last_seen) VALUES(?,?,?,?)",
            (user_id, now, now, now),
        )
        self.run("UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
        return self.get_user(user_id)  # type: ignore[return-value]

    def update_user(self, user_id: str, **fields: Any) -> None:
        bad = set(fields) - set(USER_FIELDS)
        if bad:
            raise ValueError(f"unknown user fields: {bad}")
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.run(
            f"UPDATE users SET {cols}, updated_at=? WHERE user_id=?",
            (*fields.values(), time.time(), user_id),
        )

    def delete_user(self, user_id: str) -> None:
        c = self.conn()
        with c:
            c.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM users WHERE user_id=?", (user_id,))

    def list_users(self, search: str = "") -> List[Dict[str, Any]]:
        like = f"%{search}%"
        return self.query(
            "SELECT u.*, (SELECT COUNT(*) FROM messages m WHERE m.user_id=u.user_id AND m.role='user') AS n_msgs "
            "FROM users u WHERE u.user_id NOT LIKE 'gui-%' AND (u.name LIKE ? OR u.user_id LIKE ?) "
            "ORDER BY u.last_seen DESC",
            (like, like),
        )

    # ---- messages ----------------------------------------------------------
    def add_message(self, user_id: str, role: str, text: str, flag: Optional[str] = None) -> int:
        return self.run(
            "INSERT INTO messages(user_id, role, text, flag, ts) VALUES(?,?,?,?,?)",
            (user_id, role, text, flag, time.time()),
        ).lastrowid

    def set_flag(self, message_id: int, flag: Optional[str]) -> None:
        self.run("UPDATE messages SET flag=? WHERE id=?", (flag, message_id))

    def recent_messages(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.query(
            "SELECT role, text, ts FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return rows[::-1]

    def unanswered(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.query(
            "SELECT m.id, m.user_id, m.text, m.flag, m.ts, u.name FROM messages m "
            "LEFT JOIN users u ON u.user_id=m.user_id "
            "WHERE m.flag IS NOT NULL AND m.user_id NOT LIKE 'gui-%' ORDER BY m.id DESC LIMIT ?",
            (limit,),
        )

    # ---- settings ----------------------------------------------------------
    def load_settings(self) -> Dict[str, str]:
        return {r["key"]: r["value"] for r in self.query("SELECT key, value FROM settings")}

    def save_settings(self, items: Dict[str, str]) -> None:
        c = self.conn()
        with c:
            c.executemany(
                "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(items.items()),
            )

    def backup_to(self, dest: Path) -> None:
        """Consistent online copy using SQLite's backup API."""
        out = sqlite3.connect(str(dest))
        try:
            self.conn().backup(out)
        finally:
            out.close()
