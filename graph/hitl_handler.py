"""
Human-in-the-Loop handler.
When human_review_decisions are pre-populated (via the Streamlit HITL form after a
LangGraph interrupt_before pause), they are applied to compliance_decisions and totals.
Falls back to auto-approval when no decisions are provided (direct-call / test path).
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_DECISION_TO_STATUS = {
    "APPROVED": "ALLOWABLE",
    "CONDITIONALLY_APPROVED": "CONDITIONALLY_ALLOWABLE",
    "REJECTED": "UNALLOWABLE",
}


def human_review_node(state: dict) -> dict:
    """
    Process flagged items.

    Real-HITL path: human_review_decisions already populated by the UI before
    this node runs (LangGraph resumes after interrupt_before + update_state).

    Fallback path: auto-approves all pending items (tests / no-LangGraph flow).
    """
    pending = state.get("items_pending_human_review", [])
    provided = state.get("human_review_decisions", [])

    if provided:
        return _apply_human_decisions(state, provided)
    return _auto_approve(state, pending)


# ── Private helpers ────────────────────────────────────────────────────────────

def _apply_human_decisions(state: dict, decisions: list) -> dict:
    """Merge auditor decisions back into compliance_decisions and recalculate totals."""
    decision_map = {d.get("line_number"): d for d in decisions}

    total_allowable = state.get("total_allowable", 0.0)
    total_unallowable = state.get("total_unallowable", 0.0)
    updated_decisions = []

    for cd in state.get("compliance_decisions", []):
        ln = cd.get("line_number")
        hd = decision_map.get(ln)
        if hd:
            human_decision = hd.get("human_decision", "APPROVED")
            new_status = _DECISION_TO_STATUS.get(human_decision, "ALLOWABLE")
            old_status = cd.get("status", "")
            amount = cd.get("amount", 0.0)

            # Adjust running totals for the status change
            if old_status == "ALLOWABLE":
                total_allowable -= amount
            elif old_status == "UNALLOWABLE":
                total_unallowable -= amount

            if new_status == "ALLOWABLE":
                total_allowable += amount
            elif new_status == "UNALLOWABLE":
                total_unallowable += amount

            cd = {
                **cd,
                "status": new_status,
                "human_decision": human_decision,
                "human_review_note": hd.get("human_review_note", ""),
                "reviewed_at": hd.get("reviewed_at", ""),
            }
        updated_decisions.append(cd)

    logger.info(
        "HITL applied %d human decision(s); allowable=%.2f unallowable=%.2f",
        len(decisions), total_allowable, total_unallowable,
    )
    new_message = {
        "agent": "HumanReview",
        "action": f"Auditor reviewed {len(decisions)} flagged item(s)",
        "status": "complete",
    }
    return {
        **state,
        "compliance_decisions": updated_decisions,
        "total_allowable": total_allowable,
        "total_unallowable": total_unallowable,
        "human_review_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "report_writer",
    }


def _auto_approve(state: dict, pending: list) -> dict:
    """Fallback: approve all pending items automatically."""
    logger.info("HITL: auto-approving %d pending items", len(pending))
    reviewed = [
        {
            **item,
            "human_decision": "APPROVED",
            "human_review_note": (
                f"Auto-approved by system on "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
            ),
            "reviewed_at": datetime.now().isoformat(),
        }
        for item in pending
    ]
    new_message = {
        "agent": "HumanReview",
        "action": f"Auto-approved {len(pending)} flagged item(s)",
        "status": "complete",
    }
    return {
        **state,
        "human_review_decisions": reviewed,
        "human_review_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "report_writer",
    }
