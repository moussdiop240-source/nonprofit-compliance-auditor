# Nonprofit Federal Grant Compliance Auditor — Complete Documentation

> Standards: 2026 IRS & GAAP · 2 CFR 200 Uniform Guidance · 100% local inference · SHA-256 audit ledger

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Agents](#4-agents)
5. [Tools](#5-tools)
6. [Graph (LangGraph Orchestration)](#6-graph-langgraph-orchestration)
7. [Vector Stores](#7-vector-stores)
8. [RAG Layer (Governance & Privacy)](#8-rag-layer-governance--privacy)
9. [Hallucination Guard](#9-hallucination-guard)
10. [Enhancements](#10-enhancements)
11. [Streamlit UI (app.py)](#11-streamlit-ui-apppy)
12. [Data Model — AuditState](#12-data-model--auditstate)
13. [Configuration & Environment Variables](#13-configuration--environment-variables)
14. [Installation & Local Setup](#14-installation--local-setup)
15. [Docker Deployment](#15-docker-deployment)
16. [Running Tests](#16-running-tests)
17. [Sample Documents](#17-sample-documents)
18. [Security & Compliance Controls](#18-security--compliance-controls)
19. [Technology Stack](#19-technology-stack)
20. [Glossary](#20-glossary)

---

## 1. Project Overview

The **Nonprofit Federal Grant Compliance Auditor** is an AI-powered multi-agent system that automates the review of nonprofit expense reports against federal grant requirements under **2 CFR 200 (Uniform Guidance)**. It replaces hours of manual audit work with a structured, auditable pipeline that:

- Extracts structured line items from PDF or Excel expense reports
- Checks each item against 2 CFR 200 regulations and the specific grant agreement via RAG
- Detects per-se unallowable items (alcohol, lobbying, entertainment) before reaching the LLM
- Flags statistical anomalies and cross-checks spending against grant budget limits
- Routes ambiguous items to a human auditor via a HITL (Human-in-the-Loop) form
- Generates a professional audit report with executive summary, line-item table, and recommendations
- Protects PII before any LLM call and logs all sessions with SHA-256 document hashes

All LLM inference runs **100% locally** via Ollama — no data ever leaves the machine.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit UI (app.py)                    │
│   Auth gate │ File upload │ Progress stream │ HITL form │ Tabs  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  LangGraph DAG  │  (MemorySaver + interrupt_before)
                    │  build_langgraph│  Fallback: state-machine loop
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────▼──────┐  ┌────────▼────────┐  ┌──────▼──────┐
   │  Agent 1    │  │    Agent 2      │  │  Agent 3    │
   │  Expense    │  │  Compliance     │  │  Report     │
   │  Extractor  │  │  Checker        │  │  Writer     │
   └──────┬──────┘  └────────┬────────┘  └──────┬──────┘
          │                  │                  │
          │          ┌───────┴────────┐         │
          │          │ Hallucination  │         │
          │          │ Guard (4 L)    │         │
          │          └───────┬────────┘         │
          │                  │                  │
   ┌──────▼──────────────────▼──────────────────▼──────┐
   │                    Tool Layer                      │
   │  NLP Utils │ ML Cross-Checker │ RAG Tools          │
   │  PDF/Excel │ Visualization    │ Regulatory Fetcher │
   └──────────────────────┬─────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
   ┌──────▼──────┐  ┌─────▼──────┐  ┌────▼──────────┐
   │ CFR200 Store│  │Grant Store │  │  SQLite DB    │
   │  (Chroma)   │  │ (Chroma)   │  │ (entity_mapper│
   └─────────────┘  └────────────┘  └───────────────┘
                          │
                 ┌────────▼────────┐
                 │  Ollama (local) │
                 │   llama3.2      │
                 │  all-MiniLM-L6  │
                 └─────────────────┘
```

### Audit Pipeline Stages

| Stage | Agent | LLM Used | Output |
|-------|-------|----------|--------|
| 1. Extraction | ExpenseExtractor | llama3.2 (fallback only) | `extracted_line_items[]` |
| 2. Compliance | ComplianceChecker | llama3.2 | `compliance_decisions[]` |
| 3. Human Review | HITL form | none | `human_review_decisions[]` |
| 4. Reporting | ReportWriter | llama3.2 | `audit_report_markdown` |

---

## 3. Directory Structure

```
nonprofit-compliance-auditor/
│
├── app.py                        # Streamlit UI
├── demo_audit.py                 # CLI demo (no LLM needed for tabular input)
├── generate_sample_docs.py       # Creates sample PDF/XLSX grant + expense docs
├── requirements.txt              # Python dependencies
├── docker-compose.yml            # Multi-container deployment
├── README.md                     # Setup guide
├── ENHANCEMENTS.md               # Enhancement details
├── DOCUMENTATION.md              # This file
│
├── agents/
│   ├── __init__.py
│   ├── state.py                  # AuditState TypedDict + ComplianceStatus enum
│   ├── supervisor.py             # Pipeline orchestrator
│   ├── expense_extractor.py      # Agent 1: extract line items
│   ├── compliance_checker.py     # Agent 2: compliance decisions
│   ├── report_writer.py          # Agent 3: markdown report
│   └── hallucination_guard.py    # Four-layer LLM output guard
│
├── tools/
│   ├── __init__.py
│   ├── pdf_tools.py              # PDF + Excel extraction
│   ├── rag_tools.py              # CFR200 + grant store query wrappers
│   ├── formatting_tools.py       # Markdown → PDF (fpdf2)
│   ├── excel_report_formatter.py # Audit results → .xlsx
│   ├── regulatory_fetcher.py     # Live eCFR API integration
│   ├── nlp_utils.py              # NLP preprocessing (Enhancement 1)
│   ├── ml_cross_checker.py       # Anomaly detection (Enhancement 2)
│   ├── vectorstore_maintenance.py# Read-only health checks
│   └── visualization_tools.py   # Plotly charts
│
├── graph/
│   ├── __init__.py
│   ├── multi_agent_graph.py      # LangGraph DAG builder
│   └── hitl_handler.py           # Human review node
│
├── vectorstores/
│   ├── __init__.py
│   ├── cfr200_store.py           # 2 CFR 200 Chroma store (Enhancement 3)
│   └── grant_store.py            # Per-grant dynamic Chroma store
│
├── rag_layer/
│   ├── __init__.py
│   ├── access_control.py         # RBAC authentication
│   ├── pseudonymizer.py          # PII masking before LLM
│   ├── retention_policy.py       # Configurable data purge
│   └── entity_mapper.py          # SQLite audit session tracker
│
├── tests/
│   ├── __init__.py
│   ├── test_agents.py
│   ├── test_graph.py
│   ├── test_tools.py
│   ├── test_additional_tools.py
│   ├── test_rag_layer.py
│   ├── test_vectorstores.py
│   ├── test_regulatory_fetcher.py
│   ├── test_ml_cross_checker.py
│   └── test_hallucination_guard.py
│
└── data/
    ├── cfr200_docs/              # Mount real 2 CFR 200 PDFs here
    └── sample_documents/         # 8 generated sample files (PDF + XLSX)
```

---

## 4. Agents

### 4.1 AuditState (`agents/state.py`)

Shared TypedDict that flows through every node in the pipeline:

```python
class AuditState(TypedDict):
    # Inputs
    expense_report_text: str
    grant_agreement_text: str
    organization_name: str
    grant_number: str

    # Extraction outputs
    extracted_line_items: list
    extraction_complete: bool
    report_format: str          # "tabular" | "list" | "prose"
    extraction_method: str      # "tabular_direct" | "llm"

    # Compliance outputs
    compliance_decisions: list
    flagged_items: list
    total_allowable: float
    total_unallowable: float
    compliance_check_complete: bool
    grant_budget: dict
    budget_analysis: dict

    # HITL
    items_pending_human_review: list
    human_review_decisions: list
    human_review_complete: bool

    # Report
    audit_report_markdown: str
    report_generation_complete: bool

    # Control
    current_agent: str
    messages: list
    audit_complete: bool
```

**ComplianceStatus enum** — the only four valid status values:

| Value | Meaning |
|-------|---------|
| `ALLOWABLE` | Expense is clearly permitted under 2 CFR 200 and grant terms |
| `UNALLOWABLE` | Expense violates 2 CFR 200 or grant agreement |
| `CONDITIONALLY_ALLOWABLE` | Allowable only with documented conditions |
| `REQUIRES_REVIEW` | Complex — requires human auditor judgment |

---

### 4.2 Agent 1 — Expense Extractor (`agents/expense_extractor.py`)

Extracts structured line items from expense report text.

**Fast path (no LLM):** If the report is detected as `tabular` format, `parse_tabular_expenses()` extracts items directly via regex — typically 10–100× faster than the LLM path.

**LLM path:** For `list` and `prose` formats, the text is preprocessed by `preprocess_expense_text()`, enriched with an NLP hint block, capped at `MAX_EXPENSE_TEXT_CHARS` (default 12,000), and sent to the local llama3.2 model via a lazy singleton (`_get_extractor_llm()`).

**Post-processing (both paths):**
- `enrich_line_items()` — normalizes amounts, fills missing categories, cleans vendor names
- `flag_duplicate_items()` — TF-IDF cosine similarity ≥ 0.85 + amount within 5% → `possible_duplicate: True`

**Output fields per line item:**
```json
{
  "line_number": 1,
  "description": "Flight to conference",
  "amount": 450.00,
  "category": "travel",
  "vendor": "Delta Airlines",
  "date": "2024-03-15",
  "possible_duplicate": false,
  "amount_anomaly": false
}
```

**Environment variables:**

| Variable | Default | Effect |
|----------|---------|--------|
| `MAX_EXPENSE_TEXT_CHARS` | `12000` | Text size cap before LLM call |
| `OLLAMA_EXTRACTOR_MODEL` | `llama3.2` | Model for extraction (e.g. `llama3.2:1b` for 3× speed) |

---

### 4.3 Agent 2 — Compliance Checker (`agents/compliance_checker.py`)

Reviews each extracted line item against 2 CFR 200 and the grant agreement.

**Processing pipeline per item:**

```
1. Z-score anomaly detection (detect_amount_anomalies) — marks statistical outliers
2. Pre-screening (prescreen_unallowable) — per-se unallowable items bypass LLM
3. RAG query — retrieves relevant 2 CFR 200 sections + grant agreement terms
4. LLM call via invoke_with_guard() — compliance determination (with retry)
5. Hallucination guard — sanitizes LLM output (4 layers)
6. TF-IDF confidence scoring — low-confidence items → REQUIRES_REVIEW
7. Budget cross-check — compares category totals against grant limits
```

**Pre-screened patterns (no LLM cost):**
- Alcohol / alcoholic beverages → UNALLOWABLE (2 CFR 200.423)
- Lobbying / political activity → UNALLOWABLE (2 CFR 200.451)
- Entertainment → UNALLOWABLE (2 CFR 200.438)
- Personal expenses → UNALLOWABLE
- Alcohol at conferences → CONDITIONALLY_ALLOWABLE

**TF-IDF confidence threshold:** Default `0.15` (configurable via `TFIDF_CONFIDENCE_THRESHOLD`). Items below threshold are routed to REQUIRES_REVIEW regardless of LLM decision.

**Output fields per decision:**
```json
{
  "status": "ALLOWABLE",
  "regulation_cited": "2 CFR 200.474",
  "reasoning": "Travel cost directly related to grant performance.",
  "requires_human_review": false,
  "flagged_reason": null,
  "prescreened": false,
  "confidence_score": 0.87,
  "amount_anomaly": false,
  "line_number": 1,
  "description": "Flight to conference",
  "amount": 450.00,
  "category": "travel",
  "vendor": "Delta Airlines",
  "date": "2024-03-15"
}
```

---

### 4.4 Agent 3 — Report Writer (`agents/report_writer.py`)

Generates a professional markdown compliance audit report via the local LLM.

**Report sections:**
1. Executive Summary (organization, grant, totals, overall risk)
2. Compliance Decision Summary (table of all items with status)
3. Detailed Analysis (reasoning per item)
4. Budget vs. Actuals (if grant budget available)
5. Flagged Items (unallowable + items requiring review)
6. Human Review Decisions (if HITL was invoked)
7. Recommendations

---

### 4.5 Supervisor (`agents/supervisor.py`)

Orchestrates the four-stage audit cycle. Routes state between agents based on `current_agent` field. Used as the fallback state-machine when LangGraph is not available.

---

## 5. Tools

### 5.1 PDF & Excel Extraction (`tools/pdf_tools.py`)

| Function | Purpose |
|----------|---------|
| `extract_text_from_pdf(path)` | pdfplumber primary, PyPDF2 fallback; returns raw text string |
| `extract_text_from_excel(path)` | pandas + openpyxl; concatenates all sheets as tab-separated text |
| `get_pdf_metadata(path)` | Title, author, page count, creation date |

---

### 5.2 RAG Tools (`tools/rag_tools.py`)

| Function | Purpose |
|----------|---------|
| `query_cfr200_store(query, k=3)` | Similarity search in 2 CFR 200 Chroma store |
| `query_grant_store(grant_text, query, k=3)` | Builds/reuses per-grant Chroma store; similarity search |

Both functions include the index version tag in the returned text for traceability.

---

### 5.3 Formatting Tools (`tools/formatting_tools.py`)

| Function | Purpose |
|----------|---------|
| `markdown_to_pdf(markdown_text, output_path)` | Converts audit report markdown to PDF via fpdf2 |

Handles long words, markdown stripping, UTF-8 encoding fallbacks, and plain-text fallback on fpdf2 errors.

---

### 5.4 Excel Report Formatter (`tools/excel_report_formatter.py`)

Exports audit results to a multi-sheet `.xlsx` file:

| Sheet | Contents |
|-------|---------|
| Summary | Organization, grant, totals, overall risk assessment |
| Line Items | All extracted expenses with metadata |
| Decisions | Compliance decisions with status color-coding |
| Human Review | HITL decisions (if applicable) |

---

### 5.5 Regulatory Fetcher (`tools/regulatory_fetcher.py`)

Live eCFR API integration for Enhancement 3:

| Function | Purpose |
|----------|---------|
| `get_latest_version_date()` | Returns latest 2 CFR Part 200 publication date from eCFR API |
| `fetch_cfr200_sections(version_date)` | Downloads all Part 200 sections as LangChain Document objects |

---

### 5.6 NLP Utilities (`tools/nlp_utils.py`) — Enhancement 1

| Function | Purpose |
|----------|---------|
| `preprocess_expense_text(text)` | Extracts amounts, dates, vendor candidates; returns hint dict |
| `detect_report_format(text)` | Classifies as `tabular`, `list`, or `prose` |
| `parse_tabular_expenses(text)` | Direct regex extraction for tabular reports (no LLM) |
| `build_nlp_hint_block(preprocessed)` | Formats NLP findings as LLM prompt prefix |
| `enrich_line_items(items)` | Normalizes amounts, fills missing categories, cleans vendors |
| `flag_duplicate_items(items)` | TF-IDF duplicate detection (similarity ≥ 0.85 + amount ±5%) |
| `extract_grant_budget(grant_text)` | Parses budget amounts per category from grant text |

---

### 5.7 ML Cross-Checker (`tools/ml_cross_checker.py`) — Enhancement 2

| Function | Purpose |
|----------|---------|
| `prescreen_unallowable(description, amount)` | Rule-based pre-screen; returns `{prescreened, unallowable, conditionally_allowable, regulation, reason}` |
| `detect_amount_anomalies(items)` | Modified Z-score per category; annotates `amount_anomaly: True` on outliers |
| `cross_check_budget(decisions, budget)` | Compares actual spend per category against grant budget limits |

---

### 5.8 Vectorstore Maintenance (`tools/vectorstore_maintenance.py`)

Read-only health and stats API — safe to call at any time:

| Function | Purpose |
|----------|---------|
| `get_cfr200_stats()` | Version, doc count, persist dir existence, healthy flag |
| `check_cfr200_health(query)` | Live test query; returns latency, result preview |
| `get_grant_store_stats()` | Count and disk size of all `chroma_grant_*` stores |
| `full_maintenance_report()` | Combined health report across all stores |

---

### 5.9 Visualization Tools (`tools/visualization_tools.py`)

All functions return a Plotly Figure or `None` (when plotly is unavailable):

| Function | Chart type |
|----------|-----------|
| `compliance_breakdown_chart(decisions)` | Donut — ALLOWABLE / UNALLOWABLE / CONDITIONALLY_ALLOWABLE / REQUIRES_REVIEW proportions |
| `expense_by_category_chart(line_items)` | Horizontal bar — total spend per category |
| `confidence_distribution_chart(decisions)` | Histogram — TF-IDF confidence scores with threshold line |
| `allowable_vs_unallowable_bar(...)` | Grouped bar — allowable / conditional / unallowable dollar totals |
| `budget_vs_actuals_chart(line_items, budget)` | Grouped bar — budgeted vs actual per category |
| `render_chart(fig)` | Renders figure in Streamlit or shows fallback message |

---

## 6. Graph (LangGraph Orchestration)

### 6.1 `graph/multi_agent_graph.py`

**`build_langgraph()`** — builds the full LangGraph `StateGraph`:

```
extract_expenses → check_compliance → [human_review] → write_report
                                            ↑
                              interrupt_before (HITL pause point)
```

- Uses `MemorySaver` checkpointer for state persistence across interrupts
- `interrupt_before=["human_review"]` pauses execution and yields control to the Streamlit UI
- After the human submits decisions, execution resumes with `graph.invoke(None, config)`

**`build_graph()`** — simpler version without HITL interrupt (for testing/demo).

**`run_graph(state)`** — fallback state-machine loop when LangGraph is unavailable.

### 6.2 `graph/hitl_handler.py`

The `human_review_node` applies auditor decisions back into the state:

1. For each decision in `human_review_decisions`, finds the matching item in `compliance_decisions` by `line_number`
2. Overrides `status`, `reasoning`, `regulation_cited`, `requires_human_review`
3. Recalculates `total_allowable` and `total_unallowable`
4. Sets `human_review_complete: True`

---

## 7. Vector Stores

### 7.1 CFR200 Store (`vectorstores/cfr200_store.py`)

Chroma vector store for 2 CFR 200 (Uniform Guidance) content.

**Loading order:**
1. Load existing persist directory if found
2. Load PDFs from `CFR200_DIR` (default: `data/cfr200_docs/`)
3. Fall back to built-in excerpts for 8 key CFR sections (200.420, 200.421, 200.423, 200.431, 200.432, 200.438, 200.439, 200.451, 200.453, 200.474)

**Built-in fallback sections** (always available, no files required):
- 200.420 — Allowability factors
- 200.421 — Advertising costs
- 200.423 — Alcoholic beverages (unallowable)
- 200.431 — Fringe benefits
- 200.432 — Conferences
- 200.439 — Equipment
- 200.451 — Lobbying (unallowable)
- 200.453 — Materials and supplies
- 200.474 — Travel costs

**Key functions:**

| Function | Purpose |
|----------|---------|
| `load_cfr200_store()` | Load or create the store |
| `query_cfr200(query, k=3)` | Semantic search; lazy-loads store on first call |
| `reindex(cfr200_dir)` | Wipe and rebuild from local PDFs |
| `reindex_from_ecfr()` | Wipe and rebuild from live eCFR API |
| `check_ecfr_update()` | Check if a newer version is available |
| `get_store_version()` | Current version tag |

**Version format:** `ecfr-YYYY-MM-DD-<hash12>` for eCFR-sourced, `YYYYMMDD-HHMMSS-<hash12>` for local reindex.

---

### 7.2 Grant Store (`vectorstores/grant_store.py`)

Per-grant dynamic Chroma store built from the grant agreement text.

- Store ID derived from SHA-256 hash of grant text — same grant reuses the cached store
- Text split into 500-char chunks with 50-char overlap
- Persisted to `./chroma_grant_<store_id>/`
- Queried by `query_grant_store()` in `tools/rag_tools.py`

---

## 8. RAG Layer (Governance & Privacy)

### 8.1 Access Control (`rag_layer/access_control.py`)

Role-based authentication with three permission levels:

| Role | Permissions |
|------|-------------|
| `admin` | Full access: run audits, view all results, manage vector stores, configure retention |
| `auditor` | Run audits, view results, submit HITL decisions |
| `viewer` | Read-only access to results |

**Credential configuration** (environment variables):
```
AUDIT_USER_ALICE=auditor:password_hash
AUDIT_USER_BOB=admin:password_hash
```

Passwords are hashed with SHA-256 before storage. Default test credentials:
- `admin` / `admin123`
- `auditor` / `audit456`
- `viewer` / `view789`

---

### 8.2 PII Pseudonymizer (`rag_layer/pseudonymizer.py`)

Masks sensitive data **before** any text is sent to the LLM:

| Pattern | Replaced with |
|---------|--------------|
| SSN (XXX-XX-XXXX) | `[SSN-REDACTED]` |
| EIN (XX-XXXXXXX) | `[EIN-REDACTED]` |
| Email addresses | `[EMAIL-REDACTED]` |
| Phone numbers | `[PHONE-REDACTED]` |
| Credit card numbers | `[CARD-REDACTED]` |
| Bank account numbers | `[ACCOUNT-REDACTED]` |

Returns a redaction count dict for the transparency notice shown in the UI.

---

### 8.3 Retention Policy (`rag_layer/retention_policy.py`)

Configurable automatic purge of old audit data:

| Variable | Default | Scope |
|----------|---------|-------|
| `AUDIT_SESSION_RETENTION_DAYS` | `365` | SQLite session records |
| `GRANT_STORE_RETENTION_DAYS` | `90` | `chroma_grant_*` directories |

Retention checks can be triggered manually from the admin panel in the UI.

---

### 8.4 Entity Mapper (`rag_layer/entity_mapper.py`)

SQLite-backed audit session tracker at `data/audit_log.db`:

| Column | Content |
|--------|---------|
| `session_id` | UUID |
| `organization` | Organization name |
| `grant_number` | Grant identifier |
| `expense_doc_hash` | SHA-256 of expense report text |
| `grant_doc_hash` | SHA-256 of grant agreement text |
| `status` | `in_progress` \| `complete` \| `error` |
| `result_summary` | JSON summary of totals |
| `created_at` | ISO timestamp |
| `updated_at` | ISO timestamp |

Raw document text is **never stored** — only hashes.

---

## 9. Hallucination Guard

`agents/hallucination_guard.py` provides a four-layer defense against LLM output errors applied to every compliance decision before it enters the audit state.

### Layer overview

| Layer | What it catches | Action |
|-------|----------------|--------|
| **L1 Schema** | Unknown fields injected by LLM; `requires_human_review` as string `"true"` or integer `1` | Strip unknown fields; coerce to correct Python types |
| **L2 Status enum** | Any `status` value not in `{ALLOWABLE, UNALLOWABLE, CONDITIONALLY_ALLOWABLE, REQUIRES_REVIEW}` — including wrong case, typos, invented values | Coerce to `REQUIRES_REVIEW`; set `requires_human_review=True` |
| **L3 Consistency** | `REQUIRES_REVIEW` without `requires_human_review=True`; `requires_human_review=True` without `flagged_reason`; stale `flagged_reason` on clean `ALLOWABLE` | Enforce all three invariants |
| **L4 Citation** | Empty or implausibly short `regulation_cited` string | Replace with `"2 CFR 200 — see manual review"` |

### Retry wrapper

`invoke_with_guard(chain, args, max_retries=2)` retries the LangChain chain on any JSON parse or connection error. After all retries are exhausted it returns a safe `REQUIRES_REVIEW` sentinel — the pipeline never crashes or stores a corrupt decision.

### Field protection (merge order)

The merge `{**decision, **item}` ensures item fields (`amount`, `line_number`, `description`, `vendor`, `category`) are always authoritative. LLM-returned values for those fields are stripped by L1 and cannot override the original extracted data.

---

## 10. Enhancements

### Enhancement 1 — Advanced NLP Pipeline

**Location:** `tools/nlp_utils.py`, `agents/expense_extractor.py`

Regex-based preprocessing runs before the LLM to:
- Detect report format (tabular → direct parse, no LLM needed)
- Extract dollar amounts, dates, vendor candidates as hints
- Build a `[NLP PRE-ANALYSIS]` block prepended to the LLM prompt
- Enrich and normalize extracted line items post-LLM
- Flag near-duplicate line items via TF-IDF cosine similarity

**Benefit:** Tabular expense reports (the most common format) are processed entirely without any LLM call.

---

### Enhancement 2 — ML-Driven Cross-Checking

**Location:** `tools/ml_cross_checker.py`, `agents/compliance_checker.py`

Three ML/rule-based checks run alongside the LLM:

1. **Per-se unallowable pre-screening** — regex patterns for alcohol, lobbying, entertainment, personal expenses — bypasses the LLM entirely when a violation is certain
2. **Z-score anomaly detection** — modified Z-score per expense category; items with |Z| > 3.5 are annotated `amount_anomaly: True` and the LLM prompt is flagged
3. **Budget cross-check** — totals actual spend per category against parsed grant budget limits; exceeded categories are noted in the audit report

---

### Enhancement 3 — Regulatory Database Integration

**Location:** `vectorstores/cfr200_store.py`, `tools/regulatory_fetcher.py`

- **Live eCFR sync** — `reindex_from_ecfr()` fetches 2 CFR Part 200 sections directly from the eCFR API and rebuilds the Chroma index
- **Version tagging** — every index is stamped with a date + content hash (`ecfr-YYYY-MM-DD-<hash12>`) for traceability
- **Update check** — `check_ecfr_update()` compares the current index date against the latest eCFR publication date
- **Admin UI** — the Streamlit admin panel exposes reindex and update-check controls

---

## 11. Streamlit UI (`app.py`)

### Authentication

Login form gated by `require_auth()`. Role-based: admin, auditor, viewer.

### Phase 1 — Audit Run

1. Upload grant agreement (PDF or Excel)
2. Upload expense report (PDF or Excel)
3. Enter organization name and grant number
4. Click **Run Compliance Audit**
5. UI streams LangGraph node completions until the HITL interrupt

### Phase 2 — Human Review (HITL)

For each flagged item, the auditor selects:
- Override status (ALLOWABLE / UNALLOWABLE / CONDITIONALLY_ALLOWABLE / REQUIRES_REVIEW)
- Optional reasoning note

On submission, the pipeline resumes and generates the final report.

### Results Tabs

| Tab | Content |
|-----|---------|
| Summary | Totals, status counts, budget vs. actuals chart, confidence distribution |
| Line Items | Full table of extracted expenses with anomaly flags |
| Compliance Decisions | Detailed decisions with regulation citations and reasoning |
| Human Review | Applied HITL decisions |
| Audit Report | Full markdown report + download as PDF or Excel |
| Charts | All Plotly visualizations |

### Admin Panel (admin role only)

- CFR200 store health check and stats
- Manual reindex from local PDFs
- Live eCFR update check and reindex
- Grant store inventory
- Retention policy trigger

---

## 12. Data Model — AuditState

See [Section 4.1](#41-auditstate-agentsstatepy) for the full TypedDict definition.

**Line item schema:**
```json
{
  "line_number": 1,
  "description": "string",
  "amount": 0.0,
  "category": "travel|personnel|supplies|equipment|indirect|other",
  "vendor": "string|null",
  "date": "YYYY-MM-DD|null",
  "possible_duplicate": false,
  "amount_anomaly": false
}
```

**Compliance decision schema (after hallucination guard):**
```json
{
  "status": "ALLOWABLE|UNALLOWABLE|CONDITIONALLY_ALLOWABLE|REQUIRES_REVIEW",
  "regulation_cited": "2 CFR 200.XXX",
  "reasoning": "string",
  "requires_human_review": false,
  "flagged_reason": "string|null",
  "prescreened": false,
  "confidence_score": 0.0,
  "line_number": 1,
  "description": "string",
  "amount": 0.0,
  "category": "string",
  "vendor": "string|null",
  "date": "string|null",
  "amount_anomaly": false
}
```

---

## 13. Configuration & Environment Variables

| Variable | Default | Module | Description |
|----------|---------|--------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | LangChain | Ollama server URL |
| `OLLAMA_EXTRACTOR_MODEL` | `llama3.2` | expense_extractor | LLM for extraction (e.g. `llama3.2:1b` for speed) |
| `MAX_EXPENSE_TEXT_CHARS` | `12000` | expense_extractor | Max characters sent to LLM for extraction |
| `TFIDF_CONFIDENCE_THRESHOLD` | `0.15` | compliance_checker | Minimum TF-IDF score; below → REQUIRES_REVIEW |
| `CFR200_DIR` | `./data/cfr200_docs` | cfr200_store | Path to 2 CFR 200 PDF documents |
| `CFR200_PERSIST_DIR` | `./chroma_cfr200` | cfr200_store | Chroma persistence directory |
| `AUDIT_USER_<NAME>` | — | access_control | `role:sha256hash` credential pairs |
| `AUDIT_SESSION_RETENTION_DAYS` | `365` | retention_policy | Session record retention window |
| `GRANT_STORE_RETENTION_DAYS` | `90` | retention_policy | Grant store retention window |

---

## 14. Installation & Local Setup

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running
- llama3.2 model pulled: `ollama pull llama3.2`
- (Optional) GPU — significantly improves LLM inference speed

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/moussdiop240-source/nonprofit-compliance-auditor.git
cd nonprofit-compliance-auditor

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Pull the LLM model
ollama pull llama3.2

# 5. (Optional) Add real 2 CFR 200 PDFs for a richer vector index
mkdir -p data/cfr200_docs
# Copy your PDFs into data/cfr200_docs/
# The built-in fallback excerpts work without any PDFs.

# 6. Run the app
streamlit run app.py
# Open http://localhost:8501
```

### Default credentials

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | admin |
| `auditor` | `audit456` | auditor |
| `viewer` | `view789` | viewer |

### Speed tip

For faster extraction on CPU-only machines:
```bash
ollama pull llama3.2:1b
export OLLAMA_EXTRACTOR_MODEL=llama3.2:1b
```

---

## 15. Docker Deployment

The `docker-compose.yml` orchestrates three containers:

| Service | Image | Purpose |
|---------|-------|---------|
| `app` | Built from repo | Streamlit auditor on port 8501 |
| `ollama` | `ollama/ollama:latest` | Local LLM server on port 11434 |
| `model-puller` | `ollama/ollama:latest` | One-off: pulls llama3.2, then exits |

```bash
# Start all services
docker-compose up -d

# Mount real 2 CFR 200 PDFs (optional):
# docker-compose up -d -v ./my-cfr200-pdfs:/app/data/cfr200_docs

# View logs
docker-compose logs -f app

# Stop
docker-compose down
```

**Volumes:**

| Volume | Mount | Content |
|--------|-------|---------|
| `chroma_data` | `/app/chroma_cfr200` | CFR200 Chroma index |
| `cfr200_docs` | `/app/data/cfr200_docs` | 2 CFR 200 PDF source documents |
| `ollama_data` | `/root/.ollama` | Downloaded Ollama models |

The app waits for Ollama to pass its health check before starting (`depends_on: condition: service_healthy`).

---

## 16. Running Tests

```bash
# Run full suite (244 tests)
pytest

# Run with verbose output
pytest -v

# Run a specific module
pytest tests/test_hallucination_guard.py -v
pytest tests/test_agents.py -v
pytest tests/test_ml_cross_checker.py -v

# Run with short traceback
pytest --tb=short -q
```

### Test modules

| File | Tests | Coverage area |
|------|-------|--------------|
| `test_agents.py` | ~40 | Agent 1, 2, 3 with mocked LLM chains |
| `test_graph.py` | ~20 | LangGraph build, state-machine routing |
| `test_tools.py` | ~35 | PDF/Excel, formatting, NLP, visualization |
| `test_additional_tools.py` | ~20 | Regulatory fetcher, maintenance utilities |
| `test_rag_layer.py` | ~30 | Auth, pseudonymizer, retention, SQLite |
| `test_vectorstores.py` | ~25 | Chroma store load/query/reindex |
| `test_regulatory_fetcher.py` | ~15 | eCFR API integration |
| `test_ml_cross_checker.py` | ~20 | Pre-screening, anomalies, budget checks |
| `test_hallucination_guard.py` | **32** | All 4 guard layers + retry logic |

---

## 17. Sample Documents

Generated by `generate_sample_docs.py` using reportlab (PDF) and openpyxl (Excel):

| File | Type | Content |
|------|------|---------|
| `example1_grant_agreement_HHS101.pdf/xlsx` | Grant | HHS award $85,000 — community health program |
| `example1_expense_report_HHS101.pdf/xlsx` | Expenses | Clean expenses within budget |
| `example2_grant_agreement_DOE207.pdf/xlsx` | Grant | DoE award $120,000 — STEM tutoring program |
| `example2_expense_report_DOE207.pdf/xlsx` | Expenses | Mixed: allowable travel + flagged alcohol/lobbying items |

Regenerate at any time:
```bash
python generate_sample_docs.py
```

---

## 18. Security & Compliance Controls

| Control | Implementation |
|---------|---------------|
| **100% local inference** | Ollama runs llama3.2 locally; no data sent to external APIs |
| **PII masking** | SSN, EIN, email, phone, card, account numbers replaced before LLM |
| **SHA-256 audit ledger** | Document hashes stored in SQLite; raw text never persisted |
| **Role-based access control** | admin / auditor / viewer with hashed credentials |
| **Hallucination guard** | 4-layer validation on all LLM output — no corrupt decision enters the state |
| **IRS $75 receipt rule** | Flagged in compliance reasoning for travel items >$75 |
| **Configurable retention** | Session and vector store data purged after configurable windows |
| **Grant store isolation** | Each grant gets its own Chroma namespace (SHA-256-keyed) |

---

## 19. Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| LLM | Ollama / llama3.2 | ollama ≥ 0.3.0 |
| Embeddings | HuggingFace all-MiniLM-L6-v2 | sentence-transformers ≥ 5.5.0 |
| LLM framework | LangChain + LangChain-Ollama | ≥ 0.3.0 |
| Workflow | LangGraph | ≥ 0.2.0 |
| Vector DB | Chroma | chromadb ≥ 1.5.9 |
| UI | Streamlit | ≥ 1.39.0 |
| PDF read | pdfplumber / PyPDF2 | ≥ 0.11.0 / ≥ 3.0.0 |
| PDF write | fpdf2 | ≥ 2.7.0 |
| Excel | pandas + openpyxl | ≥ 2.0.0 / ≥ 3.1.0 |
| ML/NLP | scikit-learn | ≥ 1.4.0 |
| Visualization | plotly | ≥ 5.18.0 |
| Database | SQLite (stdlib) | — |
| HTTP | requests | ≥ 2.28.0 |
| Testing | pytest + pytest-mock | ≥ 8.0.0 / ≥ 3.14.0 |
| Deployment | Docker + docker-compose | — |

---

## 20. Glossary

| Term | Definition |
|------|-----------|
| **2 CFR 200** | Uniform Administrative Requirements, Cost Principles, and Audit Requirements for Federal Awards — the governing regulation for federal grant compliance |
| **ALLOWABLE** | An expense that is permitted under 2 CFR 200 and the specific grant agreement |
| **CONDITIONALLY_ALLOWABLE** | An expense that is permitted only under specific documented conditions |
| **UNALLOWABLE** | An expense that violates 2 CFR 200 or the grant agreement |
| **REQUIRES_REVIEW** | An expense that cannot be automatically classified and needs human auditor judgment |
| **HITL** | Human-in-the-Loop — the pipeline pause that routes flagged items to an auditor before the final report |
| **RAG** | Retrieval-Augmented Generation — querying a vector store for relevant regulatory text before LLM inference |
| **TF-IDF** | Term Frequency–Inverse Document Frequency — a text similarity metric used for confidence scoring and duplicate detection |
| **Z-score** | Modified Z-score for statistical anomaly detection in expense amounts per category |
| **Per-se unallowable** | Expenses that are categorically forbidden regardless of context (alcohol, lobbying, entertainment) |
| **Hallucination guard** | The four-layer validation system that prevents invalid LLM output from entering the audit state |
| **MemorySaver** | LangGraph checkpointer that persists state between graph interrupts (required for HITL) |
| **UNICAP** | Uniform Capitalization Rules — IRS threshold of $31M above which inventory capitalization rules change |
| **IRS $75 rule** | Receipts required for any single expense over $75 under federal grant accounting |
