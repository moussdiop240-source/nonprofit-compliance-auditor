"""
Enhancement 2: ML-driven cross-checking tools for Agent 2 (ComplianceChecker).

Three analytical layers that run alongside the LLM:
  1. prescreen_unallowable  — pattern-based detection of per-se unallowable items
  2. detect_amount_anomalies — Z-score outlier detection per expense category
  3. cross_check_budget      — category spending vs. grant budget limits
"""
import re
import logging
import statistics
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Per-se unallowable patterns (2 CFR 200) ───────────────────────────────────

_UNALLOWABLE_RULES: List[tuple] = [
    (
        re.compile(
            r"\b(beer|wine|liquor|spirits|cocktail|alcohol|alcoholic|bar tab|open bar"
            r"|champagne|whiskey|vodka|tequila|rum|gin)\b",
            re.IGNORECASE,
        ),
        "2 CFR 200.423",
        "Alcoholic beverages are unallowable under federal awards",
    ),
    (
        re.compile(
            r"\b(lobby|lobbying|political contribution|campaign contribution"
            r"|legislative advocacy|influencing legislation|PAC)\b",
            re.IGNORECASE,
        ),
        "2 CFR 200.451",
        "Lobbying costs are unallowable",
    ),
    (
        re.compile(
            r"\b(entertainment|nightclub|casino|gambling|slot machine|amusement park"
            r"|theme park|sporting event ticket|concert ticket|theater ticket)\b",
            re.IGNORECASE,
        ),
        "2 CFR 200.438",
        "Entertainment costs are generally unallowable",
    ),
    (
        re.compile(
            r"\b(personal use|personal item|personal expense|family trip|family vacation"
            r"|vacation|tourism|sightseeing|personal travel|spouse travel)\b",
            re.IGNORECASE,
        ),
        "2 CFR 200.420",
        "Costs must be necessary for the performance of the award; personal costs are unallowable",
    ),
    (
        re.compile(
            r"\b(first.?class|business.?class airfare)\b",
            re.IGNORECASE,
        ),
        "2 CFR 200.474",
        "Premium airfare requires documented justification; economy class required absent approval",
    ),
]

# ── Z-score threshold for amount anomalies ────────────────────────────────────
_ANOMALY_Z_THRESHOLD = float(2.0)
# Minimum items per category before anomaly detection is meaningful
_ANOMALY_MIN_ITEMS = 2


def prescreen_unallowable(description: str, amount: float) -> dict:  # noqa: ARG001
    """
    Check an expense description against known per-se unallowable patterns.

    Returns:
        {
          "prescreened": bool,        # True when a pattern matched
          "unallowable": bool,        # True → item is unallowable per regulation
          "conditionally_allowable": bool,  # True → allowable only with justification
          "regulation": str,
          "reason": str,
        }
    """
    for pattern, regulation, reason in _UNALLOWABLE_RULES:
        if pattern.search(description):
            # First-class / business-class is conditionally allowable, not auto-unallowable
            conditionally = "200.474" in regulation
            return {
                "prescreened": True,
                "unallowable": not conditionally,
                "conditionally_allowable": conditionally,
                "regulation": regulation,
                "reason": reason,
            }
    return {
        "prescreened": False,
        "unallowable": False,
        "conditionally_allowable": False,
        "regulation": "",
        "reason": "",
    }


def detect_amount_anomalies(line_items: List[dict]) -> List[dict]:
    """
    Annotate each line item with a modified Z-score (median + MAD) relative to
    its category peers. Modified Z is robust against small samples and extreme
    outliers that distort the mean.

    Items with |modified Z| > threshold receive ``amount_anomaly: True``.
    Categories with fewer than _ANOMALY_MIN_ITEMS items are skipped.

    Mutates and returns the input list.
    """
    by_category: Dict[str, List[int]] = {}
    for idx, item in enumerate(line_items):
        cat = str(item.get("category", "other")).lower()
        by_category.setdefault(cat, []).append(idx)

    for cat, indices in by_category.items():
        if len(indices) < _ANOMALY_MIN_ITEMS:
            for i in indices:
                line_items[i]["amount_anomaly"] = False
                line_items[i]["amount_z_score"] = 0.0
            continue

        amounts = [float(line_items[i].get("amount") or 0) for i in indices]
        try:
            med = statistics.median(amounts)
            abs_devs = [abs(a - med) for a in amounts]
            mad = statistics.median(abs_devs)
        except statistics.StatisticsError:
            for i in indices:
                line_items[i]["amount_anomaly"] = False
                line_items[i]["amount_z_score"] = 0.0
            continue

        for i in indices:
            amt = float(line_items[i].get("amount") or 0)
            if mad > 0:
                # Standard modified Z-score (Iglewicz & Hoaglin, 1993)
                mz = 0.6745 * (amt - med) / mad
            else:
                # MAD = 0: all peers are identical; any different value is an outlier
                mz = 0.0 if amt == med else float("inf")
            line_items[i]["amount_z_score"] = round(mz, 3) if mz != float("inf") else 9999.0
            line_items[i]["amount_anomaly"] = abs(mz) > _ANOMALY_Z_THRESHOLD
            if line_items[i]["amount_anomaly"]:
                logger.info(
                    "Amount anomaly (modified Z=%.2f) for '%s' $%.2f in category '%s'",
                    mz, line_items[i].get("description", "")[:50], amt, cat,
                )

    return line_items


def cross_check_budget(line_items: List[dict], grant_budget: Dict[str, float]) -> dict:
    """
    Compare per-category spending totals against the grant budget limits.

    Args:
        line_items:   Compliance-checked line items (dicts with ``category`` and ``amount``).
        grant_budget: {category: budgeted_amount} from extract_grant_budget().

    Returns:
        {
          category: {
            "spent":    float,
            "budget":   float | None,   # None when no budget line found
            "exceeded": bool,
            "pct_used": float | None,
          },
          ...
        }
    """
    # Aggregate actual spending by category
    spent: Dict[str, float] = {}
    for item in line_items:
        cat = str(item.get("category", "other")).lower()
        amt = float(item.get("amount") or 0)
        spent[cat] = spent.get(cat, 0.0) + amt

    analysis: dict = {}
    all_categories = set(spent) | set(grant_budget)

    for cat in all_categories:
        actual = spent.get(cat, 0.0)
        budgeted = grant_budget.get(cat)
        exceeded = bool(budgeted is not None and actual > budgeted)
        pct = round(actual / budgeted * 100, 1) if budgeted else None
        analysis[cat] = {
            "spent": round(actual, 2),
            "budget": budgeted,
            "exceeded": exceeded,
            "pct_used": pct,
        }
        if exceeded:
            logger.warning(
                "Budget exceeded for category '%s': spent $%.2f vs budget $%.2f",
                cat, actual, budgeted,
            )

    return analysis
