import sqlite3
import os
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitored_sites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                channel_id  TEXT    NOT NULL,
                url         TEXT    NOT NULL,
                label       TEXT,
                interval    INTEGER NOT NULL DEFAULT 30,
                last_hash   TEXT,
                last_status INTEGER,
                added_by    TEXT,
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, url)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS change_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL,
                change_type TEXT    NOT NULL,
                summary     TEXT,
                detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(site_id) REFERENCES monitored_sites(id)
            )
        """)
        conn.commit()


# ──────────────────────────────────────────────
# Site CRUD
# ──────────────────────────────────────────────

def add_site(guild_id: str, channel_id: str, url: str, label: str,
             interval: int, added_by: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitored_sites
               (guild_id, channel_id, url, label, interval, added_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, channel_id, url, label, interval, added_by)
        )
        conn.commit()
        return cur.lastrowid


def remove_site(guild_id: str, url: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM monitored_sites WHERE guild_id=? AND url=?",
            (guild_id, url)
        )
        conn.commit()
        return cur.rowcount > 0


def get_sites(guild_id: str) -> list:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM monitored_sites WHERE guild_id=?",
            (guild_id,)
        ).fetchall()


def get_all_sites() -> list:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM monitored_sites").fetchall()


def update_site_state(site_id: int, new_hash: str, status_code: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE monitored_sites SET last_hash=?, last_status=? WHERE id=?",
            (new_hash, status_code, site_id)
        )
        conn.commit()


def site_exists(guild_id: str, url: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM monitored_sites WHERE guild_id=? AND url=?",
            (guild_id, url)
        ).fetchone()
        return row is not None


def count_sites(guild_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM monitored_sites WHERE guild_id=?",
            (guild_id,)
        ).fetchone()
        return row["cnt"]


# ──────────────────────────────────────────────
# Change log
# ──────────────────────────────────────────────

def log_change(site_id: int, change_type: str, summary: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO change_log (site_id, change_type, summary) VALUES (?, ?, ?)",
            (site_id, change_type, summary)
        )
        conn.commit()