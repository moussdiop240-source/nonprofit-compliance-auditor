"""
Advanced Data Visualization Tools.
Generates charts for compliance breakdowns, category spending, and ML confidence
distributions. Uses plotly when available; falls back to pandas/Streamlit natives.
"""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Status colours consistent with the app's UI palette
_STATUS_COLORS = {
    "ALLOWABLE":              "#22c55e",
    "UNALLOWABLE":            "#ef4444",
    "CONDITIONALLY_ALLOWABLE": "#f59e0b",
    "REQUIRES_REVIEW":        "#3b82f6",
}


# ── Public chart builders ─────────────────────────────────────────────────────

def compliance_breakdown_chart(decisions: list) -> Optional[Any]:
    """
    Pie/donut chart: proportion of ALLOWABLE / UNALLOWABLE /
    CONDITIONALLY_ALLOWABLE / REQUIRES_REVIEW decisions.
    Returns a plotly Figure or None when plotly is unavailable.
    """
    if not decisions:
        return None

    counts: dict[str, int] = {}
    for d in decisions:
        status = d.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

    try:
        import plotly.graph_objects as go

        labels = list(counts.keys())
        values = [counts[k] for k in labels]
        colors = [_STATUS_COLORS.get(l, "#94a3b8") for l in labels]

        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.45,
            marker_colors=colors,
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} items<extra></extra>",
        ))
        fig.update_layout(
            title="Compliance Decision Breakdown",
            showlegend=True,
            margin=dict(t=50, b=20, l=20, r=20),
            height=350,
        )
        return fig
    except ImportError:
        logger.debug("plotly not available — compliance_breakdown_chart returns None")
        return None


def expense_by_category_chart(line_items: list) -> Optional[Any]:
    """
    Horizontal bar chart: total spend grouped by expense category.
    Returns a plotly Figure or None.
    """
    if not line_items:
        return None

    totals: dict[str, float] = {}
    for item in line_items:
        cat = (item.get("category") or "unknown").lower()
        totals[cat] = totals.get(cat, 0.0) + float(item.get("amount", 0))

    sorted_cats = sorted(totals, key=lambda c: totals[c], reverse=True)

    try:
        import plotly.graph_objects as go

        fig = go.Figure(go.Bar(
            x=[totals[c] for c in sorted_cats],
            y=sorted_cats,
            orientation="h",
            marker_color="#3b82f6",
            text=[f"${totals[c]:,.2f}" for c in sorted_cats],
            textposition="outside",
            hovertemplate="%{y}: $%{x:,.2f}<extra></extra>",
        ))
        fig.update_layout(
            title="Expense Spend by Category",
            xaxis_title="Total ($)",
            yaxis_title="",
            margin=dict(t=50, b=40, l=120, r=80),
            height=max(280, len(sorted_cats) * 45 + 80),
        )
        return fig
    except ImportError:
        logger.debug("plotly not available — expense_by_category_chart returns None")
        return None


def confidence_distribution_chart(decisions: list) -> Optional[Any]:
    """
    Histogram: distribution of ML TF-IDF confidence scores across all decisions.
    Returns a plotly Figure or None.
    """
    scores = [d.get("confidence_score") for d in decisions
              if isinstance(d.get("confidence_score"), (int, float))]
    if not scores:
        return None

    try:
        import plotly.graph_objects as go

        fig = go.Figure(go.Histogram(
            x=scores,
            nbinsx=20,
            marker_color="#a855f7",
            opacity=0.85,
            hovertemplate="Confidence %{x:.2f}: %{y} items<extra></extra>",
        ))
        fig.add_vline(
            x=0.7, line_dash="dash", line_color="#ef4444",
            annotation_text="Review threshold (0.70)",
            annotation_position="top right",
        )
        fig.update_layout(
            title="ML Confidence Score Distribution",
            xaxis_title="TF-IDF Cosine Similarity",
            yaxis_title="# Items",
            margin=dict(t=50, b=40, l=60, r=20),
            height=320,
        )
        return fig
    except ImportError:
        logger.debug("plotly not available — confidence_distribution_chart returns None")
        return None


def allowable_vs_unallowable_bar(
    total_allowable: float,
    total_unallowable: float,
    total_conditional: float = 0.0,
) -> Optional[Any]:
    """
    Grouped bar chart comparing allowable, conditional, and unallowable dollar totals.
    Returns a plotly Figure or None.
    """
    try:
        import plotly.graph_objects as go

        categories = ["Allowable", "Conditionally Allowable", "Unallowable"]
        amounts = [total_allowable, total_conditional, total_unallowable]
        colors = ["#22c55e", "#f59e0b", "#ef4444"]

        fig = go.Figure(go.Bar(
            x=categories,
            y=amounts,
            marker_color=colors,
            text=[f"${a:,.2f}" for a in amounts],
            textposition="outside",
            hovertemplate="%{x}: $%{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(
            title="Allowable vs Unallowable Dollar Totals",
            yaxis_title="Amount ($)",
            margin=dict(t=50, b=40, l=70, r=20),
            height=330,
        )
        return fig
    except ImportError:
        return None


# ── Streamlit rendering helper ────────────────────────────────────────────────

def render_chart(fig: Optional[Any], fallback_message: str = "Chart unavailable (plotly not installed)") -> None:
    """
    Render a plotly figure in Streamlit, or show a fallback message.
    Import streamlit lazily so this module is usable outside Streamlit contexts.
    """
    try:
        import streamlit as st
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(fallback_message)
    except ImportError:
        logger.warning("streamlit not available — cannot render chart")
