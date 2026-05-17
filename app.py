"""
Streamlit UI — Nonprofit Federal Grant Compliance Auditor
Two-phase audit flow:
  Phase 1 — LangGraph streams extract → compliance, then pauses at interrupt_before human_review.
  Phase 2 — Auditor submits HITL decisions; graph resumes human_review → report.
Falls back to direct agent calls if LangGraph/MemorySaver is unavailable.
"""
import io
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from tools.pdf_tools import extract_text_from_pdf, extract_text_from_file
from tools.formatting_tools import generate_pdf
from agents.expense_extractor import extract_expenses
from agents.compliance_checker import check_compliance
from agents.report_writer import write_audit_report
from agents.supervisor import run_audit
from graph.hitl_handler import human_review_node
from graph.multi_agent_graph import build_langgraph, run_graph
from vectorstores.cfr200_store import (
    get_store_version,
    reindex as cfr200_reindex,
    check_ecfr_update,
    reindex_from_ecfr,
)
from rag_layer.entity_mapper import create_session as _em_create, complete_session as _em_complete, list_sessions as _em_list
from rag_layer.pseudonymizer import pseudonymize, redaction_summary
from rag_layer.retention_policy import run_all as run_retention
from rag_layer.access_control import require_auth, logout, current_role, current_user, has_permission
from tools.vectorstore_maintenance import full_maintenance_report
from tools.visualization_tools import (
    compliance_breakdown_chart,
    expense_by_category_chart,
    confidence_distribution_chart,
    allowable_vs_unallowable_bar,
    budget_vs_actuals_chart,
    render_chart,
)
from tools.nlp_utils import extract_grant_budget
from tools.excel_report_formatter import generate_excel_report

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nonprofit Compliance Auditor",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
for _key, _val in {
    "audit_phase": "idle",   # idle | hitl_pending | complete
    "graph_obj": None,       # compiled LangGraph (kept across reruns)
    "graph_config": None,    # {configurable: {thread_id: ...}}
    "pre_hitl_state": None,  # AuditState snapshot at interrupt point
    "audit_result": None,
    "pdf_bytes": None,
    "auth_role": None,
    "auth_user": None,
    "audit_session_id": None,
    "pii_redaction_summary": None,
}.items():
    if _key not in st.session_state:
        st.session_state[_key] = _val

