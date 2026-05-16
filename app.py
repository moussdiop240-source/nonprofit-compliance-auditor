"""
Streamlit UI — Nonprofit Federal Grant Compliance Auditor
Upload an Expense Report PDF and a Grant Agreement PDF to run a full 2 CFR 200 audit.
"""
import io
import sys
import os

# Allow imports from project root
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from tools.pdf_tools import extract_text_from_pdf, extract_metadata_from_pdf, extract_text_from_file
from tools.formatting_tools import generate_pdf
from agents.expense_extractor import extract_expenses
from agents.compliance_checker import check_compliance
from agents.report_writer import write_audit_report
from graph.hitl_handler import human_review_node

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nonprofit Compliance Auditor",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
for _key, _val in {
    "audit_result": None,
    "pdf_bytes": None,
}.items():
    if _key not in st.session_state:
        st.session_state[_key] = _val

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📋 Nonprofit Federal Grant Compliance Auditor")
st.markdown(
    "Automatically audit every expense line item against **2 CFR 200 (Uniform Guidance)** "
    "and your grant agreement. Powered by **LangChain + Ollama (llama3.2)** — 100% local."
)
st.divider()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Organization Details")
    org_name = st.text_input(
        "Organization Name", placeholder="e.g. Community Impact Org", key="org_name"
    )
    grant_number = st.text_input(
        "Grant Number", placeholder="e.g. 2024-HHS-001", key="grant_number"
    )
    st.divider()
    st.markdown("**Workflow Architecture**")
    st.markdown("""
<div style="font-family:sans-serif; font-size:12px; padding:4px 0;">

  <div style="
      background:linear-gradient(135deg,#1e3a5f,#2c5282);
      color:white; border-radius:10px; padding:9px 12px;
      text-align:center; font-weight:700; font-size:13px;
      box-shadow:0 2px 6px rgba(0,0,0,0.25); letter-spacing:.4px;">
    🎯 Supervisor
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="
      background:#eff6ff; border-left:4px solid #3b82f6;
      border-radius:6px; padding:7px 11px; margin-bottom:3px;">
    <span style="color:#1d4ed8;font-weight:700;">① Expense Extractor</span><br>
    <span style="color:#475569;">NLP pre-analysis + Ollama</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="
      background:#f0fdf4; border-left:4px solid #22c55e;
      border-radius:6px; padding:7px 11px; margin-bottom:3px;">
    <span style="color:#15803d;font-weight:700;">② Compliance Checker</span><br>
    <span style="color:#475569;">2 CFR 200 RAG + TF-IDF</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="
      background:#fffbeb; border-left:4px solid #f59e0b;
      border-radius:6px; padding:7px 11px; margin-bottom:3px;">
    <span style="color:#b45309;font-weight:700;">⚠ HITL Human Review</span><br>
    <span style="color:#475569;">Flagged &amp; low-confidence items</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="
      background:#fdf4ff; border-left:4px solid #a855f7;
      border-radius:6px; padding:7px 11px;">
    <span style="color:#7e22ce;font-weight:700;">③ Report Writer</span><br>
    <span style="color:#475569;">Markdown → PDF audit report</span>
  </div>

</div>
""", unsafe_allow_html=True)
    st.divider()
    st.caption("2026 IRS / GAAP standards | SHA-256 ledger integrity")

# ── File preview helper ───────────────────────────────────────────────────────
def _render_file_preview(uploaded_file) -> None:
    """Render a collapsible preview of a PDF or Excel upload."""
    ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
    with st.expander(f"👁️ Preview — {uploaded_file.name}", expanded=False):
        if ext in ("xlsx", "xls"):
            try:
                import pandas as pd
                import io as _io
                sheets = pd.read_excel(
                    _io.BytesIO(uploaded_file.getvalue()),
                    sheet_name=None,
                    engine="openpyxl" if ext == "xlsx" else "xlrd",
                    dtype=str,
                )
                for sheet_name, df in sheets.items():
                    df = df.dropna(how="all").fillna("")
                    if df.empty:
                        continue
                    st.caption(f"Sheet: **{sheet_name}** — {len(df)} row(s), {len(df.columns)} column(s)")
                    st.dataframe(df.head(20), use_container_width=True, hide_index=True)
            except Exception as e:
                st.warning(f"Could not preview Excel file: {e}")
        else:
            try:
                text = extract_text_from_pdf(io.BytesIO(uploaded_file.getvalue()))
                if text.strip():
                    preview = text[:2000] + ("…" if len(text) > 2000 else "")
                    st.text_area("Extracted text (first 2 000 chars)", preview,
                                 height=220, disabled=True, label_visibility="collapsed")
                    st.caption(f"Total extracted: {len(text):,} characters")
                else:
                    st.warning("No text could be extracted — file may be image-only.")
            except Exception as e:
                st.warning(f"Could not preview PDF: {e}")


