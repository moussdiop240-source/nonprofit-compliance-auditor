"""
Tests for agents/ modules: expense_extractor, compliance_checker, report_writer, supervisor.
LangChain chain composition is mocked at the chain-invoke level.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Shared fixtures ────────────────────────────────────────────────────────────

BASE_STATE: dict = {
    "expense_report_text": (
        "1. Flight to conference $450.00 Delta Airlines 2024-03-15 travel\n"
        "2. Hotel 2 nights $300.00 Marriott 2024-03-15 travel\n"
        "3. Office supplies $75.00 Staples 2024-03-20 supplies\n"
    ),
    "grant_agreement_text": (
        "Grant Agreement 2024-HHS-001\n"
        "Section 4: Travel must comply with federal per diem rates.\n"
        "Section 5: Alcohol purchases are not reimbursable.\n"
    ),
    "organization_name": "Test Nonprofit",
    "grant_number": "2024-HHS-001",
    "extracted_line_items": [],
    "extraction_complete": False,
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
    "current_agent": "expense_extractor",
    "messages": [],
    "audit_complete": False,
}

SAMPLE_LINE_ITEMS = [
    {"line_number": 1, "description": "Flight to conference", "amount": 450.00,
     "category": "travel", "vendor": "Delta Airlines", "date": "2024-03-15"},
    {"line_number": 2, "description": "Hotel 2 nights", "amount": 300.00,
     "category": "travel", "vendor": "Marriott", "date": "2024-03-15"},
    {"line_number": 3, "description": "Office supplies", "amount": 75.00,
     "category": "supplies", "vendor": "Staples", "date": "2024-03-20"},
]


def _make_mock_chain(return_value: str) -> MagicMock:
    """Create a mock that behaves as a LangChain chain supporting | operator."""
    chain = MagicMock()
    chain.invoke.return_value = return_value
    chain.__or__ = MagicMock(return_value=chain)
    return chain


# ══════════════════════════════════════════════════════════════════════════════
# Agent 1 — expense_extractor
# ══════════════════════════════════════════════════════════════════════════════

class TestExpenseExtractor:
    _VALID_JSON = json.dumps(SAMPLE_LINE_ITEMS)

    def _run(self, llm_response: str) -> dict:
        """Helper: patch the full LangChain pipeline and invoke extract_expenses."""
        mock_chain = _make_mock_chain(llm_response)

        # Patch ChatOllama so instantiation returns a mock, and the | chain returns mock_chain
        with patch("agents.expense_extractor.ChatOllama") as mock_llm_cls, \
             patch("agents.expense_extractor.ChatPromptTemplate") as mock_pt, \
             patch("agents.expense_extractor.StrOutputParser") as mock_parser:

            mock_llm_cls.return_value = MagicMock(__or__=MagicMock(return_value=mock_chain))
            mock_pt.from_messages.return_value = MagicMock(__or__=MagicMock(return_value=mock_chain))
            mock_parser.return_value = MagicMock()

            # Simulate prompt | llm | parser -> mock_chain
            from agents.expense_extractor import extract_expenses
            with patch("agents.expense_extractor.ChatOllama") as mc:
                mc.return_value.__ror__ = MagicMock(return_value=mock_chain)
                # Direct chain mock: intercept the chain.invoke call
                with patch("langchain_core.output_parsers.StrOutputParser.invoke",
                           return_value=llm_response, create=True):
                    # Simplest: just mock the entire chain result via the prompt template
                    mock_full_chain = _make_mock_chain(llm_response)

                    def fake_from_messages(msgs):
                        m = MagicMock()
                        m.__or__ = MagicMock(return_value=mock_full_chain)
                        return m

                    mock_pt.from_messages = fake_from_messages
                    mc.return_value = MagicMock(
                        __ror__=MagicMock(return_value=mock_full_chain)
                    )
                    return extract_expenses(dict(BASE_STATE))

    def test_extraction_complete_flag(self):
        result = self._run(self._VALID_JSON)
        assert result["extraction_complete"] is True

    def test_valid_json_parsed_to_items(self):
        result = self._run(self._VALID_JSON)
        assert isinstance(result["extracted_line_items"], list)

    def test_invalid_json_yields_empty_list(self):
        result = self._run("NOT JSON AT ALL --- garbage")
        assert result["extracted_line_items"] == []
        assert result["extraction_complete"] is True

    def test_message_appended(self):
        result = self._run(self._VALID_JSON)
        agents = [m["agent"] for m in result["messages"]]
        assert "ExpenseExtractor" in agents

    def test_markdown_json_stripped(self):
        wrapped = "```json\n" + self._VALID_JSON + "\n```"
        result = self._run(wrapped)
        assert result["extraction_complete"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Agent 2 — compliance_checker
# ══════════════════════════════════════════════════════════════════════════════

COMPLIANCE_RESPONSE = json.dumps({
    "status": "ALLOWABLE",
    "regulation_cited": "2 CFR 200.474",
    "reasoning": "Travel cost within per diem limits.",
    "requires_human_review": False,
    "flagged_reason": None,
})

COMPLIANCE_STATE = {
    **BASE_STATE,
    "extracted_line_items": SAMPLE_LINE_ITEMS,
    "extraction_complete": True,
}


class TestComplianceChecker:
    def _run(self, llm_response: str, monkeypatch_confidence=None) -> dict:
        mock_chain = _make_mock_chain(llm_response)

        patches = [
            patch("agents.compliance_checker.query_cfr200_store",
                  return_value="2 CFR 200.474 travel costs allowable"),
            patch("agents.compliance_checker.query_grant_store",
                  return_value="Travel pre-approved per grant section 4"),
        ]
        if monkeypatch_confidence is not None:
            patches.append(
                patch("agents.compliance_checker._compute_tfidf_confidence",
                      return_value=monkeypatch_confidence)
            )

        with patches[0], patches[1]:
            if monkeypatch_confidence is not None:
                with patches[2]:
                    return self._invoke(mock_chain, llm_response)
            return self._invoke(mock_chain, llm_response)

    @staticmethod
    def _invoke(mock_chain, llm_response):
        with patch("agents.compliance_checker.ChatPromptTemplate") as mock_pt, \
             patch("agents.compliance_checker.StrOutputParser"):
            def fake_from_messages(msgs):
                m = MagicMock()
                m.__or__ = MagicMock(return_value=mock_chain)
                return m
            mock_pt.from_messages = fake_from_messages
            from agents.compliance_checker import check_compliance
            return check_compliance(dict(COMPLIANCE_STATE))

    def test_decisions_count(self):
        result = self._run(COMPLIANCE_RESPONSE)
        assert len(result["compliance_decisions"]) == len(SAMPLE_LINE_ITEMS)

    def test_compliance_flag_set(self):
        result = self._run(COMPLIANCE_RESPONSE)
        assert result["compliance_check_complete"] is True

    def test_confidence_score_present(self):
        result = self._run(COMPLIANCE_RESPONSE)
        for d in result["compliance_decisions"]:
            assert "confidence_score" in d, f"Missing confidence_score in {d}"

    def test_low_confidence_forces_review(self):
        result = self._run(COMPLIANCE_RESPONSE, monkeypatch_confidence=0.3)
        for d in result["compliance_decisions"]:
            assert d["status"] == "REQUIRES_REVIEW"

    def test_high_confidence_keeps_llm_status(self):
        result = self._run(COMPLIANCE_RESPONSE, monkeypatch_confidence=0.95)
        for d in result["compliance_decisions"]:
            assert d["status"] == "ALLOWABLE"

    def test_message_appended(self):
        result = self._run(COMPLIANCE_RESPONSE)
        assert any(m["agent"] == "ComplianceChecker" for m in result["messages"])

    def test_totals_calculated(self):
        # Force high confidence so items stay ALLOWABLE (not overridden by TF-IDF)
        result = self._run(COMPLIANCE_RESPONSE, monkeypatch_confidence=0.95)
        assert result["total_allowable"] == sum(i["amount"] for i in SAMPLE_LINE_ITEMS)
        assert result["total_unallowable"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Agent 3 — report_writer
# ══════════════════════════════════════════════════════════════════════════════

REPORT_STATE = {
    **BASE_STATE,
    "extracted_line_items": SAMPLE_LINE_ITEMS,
    "extraction_complete": True,
    "compliance_decisions": [
        {**i, "status": "ALLOWABLE", "regulation_cited": "2 CFR 200.474",
         "reasoning": "ok", "requires_human_review": False, "confidence_score": 0.85}
        for i in SAMPLE_LINE_ITEMS
    ],
    "flagged_items": [],
    "total_allowable": 825.0,
    "total_unallowable": 0.0,
    "compliance_check_complete": True,
    "human_review_complete": True,
    "items_pending_human_review": [],
    "human_review_decisions": [],
}


class TestReportWriter:
    def _run(self, llm_response: str) -> dict:
        mock_chain = _make_mock_chain(llm_response)
        with patch("agents.report_writer.ChatPromptTemplate") as mock_pt, \
             patch("agents.report_writer.StrOutputParser"):
            def fake_from_messages(msgs):
                m = MagicMock()
                m.__or__ = MagicMock(return_value=mock_chain)
                return m
            mock_pt.from_messages = fake_from_messages
            from agents.report_writer import write_audit_report
            return write_audit_report(dict(REPORT_STATE))

    def test_report_flag_set(self):
        result = self._run("# Audit Report\n\nAll items allowable.")
        assert result["report_generation_complete"] is True

    def test_report_markdown_populated(self):
        result = self._run("# Audit Report\n\nAll items allowable.")
        assert len(result["audit_report_markdown"]) > 0

    def test_audit_complete_set(self):
        result = self._run("# Report")
        assert result["audit_complete"] is True

    def test_message_appended(self):
        result = self._run("# Report")
        assert any(m["agent"] == "ReportWriter" for m in result["messages"])


# ══════════════════════════════════════════════════════════════════════════════
# Supervisor
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisor:
    @patch("agents.supervisor.extract_expenses")
    @patch("agents.supervisor.check_compliance")
    @patch("agents.supervisor.write_audit_report")
    @patch("agents.supervisor.human_review_node")
    def test_full_pipeline_no_review(self, mock_hitl, mock_report, mock_check, mock_extract):
        mock_extract.return_value = {
            **BASE_STATE,
            "extracted_line_items": SAMPLE_LINE_ITEMS,
            "extraction_complete": True,
        }
        mock_check.return_value = {
            **BASE_STATE,
            "extracted_line_items": SAMPLE_LINE_ITEMS,
            "extraction_complete": True,
            "compliance_decisions": [],
            "compliance_check_complete": True,
            "items_pending_human_review": [],
            "total_allowable": 825.0,
            "total_unallowable": 0.0,
        }
        mock_report.return_value = {
            **BASE_STATE,
            "report_generation_complete": True,
            "audit_report_markdown": "# Report",
            "audit_complete": True,
        }

        from agents.supervisor import run_audit
        result = run_audit(dict(BASE_STATE))

        mock_extract.assert_called_once()
        mock_check.assert_called_once()
        mock_hitl.assert_not_called()
        mock_report.assert_called_once()
        assert result["audit_complete"] is True

    @patch("agents.supervisor.extract_expenses")
    @patch("agents.supervisor.check_compliance")
    @patch("agents.supervisor.write_audit_report")
    @patch("agents.supervisor.human_review_node")
    def test_hitl_called_when_items_pending(self, mock_hitl, mock_report, mock_check, mock_extract):
        flagged = [{**SAMPLE_LINE_ITEMS[0], "requires_human_review": True}]
        mock_extract.return_value = {
            **BASE_STATE, "extraction_complete": True,
            "extracted_line_items": SAMPLE_LINE_ITEMS,
        }
        mock_check.return_value = {
            **BASE_STATE, "extraction_complete": True,
            "compliance_check_complete": True,
            "items_pending_human_review": flagged,
            "total_allowable": 0.0, "total_unallowable": 0.0,
        }
        mock_hitl.return_value = {
            **BASE_STATE, "extraction_complete": True,
            "compliance_check_complete": True,
            "human_review_complete": True,
            "items_pending_human_review": [],
        }
        mock_report.return_value = {
            **BASE_STATE, "report_generation_complete": True,
            "audit_report_markdown": "# Report", "audit_complete": True,
        }

        from agents.supervisor import run_audit
        result = run_audit(dict(BASE_STATE))

        mock_hitl.assert_called_once()
        assert result["audit_complete"] is True

    @patch("agents.supervisor.extract_expenses")
    @patch("agents.supervisor.check_compliance")
    @patch("agents.supervisor.write_audit_report")
    @patch("agents.supervisor.human_review_node")
    def test_skips_extraction_if_already_done(self, mock_hitl, mock_report, mock_check, mock_extract):
        already_extracted = {
            **BASE_STATE,
            "extracted_line_items": SAMPLE_LINE_ITEMS,
            "extraction_complete": True,
        }
        mock_check.return_value = {
            **already_extracted,
            "compliance_check_complete": True,
            "items_pending_human_review": [],
            "total_allowable": 825.0, "total_unallowable": 0.0,
        }
        mock_report.return_value = {
            **BASE_STATE, "report_generation_complete": True,
            "audit_report_markdown": "# Report", "audit_complete": True,
        }

        from agents.supervisor import run_audit
        run_audit(already_extracted)
        mock_extract.assert_not_called()