# ── Authentication gate ───────────────────────────────────────────────────────
if not require_auth(st.session_state):
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📋 Nonprofit Federal Grant Compliance Auditor")
st.markdown(
    "Automatically audit every expense line item against **2 CFR 200 (Uniform Guidance)** "
    "and your grant agreement. Powered by **LangChain + Ollama (llama3.2)** — 100% local."
)
st.divider()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # User badge + logout
    _role = current_role(st.session_state)
    _user = current_user(st.session_state)
    st.caption(f"Signed in as **{_user}** ({_role})")
    if st.button("Sign Out", use_container_width=True):
        logout(st.session_state)
        st.rerun()
    st.divider()
    st.header("⚙️ Organization Details")
    org_name = st.text_input(
        "Organization Name", placeholder="e.g. Community Impact Org", key="org_name"
    )
    grant_number = st.text_input(
        "Grant Number", placeholder="e.g. 2024-HHS-001", key="grant_number"
    )
    st.divider()
    st.markdown("**Workflow Architecture**")

    # Highlight the HITL node while awaiting review
    _hitl_active = st.session_state.get("audit_phase") == "hitl_pending"
    _hitl_extra = (
        "border:2px solid #f59e0b; box-shadow:0 0 10px #f59e0b66;"
        if _hitl_active else ""
    )

    st.markdown(f"""
<div style="font-family:sans-serif; font-size:12px; padding:4px 0;">

  <div style="
      background:linear-gradient(135deg,#1e3a5f,#2c5282);
      color:white; border-radius:10px; padding:9px 12px;
      text-align:center; font-weight:700; font-size:13px;
      box-shadow:0 2px 6px rgba(0,0,0,0.25); letter-spacing:.4px;">
    🎯 Supervisor
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="background:#eff6ff; border-left:4px solid #3b82f6;
      border-radius:6px; padding:7px 11px; margin-bottom:3px;">
    <span style="color:#1d4ed8;font-weight:700;">① Expense Extractor</span><br>
    <span style="color:#475569;">NLP pre-analysis + Ollama</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="background:#f0fdf4; border-left:4px solid #22c55e;
      border-radius:6px; padding:7px 11px; margin-bottom:3px;">
    <span style="color:#15803d;font-weight:700;">② Compliance Checker</span><br>
    <span style="color:#475569;">2 CFR 200 RAG + TF-IDF</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="background:#fffbeb; border-left:4px solid #f59e0b;
      border-radius:6px; padding:7px 11px; margin-bottom:3px; {_hitl_extra}">
    <span style="color:#b45309;font-weight:700;">⚠ HITL Human Review</span><br>
    <span style="color:#475569;">Flagged &amp; low-confidence items</span>
  </div>

  <div style="text-align:center;color:#94a3b8;font-size:20px;line-height:1.4;">↓</div>

  <div style="background:#fdf4ff; border-left:4px solid #a855f7;
      border-radius:6px; padding:7px 11px;">
    <span style="color:#7e22ce;font-weight:700;">③ Report Writer</span><br>
    <span style="color:#475569;">Markdown → PDF audit report</span>
  </div>

</div>
""", unsafe_allow_html=True)
    st.divider()

    # CFR200 regulatory knowledge base controls
    st.markdown("**2 CFR 200 Knowledge Base**")
    _cfr_version = get_store_version()
    if _cfr_version:
        _origin = "eCFR live" if str(_cfr_version).startswith("ecfr-") else "local PDF"
        st.caption(f"Version: `{_cfr_version}` ({_origin})")
    else:
        st.caption("Index: not yet loaded")

    # Show cached eCFR update status
    if "ecfr_update_status" not in st.session_state:
        st.session_state["ecfr_update_status"] = None
    _ecfr_status = st.session_state.get("ecfr_update_status")
    if _ecfr_status and _ecfr_status.get("update_available"):
        st.warning(f"eCFR update available: `{_ecfr_status['latest_ecfr_date']}`")

    with st.expander("Update regulatory index"):
        st.markdown("**Live sync from eCFR** (requires internet)")
        _col1, _col2 = st.columns(2)
        with _col1:
            if st.button("Check for Updates", use_container_width=True):
                with st.spinner("Checking eCFR…"):
                    try:
                        _status = check_ecfr_update()
                        st.session_state["ecfr_update_status"] = _status
                        if _status["update_available"]:
                            st.warning(f"Update available: `{_status['latest_ecfr_date']}`")
                        elif _status["latest_ecfr_date"]:
                            st.success(f"Up to date (`{_status['latest_ecfr_date']}`)")
                        else:
                            st.error("Could not reach eCFR — check network")
                    except Exception as _e:
                        st.error(f"Check failed: {_e}")
        with _col2:
            if st.button("Sync from eCFR", use_container_width=True):
                with st.spinner("Fetching 2 CFR Part 200 from eCFR…"):
                    try:
                        reindex_from_ecfr()
                        st.session_state["ecfr_update_status"] = None
                        st.success(f"Synced — version: `{get_store_version()}`")
                    except Exception as _e:
                        st.error(f"Sync failed: {_e}")

        st.divider()
        st.markdown("**Local PDF reindex** — drop updated PDFs into `data/cfr200_docs/`")
        if st.button("Reindex from local PDFs", use_container_width=True):
            with st.spinner("Rebuilding 2 CFR 200 vector index…"):
                try:
                    cfr200_reindex()
                    st.success(f"Reindexed — new version: `{get_store_version()}`")
                except Exception as _e:
                    st.error(f"Reindex failed: {_e}")

    st.divider()

    # Admin-only panel
    if has_permission(_role or "", "admin_panel"):
        with st.expander("🔐 Admin Panel"):
            st.markdown("**Vector Store Health**")
            if st.button("Run Maintenance Check", use_container_width=True):
                with st.spinner("Inspecting vector stores…"):
                    report = full_maintenance_report()
                cfr = report["cfr200"]
                st.caption(
                    f"CFR200 — version: `{cfr.get('version','?')}` | "
                    f"docs: `{cfr.get('doc_count','?')}` | "
                    f"latency: `{cfr.get('latency_ms','?')} ms` | "
                    f"{'✅ healthy' if cfr.get('healthy') else '⚠️ unavailable'}"
                )
                gs = report["grant_stores"]
                st.caption(
                    f"Grant stores cached: `{gs.get('store_count',0)}` | "
                    f"total size: `{gs.get('total_size_mb',0):.1f} MB`"
                )
            st.divider()
            st.markdown("**Data Retention Policy**")
            s_days = st.number_input("Session retention (days)", value=365, min_value=1, key="ret_session_days")
            v_days = st.number_input("Store retention (days)", value=90, min_value=1, key="ret_store_days")
            if st.button("Run Retention Sweep", use_container_width=True):
                with st.spinner("Running retention sweep…"):
                    summary = run_retention(session_retention_days=int(s_days), store_retention_days=int(v_days))
                st.success(
                    f"Purged {summary['sessions_deleted']} session(s) and "
                    f"{summary['stores_removed']} store(s)."
                )

    st.divider()
    st.caption("2026 IRS / GAAP standards | SHA-256 ledger integrity")

