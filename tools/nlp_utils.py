"""
NLP preprocessing utilities for expense text extraction.
Enhancement 1: Advanced NLP for improved line-item extraction accuracy.
"""
import re
from typing import List, Optional, Dict

# ── Compiled regex patterns ────────────────────────────────────────────────────
_AMOUNT_PATTERN = re.compile(
    r'\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
)

_DATE_PATTERNS = [
    re.compile(r'\b(\d{4}-\d{2}-\d{2})\b'),                          # ISO: 2024-03-15
    re.compile(r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b'),                    # US:  3/15/2024
    re.compile(r'\b(\d{1,2}-\d{1,2}-\d{2,4})\b'),                    # Dashes: 03-15-2024
    re.compile(r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
               r'[a-z]*\.?\s+\d{1,2},?\s*\d{4})\b', re.IGNORECASE),  # Jan 15, 2024
]

_VENDOR_NOISE = re.compile(
    r'\b(Inc\.?|LLC\.?|Corp\.?|Ltd\.?|Co\.?|Company|Corporation|Associates|'
    r'Services|Solutions|Group|Partners|Consulting|International)\b',
    re.IGNORECASE,
)

_CATEGORY_HINTS = {
    "travel": r'\b(flight|airfare|hotel|lodging|mileage|uber|lyft|taxi|transit|train|rental car|per diem)\b',
    "personnel": r'\b(salary|wage|payroll|fringe|benefit|overtime|stipend|consultant fee)\b',
    "supplies": r'\b(office supplies|paper|toner|pen|notebook|folder|binder|printing)\b',
    "equipment": r'\b(computer|laptop|monitor|printer|scanner|camera|projector|software)\b',
    "indirect": r'\b(overhead|indirect|administrative|facility|utilities|rent|lease)\b',
    "food": r'\b(meal|lunch|dinner|breakfast|catering|food|restaurant|coffee)\b',
    "professional": r'\b(training|conference|registration|membership|subscription|journal)\b',
}

_COMPILED_CATEGORY_HINTS = {
    cat: re.compile(pattern, re.IGNORECASE)
    for cat, pattern in _CATEGORY_HINTS.items()
}


def extract_amounts(text: str) -> List[float]:
    """Extract dollar amounts from free text, returning as list of floats."""
    matches = _AMOUNT_PATTERN.findall(text)
    results = []
    for m in matches:
        try:
            results.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return results


def extract_dates(text: str) -> List[str]:
    """Extract date strings from free text."""
    found: List[str] = []
    for pattern in _DATE_PATTERNS:
        found.extend(pattern.findall(text))
    return found


def clean_vendor_name(name: Optional[str]) -> str:
    """Normalize vendor name by stripping legal suffixes and extra whitespace."""
    if not name:
        return ""
    cleaned = _VENDOR_NOISE.sub("", name).strip().rstrip(",").strip()
    return " ".join(cleaned.split())


def detect_category(description: str) -> Optional[str]:
    """Heuristic category detection from expense description."""
    desc_lower = description.lower()
    for category, pattern in _COMPILED_CATEGORY_HINTS.items():
        if pattern.search(desc_lower):
            return category
    return None


def preprocess_expense_text(text: str) -> Dict:
    """
    Main preprocessing function called before LLM extraction.
    Returns a dict with extracted hints that can be injected into the prompt.
    """
    amounts = extract_amounts(text)
    dates = extract_dates(text)
    line_count = len([ln for ln in text.splitlines() if ln.strip()])

    # Attempt to detect vendor-like tokens (capitalized multi-word phrases)
    vendor_candidates = re.findall(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b', text)
    cleaned_vendors = [clean_vendor_name(v) for v in vendor_candidates]
    unique_vendors = list(dict.fromkeys(v for v in cleaned_vendors if v))

    return {
        "amounts": amounts,
        "dates": dates,
        "vendor_candidates": unique_vendors[:10],  # cap at 10 candidates
        "line_count": line_count,
        "cleaned_text": text.strip(),
    }


def build_nlp_hint_block(preprocessed: Dict) -> str:
    """
    Builds a text block summarising NLP findings to prepend to the LLM prompt.
    This helps the LLM identify amounts, dates, and vendors more reliably.
    """
    lines = ["[NLP PRE-ANALYSIS]"]
    if preprocessed.get("amounts"):
        lines.append(f"Detected amounts: {', '.join(f'${a:,.2f}' for a in preprocessed['amounts'][:15])}")
    if preprocessed.get("dates"):
        lines.append(f"Detected dates: {', '.join(preprocessed['dates'][:10])}")
    if preprocessed.get("vendor_candidates"):
        lines.append(f"Possible vendors: {', '.join(preprocessed['vendor_candidates'][:8])}")
    lines.append(f"Non-empty lines: {preprocessed.get('line_count', 0)}")
    lines.append("[END NLP PRE-ANALYSIS]")
    return "\n".join(lines)
