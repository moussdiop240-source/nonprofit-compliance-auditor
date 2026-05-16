"""
2 CFR 200 vector store.
Enhancement 3: supports reindex() with version tagging.
"""
import os
import hashlib
import logging
import shutil
from datetime import datetime
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
CFR200_DIR: str = os.environ.get(
    "CFR200_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "cfr200_docs"),
)
PERSIST_DIR: str = os.environ.get("CFR200_PERSIST_DIR", "./chroma_cfr200")

# ── Module-level singletons ───────────────────────────────────────────────────
_store_instance: Optional[Any] = None
_store_version: Optional[str] = None


# ── Public API ────────────────────────────────────────────────────────────────

def load_cfr200_store(persist_dir: str = PERSIST_DIR) -> Optional[Any]:
    """
    Load (or create) the 2 CFR 200 Chroma vector store.
    Falls back gracefully when chromadb / langchain_community are unavailable.
    """
    global _store_instance, _store_version

    try:
        from langchain_community.vectorstores import Chroma
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except ImportError:
        logger.warning("langchain_community not available — using stub store")
        _store_version = "stub-" + datetime.now().strftime("%Y%m%d")
        _store_instance = None
        return None

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    if os.path.exists(persist_dir):
        _store_instance = Chroma(
            persist_directory=persist_dir, embedding_function=embeddings
        )
        _store_version = _compute_dir_hash(CFR200_DIR)
        logger.info("Loaded existing CFR200 store (version=%s)", _store_version)
        return _store_instance

    # Build from PDFs or fallback docs
    docs = _load_pdfs_from_dir(CFR200_DIR)
    if docs:
        _store_instance = Chroma.from_documents(
            docs, embeddings, persist_directory=persist_dir
        )
    else:
        _store_instance = Chroma(
            persist_directory=persist_dir, embedding_function=embeddings
        )
        _add_fallback_cfr200_docs(_store_instance)

    _store_version = _compute_dir_hash(CFR200_DIR)
    logger.info("Created CFR200 store (version=%s)", _store_version)
    return _store_instance


def reindex(
    cfr200_dir: Optional[str] = None,
    persist_dir: str = PERSIST_DIR,
) -> Optional[Any]:
    """
    Enhancement 3 — reindex():
    Wipe the existing Chroma collection, reload PDFs from cfr200_dir,
    and stamp a new version tag (datetime + content hash).
    The original load_cfr200_store() path remains intact.
    """
    global _store_instance, _store_version
    target_dir = cfr200_dir or CFR200_DIR

    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir)
        logger.info("Removed stale index at %s", persist_dir)

    try:
        from langchain_community.vectorstores import Chroma
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except ImportError:
        logger.warning("Cannot reindex: langchain_community not available")
        return None

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    docs = _load_pdfs_from_dir(target_dir)

    if docs:
        _store_instance = Chroma.from_documents(
            docs, embeddings, persist_directory=persist_dir
        )
    else:
        _store_instance = Chroma(
            persist_directory=persist_dir, embedding_function=embeddings
        )
        _add_fallback_cfr200_docs(_store_instance)

    _store_version = (
        datetime.now().strftime("%Y%m%d-%H%M%S")
        + "-"
        + _compute_dir_hash(target_dir)
    )
    logger.info("Reindexed CFR200 store, new version: %s", _store_version)
    return _store_instance


def query_cfr200(query: str, k: int = 3) -> str:
    """Query the CFR200 vector store; lazily loads if not yet initialised."""
    global _store_instance, _store_version
    if _store_instance is None:
        load_cfr200_store()

    version_tag = f"[CFR200 index v{_store_version or 'unknown'}]"

    if _store_instance is None:
        logger.debug("Using fallback CFR200 text for query: %s", query[:60])
        return version_tag + "\n" + _fallback_cfr200_text()

    try:
        docs = _store_instance.similarity_search(query, k=k)
        logger.info("CFR200 query (version=%s): %s", _store_version, query[:60])
        return version_tag + "\n" + "\n---\n".join(d.page_content for d in docs)
    except Exception as e:
        logger.error("CFR200 similarity_search error: %s", e)
        return version_tag + "\n" + _fallback_cfr200_text()


def get_store_version() -> Optional[str]:
    """Return the current index version tag."""
    return _store_version


# ── Private helpers ────────────────────────────────────────────────────────────

def _compute_dir_hash(directory: str) -> str:
    h = hashlib.sha256()
    if not os.path.isdir(directory):
        return "empty"
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".pdf"):
            h.update(fname.encode())
            try:
                with open(os.path.join(directory, fname), "rb") as f:
                    h.update(f.read(8192))
            except OSError:
                pass
    return h.hexdigest()[:12]


