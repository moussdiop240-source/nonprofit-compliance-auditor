from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from datetime import datetime

llm = ChatOllama(model="llama3.2", temperature=0.1)

_MAX_DECISIONS_IN_PROMPT = 60


def _format_decisions(decisions: list) -> str:
    """Render compliance decisions as a concise text table for the LLM prompt."""
    lines = []
    for d in decisions[:_MAX_DECISIONS_IN_PROMPT]:
        conf = d.get("confidence_score")
        conf_str = f" conf={conf:.2f}" if isinstance(conf, float) else ""
        human_note = f" | Reviewer: {d['human_review_note']}" if d.get("human_review_note") else ""
        lines.append(
            f"#{d.get('line_number','?')} | {d.get('description','')[:55]} | "
            f"${d.get('amount', 0):,.2f} | {d.get('category','N/A')} | "
            f"[{d.get('status','')}] | Reg: {d.get('regulation_cited','N/A')} | "
            f"{d.get('reasoning','')[:80]}{conf_str}{human_note}"
        )
    if len(decisions) > _MAX_DECISIONS_IN_PROMPT:
        lines.append(f"... and {len(decisions) - _MAX_DECISIONS_IN_PROMPT} additional items (all reviewed)")
    return "\n".join(lines)


def write_audit_report(state: dict) -> dict:
    """
    Agent 3: Generates a professional, formatted compliance audit report.
    """
    decisions = state["compliance_decisions"]
    allowable = [d for d in decisions if d["status"] == "ALLOWABLE"]
    unallowable = [d for d in decisions if d["status"] == "UNALLOWABLE"]
    conditional = [d for d in decisions if d["status"] == "CONDITIONALLY_ALLOWABLE"]
    needs_review = [d for d in decisions if d["status"] == "REQUIRES_REVIEW"]

    # Build budget vs actuals block if budget data is available
    grant_budget = state.get("grant_budget", {})
    if grant_budget:
        actuals: dict = {}
        for d in decisions:
            cat = (d.get("category") or "other").lower()
            actuals[cat] = actuals.get(cat, 0.0) + float(d.get("amount", 0))
        budget_lines = []
        for cat, budgeted in sorted(grant_budget.items()):
            actual = actuals.get(cat, 0.0)
            variance = actual - budgeted
            flag = " ⚠ OVER BUDGET" if variance > 0 else ""
            budget_lines.append(
                f"  {cat.title()}: budgeted=${budgeted:,.2f} | actual=${actual:,.2f} | variance=${variance:+,.2f}{flag}"
            )
        budget_section = "BUDGET VS ACTUALS:\n" + "\n".join(budget_lines)
    else:
        budget_section = "BUDGET VS ACTUALS: No budget data provided."

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a nonprofit audit report writer specializing in 2 CFR 200 federal grant compliance. "
            "Generate a professional markdown audit report with: "
            "(1) executive summary, "
            "(2) a detailed findings table listing every line item with its status, regulation cited, and reasoning, "
            "(3) a budget vs actuals section comparing category spend to grant budget, "
            "(4) a section on flagged/unallowable items with specific remediation steps, "
            "(5) actionable recommendations. "
            "Use the exact line item data provided — do not invent or generalize."
        )),
        ("human", """
Organization: {org}
Grant: {grant}
Audit Date: {date}

SUMMARY TOTALS:
- Allowable ({num_allowable} items): ${allowable_total:,.2f}
- Unallowable ({num_unallowable} items): ${unallowable_total:,.2f}
- Conditionally Allowable: {num_conditional} items
- Requires Review: {num_review} items

DETAILED LINE ITEM DECISIONS:
(Format: #No | Description | Amount | Category | [Status] | Reg: Citation | Reasoning | ML Confidence)
{decisions_detail}

{budget_section}

Generate the full audit report in markdown:
""")
    ])
    chain = prompt | llm | StrOutputParser()
    report = chain.invoke({
        "org": state.get("organization_name", "Nonprofit"),
        "grant": state.get("grant_number", "Unknown Grant"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "num_allowable": len(allowable),
        "allowable_total": state["total_allowable"],
        "num_unallowable": len(unallowable),
        "unallowable_total": state["total_unallowable"],
        "num_conditional": len(conditional),
        "num_review": len(needs_review),
        "decisions_detail": _format_decisions(decisions),
        "budget_section": budget_section,
    })

    new_message = {
        "agent": "ReportWriter",
        "action": "Audit report generated",
        "status": "complete"
    }

    return {
        **state,
        "audit_report_markdown": report,
        "report_generation_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "supervisor",
        "audit_complete": True
    }