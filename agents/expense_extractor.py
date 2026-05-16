import json
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tools.nlp_utils import preprocess_expense_text, build_nlp_hint_block

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
    Agent 1: Extracts structured line items from expense report using local Ollama.
    Enhancement 1: NLP preprocessing is applied before LLM extraction.
    """
    # Enhancement 1 — NLP preprocessing (prepended, original logic unchanged below)
    preprocessed = preprocess_expense_text(state["expense_report_text"])
    nlp_hints = build_nlp_hint_block(preprocessed)
    augmented_text = nlp_hints + "\n\n" + state["expense_report_text"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", EXTRACTOR_SYSTEM_PROMPT),
        ("human", "Expense Report:\n\n{expense_report}")
    ])
    # Use Ollama's model via LangChain
    llm = ChatOllama(model="llama3.2", temperature=0)
    chain = prompt | llm | StrOutputParser()
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

    new_message = {
        "agent": "ExpenseExtractor",
        "action": f"Extracted {len(line_items)} line items from expense report",
        "status": "complete"
    }
    return {
        **state,
        "extracted_line_items": line_items,
        "extraction_complete": True,
        "messages": state.get("messages", []) + [new_message],
        "current_agent": "compliance_checker"
    }