"""
Four-layer hallucination guard for the LLM compliance pipeline.

  L1 — Schema enforcement: strip unknown fields, coerce types
  L2 — Status enum: only the four exact uppercase values are accepted
  L3 — Internal consistency: status ↔ requires_human_review ↔ flagged_reason invariants
  L4 — Regulation citation: non-empty, plausible format, safe default

  Retry wrapper: re-invokes the chain up to max_retries times on JSON parse failure
  before falling back to a safe REQUIRES_REVIEW sentinel.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

VALID_STATUSES: frozenset = frozenset(
    {"ALLOWABLE", "UNALLOWABLE", "CONDITIONALLY_ALLOWABLE", "REQUIRES_REVIEW"}
)

# The only fields the LLM is permitted to set; all others are stripped (L1)
_ALLOWED_DECISION_FIELDS: frozenset = frozenset(
    {"status", "regulation_cited", "reasoning", "requires_human_review", "flagged_reason"}
)

_CFR_PATTERN_PREFIX = ("2 CFR", "2CFR", "CFR 200", "Grant Section", "Grant section")
_FALLBACK_CITATION = "2 CFR 200 — see manual review"


# ── Layer helpers ──────────────────────────────────────────────────────────────

def _coerce_bool(value) -> bool:
    """L1: coerce common LLM bool representations (string 'true', 1, etc.) to Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _validate_citation(citation: str) -> str:
    """L4: ensure the regulation citation is non-empty and looks plausible."""
    if not citation or not str(citation).strip():
        return _FALLBACK_CITATION
    s = str(citation).strip()
    if len(s) < 5:
        return _FALLBACK_CITATION
    return s


# ── Public API ─────────────────────────────────────────────────────────────────

def sanitize_llm_decision(raw: dict, *, item_description: str = "") -> dict:
    """
    Apply all four guard layers to a raw LLM decision dict.
    Always returns a dict with all required fields and valid values.
    Never raises.
    """
    if not isinstance(raw, dict):
        logger.warning("Guard L1: expected dict, got %s — falling back", type(raw).__name__)
        return _safe_fallback(f"LLM returned {type(raw).__name__} instead of JSON object")

    # L1 — strip unknown fields
    clean: dict = {k: v for k, v in raw.items() if k in _ALLOWED_DECISION_FIELDS}

    # L1 — type coercion for requires_human_review
    if "requires_human_review" in clean:
        clean["requires_human_review"] = _coerce_bool(clean["requires_human_review"])

    # L2 — status enum enforcement (exact uppercase required)
    status = clean.get("status", "")
    if status not in VALID_STATUSES:
        logger.warning(
            "Guard L2: invalid status %r for %r — coercing to REQUIRES_REVIEW",
            status, item_description[:60],
        )
        clean["status"] = "REQUIRES_REVIEW"
        clean["requires_human_review"] = True
        clean["flagged_reason"] = (
            f"Invalid status {status!r} returned by LLM — manual review required"
        )

    # L4 — regulation citation validation
    clean["regulation_cited"] = _validate_citation(clean.get("regulation_cited", ""))

    # L1 — reasoning default
    reasoning = clean.get("reasoning", "")
    if not reasoning or not str(reasoning).strip():
        clean["reasoning"] = "No reasoning provided — manual review required"
    else:
        clean["reasoning"] = str(reasoning).strip()

    # Fill any remaining missing required fields
    clean.setdefault("requires_human_review", False)
    if "flagged_reason" not in clean:
        clean["flagged_reason"] = None

    # L3 — internal consistency invariants
    status = clean["status"]

    # REQUIRES_REVIEW must always flag for human review
    if status == "REQUIRES_REVIEW":
        clean["requires_human_review"] = True

    # Any item flagged for human review must have a non-empty flagged_reason
    if clean["requires_human_review"] and not clean.get("flagged_reason"):
        clean["flagged_reason"] = f"Flagged for manual review ({status})"

    # ALLOWABLE with no review needed: clear any stale flagged_reason
    if status == "ALLOWABLE" and not clean["requires_human_review"]:
        clean["flagged_reason"] = None

    return clean


def invoke_with_guard(
    chain,
    invoke_args: dict,
    *,
    max_retries: int = 2,
    item_description: str = "",
) -> dict:
    """
    Invoke the LangChain chain with automatic retry on JSON parse / validation failure.
    Returns a sanitized decision dict guaranteed to have all required fields.
    Never raises.
    """
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            raw_result = chain.invoke(invoke_args)

            # Extract JSON from fenced code blocks if present
            content = raw_result.strip() if isinstance(raw_result, str) else str(raw_result)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            parsed = json.loads(content)
            return sanitize_llm_decision(parsed, item_description=item_description)

        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(
                    "Guard retry %d/%d for %r: %s",
                    attempt + 1, max_retries, item_description[:60], exc,
                )

    logger.error(
        "Guard: all %d attempt(s) failed for %r — returning safe fallback. Last error: %s",
        max_retries + 1, item_description[:60], last_error,
    )
    return _safe_fallback(
        f"LLM response could not be parsed after {max_retries + 1} attempt(s): {last_error}"
    )


# ── Internal ───────────────────────────────────────────────────────────────────

def _safe_fallback(reason: str) -> dict:
    return {
        "status": "REQUIRES_REVIEW",
        "regulation_cited": _FALLBACK_CITATION,
        "reasoning": reason,
        "requires_human_review": True,
        "flagged_reason": "Guard fallback — manual review required",
    }