def _load_pdfs_from_dir(directory: str) -> list:
    if not os.path.isdir(directory):
        return []
    try:
        from langchain_community.document_loaders import PyPDFLoader
    except ImportError:
        return []
    docs = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".pdf"):
            try:
                loader = PyPDFLoader(os.path.join(directory, fname))
                docs.extend(loader.load())
            except Exception as e:
                logger.warning("Failed to load %s: %s", fname, e)
    return docs


def _add_fallback_cfr200_docs(store: Any) -> None:
    """Seed the store with built-in 2 CFR 200 excerpts when no PDFs are available."""
    try:
        from langchain_core.documents import Document
    except ImportError:
        return

    fallback_docs = [
        Document(
            page_content=(
                "2 CFR 200.420 — Factors affecting allowability of costs. "
                "To be allowable, costs must be: (1) necessary and reasonable for the "
                "performance of the award; (2) allocable; (3) in conformance with any "
                "limitations in these principles or the award; (4) consistent with "
                "policies applied uniformly to federally and non-federally financed "
                "activities; (5) accorded consistent treatment; (6) determined in "
                "accordance with GAAP; (7) not included as a cost or used to meet a "
                "cost-sharing requirement of any other federally-financed program; "
                "(8) adequately documented."
            ),
            metadata={"source": "2CFR200.420"},
        ),
        Document(
            page_content=(
                "2 CFR 200.474 — Travel costs. Travel costs are allowable when they "
                "are directly related to the performance of a Federal award. "
                "The $75 receipt rule: documentation required for any single expense "
                "over $75. Airfare must be coach/economy unless business class is "
                "justified. Per diem rates per GSA schedule apply for meals and lodging."
            ),
            metadata={"source": "2CFR200.474"},
        ),
        Document(
            page_content=(
                "2 CFR 200.431 — Compensation — fringe benefits. "
                "Fringe benefits are allowances and services provided to employees as "
                "compensation in addition to regular salaries. They are allowable if "
                "they are granted under established written policies. "
                "Unusually generous fringe benefits may be unallowable."
            ),
            metadata={"source": "2CFR200.431"},
        ),
        Document(
            page_content=(
                "2 CFR 200.421 — Advertising and public relations costs. "
                "Allowable only for: recruitment of personnel required for the project; "
                "procurement of goods and services; disposal of scrap or surplus. "
                "Costs for promoting the non-Federal entity's image are unallowable."
            ),
            metadata={"source": "2CFR200.421"},
        ),
        Document(
            page_content=(
                "2 CFR 200.451 — Lobbying costs. "
                "Costs associated with the following activities are unallowable: "
                "attempting to influence federal, state, or local legislation; "
                "influencing the introduction or enactment of any legislation."
            ),
            metadata={"source": "2CFR200.451"},
        ),
        Document(
            page_content=(
                "2 CFR 200.453 — Materials and supplies costs, including computing devices. "
                "Materials and supplies used for the performance of a Federal award are "
                "allowable. Computing devices are allowable as supplies if they are "
                "essential and allocable to the award."
            ),
            metadata={"source": "2CFR200.453"},
        ),
        Document(
            page_content=(
                "2 CFR 200.439 — Equipment and other capital expenditures. "
                "Capital expenditures for general-purpose equipment are unallowable as "
                "direct costs unless approved by the Federal awarding agency in advance. "
                "Special-purpose equipment used solely for research is allowable."
            ),
            metadata={"source": "2CFR200.439"},
        ),
        Document(
            page_content=(
                "2 CFR 200.432 — Conferences. "
                "Costs of meetings and conferences, the primary purpose of which is the "
                "dissemination of technical information, are allowable. "
                "Costs must be necessary and reasonable. "
                "Alcoholic beverages are unallowable (2 CFR 200.423)."
            ),
            metadata={"source": "2CFR200.432"},
        ),
    ]
    try:
        store.add_documents(fallback_docs)
    except Exception as e:
        logger.warning("Could not seed fallback CFR200 docs: %s", e)


def _fallback_cfr200_text() -> str:
    return (
        "2 CFR 200.420: Costs must be reasonable, allocable, and adequately documented. "
        "2 CFR 200.474: Travel costs allowable when they benefit the award; "
        "receipts required for expenses over $75; economy airfare required. "
        "2 CFR 200.451: Lobbying costs are unallowable. "
        "2 CFR 200.423: Alcoholic beverages are unallowable. "
        "2 CFR 200.439: General-purpose equipment requires prior approval."
    )
