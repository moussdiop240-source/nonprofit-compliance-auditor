import json
import os
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tools.nlp_utils import (
    preprocess_expense_text,
    build_nlp_hint_block,
    detect_report_format,
    parse_tabular_expenses,
    enrich_line_items,
    flag_duplicate_items,
)

# Cap text sent to the LLM — avoids slow inference on large PDF extracts.
# Override with MAX_EXPENSE_TEXT_CHARS env var if needed.
_MAX_TEXT_CHARS = int(os.environ.get("MAX_EXPENSE_TEXT_CHARS", "12000"))

# Configurable model — swap in a smaller model (e.g. llama3.2:1b) for faster extraction.
_extractor_llm = None


def _get_extractor_llm():
    global _extractor_llm
    if _extractor_llm is None:
        model = os.environ.get("OLLAMA_EXTRACTOR_MODEL", "llama3.2")
        _extractor_llm = ChatOllama(model=model, temperature=0)
    return _extractor_llm

EXTRACTOR_SYSTEM_PROMPT = """You are an expert financial document analyst specializing in nonprofit expense reports.
Your job is to extract ALL expense line items from the provided expense report.
For each line item, extract:
- line_number (sequential integer)
- description (what was purchased/expensed)
- amount (dollar amount as float)
- category (travel, personnel, supplies, equipment, indirect, etc.)
- vendor (if mentioned)
- date (if mentioned)
Return ONLY a valid JSON array. No explanation. No markdown.
Example format:
[
  {{
    "line_number": 1,
    "description": "Flight to conference",
    "amount": 450.00,
    "category": "travel",
    "vendor": "Delta Airlines",
    "date": "2024-03-15"
  }}
]"""

def extract_expenses(state: dict) -> dict:
    """
    Agent 1: Extracts structured line items from expense report.
    Enhancement 1: format-aware extraction with post-LLM enrichment and duplicate flagging.
    """
    text = state["expense_report_text"]

    # Enhancement 1a — detect report structure
    report_format = detect_report_format(text)
    extraction_method = "llm"

    # Enhancement 1b — for tabular reports, attempt direct parse (faster, no LLM cost)
    line_items = []
    if report_format == "tabular":
        line_items = parse_tabular_expenses(text)
        if line_items:
            extraction_method = "tabular_direct"

    # Fall back to LLM for list/prose formats or when tabular parse yields nothing
    if not line_items:
        preprocessed = preprocess_expense_text(text)
        nlp_hints = build_nlp_hint_block(preprocessed)
        # Inject format hint so the LLM knows the document structure
        format_hint = f"[DOCUMENT FORMAT: {report_format.upper()}]\n"
        augmented_text = format_hint + nlp_hints + "\n\n" + text

        if len(augmented_text) > _MAX_TEXT_CHARS:
            augmented_text = augmented_text[:_MAX_TEXT_CHARS]

        prompt = ChatPromptTemplate.from_messages([
            ("system", EXTRACTOR_SYSTEM_PROMPT),
            ("human", "Expense Report:\n\n{expense_report}")
        ])
        chain = prompt | _get_extractor_llm() | StrOutputParser()
        result = chain.invoke({"expense_report": augmented_text})

        try:
            content = result.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            line_items = json.loads(content)
        except json.JSONDecodeError:
            line_items = []

    # Enhancement 1c — post-processing: fill gaps, normalize types, clean vendors
    line_items = enrich_line_items(line_items)

    # Enhancement 1d — flag near-duplicate line items via TF-IDF similarity
    line_items = flag_duplicate_items(line_items)
    duplicate_count = sum(1 for i in line_items if i.get("possible_duplicate"))

    new_message = {
        "agent": "ExpenseExtractor",
        "action": (
            f"Extracted {len(line_items)} line items via {extraction_method} "
            f"(format: {report_format}"
            + (f", {duplicate_count} possible duplicate(s)" if duplicate_count else "")
            + ")"
        ),
        "status": "complete"
    }
    return {
        **state,
        "extracted_line_items": line_items,
        "extraction_complete": True,
        "report_format": report_format,
        "extraction_method": extraction_method,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "compliance_checker"
    }