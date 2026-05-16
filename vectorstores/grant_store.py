"""
Dynamic grant agreement vector store.
Creates a temporary Chroma collection from a single grant document text.
"""
import logging
import uuid
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cache so the same grant text doesn't get re-embedded on every query
_grant_stores: Dict[str, Any] = {}


def create_grant_store(grant_text: str, store_id: Optional[str] = None) -> Dict:
    """
    Build (or retrieve) a vector store from grant agreement text.

    Args:
        grant_text: Full text of the grant agreement.
        store_id:   Optional stable ID so the store can be reused.

    Returns:
        Dict with keys 'store', 'store_id', 'chunk_count' (or 'chunks' on fallback).
    """
    sid = store_id or str(uuid.uuid4())[:8]

    if sid in _grant_stores:
        return _grant_stores[sid]

    try:
        from langchain_community.vectorstores import Chroma
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_core.documents import Document
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_text(grant_text)
        docs = [
            Document(page_content=c, metadata={"source": "grant_agreement", "chunk": i})
            for i, c in enumerate(chunks)
        ]
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        store = Chroma.from_documents(docs, embeddings)
        result: Dict = {"store": store, "store_id": sid, "chunk_count": len(docs)}
        _grant_stores[sid] = result
        logger.info("Created Chroma grant store id=%s (%d chunks)", sid, len(docs))
        return result

    except Exception as e:
        logger.warning(
            "Chroma grant store unavailable (%s) — using keyword fallback", e
        )
        chunks_raw = [c.strip() for c in grant_text.split("\n\n") if c.strip()]
        result = {
            "store": None,
            "store_id": sid,
            "chunks": chunks_raw,
            "chunk_count": len(chunks_raw),
        }
        _grant_stores[sid] = result
        return result


def query_grant_store(grant_text: str, query: str, k: int = 3) -> str:
    """
    Query the grant agreement store for context relevant to `query`.

    Args:
        grant_text: Raw grant agreement text (used to build the store if needed).
        query:      Query string.
        k:          Number of results to return.

    Returns:
        Concatenated relevant excerpts as a single string.
    """
    result = create_grant_store(grant_text)

    if result.get("store") is not None:
        try:
            docs = result["store"].similarity_search(query, k=k)
            return "\n---\n".join(d.page_content for d in docs)
        except Exception as e:
            logger.error("Grant store similarity_search error: %s", e)

    # Keyword-based fallback
    chunks = result.get("chunks", [c.strip() for c in grant_text.split("\n\n") if c.strip()])
    if not chunks:
        return grant_text[:500]

    query_words = set(query.lower().split())
    scored = [
        (sum(1 for w in query_words if w in c.lower()), c)
        for c in chunks
    ]
    scored.sort(key=lambda x: -x[0])
    top = [c for _, c in scored[:k]]
    return "\n---\n".join(top) if top else "\n---\n".join(chunks[:k])
