"""
Enhancement 3: Live eCFR regulatory data fetcher.
Fetches 2 CFR Part 200 (Uniform Guidance) from the eCFR public API and converts
sections into LangChain Documents ready for vector store ingestion.
"""
import logging
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

ECFR_BASE = "https://www.ecfr.gov/api/versioner/v1"
_CFR_TITLE = 2
_CFR_PART = 200


def get_latest_version_date() -> Optional[str]:
    """Return the most recent amendment date for 2 CFR as 'YYYY-MM-DD', or None on failure."""
    if requests is None:
        logger.warning("requests not installed — cannot check eCFR")
        return None
    try:
        resp = requests.get(
            f"{ECFR_BASE}/versions/title-{_CFR_TITLE}.json", timeout=10
        )
        resp.raise_for_status()
        versions = resp.json().get("content_versions", [])
        if versions:
            return max(versions, key=lambda v: v.get("date", "")).get("date")
    except Exception as e:
        logger.warning("eCFR version check failed: %s", e)
    return None


def fetch_cfr200_sections(version_date: Optional[str] = None) -> list:
    """
    Fetch 2 CFR Part 200 from the eCFR API and return a list of LangChain Documents.
    Returns an empty list if the network or parse step fails.
    """
    if requests is None:
        logger.warning("requests not installed — cannot fetch from eCFR")
        return []
    try:
        from langchain_core.documents import Document  # noqa: F401 — verify importable
    except ImportError:
        logger.warning("langchain_core unavailable — cannot fetch from eCFR")
        return []

    date_str = version_date or "current"
    url = f"{ECFR_BASE}/full/{date_str}/title-{_CFR_TITLE}.xml?part={_CFR_PART}"

    try:
        logger.info("Fetching 2 CFR Part 200 from eCFR (date=%s)", date_str)
        resp = requests.get(url, timeout=60)  # type: ignore[union-attr]
        resp.raise_for_status()
        docs = _parse_cfr_xml(resp.text, version_date or str(date.today()))
        logger.info("Parsed %d sections from eCFR", len(docs))
        return docs
    except Exception as e:
        logger.warning("eCFR fetch failed: %s", e)
        return []


def _parse_cfr_xml(xml_text: str, version_date: str) -> list:
    """Parse eCFR XML into LangChain Documents, one per §200.x section."""
    try:
        from langchain_core.documents import Document
    except ImportError:
        return []

    docs = []
    try:
        root = ET.fromstring(xml_text)
        # Handle optional XML namespace prefix
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        # eCFR may use DIV8 (SGML-derived) or SECTION (traditional XML)
        sections = list(root.iter(f"{ns}DIV8")) or list(root.iter(f"{ns}SECTION"))

        for section in sections:
            # Section number: N attribute (DIV8) or SECTNO child text
            section_num = section.get("N", "")
            if not section_num:
                sectno_el = section.find(f"{ns}SECTNO")
                if sectno_el is not None and sectno_el.text:
                    section_num = sectno_el.text.strip().lstrip("§").strip()

            # Heading: HEAD child (DIV8) or SUBJECT child (SECTION)
            head_el = section.find(f"{ns}HEAD") or section.find(f"{ns}SUBJECT")
            if head_el is not None and head_el.text:
                head = f"§ {section_num} {head_el.text.strip()}"
            else:
                head = f"§ {section_num}" if section_num else "2 CFR 200 section"

            paragraphs = [
                p.text.strip()
                for p in section.iter(f"{ns}P")
                if p.text and p.text.strip()
            ]
            if not paragraphs:
                continue

            docs.append(Document(
                page_content=f"{head}\n" + "\n".join(paragraphs),
                metadata={
                    "source": f"2CFR{section_num}" if section_num else "2CFR200",
                    "section": section_num,
                    "version_date": version_date,
                    "origin": "ecfr_live",
                },
            ))
    except ET.ParseError as e:
        logger.warning("eCFR XML parse error: %s", e)

    return docs
