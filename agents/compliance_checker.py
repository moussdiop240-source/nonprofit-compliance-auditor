import json
import logging
import os
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tools.rag_tools import query_cfr200_store, query_grant_store
from tools.ml_cross_checker import prescreen_unallowable, detect_amount_anomalies, cross_check_budget
from tools.nlp_utils import extract_grant_budget

logger = logging.getLogger(__name__)

# TF-IDF threshold — configurable via env var; 0.15 is appropriate for
# short expense descriptions vs long regulatory text (previously 0.70 caused
# all items to be flagged regardless of LLM decision).
_CONFIDENCE_THRESHOLD = float(os.environ.get("TFIDF_CONFIDENCE_THRESHOLD", "0.15"))

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOllama(model="llama3.2", temperature=0)
    return _llm


def _compute_tfidf_confidence(description: str, rag_context: str) -> float:
    """
    Enhancement 2: TF-IDF cosine similarity between expense description and RAG context.
    Returns a float in [0, 1]. Falls back to 1.0 if sklearn is unavailable.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = [description, rag_context]
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(corpus)
        score = float(cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0])
        return score
    except Exception as e:
        logger.warning("TF-IDF confidence computation failed: %s", e)
        return 1.0  # Assume high confidence on error so LLM decision stands

COMPLIANCE_SYSTEM_PROMPT = """You are a federal grant compliance expert with 20+ years experience in 2 CFR 200 (Uniform Guidance) and nonprofit financial management.
For each expense line item, you will:
1. Retrieve relevant 2 CFR 200 sections about this expense type
2. Check the grant agreement for specific restrictions
3. Make a compliance determination

Your determination must be one of:
- ALLOWABLE: Expense is clearly permitted
- UNALLOWABLE: Expense violates 2 CFR 200 or grant terms (cite specific section)
- CONDITIONALLY_ALLOWABLE: Allowable with conditions (specify conditions)
- REQUIRES_REVIEW: Complex case needing human expert judgment

Return JSON:
{{
  "status": "ALLOWABLE|UNALLOWABLE|CONDITIONALLY_ALLOWABLE|REQUIRES_REVIEW",
  "regulation_cited": "2 CFR 200.XXX or Grant Section X.X",
  "reasoning": "Brief explanation",
  "requires_human_review": true/false,
  "flagged_reason": "Only if requires_human_review is true"
}}"""

def check_compliance(state: dict) -> dict:
    """
    Agent 2: Reviews each line item against 2 CFR 200 and grant agreement.
    Enhancement 2: pre-screening, anomaly detection, and budget cross-check.
    """
    line_items = state["extracted_line_items"]
    compliance_decisions = []
    flagged_items = []
    total_allowable = 0.0
    total_unallowable = 0.0
    items_pending_review = []

    # Enhancement 2a — annotate all items with per-category Z-score anomaly flags
    line_items = detect_amount_anomalies(list(line_items))

    for item in line_items:
        # Enhancement 2b — pre-screen for per-se unallowable items (skip LLM when certain)
        cfr_context = ""
        grant_context = ""
        prescreen = prescreen_unallowable(item["description"], float(item.get("amount") or 0))
        if prescreen["prescreened"] and prescreen["unallowable"]:
            decision = {
                "status": "UNALLOWABLE",
                "regulation_cited": prescreen["regulation"],
                "reasoning": prescreen["reason"],
                "requires_human_review": False,
                "flagged_reason": None,
                "prescreened": True,
            }
        elif prescreen["prescreened"] and prescreen["conditionally_allowable"]:
            decision = {
                "status": "CONDITIONALLY_ALLOWABLE",
                "regulation_cited": prescreen["regulation"],
                "reasoning": prescreen["reason"],
                "requires_human_review": True,
                "flagged_reason": prescreen["reason"],
                "prescreened": True,
            }
        else:
            cfr_context = query_cfr200_store(
                f"{item['category']} costs {item['description']} allowable"
            )
            grant_context = query_grant_store(
                state["grant_agreement_text"],
                f"{item['category']} {item['description']}"
            )

            prompt = ChatPromptTemplate.from_messages([
                ("system", COMPLIANCE_SYSTEM_PROMPT),
                ("human", """
