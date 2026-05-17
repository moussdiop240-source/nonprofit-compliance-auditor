"""
Tests for tools/regulatory_fetcher.py (Enhancement 3 — eCFR live integration).
All network calls are mocked.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.regulatory_fetcher import (
    get_latest_version_date,
    fetch_cfr200_sections,
    _parse_cfr_xml,
)

# ── Sample data ────────────────────────────────────────────────────────────────

_VERSIONS_JSON = {
    "content_versions": [
        {"date": "2024-01-15"},
        {"date": "2024-06-01"},
        {"date": "2023-11-20"},
    ]
}

_SAMPLE_XML = """<?xml version="1.0"?>
<ECFR>
  <DIV8 N="200.1">
    <HEAD>Definitions.</HEAD>
    <P>As used in this part the following definitions apply.</P>
    <P>Advance means a payment made before outlays are made.</P>
  </DIV8>
  <DIV8 N="200.420">
    <HEAD>Considerations for selected items of cost.</HEAD>
    <P>Sections 200.421 through 200.475 provide principles for allowability.</P>
  </DIV8>
  <DIV8 N="200.474">
    <HEAD>Travel costs.</HEAD>
    <P>Travel costs are allowable when directly related to a Federal award.</P>
    <P>Receipts required for expenses over $75.</P>
  </DIV8>
</ECFR>"""

_SECTION_ONLY_XML = """<?xml version="1.0"?>
<ROOT>
  <SECTION>
    <SECTNO>§ 200.1</SECTNO>
    <SUBJECT>Definitions.</SUBJECT>
    <P>Paragraph one.</P>
  </SECTION>
</ROOT>"""

_EMPTY_SECTIONS_XML = """<?xml version="1.0"?>
<ECFR>
  <DIV8 N="200.1">
    <HEAD>No paragraphs here.</HEAD>
  </DIV8>
