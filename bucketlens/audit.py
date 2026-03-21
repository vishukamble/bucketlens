# audit.py — BucketLens delete audit log
#
# Files created at runtime (add to .gitignore):
#   bucketlens_audit.db
#   bucketlens_audit.log

import sqlite3
import os
from datetime import datetime, timezone

_DB_PATH = os.path.join(os.path.dirname(__file__), "bucketlens_audit.db")
_LOG_PATH = os.path.join(os.path.dirname(__file__), "bucketlens_audit.log")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS delete_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    bucket      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    file_size   INTEGER,
    status      TEXT    NOT NULL,
    error_msg   TEXT,
    provider    TEXT    DEFAULT 'aws',
    user_agent  TEXT
)
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)


_init_db()


def log_delete(
    bucket: str,
    key: str,
    file_size,
    status: str,
    error_msg: str = None,
    provider: str = "aws",
    user_agent: str = None,
) -> None:
    """Write one delete event to SQLite and append to the plain-text log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO delete_log
                   (timestamp, bucket, key, file_size, status, error_msg, provider, user_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, bucket, key, file_size, status, error_msg, provider, user_agent),
            )
    except sqlite3.OperationalError:
        pass  # Don't let audit failure break the delete response

    try:
        size_str = str(file_size) if file_size is not None else "-"
        line = f"{ts} | DELETE | {provider} | {bucket} | {key} | {size_str} | {status}\n"
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def get_recent_deletes(limit: int = 100, bucket: str = None) -> list:
    """Return recent delete events as a list of dicts."""
    limit = min(limit, 500)
    try:
        with _get_conn() as conn:
            if bucket:
                rows = conn.execute(
                    "SELECT * FROM delete_log WHERE bucket = ? ORDER BY id DESC LIMIT ?",
                    (bucket, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM delete_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
