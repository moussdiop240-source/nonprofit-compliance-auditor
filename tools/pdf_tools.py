"""
PDF text and metadata extraction tools.
Tries pdfplumber first, falls back to PyPDF2.
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


# ── Internal helpers ───────────────────────────────────────────────────────────

def _to_buffer(source: Union[str, bytes, io.BytesIO]) -> Union[str, io.BytesIO]:
    """Normalise source to a file path or BytesIO."""
    if isinstance(source, bytes):
        return io.BytesIO(source)
    return source
