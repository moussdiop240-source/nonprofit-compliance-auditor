"""
Multi-agent graph assembly.
Builds a LangGraph StateGraph when langgraph is available,
falling back to a simple state-machine loop otherwise.
"""
import logging
from agents.expense_extractor import extract_expenses
from agents.compliance_checker import check_compliance
from agents.report_writer import write_audit_report
from graph.hitl_handler import human_review_node

logger = logging.getLogger(__name__)


# ── Simple state-machine fallback ─────────────────────────────────────────────

def _route(state: dict) -> str:
    """Determine the next node based on state flags."""
    if not state.get("extraction_complete"):
        return "extract"
    if not state.get("compliance_check_complete"):
        return "compliance"
    if state.get("items_pending_human_review") and not state.get("human_review_complete"):
        return "human_review"
    if not state.get("report_generation_complete"):
        return "report"
    return "end"


def run_graph(initial_state: dict) -> dict:
    """
    Execute the multi-agent workflow as a simple iterative state machine.
    Safe to call even without langgraph installed.
    """
    state = dict(initial_state)
    max_steps = 20

    for step in range(max_steps):
        next_node = _route(state)
        logger.debug("Graph step %d → node=%s", step, next_node)

        if next_node == "end":
            break
        elif next_node == "extract":
            state = extract_expenses(state)
        elif next_node == "compliance":
            state = check_compliance(state)
        elif next_node == "human_review":
            state = human_review_node(state)
        elif next_node == "report":
            state = write_audit_report(state)

    return state


# ── LangGraph-powered graph (preferred when available) ────────────────────────

def build_graph():
    """
    Build and return a compiled LangGraph StateGraph.
    Falls back to run_graph() when langgraph is not installed.

    Returns:
        A callable that accepts an AuditState dict and returns an updated dict.
    """
    try:
        from langgraph.graph import StateGraph, END
        from agents.state import AuditState

        def _compliance_router(state: dict) -> str:
            return (
                "human_review"
                if state.get("items_pending_human_review")
                else "report"
            )

        graph = StateGraph(AuditState)
        graph.add_node("extract", extract_expenses)
        graph.add_node("compliance", check_compliance)
        graph.add_node("human_review", human_review_node)
        graph.add_node("report", write_audit_report)

        graph.set_entry_point("extract")
        graph.add_edge("extract", "compliance")
        graph.add_conditional_edges(
            "compliance",
            _compliance_router,
            {"human_review": "human_review", "report": "report"},
        )
        graph.add_edge("human_review", "report")
        graph.add_edge("report", END)

        compiled = graph.compile()
        logger.info("LangGraph StateGraph compiled successfully")
        return compiled

    except ImportError:
        logger.info("langgraph not installed — using run_graph() fallback")
        return run_graph
    except Exception as e:
        logger.warning("LangGraph compilation failed (%s) — using run_graph()", e)
        return run_graph


def build_langgraph():
    """
    Build a compiled LangGraph StateGraph with MemorySaver checkpointer
    and interrupt_before=["human_review"] for real HITL support.

    Returns:
        Compiled LangGraph graph (supports .stream(), .get_state(), .update_state()),
        or None if LangGraph / MemorySaver is unavailable.
    """
    try:
        from langgraph.graph import StateGraph, END
        from agents.state import AuditState

        try:
            from langgraph.checkpoint.memory import MemorySaver
        except ImportError:
            from langgraph.checkpoint import MemorySaver  # older langgraph

        def _compliance_router(state: dict) -> str:
            return (
                "human_review"
                if state.get("items_pending_human_review")
                else "report"
            )

        graph = StateGraph(AuditState)
        graph.add_node("extract", extract_expenses)
        graph.add_node("compliance", check_compliance)
        graph.add_node("human_review", human_review_node)
        graph.add_node("report", write_audit_report)
        graph.set_entry_point("extract")
        graph.add_edge("extract", "compliance")
        graph.add_conditional_edges(
            "compliance",
            _compliance_router,
            {"human_review": "human_review", "report": "report"},
        )
        graph.add_edge("human_review", "report")
        graph.add_edge("report", END)

        memory = MemorySaver()
        compiled = graph.compile(
            checkpointer=memory,
            interrupt_before=["human_review"],
        )
        logger.info("LangGraph compiled with MemorySaver + interrupt_before=['human_review']")
        return compiled

    except Exception as e:
        logger.warning("build_langgraph failed (%s) — caller should fall back to run_graph()", e)
        return None
