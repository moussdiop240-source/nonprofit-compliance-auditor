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


def extract_grant_budget(grant_text: str) -> Dict[str, float]:
    """
    Parse the grant agreement text for budget amounts per category.
    Looks for patterns like "Personnel: $3,800" or "Travel up to $2,000".
    Returns a dict {category: amount}; empty dict if nothing found.
    """
    budget: Dict[str, float] = {}
    category_map = {
        "personnel":    r'\b(personnel|salary|salaries|fringe|payroll)\b',
        "travel":       r'\b(travel|airfare|lodging|per diem|mileage)\b',
        "supplies":     r'\b(supplies|materials|printing|software|computing)\b',
        "equipment":    r'\b(equipment|hardware|computer|laptop)\b',
        "indirect":     r'\b(indirect|overhead|administrative)\b',
        "professional": r'\b(conference|training|registration|membership)\b',
        "food":         r'\b(meal|food|catering|lunch|dinner)\b',
    }
    # Match lines that contain a category keyword AND a dollar amount
    line_pattern = re.compile(
        r'(?P<line>[^\n]*(?:' +
        '|'.join(f'(?P<cat_{k}>{v})' for k, v in category_map.items()) +
        r')[^\n]*\$\s*(?P<amount>\d[\d,]*(?:\.\d{2})?))',
        re.IGNORECASE,
    )
    for m in line_pattern.finditer(grant_text):
        try:
            amount = float(m.group("amount").replace(",", ""))
        except (ValueError, TypeError):
            continue
        line = m.group("line").lower()
        for cat, pattern in category_map.items():
            if re.search(pattern, line, re.IGNORECASE):
                if cat not in budget or amount > budget[cat]:
                    budget[cat] = amount
                break
    return budget


def detect_report_format(text: str) -> str:
    """
    Detect the structural format of an expense report.
    Returns 'tabular', 'list', or 'prose'.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "prose"

    tab_lines = sum(
        1 for ln in lines
        if "\t" in ln or "|" in ln or re.search(r" {3,}", ln)
    )
    if tab_lines / len(lines) > 0.4:
        return "tabular"

    list_lines = sum(
        1 for ln in lines
        if re.match(r"^\s*[-•*#]|\s*\d+[.)]\s", ln)
    )
    if list_lines / len(lines) > 0.3:
        return "list"

    return "prose"


def parse_tabular_expenses(text: str) -> List[Dict]:
    """
    Directly extract line items from a tabular expense report without using the LLM.
    Handles tab-separated, pipe-separated, and multi-space-aligned tables.
    Returns an empty list when the table structure is too ambiguous to parse reliably.
    """
    items = []
    lines = [ln for ln in text.splitlines() if ln.strip()]

    # Identify the delimiter
    tab_count = sum(1 for ln in lines if "\t" in ln)
    pipe_count = sum(1 for ln in lines if "|" in ln)

    if tab_count >= pipe_count and tab_count > 0:
        splitter = lambda ln: [c.strip() for c in ln.split("\t")]  # noqa: E731
    elif pipe_count > 0:
        splitter = lambda ln: [c.strip() for c in ln.strip().strip("|").split("|")]  # noqa: E731
    else:
        # Multi-space delimiter
        splitter = lambda ln: [c.strip() for c in re.split(r" {2,}", ln.strip())]  # noqa: E731

    line_num = 0
    for ln in lines:
        # Strip dates before amount detection so years aren't mistaken for amounts
        ln_no_dates = ln
        for pat in _DATE_PATTERNS:
            ln_no_dates = pat.sub("", ln_no_dates)

        amounts = extract_amounts(ln_no_dates)
        if not amounts:
            continue  # header or empty row

        line_num += 1
        cells = splitter(ln)

        # Strip amounts and dates from cells to isolate the description
        desc_parts = []
        for cell in cells:
            cleaned = _AMOUNT_PATTERN.sub("", cell)
            for pat in _DATE_PATTERNS:
                cleaned = pat.sub("", cleaned)
            cleaned = cleaned.strip().strip("|").strip()
            if cleaned:
                desc_parts.append(cleaned)

        description = " ".join(desc_parts) if desc_parts else ln.strip()
        dates = extract_dates(ln)
        category = detect_category(description) or "other"

        items.append({
            "line_number": line_num,
            "description": description,
            "amount": max(amounts),
            "category": category,
            "vendor": "",
            "date": dates[0] if dates else "",
        })

    return items


def enrich_line_items(items: List[Dict]) -> List[Dict]:
    """
    Post-LLM enrichment pass applied to all extracted line items:
    - Fill missing or unknown categories via heuristic detection
    - Normalize amount values (string → float)
    - Clean vendor names
    """
    for item in items:
        # Normalize amount
        amt = item.get("amount")
        if isinstance(amt, str):
            parsed = extract_amounts(amt)
            item["amount"] = parsed[0] if parsed else 0.0
        elif amt is None:
            item["amount"] = 0.0

        # Fill missing category
        cat = item.get("category", "")
        if not cat or cat.lower() in ("", "other", "unknown", "n/a"):
            detected = detect_category(item.get("description", ""))
            if detected:
                item["category"] = detected

        # Clean vendor
        if item.get("vendor"):
            item["vendor"] = clean_vendor_name(item["vendor"])

    return items


def flag_duplicate_items(items: List[Dict]) -> List[Dict]:
    """
    Use TF-IDF cosine similarity to annotate potential duplicate line items.
    Items with description similarity > 0.85 AND amount within 5% are marked
    with 'possible_duplicate': True.
    """
    if len(items) < 2:
        return items

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        descriptions = [str(item.get("description", "")) for item in items]
        vec = TfidfVectorizer(stop_words="english", min_df=1)
        matrix = vec.fit_transform(descriptions)
        sim = cosine_similarity(matrix)

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if sim[i, j] < 0.85:
                    continue
                amt_i = float(items[i].get("amount") or 0)
                amt_j = float(items[j].get("amount") or 0)
                denom = max(amt_i, amt_j, 1)
                if abs(amt_i - amt_j) / denom < 0.05:
                    items[i]["possible_duplicate"] = True
                    items[j]["possible_duplicate"] = True
    except Exception:
        pass

    return items


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