# ── File preview helper ───────────────────────────────────────────────────────
def _render_file_preview(uploaded_file) -> None:
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
                    st.text_area("", preview, height=220, disabled=True,
                                 label_visibility="collapsed")
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

# ── Run audit button ──────────────────────────────────────────────────────────
st.divider()
run_disabled = not (expense_file and grant_file)
run_btn = st.button(
    "🚀  Run Compliance Audit",
    type="primary",
    disabled=run_disabled,
    use_container_width=True,
    help="Both files must be uploaded before running.",
)

if run_disabled and not (expense_file and grant_file):
    st.info("Upload both files above, then click **Run Compliance Audit**.")

# ── Phase 1: extract + compliance (LangGraph pauses at human_review) ──────────
if run_btn and expense_file and grant_file:
    for k in ("audit_phase", "graph_obj", "graph_config", "pre_hitl_state",
               "audit_result", "pdf_bytes"):
        st.session_state[k] = None
    st.session_state["audit_phase"] = "idle"

    progress = st.progress(0, text="Initialising…")
    status = st.empty()

    def _update(pct: int, msg: str) -> None:
        progress.progress(pct, text=msg)
        status.info(msg)

    try:
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

        # Pseudonymize PII before any text reaches the LLM
        _update(8, "Applying PII pseudonymization…")
        expense_text, _exp_counts = pseudonymize(expense_text)
        grant_text, _grant_counts = pseudonymize(grant_text)
        _all_counts = {k: _exp_counts.get(k, 0) + _grant_counts.get(k, 0)
                       for k in set(_exp_counts) | set(_grant_counts)}
        st.session_state["pii_redaction_summary"] = redaction_summary(_all_counts)

        # Open a new audit session record (stores only SHA-256 hashes)
        _session_id = _em_create(
            organization=org_name or "Unknown Organization",
            grant_number=grant_number or "Unknown Grant",
            expense_text=expense_text,
            grant_text=grant_text,
        )
        st.session_state["audit_session_id"] = _session_id

        _grant_budget = extract_grant_budget(grant_text)

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
            "grant_budget": _grant_budget,
            "current_agent": "expense_extractor",
            "messages": [],
            "audit_complete": False,
        }

        _update(10, "Building LangGraph audit pipeline…")
        compiled = build_langgraph()

        if compiled is not None:
            # ── LangGraph path ────────────────────────────────────────────────
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            _update(15, "Agent 1: Extracting expense line items (NLP + Ollama)…")

            _NODE_PROGRESS = {
                "extract":    (35, "Agent 1 complete — expense line items extracted."),
                "compliance": (65, "Agent 2 complete — compliance decisions ready."),
            }
            for event in compiled.stream(initial_state, config, stream_mode="updates"):
                for node_name in event:
                    if node_name in _NODE_PROGRESS:
                        pct, msg = _NODE_PROGRESS[node_name]
                        _update(pct, msg)

            snapshot = compiled.get_state(config)
            pending = snapshot.values.get("items_pending_human_review", [])

            if snapshot.next and "human_review" in snapshot.next:
                # Graph paused at interrupt_before human_review
                _update(68, f"{len(pending)} item(s) flagged — awaiting your review below.")
                status.warning(
                    f"⚠️ **{len(pending)} item(s) require your review.** "
                    "Complete the form below, then click Submit to generate the report."
                )
                st.session_state.update({
                    "audit_phase": "hitl_pending",
                    "graph_obj": compiled,
                    "graph_config": config,
                    "pre_hitl_state": dict(snapshot.values),
                })
                st.rerun()
            else:
                # No items flagged — graph completed without HITL
                final_state = dict(snapshot.values)
                _update(90, "Generating PDF…")
                pdf_bytes = generate_pdf(final_state.get("audit_report_markdown", ""))
                _em_complete(
                    _session_id,
                    item_count=len(final_state.get("extracted_line_items", [])),
                    allowable=final_state.get("total_allowable", 0.0),
                    unallowable=final_state.get("total_unallowable", 0.0),
                )
                st.session_state.update({
                    "audit_result": final_state,
                    "pdf_bytes": pdf_bytes,
                    "audit_phase": "complete",
                })
                _update(100, "Audit complete!")
                status.success("✅ Audit complete!")

        else:
            # ── Direct-call fallback (routed through Supervisor) ──────────────
            _update(15, "Supervisor: orchestrating audit pipeline…")
            state = run_audit(initial_state)
            n_items = len(state.get("extracted_line_items", []))
            _update(90, f"Supervisor complete — {n_items} item(s) audited. Rendering PDF…")

            pdf_bytes = generate_pdf(state.get("audit_report_markdown", ""))
            _em_complete(
                _session_id,
                item_count=len(state.get("extracted_line_items", [])),
                allowable=state.get("total_allowable", 0.0),
                unallowable=state.get("total_unallowable", 0.0),
            )
            st.session_state.update({
                "audit_result": state,
                "pdf_bytes": pdf_bytes,
                "audit_phase": "complete",
            })
            _update(100, "Audit complete!")
            status.success("✅ Audit complete!")

    except Exception as exc:
        st.error(f"Audit failed: {exc}")
        st.exception(exc)

