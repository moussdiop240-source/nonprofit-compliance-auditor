"""
RAG Layer — Pseudonymization
Masks PII in expense/grant text before it reaches the LLM.
Patterns: SSN, EIN, email, phone, credit card, bank account numbers.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── PII patterns ───────────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("SSN",     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                         "[SSN-REDACTED]"),
    ("EIN",     re.compile(r"\b\d{2}-\d{7}\b"),                               "[EIN-REDACTED]"),
    ("EMAIL",   re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b"),             "[EMAIL-REDACTED]"),
    ("PHONE",   re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "[PHONE-REDACTED]"),
    ("CARD",    re.compile(r"\b(?:\d[ -]?){13,16}\b"),                        "[CARD-REDACTED]"),
    ("BANK",    re.compile(r"\b(?:acct|account|routing)[\s#:]*\d{6,17}\b", re.IGNORECASE), "[ACCT-REDACTED]"),
]


# ── Public API ─────────────────────────────────────────────────────────────────

def pseudonymize(text: str) -> tuple[str, dict[str, int]]:
    """
    Replace PII tokens in *text* with labeled placeholders.

    Returns:
        (masked_text, redaction_counts)  — counts keyed by PII type.
    """
    counts: dict[str, int] = {}
    for label, pattern, replacement in _PATTERNS:
        masked, n = pattern.subn(replacement, text)
        if n:
            counts[label] = n
            logger.debug("Pseudonymized %d %s token(s)", n, label)
        text = masked
    return text, counts


def pseudonymize_fields(fields: dict) -> dict:
    """
    Pseudonymize string values in a flat dict (e.g., an extracted expense item).
    Returns a new dict; non-string values are left untouched.
    """
    result = {}
    for k, v in fields.items():
        if isinstance(v, str):
            result[k], _ = pseudonymize(v)
        else:
            result[k] = v
    return result


def redaction_summary(counts: dict[str, int]) -> Optional[str]:
    """Human-readable summary of what was masked; None if nothing was redacted."""
    if not counts:
        return None
    parts = [f"{n} {label}" for label, n in counts.items()]
    return "PII redacted: " + ", ".join(parts)
