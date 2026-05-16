"""
Vector Store Maintenance utilities.
Provides health checks, document counts, and version reporting
for the CFR200 and grant Chroma stores — without modifying the stores themselves.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ── CFR200 store ───────────────────────────────────────────────────────────────

def get_cfr200_stats(persist_dir: str = "./chroma_cfr200") -> dict:
    """
    Return a health/stats dict for the CFR200 Chroma store.
    Never modifies the store — read-only inspection.
    """
    from vectorstores.cfr200_store import get_store_version

    stats: dict = {
        "version": get_store_version() or "not loaded",
        "persist_dir": persist_dir,
        "persist_dir_exists": os.path.isdir(persist_dir),
        "doc_count": None,
        "healthy": False,
        "error": None,
    }

    try:
        from vectorstores.cfr200_store import load_cfr200_store
        store = load_cfr200_store(persist_dir)
        if store is not None:
            try:
                # Chroma exposes _collection.count()
                stats["doc_count"] = store._collection.count()
            except Exception:
                stats["doc_count"] = "unknown"
            stats["healthy"] = True
        else:
            stats["healthy"] = False
            stats["error"] = "Store unavailable (chromadb/embeddings missing)"
    except Exception as e:
        stats["error"] = str(e)

    return stats


def check_cfr200_health(test_query: str = "travel costs allowable") -> dict:
    """
    Run a live test query against the CFR200 store.
    Returns {healthy, latency_ms, result_preview, error}.
    """
    import time
    from tools.rag_tools import query_cfr200_store

    result: dict = {"healthy": False, "latency_ms": None, "result_preview": "", "error": None}
    try:
        t0 = time.perf_counter()
        text = query_cfr200_store(test_query, k=1)
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        result["healthy"] = bool(text and len(text) > 10)
        result["latency_ms"] = elapsed
        result["result_preview"] = text[:120] + ("…" if len(text) > 120 else "")
    except Exception as e:
        result["error"] = str(e)
    return result


# ── Grant stores ───────────────────────────────────────────────────────────────

def get_grant_store_stats(base_dir: str = ".") -> dict:
    """
    Scan for cached grant Chroma stores (chroma_grant_*) and return summary info.
    """
    import time

    stats: dict = {"store_count": 0, "stores": [], "total_size_mb": 0.0}
    try:
        for entry in sorted(os.listdir(base_dir)):
            if not entry.startswith("chroma_grant_"):
                continue
            full = os.path.join(base_dir, entry)
            if not os.path.isdir(full):
                continue
            size_bytes = _dir_size(full)
            mtime = os.path.getmtime(full)
            stats["stores"].append({
                "path": full,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "last_modified": _fmt_ts(mtime),
            })
            stats["total_size_mb"] += size_bytes / (1024 * 1024)
        stats["store_count"] = len(stats["stores"])
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    except Exception as e:
        stats["error"] = str(e)
    return stats


# ── Combined health report ─────────────────────────────────────────────────────

def full_maintenance_report(base_dir: str = ".") -> dict:
    """
    Run a complete maintenance check across all vector stores.
    Safe to call at any time — read-only.
    """
    cfr_stats = get_cfr200_stats()
    cfr_health = check_cfr200_health()
    grant_stats = get_grant_store_stats(base_dir)

    return {
        "cfr200": {**cfr_stats, **cfr_health},
        "grant_stores": grant_stats,
        "overall_healthy": cfr_health.get("healthy", False),
    }


# ── Private helpers ────────────────────────────────────────────────────────────

def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _fmt_ts(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
