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

def _strip_markdown(text: str) -> str:
    """Remove common markdown syntax for plain-text rendering."""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|.*\|.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text


def _safe_encode(text: str) -> str:
    """Encode to latin-1, replacing unsupported characters."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _render_with_fpdf(markdown_text: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    plain = _strip_markdown(markdown_text)
    lines = plain.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue

        # Detect heading-like lines (short, ALL CAPS or ends with ':')
        is_heading = (len(stripped) < 80 and stripped.isupper()) or (
            len(stripped) < 60 and stripped.endswith(":")
        )

        if is_heading:
            pdf.set_font("Arial", "B", 12)
            pdf.ln(2)
            try:
                pdf.multi_cell(0, 7, _safe_encode(stripped))
            except Exception:
                pdf.multi_cell(0, 7, stripped.encode("ascii", "replace").decode("ascii"))
            pdf.ln(1)
        elif stripped.startswith("•"):
            pdf.set_font("Arial", "", 10)
            pdf.set_x(25)
            try:
                pdf.multi_cell(0, 5, _safe_encode(stripped))
            except Exception:
                pdf.multi_cell(0, 5, stripped.encode("ascii", "replace").decode("ascii"))
        else:
            pdf.set_font("Arial", "", 10)
            try:
                pdf.multi_cell(0, 5, _safe_encode(stripped))
            except Exception:
                pdf.multi_cell(0, 5, stripped.encode("ascii", "replace").decode("ascii"))

    return bytes(pdf.output())


def _render_plain_text_pdf(text: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    plain = _strip_markdown(text)
    for line in plain.splitlines():
        try:
            pdf.multi_cell(0, 5, _safe_encode(line))
        except Exception:
            pdf.multi_cell(0, 5, line.encode("ascii", "replace").decode("ascii"))
    return bytes(pdf.output())
