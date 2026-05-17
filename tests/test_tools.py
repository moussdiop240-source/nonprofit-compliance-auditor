"""
Tests for tools/ modules: pdf_tools, nlp_utils, formatting_tools, rag_tools.
All external dependencies (pdfplumber, PyPDF2, fpdf, chromadb) are mocked.
"""
import io
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ══════════════════════════════════════════════════════════════════════════════
# tools/nlp_utils
# ══════════════════════════════════════════════════════════════════════════════

from tools.nlp_utils import (
    extract_amounts,
    extract_dates,
    clean_vendor_name,
    detect_category,
    preprocess_expense_text,
    build_nlp_hint_block,
    extract_grant_budget,
)


class TestExtractAmounts:
    def test_dollar_sign_with_decimals(self):
        assert 450.00 in extract_amounts("Flight: $450.00")

    def test_plain_number(self):
        assert 1200.0 in extract_amounts("Paid 1200 to vendor")

    def test_comma_separated(self):
        assert 1500.50 in extract_amounts("Total: $1,500.50")

    def test_multiple_amounts(self):
        amounts = extract_amounts("$100.00 for meals, $50.25 for parking")
        assert len(amounts) == 2

    def test_no_amounts(self):
        assert extract_amounts("No numbers here") == []


class TestExtractDates:
    def test_iso_format(self):
        assert "2024-03-15" in extract_dates("Date: 2024-03-15")

    def test_us_format(self):
        assert "3/15/2024" in extract_dates("Invoice 3/15/2024")

    def test_no_dates(self):
        assert extract_dates("No date here") == []

    def test_multiple_dates(self):
        dates = extract_dates("2024-01-01 and 2024-12-31")
        assert len(dates) >= 2


class TestCleanVendorName:
    def test_removes_inc(self):
        assert "Delta Airlines" in clean_vendor_name("Delta Airlines Inc.")

    def test_removes_llc(self):
        result = clean_vendor_name("Acme Consulting LLC")
        assert "LLC" not in result

    def test_none_returns_empty(self):
        assert clean_vendor_name(None) == ""

    def test_plain_name_unchanged(self):
        assert "Marriott" in clean_vendor_name("Marriott")


class TestDetectCategory:
    def test_travel(self):
        assert detect_category("Flight to annual conference") == "travel"

    def test_supplies(self):
        assert detect_category("Office supplies: paper and toner") == "supplies"

    def test_unknown(self):
        assert detect_category("Miscellaneous widget") is None


class TestPreprocessExpenseText:
    SAMPLE = "Flight to NYC: $450.00 on 2024-03-15 via Delta Airlines Inc."

    def test_returns_dict(self):
        result = preprocess_expense_text(self.SAMPLE)
        assert isinstance(result, dict)

    def test_amounts_detected(self):
        result = preprocess_expense_text(self.SAMPLE)
        assert 450.0 in result["amounts"]

    def test_dates_detected(self):
        result = preprocess_expense_text(self.SAMPLE)
        assert "2024-03-15" in result["dates"]

    def test_line_count(self):
        result = preprocess_expense_text("line1\nline2\nline3")
        assert result["line_count"] == 3


class TestBuildNlpHintBlock:
    def test_contains_header(self):
        block = build_nlp_hint_block({"amounts": [100.0], "dates": ["2024-01-01"], "vendor_candidates": [], "line_count": 1})
        assert "[NLP PRE-ANALYSIS]" in block

    def test_contains_amounts(self):
        block = build_nlp_hint_block({"amounts": [99.99], "dates": [], "vendor_candidates": [], "line_count": 1})
        assert "$99.99" in block


