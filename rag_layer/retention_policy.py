"""
RAG Layer — Data Retention Policy
Purges audit session records and Chroma vector store directories
that are older than configurable retention windows.
"""
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Defaults (overridable via env vars) ────────────────────────────────────────

DEFAULT_SESSION_RETENTION_DAYS: int = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))
DEFAULT_STORE_RETENTION_DAYS: int = int(os.environ.get("STORE_RETENTION_DAYS", "90"))

DB_PATH = Path("data/audit_log.db")
CHROMA_BASE_DIRS: list[str] = ["chroma_cfr200", "chroma_grant_"]  # prefix match


# ── Public API ─────────────────────────────────────────────────────────────────

def purge_old_sessions(retention_days: int = DEFAULT_SESSION_RETENTION_DAYS) -> int:
    """
    Delete audit_sessions rows whose created_at is older than *retention_days*.
    Returns the number of rows deleted.
    """
    if not DB_PATH.exists():
        logger.debug("No audit DB found; nothing to purge.")
        return 0

    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    try:
        con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        cur = con.execute(
            "DELETE FROM audit_sessions WHERE created_at < ?", (cutoff,)
        )
        deleted = cur.rowcount
        con.commit()
        con.close()
        if deleted:
            logger.info("Retention policy: purged %d session(s) older than %d days", deleted, retention_days)
        return deleted
    except Exception as e:
        logger.error("Failed to purge old sessions: %s", e)
        return 0


def purge_old_stores(
    base_dir: str = ".",
    retention_days: int = DEFAULT_STORE_RETENTION_DAYS,
) -> list[str]:
    """
    Remove Chroma persist directories (chroma_cfr200, chroma_grant_*) whose
    mtime is older than *retention_days*.  Returns list of removed paths.
    """
    removed: list[str] = []
    cutoff_ts = (datetime.utcnow() - timedelta(days=retention_days)).timestamp()

    try:
        entries = os.listdir(base_dir)
    except OSError:
        return removed

    for entry in entries:
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            continue
        is_chroma = entry == "chroma_cfr200" or entry.startswith("chroma_grant_")
        if not is_chroma:
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if mtime < cutoff_ts:
            try:
                shutil.rmtree(full)
                removed.append(full)
                logger.info("Retention policy: removed stale store %s (age > %d days)", full, retention_days)
            except Exception as e:
                logger.error("Could not remove %s: %s", full, e)

    return removed


def run_all(
    session_retention_days: int = DEFAULT_SESSION_RETENTION_DAYS,
    store_retention_days: int = DEFAULT_STORE_RETENTION_DAYS,
    base_dir: str = ".",
) -> dict:
    """
    Run the full retention sweep: sessions + stores.
    Returns a summary dict suitable for display in the admin UI.
    """
    sessions_deleted = purge_old_sessions(session_retention_days)
    stores_removed = purge_old_stores(base_dir, store_retention_days)
    summary = {
        "sessions_deleted": sessions_deleted,
        "stores_removed": len(stores_removed),
        "store_paths": stores_removed,
        "ran_at": datetime.utcnow().isoformat(),
    }
    logger.info("Retention sweep complete: %s", summary)
    return summary


def next_purge_estimate(retention_days: int = DEFAULT_SESSION_RETENTION_DAYS) -> str:
    """Human-readable date of the oldest record that will eventually be purged."""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    return cutoff.strftime("%Y-%m-%d")
