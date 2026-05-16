"""
Report formatting tools — converts a markdown audit report to a PDF binary.
Uses fpdf2 as the primary renderer.
"""
import io
import re
import logging
from typing import Union

logger = logging.getLogger(__name__)


def generate_pdf(markdown_text: str) -> bytes:
    """
    Convert a markdown-formatted audit report to a PDF binary.

    Args:
        markdown_text: The full audit report in markdown.

    Returns:
        Raw PDF bytes suitable for download or writing to disk.
    """
    try:
        return _render_with_fpdf(markdown_text)
    except Exception as e:
        logger.warning("fpdf render failed (%s) — using plain-text fallback", e)
        return _render_plain_text_pdf(markdown_text)


# ── Internal renderers ─────────────────────────────────────────────────────────

_MAX_WORD_LEN = 85  # characters — FPDF overflows on words wider than the page
_SEP_ROW_RE = re.compile(r"^\s*\|[\s\-|:]+\|")


def _strip_markdown(text: str) -> str:
    """Remove common markdown syntax and convert tables to readable plain text."""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.MULTILINE)
    # Convert table rows to pipe-separated readable text; drop separator rows
    text = re.sub(r"^\s*\|[^\n]*\|.*$", _table_row_to_text, text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text


def _table_row_to_text(m: re.Match) -> str:
    line = m.group(0)
    if _SEP_ROW_RE.match(line):   # |---|---| separator rows
        return ""
    cells = [c.strip() for c in line.strip().strip("|").split("|") if c.strip()]
    return "  |  ".join(cells)


def _safe_encode(text: str) -> str:
    """Encode to latin-1, replacing unsupported characters."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _break_long_words(text: str) -> str:
    """Insert spaces into words longer than _MAX_WORD_LEN to prevent FPDF overflow."""
    parts = []
    for word in text.split(" "):
        while len(word) > _MAX_WORD_LEN:
            parts.append(word[:_MAX_WORD_LEN])
            word = word[_MAX_WORD_LEN:]
        parts.append(word)
    return " ".join(parts)


def _safe_cell(pdf, h: float, text: str) -> None:
    """Render one line safely; always resets x to left margin before each attempt."""
    encoded = _break_long_words(_safe_encode(text))
    for attempt in (encoded,
                    _break_long_words(text.encode("ascii", "replace").decode("ascii")),
                    text.encode("ascii", "replace").decode("ascii")[:120]):
        pdf.set_x(pdf.l_margin)   # reset after any partial state from a prior failure
        try:
            pdf.multi_cell(0, h, attempt)
            return
        except Exception as exc:
            logger.debug("_safe_cell attempt failed (%s): %.60s", exc, attempt)
    # Last resort: silently skip the line
    logger.warning("_safe_cell: skipped unrenderable line: %.80s", text)


def _render_with_fpdf(markdown_text: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    plain = _strip_markdown(markdown_text)

    for line in plain.splitlines():
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue

        is_heading = (len(stripped) < 80 and stripped.isupper()) or (
            len(stripped) < 60 and stripped.endswith(":")
        )

        if is_heading:
            pdf.set_font("Helvetica", "B", 12)
            pdf.ln(2)
            _safe_cell(pdf, 7, stripped)
            pdf.ln(1)
        elif stripped.startswith("-"):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_x(25)
            _safe_cell(pdf, 5, stripped)
        else:
            pdf.set_font("Helvetica", "", 10)
            _safe_cell(pdf, 5, stripped)

    return bytes(pdf.output())


def _render_plain_text_pdf(text: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    plain = _strip_markdown(text)
    for line in plain.splitlines():
        _safe_cell(pdf, 5, line.strip() or " ")
    return bytes(pdf.output())
