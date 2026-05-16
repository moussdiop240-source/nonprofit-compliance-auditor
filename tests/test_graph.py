"""
Tests for graph/ modules: multi_agent_graph and hitl_handler.
All agent calls are mocked.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE_STATE: dict = {
    "expense_report_text": "Flight $450 Delta 2024-03-15",
    "grant_agreement_text": "Travel must follow GSA rates.",
    "organization_name": "Test Org",
    "grant_number": "GRANT-001",
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

ITEM = {"line_number": 1, "description": "Flight", "amount": 450.0, "category": "travel"}


# ══════════════════════════════════════════════════════════════════════════════
# graph/hitl_handler
# ══════════════════════════════════════════════════════════════════════════════

class TestHitlHandler:
    def test_no_pending_items(self):
        from graph.hitl_handler import human_review_node
        state = {**BASE_STATE}
        result = human_review_node(state)
        assert result["human_review_complete"] is True
        assert result["human_review_decisions"] == []

    def test_pending_items_all_approved(self):
        from graph.hitl_handler import human_review_node
        pending = [ITEM, {**ITEM, "line_number": 2}]
        state = {**BASE_STATE, "items_pending_human_review": pending}
        result = human_review_node(state)
        assert len(result["human_review_decisions"]) == 2
        for d in result["human_review_decisions"]:
            assert d["human_decision"] == "APPROVED"

    def test_message_appended(self):
        from graph.hitl_handler import human_review_node
        state = {**BASE_STATE, "items_pending_human_review": [ITEM]}
        result = human_review_node(state)
        assert any(m["agent"] == "HumanReview" for m in result["messages"])

    def test_current_agent_set_to_report_writer(self):
        from graph.hitl_handler import human_review_node
        result = human_review_node({**BASE_STATE})
        assert result["current_agent"] == "report_writer"

    def test_reviewed_at_present(self):
        from graph.hitl_handler import human_review_node
        state = {**BASE_STATE, "items_pending_human_review": [ITEM]}
        result = human_review_node(state)
        assert "reviewed_at" in result["human_review_decisions"][0]

    def test_review_note_present(self):
        from graph.hitl_handler import human_review_node
        state = {**BASE_STATE, "items_pending_human_review": [ITEM]}
        result = human_review_node(state)
        assert "human_review_note" in result["human_review_decisions"][0]


# ══════════════════════════════════════════════════════════════════════════════
# graph/multi_agent_graph
# ══════════════════════════════════════════════════════════════════════════════

def _make_extract_state(items):
    return {**BASE_STATE, "extracted_line_items": items, "extraction_complete": True,
            "messages": [{"agent": "ExpenseExtractor", "action": "done", "status": "complete"}]}

def _make_compliance_state(items, pending=None):
    decisions = [{**i, "status": "ALLOWABLE", "regulation_cited": "2CFR200.474",
                  "reasoning": "ok", "requires_human_review": False, "confidence_score": 0.9}
                 for i in items]
    return {**_make_extract_state(items),
            "compliance_decisions": decisions,
            "flagged_items": [],
            "total_allowable": sum(i["amount"] for i in items),
            "total_unallowable": 0.0,
            "compliance_check_complete": True,
            "items_pending_human_review": pending or [],
            "messages": [{"agent": "ComplianceChecker", "action": "done", "status": "complete"}]}

def _make_report_state(items):
    return {**_make_compliance_state(items),
            "human_review_complete": True,
            "audit_report_markdown": "# Report\n\nAll good.",
            "report_generation_complete": True,
            "current_agent": "supervisor",
            "audit_complete": True,
            "messages": [{"agent": "ReportWriter", "action": "done", "status": "complete"}]}


class TestRunGraph:
    @patch("graph.multi_agent_graph.extract_expenses")
    @patch("graph.multi_agent_graph.check_compliance")
    @patch("graph.multi_agent_graph.write_audit_report")
    @patch("graph.multi_agent_graph.human_review_node")
    def test_happy_path_no_review(self, mock_hitl, mock_report, mock_check, mock_extract):
        items = [ITEM]
        mock_extract.return_value = _make_extract_state(items)
        mock_check.return_value = _make_compliance_state(items)
        mock_report.return_value = _make_report_state(items)

        from graph.multi_agent_graph import run_graph
        result = run_graph(dict(BASE_STATE))

        mock_extract.assert_called_once()
        mock_check.assert_called_once()
        mock_hitl.assert_not_called()
        mock_report.assert_called_once()
        assert result["report_generation_complete"] is True

    @patch("graph.multi_agent_graph.extract_expenses")
    @patch("graph.multi_agent_graph.check_compliance")
    @patch("graph.multi_agent_graph.write_audit_report")
    @patch("graph.multi_agent_graph.human_review_node")
    def test_hitl_triggered_when_pending(self, mock_hitl, mock_report, mock_check, mock_extract):
        items = [ITEM]
        pending = [{**ITEM, "requires_human_review": True}]
        compliance_state = _make_compliance_state(items, pending=pending)

        mock_extract.return_value = _make_extract_state(items)
        mock_check.return_value = compliance_state
        mock_hitl.return_value = {
            **compliance_state,
            "human_review_complete": True,
            "items_pending_human_review": [],
        }
        mock_report.return_value = _make_report_state(items)

        from graph.multi_agent_graph import run_graph
        result = run_graph(dict(BASE_STATE))

        mock_hitl.assert_called_once()
        mock_report.assert_called_once()

    def test_route_end_when_complete(self):
        from graph.multi_agent_graph import _route
        state = {**BASE_STATE, "extraction_complete": True, "compliance_check_complete": True,
                 "report_generation_complete": True, "items_pending_human_review": []}
        assert _route(state) == "end"

    def test_route_extract_first(self):
        from graph.multi_agent_graph import _route
        assert _route(dict(BASE_STATE)) == "extract"

    def test_route_compliance_after_extract(self):
        from graph.multi_agent_graph import _route
        state = {**BASE_STATE, "extraction_complete": True}
        assert _route(state) == "compliance"

    def test_route_human_review_when_pending(self):
        from graph.multi_agent_graph import _route
        state = {**BASE_STATE, "extraction_complete": True,
                 "compliance_check_complete": True,
                 "items_pending_human_review": [ITEM],
                 "human_review_complete": False}
        assert _route(state) == "human_review"

    def test_route_report_after_review(self):
        from graph.multi_agent_graph import _route
        state = {**BASE_STATE, "extraction_complete": True,
                 "compliance_check_complete": True,
                 "human_review_complete": True,
                 "items_pending_human_review": [ITEM]}
        assert _route(state) == "report"


class TestBuildGraph:
    def test_build_graph_returns_callable(self):
        from graph.multi_agent_graph import build_graph
        g = build_graph()
        # LangGraph CompiledStateGraph uses .invoke(); plain fallback is callable()
        assert callable(g) or hasattr(g, "invoke")

    @patch("graph.multi_agent_graph.extract_expenses")
    @patch("graph.multi_agent_graph.check_compliance")
    @patch("graph.multi_agent_graph.write_audit_report")
    def test_run_graph_fallback_completes(self, mock_report, mock_check, mock_extract):
        items = [ITEM]
        mock_extract.return_value = _make_extract_state(items)
        mock_check.return_value = _make_compliance_state(items)
        mock_report.return_value = _make_report_state(items)

        from graph.multi_agent_graph import run_graph
        result = run_graph(dict(BASE_STATE))
        assert result.get("report_generation_complete") is True
