import json
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tools.rag_tools import query_cfr200_store, query_grant_store

llm = ChatOllama(model="llama3.2", temperature=0)

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
    """
    line_items = state["extracted_line_items"]
    compliance_decisions = []
    flagged_items = []
    total_allowable = 0.0
    total_unallowable = 0.0
    items_pending_review = []

    for item in line_items:
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

2 CFR 200 RELEVANT SECTIONS:
{cfr_context}

GRANT AGREEMENT RELEVANT TERMS:
{grant_context}

Compliance determination (JSON only):
""")
        ])
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({
            "description": item["description"],
            "amount": item["amount"],
            "category": item["category"],
            "vendor": item.get("vendor", "N/A"),
            "cfr_context": cfr_context,
            "grant_context": grant_context
        })

        try:
            content = result.strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            decision = json.loads(content)
        except:
            decision = {
                "status": "REQUIRES_REVIEW",
                "regulation_cited": "Unable to parse",
                "reasoning": "Parsing error — manual review required",
                "requires_human_review": True,
                "flagged_reason": "System parsing error"
            }

        full_decision = {**item, **decision}
        compliance_decisions.append(full_decision)

        if decision["status"] == "ALLOWABLE":
            total_allowable += item["amount"]
        elif decision["status"] == "UNALLOWABLE":
            total_unallowable += item["amount"]
            flagged_items.append(full_decision)

        if decision.get("requires_human_review"):
            items_pending_review.append(full_decision)

    new_message = {
        "agent": "ComplianceChecker",
        "action": (f"Reviewed {len(line_items)} items. "
                   f"Allowable: ${total_allowable:,.2f} | "
                   f"Unallowable: ${total_unallowable:,.2f} | "
                   f"Flagged for review: {len(items_pending_review)}"),
        "status": "complete"
    }

    return {
        **state,
        "compliance_decisions": compliance_decisions,
        "flagged_items": flagged_items,
        "total_allowable": total_allowable,
        "total_unallowable": total_unallowable,
        "items_pending_human_review": items_pending_review,
        "compliance_check_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "human_review" if items_pending_review else "report_writer"
    }