"""
RAG (Retrieval-Augmented Generation) interface tools.
Enhancement 3: logs the CFR200 index version used in each query.
"""
import logging
from vectorstores.cfr200_store import query_cfr200, get_store_version
from vectorstores.grant_store import query_grant_store as _query_grant_store

logger = logging.getLogger(__name__)


def query_cfr200_store(query: str, k: int = 3) -> str:
    """
    Query the 2 CFR 200 vector store.
    Logs the index version used (Enhancement 3).

    Args:
        query: Natural-language query about an expense type.
        k:     Number of document chunks to retrieve.

    Returns:
        Concatenated relevant 2 CFR 200 passages, prefixed with the index version tag.
    """
    version = get_store_version()
    logger.info(
        "CFR200 RAG query | index_version=%s | query=%s",
        version or "not_loaded",
        query[:80],
    )
    result = query_cfr200(query, k=k)
    return result


def query_grant_store(grant_text: str, query: str, k: int = 3) -> str:
    """
    Query the dynamic grant agreement store.

    Args:
        grant_text: Full text of the grant agreement (used to build store if needed).
        query:      Natural-language query about specific grant restrictions.
        k:          Number of chunks to retrieve.

    Returns:
        Concatenated relevant grant agreement passages.
    """
    logger.info("Grant RAG query | query=%s", query[:80])
    return _query_grant_store(grant_text, query, k=k)