# ── Phase 2: HITL review form ─────────────────────────────────────────────────
if st.session_state.get("audit_phase") == "hitl_pending":
    from datetime import datetime as _dt

    pre_state = st.session_state.get("pre_hitl_state", {})
    pending = pre_state.get("items_pending_human_review", [])

    st.divider()
    st.subheader(f"👤 Human Review Required — {len(pending)} item(s) flagged")
    st.info(
        "The compliance checker flagged the items below (low ML confidence or ambiguous regulation). "
        "Review each one and submit your decision — the audit report will be generated immediately after."
    )

    _DECISION_OPTS = ["APPROVED", "CONDITIONALLY_APPROVED", "REJECTED"]

    collected: dict = {}
    with st.form("hitl_review_form"):
        for item in pending:
            ln = item.get("line_number", "?")
            desc = item.get("description", "")
            amt = item.get("amount", 0.0)
            conf = item.get("confidence_score")

            with st.expander(
                f"#{ln} — {desc[:65]} — ${amt:,.2f}", expanded=True
            ):
                c1, c2, c3 = st.columns(3)
                c1.caption(f"**Category:** {item.get('category', 'N/A')}")
                c2.caption(f"**Vendor:** {item.get('vendor', 'N/A')}")
                c3.caption(
                    f"**ML Confidence:** {conf:.0%}" if conf is not None
                    else "**ML Confidence:** N/A"
                )
                st.caption(f"**Regulation cited:** {item.get('regulation_cited', 'N/A')}")
                st.caption(f"**Checker reasoning:** {item.get('reasoning', 'N/A')}")
                if item.get("flagged_reason"):
                    st.warning(f"⚑ {item['flagged_reason']}")

                d_col, n_col = st.columns([1, 2])
                decision = d_col.selectbox(
                    "Your Decision", _DECISION_OPTS, key=f"hitl_decision_{ln}"
                )
                note = n_col.text_input(
                    "Reviewer Note",
                    placeholder="Briefly explain your decision…",
                    key=f"hitl_note_{ln}",
                )
                collected[ln] = {"item": item, "decision": decision, "note": note}

        submitted = st.form_submit_button(
            "✅  Submit Review & Generate Report",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        human_decisions = [
            {
                **d["item"],
                "human_decision": d["decision"],
                "human_review_note": d["note"]
                    or f"Reviewed by auditor on {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "reviewed_at": _dt.now().isoformat(),
            }
            for d in collected.values()
        ]

        compiled = st.session_state["graph_obj"]
        config = st.session_state["graph_config"]

        with st.spinner("Resuming audit after human review…"):
            compiled.update_state(config, {"human_review_decisions": human_decisions})

            for _event in compiled.stream(None, config, stream_mode="updates"):
                pass

            final_state = dict(compiled.get_state(config).values)
            pdf_bytes = generate_pdf(final_state.get("audit_report_markdown", ""))
            _sid = st.session_state.get("audit_session_id")
            if _sid:
                _em_complete(
                    _sid,
                    item_count=len(final_state.get("extracted_line_items", [])),
                    allowable=final_state.get("total_allowable", 0.0),
                    unallowable=final_state.get("total_unallowable", 0.0),
                )
            st.session_state.update({
                "audit_result": final_state,
                "pdf_bytes": pdf_bytes,
                "audit_phase": "complete",
            })
        st.rerun()

# ── Results display ───────────────────────────────────────────────────────────
result = st.session_state.get("audit_result")

if result:
    st.divider()
    st.subheader("📊 Audit Results")

    decisions = result.get("compliance_decisions", [])
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Line Items", len(result.get("extracted_line_items", [])))
    m2.metric("Allowable", f"${result.get('total_allowable', 0):,.2f}")
    m3.metric("Unallowable", f"${result.get('total_unallowable', 0):,.2f}")
    m4.metric(
        "Conditionally Allowable",
        sum(1 for d in decisions if d.get("status") == "CONDITIONALLY_ALLOWABLE"),
    )
    m5.metric("Human Reviewed", len(result.get("human_review_decisions", [])))

    st.divider()

    # PII redaction notice
    _pii_note = st.session_state.get("pii_redaction_summary")
    if _pii_note:
        st.info(f"🔒 {_pii_note} — no raw PII was sent to the LLM.")

    _tabs_labels = ["📄 Extracted Line Items", "✅ Compliance Decisions", "📋 Audit Report", "📈 Visualizations", "🔄 Workflow Log"]
    _show_admin_log = has_permission(current_role(st.session_state) or "", "view_log")
    if _show_admin_log:
        _tabs_labels.append("📊 Audit Log")
    _tabs = st.tabs(_tabs_labels)
    tab_items, tab_decisions, tab_report, tab_viz, tab_log = _tabs[:5]

    with tab_items:
        items = result.get("extracted_line_items", [])
        if items:
            try:
                import pandas as pd
                st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
            except ImportError:
                for i in items:
                    st.json(i)
        else:
            st.info("No line items were extracted.")

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

    with tab_report:
        report_md = result.get("audit_report_markdown", "")
        if report_md:
            st.markdown(report_md)
            st.divider()
            pdf_bytes = st.session_state.get("pdf_bytes")
            if pdf_bytes:
                gn = result.get("grant_number", "report").replace("/", "-").replace(" ", "_")
                dl_col1, dl_col2 = st.columns(2)
                dl_col1.download_button(
                    label="⬇️  Download Audit Report (PDF)",
                    data=pdf_bytes,
                    file_name=f"audit_report_{gn}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
                try:
                    _xlsx_bytes = generate_excel_report(result)
                    dl_col2.download_button(
                        label="⬇️  Download Audit Report (Excel)",
                        data=_xlsx_bytes,
                        file_name=f"audit_report_{gn}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except Exception as _xe:
                    dl_col2.warning(f"Excel export unavailable: {_xe}")
        else:
            st.info("Report not yet generated.")

    with tab_viz:
        st.subheader("Compliance Visualizations")
        _decisions = result.get("compliance_decisions", [])
        _items     = result.get("extracted_line_items", [])
        _allowable    = result.get("total_allowable", 0.0)
        _unallowable  = result.get("total_unallowable", 0.0)
        _conditional  = sum(
            d.get("amount", 0) for d in _decisions
            if d.get("status") == "CONDITIONALLY_ALLOWABLE"
        )

        vc1, vc2 = st.columns(2)
        with vc1:
            render_chart(
                compliance_breakdown_chart(_decisions),
                "Compliance breakdown chart requires plotly — pip install plotly",
            )
        with vc2:
            render_chart(
                allowable_vs_unallowable_bar(_allowable, _unallowable, _conditional),
                "Dollar totals chart requires plotly — pip install plotly",
            )

        render_chart(
            expense_by_category_chart(_items),
            "Category chart requires plotly — pip install plotly",
        )
        render_chart(
            confidence_distribution_chart(_decisions),
            "Confidence chart requires plotly — pip install plotly",
        )
        _grant_budget_result = result.get("grant_budget", {})
        if _grant_budget_result:
            render_chart(
                budget_vs_actuals_chart(_decisions, _grant_budget_result),
                "Budget vs actuals chart requires plotly — pip install plotly",
            )
        else:
            st.info(
                "No budget categories were detected in the grant agreement. "
                "The budget vs actuals chart will appear once a grant with "
                "explicit budget line items is uploaded."
            )

    with tab_log:
        messages = result.get("messages", [])
        if messages:
            for msg in messages:
                icon = "✅" if msg.get("status") == "complete" else "ℹ️"
                st.info(f"{icon} **{msg.get('agent', 'System')}** — {msg.get('action', '')}")
        else:
            st.info("No workflow messages logged.")

    if _show_admin_log:
        with _tabs[5]:
            st.subheader("Audit Session Log")
            st.caption("SHA-256 hashes only — no raw document text is stored.")

            # Filter controls
            _fc1, _fc2, _fc3, _fc4 = st.columns([2, 1, 1, 1])
            _log_search = _fc1.text_input(
                "Search org / grant", placeholder="e.g. Community Impact", key="log_search"
            )
            _log_status = _fc2.selectbox(
                "Status", ["(all)", "complete", "started"], key="log_status"
            )
            _log_from = _fc3.date_input("From date", value=None, key="log_from")
            _log_to   = _fc4.date_input("To date",   value=None, key="log_to")

            try:
                import pandas as pd
                sessions = _em_list(
                    limit=200,
                    search=_log_search or None,
                    status_filter=None if _log_status == "(all)" else _log_status,
                    date_from=str(_log_from) if _log_from else None,
                    date_to=str(_log_to)   if _log_to   else None,
                )
                if sessions:
                    st.dataframe(pd.DataFrame(sessions), use_container_width=True, hide_index=True)
                else:
                    st.info("No audit sessions match the current filters.")
            except Exception as _e:
                st.warning(f"Could not load audit log: {_e}")
