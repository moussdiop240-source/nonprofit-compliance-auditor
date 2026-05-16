"""
Document text and metadata extraction tools.
Supports PDF (pdfplumber → PyPDF2) and Excel (.xlsx / .xls via pandas + openpyxl).
"""
import io
import logging
from typing import Union, Dict

logger = logging.getLogger(__name__)


def extract_text_from_pdf(source: Union[str, bytes, io.BytesIO]) -> str:
    """
    Extract all text from a PDF file.

    Args:
        source: File path (str), raw bytes, or BytesIO object.

    Returns:
        Extracted text as a single string with pages separated by newlines.
    """
    try:
        import pdfplumber
        buf = _to_buffer(source)
        with pdfplumber.open(buf) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
    except ImportError:
        logger.debug("pdfplumber not available, trying PyPDF2")
    except Exception as e:
        logger.warning("pdfplumber failed: %s — trying PyPDF2", e)

    try:
        import PyPDF2
        buf = _to_buffer(source)
        reader = PyPDF2.PdfReader(buf)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except ImportError:
        raise RuntimeError(
            "No PDF library available. Install pdfplumber or PyPDF2:\n"
            "  pip install pdfplumber"
        )
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e


def extract_metadata_from_pdf(source: Union[str, bytes, io.BytesIO]) -> Dict:
    """
    Extract metadata (title, author, page count, etc.) from a PDF.

    Args:
        source: File path (str), raw bytes, or BytesIO object.

    Returns:
        Dict with keys: page_count, title, author, creator, producer.
    """
    try:
        import pdfplumber
        buf = _to_buffer(source)
        with pdfplumber.open(buf) as pdf:
            meta = pdf.metadata or {}
            return {
                "page_count": len(pdf.pages),
                "title": meta.get("Title", ""),
                "author": meta.get("Author", ""),
                "creator": meta.get("Creator", ""),
                "producer": meta.get("Producer", ""),
            }
    except ImportError:
        pass
    except Exception as e:
        logger.warning("pdfplumber metadata failed: %s — trying PyPDF2", e)

    try:
        import PyPDF2
        buf = _to_buffer(source)
        reader = PyPDF2.PdfReader(buf)
        meta = reader.metadata or {}
        return {
            "page_count": len(reader.pages),
            "title": meta.get("/Title", ""),
            "author": meta.get("/Author", ""),
            "creator": meta.get("/Creator", ""),
            "producer": meta.get("/Producer", ""),
        }
    except ImportError:
        raise RuntimeError("Install pdfplumber or PyPDF2: pip install pdfplumber")
    except Exception as e:
        raise RuntimeError(f"PDF metadata extraction failed: {e}") from e


def extract_text_from_excel(source: Union[str, bytes, io.BytesIO]) -> str:
    """
    Extract text from an Excel file (.xlsx / .xls).
    Each sheet is rendered as a plain-text table with column headers,
    producing output the LLM can parse the same way it parses PDF text.
    """
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required for Excel support: pip install pandas openpyxl")

    buf = _to_buffer(source)
    try:
        sheets = pd.read_excel(buf, sheet_name=None, engine="openpyxl", dtype=str)
    except Exception:
        buf = _to_buffer(source)
        try:
            sheets = pd.read_excel(buf, sheet_name=None, engine="xlrd", dtype=str)
        except Exception as e:
            raise RuntimeError(f"Excel extraction failed: {e}") from e

    parts: list[str] = []
    for sheet_name, df in sheets.items():
        df = df.dropna(how="all").fillna("")
        if df.empty:
            continue
        parts.append(f"[Sheet: {sheet_name}]")
        parts.append(df.to_string(index=False))
        parts.append("")  # blank line between sheets

    return "\n".join(parts)


def extract_text_from_file(
    source: Union[str, bytes, io.BytesIO],
    filename: str = "",
) -> str:
    """
    Dispatch to the right extractor based on filename extension.
    Falls back to PDF extraction when extension is unknown.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if filename else ""
    if ext in ("xlsx", "xls"):
        return extract_text_from_excel(source)
    return extract_text_from_pdf(source)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _to_buffer(source: Union[str, bytes, io.BytesIO]) -> Union[str, io.BytesIO]:
    """Normalise source to a file path or BytesIO."""
    if isinstance(source, bytes):
        return io.BytesIO(source)
    return source
