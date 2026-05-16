"""
Supervisor agent — orchestrates the full audit workflow.
Delegates to three specialist agents and routes to human review when needed.
"""
import logging
from agents.expense_extractor import extract_expenses
from agents.compliance_checker import check_compliance
from agents.report_writer import write_audit_report
from graph.hitl_handler import human_review_node

logger = logging.getLogger(__name__)


def run_audit(state: dict) -> dict:
    """
    Orchestrate the full audit cycle:
      1. Agent 1 — extract expense line items (if not already done)
      2. Agent 2 — check compliance for each item (if extraction is complete)
      3. HITL    — route to human review if items_pending_human_review is non-empty
      4. Agent 3 — generate the final audit report

    State flags used:
        extraction_complete          — set by Agent 1
        compliance_check_complete    — set by Agent 2
        human_review_complete        — set by the HITL handler
        report_generation_complete   — set by Agent 3
        audit_complete               — set here when everything is done

    Args:
        state: AuditState-compatible dict containing the input documents
               and all intermediate outputs.

    Returns:
        Updated state dict with audit_complete=True when done.
    """
    logger.info("Supervisor: starting audit for org=%s grant=%s",
                state.get("organization_name", "?"),
                state.get("grant_number", "?"))

    # Step 1 — Expense extraction
    if not state.get("extraction_complete"):
        logger.info("Supervisor → Agent 1 (expense extraction)")
        state = extract_expenses(state)

    # Step 2 — Compliance checking
    if state.get("extraction_complete") and not state.get("compliance_check_complete"):
        logger.info("Supervisor → Agent 2 (compliance checking)")
        state = check_compliance(state)

    # Step 3 — Human review for flagged items
    if (
        state.get("compliance_check_complete")
        and state.get("items_pending_human_review")
        and not state.get("human_review_complete")
    ):
        logger.info(
            "Supervisor → HITL (%d items pending review)",
            len(state["items_pending_human_review"]),
        )
        state = human_review_node(state)

    # Step 4 — Report generation
    if state.get("compliance_check_complete") and not state.get("report_generation_complete"):
        logger.info("Supervisor → Agent 3 (report writing)")
        state = write_audit_report(state)

    audit_complete = bool(state.get("report_generation_complete"))
    logger.info("Supervisor: audit_complete=%s", audit_complete)

    return {**state, "audit_complete": audit_complete}
