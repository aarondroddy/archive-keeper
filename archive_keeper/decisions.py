from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class DecisionStore:
    def __init__(self, path: Path):
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS keeper_decisions (
          group_id INTEGER PRIMARY KEY,
          keeper_path TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT 'manual selection',
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS favorites (
          path TEXT PRIMARY KEY,
          note TEXT NOT NULL DEFAULT '',
          updated_at REAL NOT NULL
        );
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def set_keeper(self, group_id: int, path: Path, reason: str = "manual selection"):
        self.conn.execute(
            "INSERT INTO keeper_decisions(group_id,keeper_path,reason,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(group_id) DO UPDATE SET keeper_path=excluded.keeper_path, reason=excluded.reason, updated_at=excluded.updated_at",
            (group_id, str(path), reason, time.time()),
        )
        self.conn.commit()

    def get_keeper(self, group_id: int) -> Path | None:
        row = self.conn.execute("SELECT keeper_path FROM keeper_decisions WHERE group_id=?", (group_id,)).fetchone()
        return Path(row[0]) if row else None

    def toggle_favorite(self, path: Path) -> bool:
        existing = self.conn.execute("SELECT 1 FROM favorites WHERE path=?", (str(path),)).fetchone()
        if existing:
            self.conn.execute("DELETE FROM favorites WHERE path=?", (str(path),))
            state = False
        else:
            self.conn.execute("INSERT INTO favorites(path,updated_at) VALUES(?,?)", (str(path), time.time()))
            state = True
        self.conn.commit()
        return state

    def is_favorite(self, path: Path) -> bool:
        return self.conn.execute("SELECT 1 FROM favorites WHERE path=?", (str(path),)).fetchone() is not None

    def list_decisions(self):
        return self.conn.execute("SELECT group_id,keeper_path,reason,updated_at FROM keeper_decisions ORDER BY group_id").fetchall()
