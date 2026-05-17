"""
RAG Layer — Entity Data Mapping
Records audit sessions to SQLite for transparency and accountability.
Each audit is stamped with document SHA-256 hashes, org metadata, and results.
"""
import hashlib
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("data/audit_log.db")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit_sessions (
            session_id    TEXT PRIMARY KEY,
            organization  TEXT,
            grant_number  TEXT,
            expense_hash  TEXT,
            grant_hash    TEXT,
            item_count    INTEGER,
            allowable     REAL,
            unallowable   REAL,
            status        TEXT DEFAULT 'started',
            created_at    TEXT,
            completed_at  TEXT
        )
    """)
    con.commit()
    return con


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Public API ─────────────────────────────────────────────────────────────────

def create_session(
    organization: str,
    grant_number: str,
    expense_text: str,
    grant_text: str,
) -> str:
    """
    Open a new audit session record.
    Document contents are stored only as SHA-256 hashes — never as raw text.
    Returns the session_id UUID.
    """
    session_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """INSERT INTO audit_sessions
               (session_id, organization, grant_number, expense_hash, grant_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, organization, grant_number,
             _sha256(expense_text), _sha256(grant_text), now),
        )
    logger.info("Audit session created: %s  org=%s  grant=%s", session_id, organization, grant_number)
    return session_id


def complete_session(
    session_id: str,
    item_count: int,
    allowable: float,
    unallowable: float,
) -> None:
    """Stamp an existing session with final audit results."""
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute(
            """UPDATE audit_sessions
               SET status='complete', item_count=?, allowable=?, unallowable=?, completed_at=?
               WHERE session_id=?""",
            (item_count, allowable, unallowable, now, session_id),
        )
    logger.info(
        "Audit session completed: %s  items=%d  allowable=%.2f  unallowable=%.2f",
        session_id, item_count, allowable, unallowable,
    )


def list_sessions(
    limit: int = 100,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list:
    """
    Return recent audit sessions for the admin audit-log view.
    Supports optional filtering by org/grant keyword, status, and date range.
    """
    query = """SELECT session_id, organization, grant_number, item_count,
                      allowable, unallowable, status, created_at, completed_at
               FROM audit_sessions WHERE 1=1"""
    params: list = []

    if search:
        query += " AND (organization LIKE ? OR grant_number LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    if date_from:
        query += " AND created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND created_at <= ?"
        params.append(date_to + "T23:59:59")

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()
    return [
        {
            "session_id":   r[0][:8] + "…",
            "organization": r[1],
            "grant_number": r[2],
            "item_count":   r[3],
            "allowable":    r[4],
            "unallowable":  r[5],
            "status":       r[6],
            "created_at":   r[7],
            "completed_at": r[8],
        }
        for r in rows
    ]
