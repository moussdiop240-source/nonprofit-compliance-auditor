"""
Human-in-the-Loop handler.
Currently simulates approval of all pending items.
Replace the body of human_review_node() with an interactive step when ready.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def human_review_node(state: dict) -> dict:
    """
    Process all items in items_pending_human_review.

    Simulation mode: every pending item is auto-approved with a timestamped note.
    A future interactive implementation can replace this logic while keeping the
    same input/output contract.

    Args:
        state: Current AuditState dict.

    Returns:
        Updated state with human_review_decisions populated and
        human_review_complete set to True.
    """
    pending = state.get("items_pending_human_review", [])
    logger.info("HITL: processing %d pending items (simulated approval)", len(pending))

    reviewed = []
    for item in pending:
        reviewed.append({
            **item,
            "human_decision": "APPROVED",
            "human_review_note": (
                f"Auto-approved by system on "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                "Replace this node with an interactive UI step for real human review."
            ),
            "reviewed_at": datetime.now().isoformat(),
        })

    new_message = {
        "agent": "HumanReview",
        "action": f"Reviewed {len(pending)} flagged item(s) — simulated approval",
        "status": "complete",
    }

    return {
        **state,
        "human_review_decisions": reviewed,
        "human_review_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "report_writer",
    }
