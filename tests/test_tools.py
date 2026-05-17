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
    detect_report_format,
    parse_tabular_expenses,
    enrich_line_items,
    flag_duplicate_items,
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
# Enhancement 1 NLP additions
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectReportFormat:
    def test_tabular_tab_separated(self):
        text = "Description\tAmount\tDate\nFlight\t$450.00\t2024-03-15\nHotel\t$300.00\t2024-03-16"
        assert detect_report_format(text) == "tabular"

    def test_tabular_pipe_separated(self):
        text = "| Description | Amount |\n| Flight | $450 |\n| Hotel | $300 |"
        assert detect_report_format(text) == "tabular"

    def test_list_numbered(self):
        text = "1. Flight to NYC $450.00\n2. Hotel stay $300.00\n3. Meals $75.00"
        assert detect_report_format(text) == "list"

    def test_list_bulleted(self):
        text = "- Flight $450.00\n- Hotel $300.00\n- Supplies $75.00"
        assert detect_report_format(text) == "list"

    def test_prose(self):
        text = (
            "The organization incurred travel expenses during the grant period. "
            "A flight costing $450 was taken to attend the annual conference. "
            "Hotel accommodations totaled $300 for two nights."
        )
        assert detect_report_format(text) == "prose"

    def test_empty_text_returns_prose(self):
        assert detect_report_format("") == "prose"


class TestParseTabularExpenses:
    _TAB_TEXT = (
        "Description\tAmount\tDate\tVendor\n"
        "Flight to conference\t$450.00\t2024-03-15\tDelta\n"
        "Hotel stay\t$300.00\t2024-03-16\tMarriott\n"
    )
    _PIPE_TEXT = (
        "| Description | Amount | Date |\n"
        "| Flight | $450.00 | 2024-03-15 |\n"
        "| Hotel | $300.00 | 2024-03-16 |\n"
    )

    def test_tab_separated_returns_items(self):
        items = parse_tabular_expenses(self._TAB_TEXT)
        assert len(items) == 2

    def test_pipe_separated_returns_items(self):
        items = parse_tabular_expenses(self._PIPE_TEXT)
        assert len(items) == 2

    def test_amounts_extracted(self):
        items = parse_tabular_expenses(self._TAB_TEXT)
        amounts = {i["amount"] for i in items}
        assert 450.0 in amounts
        assert 300.0 in amounts

    def test_dates_extracted(self):
        items = parse_tabular_expenses(self._TAB_TEXT)
        dates = {i["date"] for i in items}
        assert "2024-03-15" in dates

    def test_category_detected(self):
        items = parse_tabular_expenses(self._TAB_TEXT)
        assert items[0]["category"] == "travel"

    def test_no_amounts_returns_empty(self):
        items = parse_tabular_expenses("Description\tDate\nFlight\t2024-03-15")
        assert items == []

    def test_line_numbers_sequential(self):
        items = parse_tabular_expenses(self._TAB_TEXT)
        assert [i["line_number"] for i in items] == [1, 2]


class TestEnrichLineItems:
    def test_fills_missing_category(self):
        items = [{"description": "Flight to NYC", "amount": 450.0, "category": "", "vendor": ""}]
        enriched = enrich_line_items(items)
        assert enriched[0]["category"] == "travel"

    def test_normalizes_string_amount(self):
        items = [{"description": "Supplies", "amount": "$75.50", "category": "supplies", "vendor": ""}]
        enriched = enrich_line_items(items)
        assert enriched[0]["amount"] == 75.50

    def test_none_amount_becomes_zero(self):
        items = [{"description": "Misc", "amount": None, "category": "other", "vendor": ""}]
        enriched = enrich_line_items(items)
        assert enriched[0]["amount"] == 0.0

    def test_cleans_vendor_name(self):
        items = [{"description": "Supplies", "amount": 50.0, "category": "supplies", "vendor": "Acme Inc."}]
        enriched = enrich_line_items(items)
        assert "Inc" not in enriched[0]["vendor"]

    def test_does_not_overwrite_valid_category(self):
        items = [{"description": "Flight", "amount": 450.0, "category": "equipment", "vendor": ""}]
        enriched = enrich_line_items(items)
        assert enriched[0]["category"] == "equipment"

    def test_returns_same_list_length(self):
        items = [
            {"description": "A", "amount": 100.0, "category": "", "vendor": ""},
            {"description": "B", "amount": 200.0, "category": "travel", "vendor": ""},
        ]
        assert len(enrich_line_items(items)) == 2


class TestFlagDuplicateItems:
    def test_identical_descriptions_same_amount_flagged(self):
        items = [
            {"description": "Flight to conference", "amount": 450.0},
            {"description": "Flight to conference", "amount": 450.0},
        ]
        result = flag_duplicate_items(items)
        assert any(i.get("possible_duplicate") for i in result)

    def test_distinct_items_not_flagged(self):
        items = [
            {"description": "Flight to conference", "amount": 450.0},
            {"description": "Office supplies purchase", "amount": 75.0},
            {"description": "Hotel accommodation", "amount": 300.0},
        ]
        result = flag_duplicate_items(items)
        assert not any(i.get("possible_duplicate") for i in result)

    def test_single_item_unchanged(self):
        items = [{"description": "Flight", "amount": 450.0}]
        assert flag_duplicate_items(items) == items

    def test_similar_descriptions_different_amounts_not_flagged(self):
        items = [
            {"description": "Hotel stay first night", "amount": 150.0},
            {"description": "Hotel stay second night", "amount": 300.0},
        ]
        result = flag_duplicate_items(items)
        # Amounts differ by 100% — should not be flagged
        assert not all(i.get("possible_duplicate") for i in result)

    def test_empty_list_returns_empty(self):
        assert flag_duplicate_items([]) == []


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