# ── File upload ───────────────────────────────────────────────────────────────
col_left, col_right = st.columns(2)

_ACCEPTED_TYPES = ["pdf", "xlsx", "xls"]

with col_left:
    expense_file = st.file_uploader(
        "📄 Expense Report (PDF or Excel)",
        type=_ACCEPTED_TYPES,
        help="Upload the nonprofit's expense report — PDF or Excel (.xlsx / .xls)",
        key="expense_upload",
    )
    if expense_file:
        st.success(f"✓ {expense_file.name}  ({expense_file.size:,} bytes)")
        _render_file_preview(expense_file)

with col_right:
    grant_file = st.file_uploader(
        "📑 Grant Agreement (PDF or Excel)",
        type=_ACCEPTED_TYPES,
        help="Upload the corresponding federal grant agreement — PDF or Excel (.xlsx / .xls)",
        key="grant_upload",
    )
    if grant_file:
        st.success(f"✓ {grant_file.name}  ({grant_file.size:,} bytes)")
        _render_file_preview(grant_file)

# ── Run audit ─────────────────────────────────────────────────────────────────
st.divider()
run_disabled = not (expense_file and grant_file)
run_btn = st.button(
    "🚀  Run Compliance Audit",
    type="primary",
    disabled=run_disabled,
    use_container_width=True,
    help="Both PDFs must be uploaded before running.",
)

if run_disabled and not (expense_file and grant_file):
    st.info("Upload both PDFs above, then click **Run Compliance Audit**.")

if run_btn and expense_file and grant_file:
    progress = st.progress(0, text="Initialising…")
    status = st.empty()

    def _update(pct: int, msg: str) -> None:
        progress.progress(pct, text=msg)
        status.info(msg)

    try:
        # ── Extract text from uploaded files (PDF or Excel) ──────────────────
        _update(5, "Extracting text from uploaded files…")
        expense_text = extract_text_from_file(
            io.BytesIO(expense_file.getvalue()), expense_file.name
        )
        grant_text = extract_text_from_file(
            io.BytesIO(grant_file.getvalue()), grant_file.name
        )

        if not expense_text.strip():
            st.error(
                "Could not extract text from the expense report. "
                "For PDFs, ensure the file is not scanned/image-only. "
                "For Excel files, ensure the workbook contains data."
            )
            st.stop()
        if not grant_text.strip():
            st.error(
                "Could not extract text from the grant agreement. "
                "For PDFs, ensure the file is not scanned/image-only. "
                "For Excel files, ensure the workbook contains data."
            )
            st.stop()

        # ── Build initial state ───────────────────────────────────────────────
        initial_state: dict = {
            "expense_report_text": expense_text,
            "grant_agreement_text": grant_text,
            "organization_name": org_name or "Unknown Organization",
            "grant_number": grant_number or "Unknown Grant",
            "extracted_line_items": [],
            "extraction_complete": False,
            "compliance_decisions": [],
            "flagged_items": [],
            "total_allowable": 0.0,
            "total_unallowable": 0.0,
            "compliance_check_complete": False,
            "items_pending_human_review": [],
            "human_review_decisions": [],
            "human_review_complete": False,
            "audit_report_markdown": "",
            "report_generation_complete": False,
            "current_agent": "expense_extractor",
            "messages": [],
            "audit_complete": False,
        }

        # ── Agent 1: Expense Extraction ───────────────────────────────────────
        _update(15, "Agent 1: Extracting expense line items (NLP + Ollama)…")
        state = extract_expenses(initial_state)
        n_items = len(state.get("extracted_line_items", []))
        _update(35, f"Agent 1 complete — {n_items} line item(s) extracted.")

        # ── Agent 2: Compliance Check ─────────────────────────────────────────
        _update(40, f"Agent 2: Checking compliance for {n_items} item(s)…")
        state = check_compliance(state)
        _update(65, "Agent 2 complete — compliance decisions ready.")

        # ── HITL ──────────────────────────────────────────────────────────────
        pending = state.get("items_pending_human_review", [])
        if pending:
            _update(68, f"HITL: Auto-reviewing {len(pending)} flagged item(s)…")
            state = human_review_node(state)
            _update(72, "Human review step complete.")

        # ── Agent 3: Report Writing ───────────────────────────────────────────
        _update(75, "Agent 3: Generating audit report…")
        state = write_audit_report(state)
        _update(90, "Report generated — rendering PDF…")

        # ── PDF generation ────────────────────────────────────────────────────
        pdf_bytes = generate_pdf(state.get("audit_report_markdown", ""))
        st.session_state["audit_result"] = state
        st.session_state["pdf_bytes"] = pdf_bytes
        _update(100, "Audit complete!")
        status.success("✅ Audit complete!")

    except Exception as exc:
        st.error(f"Audit failed: {exc}")
        st.exception(exc)