</ECFR>"""


# ══════════════════════════════════════════════════════════════════════════════
# get_latest_version_date
# ══════════════════════════════════════════════════════════════════════════════

class TestGetLatestVersionDate:
    def test_returns_most_recent_date(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _VERSIONS_JSON
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp):
            result = get_latest_version_date()
        assert result == "2024-06-01"

    def test_returns_none_on_network_error(self):
        with patch("tools.regulatory_fetcher.requests.get", side_effect=Exception("timeout")):
            result = get_latest_version_date()
        assert result is None

    def test_returns_none_on_empty_versions(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"content_versions": []}
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp):
            result = get_latest_version_date()
        assert result is None

    def test_returns_none_when_requests_unavailable(self):
        with patch("tools.regulatory_fetcher.requests", None):
            result = get_latest_version_date()
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# fetch_cfr200_sections
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchCfr200Sections:
    def test_returns_documents_on_success(self):
        mock_resp = MagicMock()
        mock_resp.text = _SAMPLE_XML
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp):
            docs = fetch_cfr200_sections("2024-06-01")
        assert len(docs) == 3
        assert all(hasattr(d, "page_content") for d in docs)

    def test_returns_empty_on_network_failure(self):
        with patch("tools.regulatory_fetcher.requests.get", side_effect=Exception("refused")):
            docs = fetch_cfr200_sections()
        assert docs == []

    def test_uses_current_when_no_date_given(self):
        mock_resp = MagicMock()
        mock_resp.text = _SAMPLE_XML
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp) as mock_get:
            fetch_cfr200_sections()
        call_url = mock_get.call_args[0][0]
        assert "current" in call_url

    def test_uses_provided_date_in_url(self):
        mock_resp = MagicMock()
        mock_resp.text = _SAMPLE_XML
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp) as mock_get:
            fetch_cfr200_sections("2024-06-01")
        call_url = mock_get.call_args[0][0]
        assert "2024-06-01" in call_url

    def test_part_200_filter_in_url(self):
        mock_resp = MagicMock()
        mock_resp.text = _SAMPLE_XML
        with patch("tools.regulatory_fetcher.requests.get", return_value=mock_resp) as mock_get:
            fetch_cfr200_sections()
        call_url = mock_get.call_args[0][0]
        assert "part=200" in call_url


# ══════════════════════════════════════════════════════════════════════════════
# _parse_cfr_xml
# ══════════════════════════════════════════════════════════════════════════════

class TestParseCfrXml:
    def test_parses_div8_sections(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        assert len(docs) == 3

    def test_section_numbers_in_metadata(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        nums = {d.metadata["section"] for d in docs}
        assert "200.1" in nums
        assert "200.420" in nums
        assert "200.474" in nums

    def test_version_date_in_metadata(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        assert all(d.metadata["version_date"] == "2024-06-01" for d in docs)

    def test_origin_is_ecfr_live(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        assert all(d.metadata["origin"] == "ecfr_live" for d in docs)

    def test_page_content_contains_heading_and_paragraphs(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        travel = next(d for d in docs if d.metadata["section"] == "200.474")
        assert "Travel costs" in travel.page_content
        assert "$75" in travel.page_content

    def test_parses_section_element_fallback(self):
        docs = _parse_cfr_xml(_SECTION_ONLY_XML, "2024-01-01")
        assert len(docs) == 1
        assert "Paragraph one" in docs[0].page_content

    def test_skips_sections_with_no_paragraphs(self):
        docs = _parse_cfr_xml(_EMPTY_SECTIONS_XML, "2024-01-01")
        assert docs == []

    def test_returns_empty_on_invalid_xml(self):
        docs = _parse_cfr_xml("<<<not xml>>>", "2024-01-01")
        assert docs == []

    def test_source_metadata_format(self):
        docs = _parse_cfr_xml(_SAMPLE_XML, "2024-06-01")
        sources = {d.metadata["source"] for d in docs}
        assert "2CFR200.1" in sources


# ══════════════════════════════════════════════════════════════════════════════
# check_ecfr_update (via cfr200_store)
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckEcfrUpdate:
    def test_update_available_when_store_not_loaded(self):
        import vectorstores.cfr200_store as cs
        cs._store_version = None
        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            from vectorstores.cfr200_store import check_ecfr_update
            result = check_ecfr_update()
        assert result["update_available"] is True
        assert result["latest_ecfr_date"] == "2024-06-01"

    def test_no_update_when_already_current(self):
        import vectorstores.cfr200_store as cs
        cs._store_version = "ecfr-2024-06-01-abc123def456"
        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            from vectorstores.cfr200_store import check_ecfr_update
            result = check_ecfr_update()
        assert result["update_available"] is False
        assert result["current_date"] == "2024-06-01"

    def test_update_available_when_index_is_older(self):
        import vectorstores.cfr200_store as cs
        cs._store_version = "ecfr-2023-01-01-abc123def456"
        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            from vectorstores.cfr200_store import check_ecfr_update
            result = check_ecfr_update()
        assert result["update_available"] is True

    def test_update_available_when_pdf_indexed(self):
        import vectorstores.cfr200_store as cs
        cs._store_version = "20240101-120000-abc123def456"  # local PDF reindex
        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            from vectorstores.cfr200_store import check_ecfr_update
            result = check_ecfr_update()
        # No date embedded → treat as update available
        assert result["update_available"] is True
        assert result["current_date"] is None

    def test_no_update_when_ecfr_unreachable(self):
        import vectorstores.cfr200_store as cs
        cs._store_version = "ecfr-2024-06-01-abc123def456"
        with patch("tools.regulatory_fetcher.requests.get", side_effect=Exception("timeout")):
            from vectorstores.cfr200_store import check_ecfr_update
            result = check_ecfr_update()
        assert result["latest_ecfr_date"] is None
        assert result["update_available"] is False


# ══════════════════════════════════════════════════════════════════════════════
# reindex_from_ecfr (via cfr200_store)
# ══════════════════════════════════════════════════════════════════════════════

class TestReindexFromEcfr:
    def setup_method(self):
        import vectorstores.cfr200_store as cs
        cs._store_instance = None
        cs._store_version = None

    def test_sets_ecfr_version_stamp(self):
        import vectorstores.cfr200_store as cs
        mock_store = MagicMock()
        mock_chroma = MagicMock(return_value=mock_store)
        mock_chroma.from_documents = MagicMock(return_value=mock_store)
        mock_embed = MagicMock()

        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            mock_get.return_value.text = _SAMPLE_XML

            with patch.dict("sys.modules", {
                "langchain_huggingface": MagicMock(HuggingFaceEmbeddings=MagicMock(return_value=mock_embed)),
                "langchain_chroma": MagicMock(Chroma=mock_chroma),
            }):
                with patch("vectorstores.cfr200_store.os.path.exists", return_value=False):
                    from vectorstores.cfr200_store import reindex_from_ecfr
                    reindex_from_ecfr(persist_dir="./fake_chroma")

        assert cs._store_version is not None
        assert cs._store_version.startswith("ecfr-")

    def test_returns_none_when_no_docs_fetched(self):
        with patch("tools.regulatory_fetcher.requests.get", side_effect=Exception("down")):
            from vectorstores.cfr200_store import reindex_from_ecfr
            result = reindex_from_ecfr(persist_dir="./fake_chroma")
        assert result is None

    def test_version_contains_ecfr_date(self):
        import vectorstores.cfr200_store as cs
        mock_store = MagicMock()
        mock_chroma = MagicMock()
        mock_chroma.from_documents = MagicMock(return_value=mock_store)
        mock_embed = MagicMock()

        with patch("tools.regulatory_fetcher.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VERSIONS_JSON
            mock_get.return_value.text = _SAMPLE_XML

            with patch.dict("sys.modules", {
                "langchain_huggingface": MagicMock(HuggingFaceEmbeddings=MagicMock(return_value=mock_embed)),
                "langchain_chroma": MagicMock(Chroma=mock_chroma),
            }):
                with patch("vectorstores.cfr200_store.os.path.exists", return_value=False):
                    from vectorstores.cfr200_store import reindex_from_ecfr
                    reindex_from_ecfr(persist_dir="./fake_chroma")

        assert "2024-06-01" in cs._store_version