class TestExtractGrantBudget:
    def test_detects_personnel_budget(self):
        text = "Personnel salaries: $45,000 for the project period."
        budget = extract_grant_budget(text)
        assert "personnel" in budget
        assert budget["personnel"] == 45000.0

    def test_detects_travel_budget(self):
        text = "Travel and per diem expenses not to exceed $5,000."
        budget = extract_grant_budget(text)
        assert "travel" in budget
        assert budget["travel"] == 5000.0

    def test_detects_multiple_categories(self):
        text = (
            "Personnel salary: $30,000\n"
            "Travel airfare: $3,500\n"
            "Supplies and materials: $1,200\n"
        )
        budget = extract_grant_budget(text)
        assert "personnel" in budget
        assert "travel" in budget
        assert "supplies" in budget

    def test_empty_text_returns_empty_dict(self):
        assert extract_grant_budget("") == {}

    def test_no_dollar_amounts_returns_empty_dict(self):
        text = "This grant covers personnel and travel activities."
        budget = extract_grant_budget(text)
        # No dollar amounts — should return empty
        assert budget == {}

    def test_keeps_largest_amount_per_category(self):
        text = (
            "Personnel: $10,000\n"
            "Personnel salaries: $50,000\n"
        )
        budget = extract_grant_budget(text)
        assert budget.get("personnel") == 50000.0


# ══════════════════════════════════════════════════════════════════════════════
# tools/pdf_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfTools:
    """Mock pdfplumber so no real PDF library is required during tests."""

    def _make_mock_pdf(self, text: str):
        page = MagicMock()
        page.extract_text.return_value = text
        pdf_ctx = MagicMock()
        pdf_ctx.__enter__ = MagicMock(return_value=pdf_ctx)
        pdf_ctx.__exit__ = MagicMock(return_value=False)
        pdf_ctx.pages = [page]
        pdf_ctx.metadata = {"Title": "Test", "Author": "Tester"}
        return pdf_ctx

    @patch("tools.pdf_tools._to_buffer", return_value=io.BytesIO(b"fake"))
    @patch("pdfplumber.open")
    def test_extract_text(self, mock_open_fn, mock_buf):
        mock_open_fn.return_value = self._make_mock_pdf("Expense: $500")
        from tools.pdf_tools import extract_text_from_pdf
        text = extract_text_from_pdf(b"fake_pdf")
        assert "Expense" in text

    @patch("tools.pdf_tools._to_buffer", return_value=io.BytesIO(b"fake"))
    @patch("pdfplumber.open")
    def test_extract_metadata(self, mock_open_fn, mock_buf):
        mock_open_fn.return_value = self._make_mock_pdf("")
        from tools.pdf_tools import extract_metadata_from_pdf
        meta = extract_metadata_from_pdf(b"fake_pdf")
        assert "page_count" in meta
        assert meta["title"] == "Test"


# ══════════════════════════════════════════════════════════════════════════════
# tools/formatting_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestFormattingTools:
    SAMPLE_MARKDOWN = (
        "# Audit Report\n\n"
        "**Organization:** Test Org\n\n"
        "## Summary\n\n"
        "- Item 1: ALLOWABLE\n"
        "- Item 2: UNALLOWABLE\n\n"
        "Total allowable: $1,000.00\n"
    )

    def test_generate_pdf_returns_bytes(self):
        from tools.formatting_tools import generate_pdf
        result = generate_pdf(self.SAMPLE_MARKDOWN)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_generate_pdf_starts_with_pdf_header(self):
        from tools.formatting_tools import generate_pdf
        result = generate_pdf(self.SAMPLE_MARKDOWN)
        assert result[:4] == b"%PDF"

    def test_strip_markdown_removes_headers(self):
        from tools.formatting_tools import _strip_markdown
        assert "# " not in _strip_markdown("# Title")

    def test_strip_markdown_removes_bold(self):
        from tools.formatting_tools import _strip_markdown
        assert "**" not in _strip_markdown("**bold text**")


# ══════════════════════════════════════════════════════════════════════════════
# tools/rag_tools
# ══════════════════════════════════════════════════════════════════════════════

class TestRagTools:
    @patch("tools.rag_tools.query_cfr200", return_value="[CFR200 index v1]\n2 CFR 200.474 travel costs")
    @patch("tools.rag_tools.get_store_version", return_value="test-v1")
    def test_query_cfr200_store(self, mock_ver, mock_query):
        from tools.rag_tools import query_cfr200_store
        result = query_cfr200_store("travel expenses")
        assert "travel" in result.lower()
        mock_query.assert_called_once()

    @patch("tools.rag_tools._query_grant_store", return_value="Grant Section 3: travel pre-approval required")
    def test_query_grant_store(self, mock_query):
        from tools.rag_tools import query_grant_store
        result = query_grant_store("Grant text here", "travel approval")
        assert "travel" in result.lower()
        mock_query.assert_called_once()
