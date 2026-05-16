from typing import TypedDict, List, Optional, Dict
from enum import Enum
from dataclasses import dataclass

class ComplianceStatus(str, Enum):
    ALLOWABLE = "ALLOWABLE"
    UNALLOWABLE = "UNALLOWABLE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    CONDITIONALLY_ALLOWABLE = "CONDITIONALLY_ALLOWABLE"

@dataclass
class ExpenseLineItem:
    line_number: int
    description: str
    amount: float
    category: str
    vendor: Optional[str] = None
    date: Optional[str] = None

@dataclass
class ComplianceDecision:
    line_item: ExpenseLineItem
    status: ComplianceStatus
    regulation_cited: str
    reasoning: str
    requires_human_review: bool
    flagged_reason: Optional[str] = None
    confidence_score: Optional[float] = None

class AuditState(TypedDict):
    # Inputs
    expense_report_text: str
    grant_agreement_text: str
    organization_name: str
    grant_number: str
    # Agent 1 outputs
    extracted_line_items: List[dict]
    extraction_complete: bool
    # Agent 2 outputs
    compliance_decisions: List[dict]
    flagged_items: List[dict]
    total_allowable: float
    total_unallowable: float
    compliance_check_complete: bool
    # Human review
    items_pending_human_review: List[dict]
    human_review_decisions: List[dict]
    human_review_complete: bool
    # Agent 3 outputs
    audit_report_markdown: str
    report_generation_complete: bool
    # Supervisor control
    current_agent: str
    messages: List[dict]
    audit_complete: bool