# ── Results display ───────────────────────────────────────────────────────────
result = st.session_state.get("audit_result")

if result:
    st.divider()
    st.subheader("📊 Audit Results")

    # Summary metrics row
    decisions = result.get("compliance_decisions", [])
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Line Items", len(result.get("extracted_line_items", [])))
    m2.metric("Allowable", f"${result.get('total_allowable', 0):,.2f}")
    m3.metric("Unallowable", f"${result.get('total_unallowable', 0):,.2f}")
    m4.metric(
        "Conditionally Allowable",
        sum(1 for d in decisions if d.get("status") == "CONDITIONALLY_ALLOWABLE"),
    )
    m5.metric("Flagged for Review", len(result.get("items_pending_human_review", [])))

    st.divider()

    tab_items, tab_decisions, tab_report, tab_log = st.tabs(
        ["📄 Extracted Line Items", "✅ Compliance Decisions", "📋 Audit Report", "🔄 Workflow Log"]
    )

    # ── Tab 1: Line Items ─────────────────────────────────────────────────────
    with tab_items:
        items = result.get("extracted_line_items", [])
        if items:
            try:
                import pandas as pd
                df = pd.DataFrame(items)
                st.dataframe(df, use_container_width=True, hide_index=True)
            except ImportError:
                for i in items:
                    st.json(i)
        else:
            st.info("No line items were extracted. Check that your expense report PDF contains readable text.")

    # ── Tab 2: Compliance Decisions ───────────────────────────────────────────
    with tab_decisions:
        if decisions:
            _STATUS_ICON = {
                "ALLOWABLE": "✅",
                "UNALLOWABLE": "❌",
                "CONDITIONALLY_ALLOWABLE": "⚠️",
                "REQUIRES_REVIEW": "🔍",
            }
            for d in decisions:
                status_str = d.get("status", "UNKNOWN")
                icon = _STATUS_ICON.get(status_str, "❓")
                conf = d.get("confidence_score")
                conf_label = f" | Confidence: {conf:.0%}" if conf is not None else ""
                label = (
                    f"{icon} #{d.get('line_number', '?')} "
                    f"{d.get('description', '')[:55]}  "
                    f"${d.get('amount', 0):,.2f}  [{status_str}]{conf_label}"
                )
                with st.expander(label):
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**Regulation Cited:** {d.get('regulation_cited', 'N/A')}")
                    c2.markdown(f"**Category:** {d.get('category', 'N/A')}")
                    st.markdown(f"**Reasoning:** {d.get('reasoning', 'N/A')}")
                    if d.get("flagged_reason"):
                        st.warning(f"⚑ Flagged: {d['flagged_reason']}")
                    if d.get("human_review_note"):
                        st.info(f"👤 Human Review: {d['human_review_note']}")
                    if conf is not None:
                        st.caption(f"ML Confidence Score (TF-IDF): {conf:.4f}")
        else:
            st.info("No compliance decisions available.")

    # ── Tab 3: Audit Report ───────────────────────────────────────────────────
    with tab_report:
        report_md = result.get("audit_report_markdown", "")
        if report_md:
            st.markdown(report_md)
            st.divider()
            pdf_bytes = st.session_state.get("pdf_bytes")
            if pdf_bytes:
                gn = result.get("grant_number", "report").replace("/", "-").replace(" ", "_")
                st.download_button(
                    label="⬇️  Download Audit Report (PDF)",
                    data=pdf_bytes,
                    file_name=f"audit_report_{gn}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
        else:
            st.info("Report not yet generated.")

    # ── Tab 4: Workflow Log ───────────────────────────────────────────────────
    with tab_log:
        messages = result.get("messages", [])
        if messages:
            for msg in messages:
                agent = msg.get("agent", "System")
                action = msg.get("action", "")
                msg_status = msg.get("status", "")
                icon = "✅" if msg_status == "complete" else "ℹ️"
                st.info(f"{icon} **{agent}** — {action}")
        else:
            st.info("No workflow messages logged.")
