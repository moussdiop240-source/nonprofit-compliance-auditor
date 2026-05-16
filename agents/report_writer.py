from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from datetime import datetime

llm = ChatOllama(model="llama3.2", temperature=0.1)

def write_audit_report(state: dict) -> dict:
    """
    Agent 3: Generates a professional, formatted compliance audit report.
    """
    decisions = state["compliance_decisions"]
    allowable = [d for d in decisions if d["status"] == "ALLOWABLE"]
    unallowable = [d for d in decisions if d["status"] == "UNALLOWABLE"]
    conditional = [d for d in decisions if d["status"] == "CONDITIONALLY_ALLOWABLE"]
    needs_review = [d for d in decisions if d["status"] == "REQUIRES_REVIEW"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a nonprofit audit report writer. Generate a professional markdown audit report summarizing the compliance review."),
        ("human", """
        Organization: {org}
        Grant: {grant}
        Date: {date}
        
        Allowable items ({num_allowable}): ${allowable_total:,.2f}
        Unallowable items ({num_unallowable}): ${unallowable_total:,.2f}
        Conditionally allowable ({num_conditional})
        Items needing review ({num_review})
        
        Provide an executive summary, detailed findings table, and recommendations.
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
        "num_review": len(needs_review)
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