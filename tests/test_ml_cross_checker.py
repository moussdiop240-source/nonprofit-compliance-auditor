"""
Tests for tools/ml_cross_checker.py (Enhancement 2 — ML-driven cross-checking).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.ml_cross_checker import (
    prescreen_unallowable,
    detect_amount_anomalies,
    cross_check_budget,
)


# ══════════════════════════════════════════════════════════════════════════════
# prescreen_unallowable
# ══════════════════════════════════════════════════════════════════════════════

class TestPrescreenUnallowable:
    def test_alcohol_flagged(self):
        r = prescreen_unallowable("Beer and wine for team dinner", 120.0)
        assert r["prescreened"] is True
        assert r["unallowable"] is True
        assert "200.423" in r["regulation"]

    def test_lobbying_flagged(self):
        r = prescreen_unallowable("Lobbying consultant fee", 5000.0)
        assert r["prescreened"] is True
        assert r["unallowable"] is True
        assert "200.451" in r["regulation"]

    def test_entertainment_flagged(self):
        r = prescreen_unallowable("Casino entertainment night", 300.0)
        assert r["prescreened"] is True
        assert r["unallowable"] is True
        assert "200.438" in r["regulation"]

    def test_personal_expense_flagged(self):
        r = prescreen_unallowable("Personal vacation travel", 800.0)
        assert r["prescreened"] is True
        assert r["unallowable"] is True

    def test_first_class_conditionally_allowable(self):
        r = prescreen_unallowable("First-class airfare to conference", 2400.0)
        assert r["prescreened"] is True
        assert r["unallowable"] is False
        assert r["conditionally_allowable"] is True
        assert "200.474" in r["regulation"]

    def test_allowable_expense_not_flagged(self):
        r = prescreen_unallowable("Flight to annual conference", 450.0)
        assert r["prescreened"] is False
        assert r["unallowable"] is False
        assert r["conditionally_allowable"] is False

    def test_office_supplies_not_flagged(self):
        r = prescreen_unallowable("Office supplies — paper and toner", 75.0)
        assert r["prescreened"] is False

    def test_returns_dict_with_required_keys(self):
        r = prescreen_unallowable("Any expense", 100.0)
        for key in ("prescreened", "unallowable", "conditionally_allowable", "regulation", "reason"):
            assert key in r

    def test_case_insensitive_matching(self):
        r = prescreen_unallowable("BEER AND WINE purchase", 50.0)
        assert r["unallowable"] is True

    def test_empty_description_not_flagged(self):
        r = prescreen_unallowable("", 0.0)
        assert r["prescreened"] is False


# ══════════════════════════════════════════════════════════════════════════════
# detect_amount_anomalies
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectAmountAnomalies:
    def test_outlier_flagged(self):
        items = [
            {"description": "Hotel A", "amount": 150.0, "category": "travel"},
            {"description": "Hotel B", "amount": 160.0, "category": "travel"},
            {"description": "Hotel C", "amount": 155.0, "category": "travel"},
            {"description": "Hotel D", "amount": 5000.0, "category": "travel"},  # outlier
        ]
        result = detect_amount_anomalies(items)
        assert result[3]["amount_anomaly"] is True

    def test_normal_items_not_flagged(self):
        items = [
            {"description": "Supply A", "amount": 50.0, "category": "supplies"},
            {"description": "Supply B", "amount": 55.0, "category": "supplies"},
            {"description": "Supply C", "amount": 48.0, "category": "supplies"},
        ]
        result = detect_amount_anomalies(items)
        assert not any(i["amount_anomaly"] for i in result)

    def test_z_score_added_to_all_items(self):
        items = [
            {"description": "A", "amount": 100.0, "category": "travel"},
            {"description": "B", "amount": 200.0, "category": "travel"},
            {"description": "C", "amount": 150.0, "category": "travel"},
        ]
        result = detect_amount_anomalies(items)
        assert all("amount_z_score" in i for i in result)

    def test_single_item_not_flagged(self):
        items = [{"description": "Solo", "amount": 9999.0, "category": "equipment"}]
        result = detect_amount_anomalies(items)
        assert result[0]["amount_anomaly"] is False

    def test_categories_evaluated_separately(self):
        items = [
            {"description": "T1", "amount": 400.0, "category": "travel"},
            {"description": "T2", "amount": 420.0, "category": "travel"},
            {"description": "T3", "amount": 380.0, "category": "travel"},
            {"description": "S1", "amount": 50.0,  "category": "supplies"},
            {"description": "S2", "amount": 55.0,  "category": "supplies"},
            {"description": "S3", "amount": 4500.0, "category": "supplies"},  # outlier only in supplies
        ]
        result = detect_amount_anomalies(items)
        travel = [i for i in result if i["category"] == "travel"]
        supplies = [i for i in result if i["category"] == "supplies"]
        assert not any(i["amount_anomaly"] for i in travel)
        assert result[5]["amount_anomaly"] is True

    def test_empty_list_returns_empty(self):
        assert detect_amount_anomalies([]) == []

    def test_returns_same_list_length(self):
        items = [
            {"description": "A", "amount": 100.0, "category": "travel"},
            {"description": "B", "amount": 200.0, "category": "supplies"},
        ]
        assert len(detect_amount_anomalies(items)) == 2


# ══════════════════════════════════════════════════════════════════════════════
# cross_check_budget
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossCheckBudget:
    _ITEMS = [
        {"description": "Flight",   "amount": 600.0, "category": "travel"},
        {"description": "Hotel",    "amount": 500.0, "category": "travel"},
        {"description": "Supplies", "amount": 200.0, "category": "supplies"},
    ]
    _BUDGET = {"travel": 1000.0, "supplies": 500.0}

    def test_exceeded_category_detected(self):
        result = cross_check_budget(self._ITEMS, self._BUDGET)
        assert result["travel"]["exceeded"] is True

    def test_under_budget_not_exceeded(self):
        result = cross_check_budget(self._ITEMS, self._BUDGET)
        assert result["supplies"]["exceeded"] is False

    def test_spent_totals_correct(self):
        result = cross_check_budget(self._ITEMS, self._BUDGET)
        assert result["travel"]["spent"] == 1100.0
        assert result["supplies"]["spent"] == 200.0

    def test_pct_used_computed(self):
        result = cross_check_budget(self._ITEMS, self._BUDGET)
        assert result["travel"]["pct_used"] == 110.0  # 1100/1000 * 100
        assert result["supplies"]["pct_used"] == 40.0

    def test_no_budget_line_gives_none(self):
        items = [{"description": "Training", "amount": 300.0, "category": "professional"}]
        result = cross_check_budget(items, {})
        assert result["professional"]["budget"] is None
        assert result["professional"]["exceeded"] is False
        assert result["professional"]["pct_used"] is None

    def test_empty_items_returns_budget_categories(self):
        result = cross_check_budget([], {"travel": 1000.0})
        assert result["travel"]["spent"] == 0.0
        assert result["travel"]["exceeded"] is False

    def test_empty_budget_and_items_returns_empty(self):
        assert cross_check_budget([], {}) == {}

    def test_result_has_required_keys(self):
        result = cross_check_budget(self._ITEMS, self._BUDGET)
        for cat in result:
            for key in ("spent", "budget", "exceeded", "pct_used"):
                assert key in result[cat]


# ══════════════════════════════════════════════════════════════════════════════
# Integration: compliance_checker uses ml_cross_checker
# ══════════════════════════════════════════════════════════════════════════════

class TestComplianceCheckerWithMlLayer:
    """Verify the compliance checker correctly routes pre-screened items."""

    _BASE_STATE = {
        "expense_report_text": "",
        "grant_agreement_text": "Travel budget: $1,000. Personnel: $5,000.",
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

    def test_alcohol_item_marked_unallowable_without_llm(self):
        from unittest.mock import patch, MagicMock
        from agents.compliance_checker import check_compliance

        state = {
            **self._BASE_STATE,
            "extracted_line_items": [
                {"line_number": 1, "description": "Beer and wine reception",
                 "amount": 250.0, "category": "food", "vendor": "Bar", "date": "2024-03-15"},
            ],
        }
        with patch("agents.compliance_checker.ChatOllama") as mock_llm:
            result = check_compliance(dict(state))

        # LLM should not have been instantiated for a pre-screened item
        mock_llm.assert_not_called()
        decision = result["compliance_decisions"][0]
        assert decision["status"] == "UNALLOWABLE"
        assert "200.423" in decision["regulation_cited"]
        assert decision.get("prescreened") is True

    def test_budget_analysis_in_state(self):
        from unittest.mock import patch, MagicMock
        from agents.compliance_checker import check_compliance

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = '{"status":"ALLOWABLE","regulation_cited":"2 CFR 200.474","reasoning":"ok","requires_human_review":false,"flagged_reason":null}'

        state = {
            **self._BASE_STATE,
            "grant_agreement_text": "Travel expenses not to exceed $500.",
            "extracted_line_items": [
                {"line_number": 1, "description": "Flight to conference",
                 "amount": 600.0, "category": "travel", "vendor": "Delta", "date": "2024-03-15"},
            ],
        }
        with patch("agents.compliance_checker.ChatPromptTemplate") as mock_pt, \
             patch("agents.compliance_checker.StrOutputParser"), \
             patch("agents.compliance_checker.query_cfr200_store", return_value="travel costs"), \
             patch("agents.compliance_checker.query_grant_store", return_value="travel limit $500"):
            def fake_from_messages(msgs):
                m = MagicMock()
                m.__or__ = MagicMock(return_value=mock_chain)
                return m
            mock_pt.from_messages = fake_from_messages
            result = check_compliance(dict(state))

        assert "budget_analysis" in result
        assert isinstance(result["budget_analysis"], dict)

    def test_anomaly_flag_passed_to_llm_prompt(self):
        """Items with amount_anomaly should mention it in the LLM invocation."""
        from unittest.mock import patch, MagicMock
        from agents.compliance_checker import check_compliance

        # Two travel items: one normal, one very large outlier
        state = {
            **self._BASE_STATE,
            "extracted_line_items": [
                {"line_number": 1, "description": "Flight A", "amount": 400.0,
                 "category": "travel", "vendor": "", "date": ""},
                {"line_number": 2, "description": "Flight B", "amount": 400.0,
                 "category": "travel", "vendor": "", "date": ""},
                {"line_number": 3, "description": "Private jet", "amount": 50000.0,
                 "category": "travel", "vendor": "", "date": ""},
            ],
        }

        _ok = '{"status":"ALLOWABLE","regulation_cited":"x","reasoning":"ok","requires_human_review":false,"flagged_reason":null}'
        invoke_calls = []

        def make_chain():
            chain = MagicMock()
            chain.__or__ = MagicMock(return_value=chain)  # chain | x returns chain
            chain.invoke = MagicMock(
                side_effect=lambda kwargs: invoke_calls.append(kwargs) or _ok
            )
            return chain

        with patch("agents.compliance_checker.ChatPromptTemplate") as mock_pt, \
             patch("agents.compliance_checker.StrOutputParser"), \
             patch("agents.compliance_checker.query_cfr200_store", return_value="travel"), \
             patch("agents.compliance_checker.query_grant_store", return_value="ok"):

            def fake_from_messages(msgs):
                m = MagicMock()
                m.__or__ = MagicMock(return_value=make_chain())
                return m

            mock_pt.from_messages = fake_from_messages
            check_compliance(dict(state))

        # The outlier item's LLM call should indicate anomaly
        anomaly_calls = [c for c in invoke_calls if "YES" in str(c.get("anomaly", ""))]
        assert len(anomaly_calls) >= 1
