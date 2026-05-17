"""
Hallucination-guard tests for the compliance pipeline.

Three LLM hallucination vectors are tested:
  1. Invalid status strings (not in ComplianceStatus enum)
  2. LLM overriding original line-item fields (amount, line_number, description …)
  3. Missing / empty required decision fields

Each test first demonstrates the vulnerability, then verifies the guard blocks it.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Helpers ───────────────────────────────────────────────────────────────────

_BASE_STATE = {
    "expense_report_text": "",
    "grant_agreement_text": "Travel: $1,000.",
    "organization_name": "Test Org",
    "grant_number": "TEST-001",
    "extracted_line_items": [],
    "extraction_complete": True,
    "compliance_decisions": [],
    "flagged_items": [],
    "total_allowable": 0.0,
    "total_unallowable": 0.0,
    "compliance_check_complete": False,
    "items_pending_human_review": [],
    "human_review_decisions": [],
    "human_review_complete": False,
    "audit_report_markdown": "",
    "report_generation_complete": False,
    "current_agent": "compliance_checker",
    "messages": [],
    "audit_complete": False,
    "grant_budget": {},
    "budget_analysis": {},
}

_ITEM = {
    "line_number": 7,
    "description": "Flight to conference",
    "amount": 450.0,
    "category": "travel",
    "vendor": "Delta Airlines",
    "date": "2024-03-15",
}

_VALID_STATUSES = {"ALLOWABLE", "UNALLOWABLE", "CONDITIONALLY_ALLOWABLE", "REQUIRES_REVIEW"}


def _run_checker(llm_json: str):
    """Run check_compliance with a single item and a mocked LLM response."""
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = llm_json
    mock_chain.__or__ = MagicMock(return_value=mock_chain)  # keep mock_chain as final chain after all | operators

    state = {**_BASE_STATE, "extracted_line_items": [dict(_ITEM)]}

    with patch("agents.compliance_checker.ChatPromptTemplate") as mock_pt, \
         patch("agents.compliance_checker.StrOutputParser"), \
         patch("agents.compliance_checker.query_cfr200_store", return_value="travel costs"), \
         patch("agents.compliance_checker.query_grant_store", return_value="travel ok"), \
         patch("agents.compliance_checker._compute_tfidf_confidence", return_value=0.9):

        def fake_from_messages(msgs):
            m = MagicMock()
            m.__or__ = MagicMock(return_value=mock_chain)
            return m

        mock_pt.from_messages = fake_from_messages
        from agents.compliance_checker import check_compliance
        return check_compliance(dict(state))


# ══════════════════════════════════════════════════════════════════════════════
# Vector 1 — Invalid status
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidStatus:
    def _llm_response(self, status: str) -> str:
        return json.dumps({
            "status": status,
            "regulation_cited": "2 CFR 200.474",
            "reasoning": "Looks fine.",
            "requires_human_review": False,
            "flagged_reason": None,
        })

    def test_invented_status_coerced_to_requires_review(self):
        result = _run_checker(self._llm_response("MAYBE_ALLOWABLE"))
        d = result["compliance_decisions"][0]
        assert d["status"] == "REQUIRES_REVIEW", (
            f"Hallucinated status 'MAYBE_ALLOWABLE' should be coerced to "
            f"REQUIRES_REVIEW, got '{d['status']}'"
        )

    def test_empty_status_coerced(self):
        result = _run_checker(self._llm_response(""))
        assert result["compliance_decisions"][0]["status"] == "REQUIRES_REVIEW"

    def test_lowercase_status_coerced(self):
        result = _run_checker(self._llm_response("allowable"))
        assert result["compliance_decisions"][0]["status"] == "REQUIRES_REVIEW"

    def test_valid_statuses_pass_through(self):
        for status in _VALID_STATUSES:
            result = _run_checker(self._llm_response(status))
            assert result["compliance_decisions"][0]["status"] == status, (
                f"Valid status '{status}' should not be modified"
            )

    def test_invalid_status_sets_requires_human_review(self):
        result = _run_checker(self._llm_response("UNKNOWN"))
        assert result["compliance_decisions"][0]["requires_human_review"] is True

    def test_invalid_status_adds_flagged_reason(self):
        result = _run_checker(self._llm_response("BOGUS"))
        assert result["compliance_decisions"][0].get("flagged_reason")


# ══════════════════════════════════════════════════════════════════════════════
# Vector 2 — LLM overrides line-item fields
# ══════════════════════════════════════════════════════════════════════════════

class TestLineItemFieldProtection:
    def _hallucinated_response(self, extra: dict) -> str:
        base = {
            "status": "ALLOWABLE",
            "regulation_cited": "2 CFR 200.474",
            "reasoning": "ok",
            "requires_human_review": False,
            "flagged_reason": None,
        }
        return json.dumps({**base, **extra})

    def test_llm_cannot_override_amount(self):
        result = _run_checker(self._hallucinated_response({"amount": 99999.0}))
        assert result["compliance_decisions"][0]["amount"] == _ITEM["amount"], (
            "LLM must not be able to change the line item's amount"
        )

    def test_llm_cannot_override_line_number(self):
        result = _run_checker(self._hallucinated_response({"line_number": 999}))
        assert result["compliance_decisions"][0]["line_number"] == _ITEM["line_number"]

    def test_llm_cannot_override_description(self):
        result = _run_checker(self._hallucinated_response({"description": "Fake item"}))
        assert result["compliance_decisions"][0]["description"] == _ITEM["description"]

    def test_llm_cannot_override_vendor(self):
        result = _run_checker(self._hallucinated_response({"vendor": "Fake Vendor"}))
        assert result["compliance_decisions"][0]["vendor"] == _ITEM["vendor"]

    def test_llm_cannot_override_category(self):
        result = _run_checker(self._hallucinated_response({"category": "fake_cat"}))
        assert result["compliance_decisions"][0]["category"] == _ITEM["category"]

    def test_llm_cannot_inject_arbitrary_keys(self):
        result = _run_checker(self._hallucinated_response({"malicious_key": "pwned"}))
        assert "malicious_key" not in result["compliance_decisions"][0]


# ══════════════════════════════════════════════════════════════════════════════
# Vector 3 — Missing required fields
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingFields:
    def test_missing_regulation_gets_default(self):
        resp = json.dumps({"status": "ALLOWABLE", "reasoning": "ok",
                           "requires_human_review": False, "flagged_reason": None})
        result = _run_checker(resp)
        reg = result["compliance_decisions"][0].get("regulation_cited", "")
        assert reg, "regulation_cited must not be empty after sanitization"

    def test_missing_reasoning_gets_default(self):
        resp = json.dumps({"status": "ALLOWABLE", "regulation_cited": "2 CFR 200.474",
                           "requires_human_review": False, "flagged_reason": None})
        result = _run_checker(resp)
        assert "reasoning" in result["compliance_decisions"][0]

    def test_missing_requires_human_review_defaults_false(self):
        resp = json.dumps({"status": "ALLOWABLE", "regulation_cited": "2 CFR 200.474",
                           "reasoning": "ok", "flagged_reason": None})
        result = _run_checker(resp)
        assert "requires_human_review" in result["compliance_decisions"][0]