EXPENSE LINE ITEM:
Description: {description}
Amount: ${amount}
Category: {category}
Vendor: {vendor}
Amount anomaly flag: {anomaly}

2 CFR 200 RELEVANT SECTIONS:
{cfr_context}

GRANT AGREEMENT RELEVANT TERMS:
{grant_context}

Compliance determination (JSON only):
""")
            ])
            chain = prompt | _get_llm() | StrOutputParser()
            result = chain.invoke({
                "description": item["description"],
                "amount": item["amount"],
                "category": item["category"],
                "vendor": item.get("vendor", "N/A"),
                "anomaly": "YES — statistically unusual amount" if item.get("amount_anomaly") else "NO",
                "cfr_context": cfr_context,
                "grant_context": grant_context,
            })

            try:
                content = result.strip()
                if "```" in content:
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                decision = json.loads(content)
            except Exception:
                decision = {
                    "status": "REQUIRES_REVIEW",
                    "regulation_cited": "Unable to parse",
                    "reasoning": "Parsing error — manual review required",
                    "requires_human_review": True,
                    "flagged_reason": "System parsing error",
                }
            decision["prescreened"] = False

        # Enhancement 2 — ML confidence scoring via TF-IDF cosine similarity
        # Skip TF-IDF for pre-screened items (decision is rule-based, not RAG-derived)
        combined_context = cfr_context + " " + grant_context
        confidence = (
            1.0 if prescreen["prescreened"]
            else _compute_tfidf_confidence(item["description"], combined_context)
        )
        decision["confidence_score"] = round(confidence, 4)
        if confidence < _CONFIDENCE_THRESHOLD:
            logger.info(
                "Low confidence (%.2f) for '%s' — overriding to REQUIRES_REVIEW",
                confidence, item["description"][:50]
            )
            decision["status"] = "REQUIRES_REVIEW"
            decision["requires_human_review"] = True
            decision.setdefault(
                "flagged_reason",
                f"Low RAG confidence score ({confidence:.0%}); manual review recommended",
            )

        full_decision = {**item, **decision}
        compliance_decisions.append(full_decision)

        if decision["status"] == "ALLOWABLE":
            total_allowable += item["amount"]
        elif decision["status"] == "UNALLOWABLE":
            total_unallowable += item["amount"]
            flagged_items.append(full_decision)

        if decision.get("requires_human_review"):
            items_pending_review.append(full_decision)

    # Enhancement 2c — budget cross-check against grant agreement limits
    grant_budget = extract_grant_budget(state.get("grant_agreement_text", ""))
    budget_analysis = cross_check_budget(compliance_decisions, grant_budget)
    exceeded_categories = [cat for cat, info in budget_analysis.items() if info["exceeded"]]

    prescreened_count = sum(1 for d in compliance_decisions if d.get("prescreened"))
    anomaly_count = sum(1 for item in line_items if item.get("amount_anomaly"))

    new_message = {
        "agent": "ComplianceChecker",
        "action": (
            f"Reviewed {len(line_items)} items. "
            f"Allowable: ${total_allowable:,.2f} | "
            f"Unallowable: ${total_unallowable:,.2f} | "
            f"Flagged for review: {len(items_pending_review)}"
            + (f" | Pre-screened: {prescreened_count}" if prescreened_count else "")
            + (f" | Amount anomalies: {anomaly_count}" if anomaly_count else "")
            + (f" | Budget exceeded: {', '.join(exceeded_categories)}" if exceeded_categories else "")
        ),
        "status": "complete",
    }

    return {
        **state,
        "compliance_decisions": compliance_decisions,
        "flagged_items": flagged_items,
        "total_allowable": total_allowable,
        "total_unallowable": total_unallowable,
        "items_pending_human_review": items_pending_review,
        "compliance_check_complete": True,
        "grant_budget": grant_budget,
        "budget_analysis": budget_analysis,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "human_review" if items_pending_review else "report_writer",
    }