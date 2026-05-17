"""
End-to-end demo of all three enhancements on a synthetic expense report.
Run: python demo_audit.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# ── Sample data ───────────────────────────────────────────────────────────────

GRANT_TEXT = """
GRANT AGREEMENT — Federal Award #2024-NP-001
Grantee: Community Health Initiative
Total Award: $75,000

Budget Categories:
  Travel: $5,000
  Personnel: $45,000
  Supplies & Equipment: $10,000
  Indirect Costs: $7,500
  Training: $7,500
"""

EXPENSE_REPORT = """Date\tDescription\tAmount\tCategory\tVendor
2024-03-01\tFlight to Washington DC conference\t$450.00\ttravel\tDelta Airlines
2024-03-02\tHotel — 3 nights\t$390.00\ttravel\tMarriott
2024-03-03\tRegistration fee — Annual Nonprofit Summit\t$275.00\ttraining\tNational Council
2024-03-04\tOffice supplies — paper, toner, folders\t$87.50\tsupplies\tStaples
2024-03-05\tBeer and wine reception for board dinner\t$320.00\tfood\tLocal Caterer
2024-03-06\tFlight to Washington DC conference\t$450.00\ttravel\tDelta Airlines
2024-03-07\tPrivate jet charter to NYC\t$14,500.00\ttravel\tJetBlue Charter
2024-03-08\tLobbyist consulting fee — legislative session\t$2,500.00\tprofessional\tDC Advocacy Group
2024-03-09\tFirst-class airfare to Los Angeles\t$2,100.00\ttravel\tUnited Airlines
2024-03-10\tPersonal vacation — family trip to Miami\t$1,800.00\tother\tPersonal
"""

# ── Enhancement 1: NLP Pipeline ───────────────────────────────────────────────

print("=" * 70)
print("ENHANCEMENT 1 — NLP Expense Extraction Pipeline")
print("=" * 70)

from tools.nlp_utils import (
    detect_report_format,
    parse_tabular_expenses,
    enrich_line_items,
    flag_duplicate_items,
)

fmt = detect_report_format(EXPENSE_REPORT)
print(f"\nDetected format: {fmt.upper()}")

items = parse_tabular_expenses(EXPENSE_REPORT)
print(f"Directly extracted {len(items)} line items (no LLM needed)\n")

items = enrich_line_items(items)
items = flag_duplicate_items(items)

duplicates = [i for i in items if i.get("possible_duplicate")]
print(f"Duplicate detection: {len(duplicates)} flagged")
for d in duplicates:
    print(f"  [DUP] Line {d.get('line_number','?')}: {d['description'][:50]}  ${d['amount']:.2f}")

print("\nExtracted line items:")
print(f"  {'#':<3} {'Description':<42} {'Amount':>10}  {'Category':<12}  Flags")
print(f"  {'-'*3} {'-'*42} {'-'*10}  {'-'*12}  {'-'*20}")
for item in items:
    flags = []
    if item.get("possible_duplicate"):
        flags.append("DUPLICATE?")
    print(f"  {item.get('line_number','?'):<3} {item['description'][:42]:<42} ${item['amount']:>9.2f}  {item.get('category',''):<12}  {', '.join(flags)}")

# ── Enhancement 2a: Amount Anomaly Detection ──────────────────────────────────

print("\n" + "=" * 70)
print("ENHANCEMENT 2a — Amount Anomaly Detection (Modified Z-Score)")
print("=" * 70)

from tools.ml_cross_checker import detect_amount_anomalies, prescreen_unallowable, cross_check_budget

items_with_anomalies = detect_amount_anomalies(list(items))
anomalies = [i for i in items_with_anomalies if i.get("amount_anomaly")]
print(f"\nAnomalies detected: {len(anomalies)}")
for a in anomalies:
    print(f"  [!] {a['description'][:45]:<45} ${a['amount']:>10.2f}  Z={a.get('amount_z_score', 0):.1f}")

# ── Enhancement 2b: Per-Se Unallowable Pre-Screening ─────────────────────────

print("\n" + "=" * 70)
print("ENHANCEMENT 2b — Per-Se Unallowable Pre-Screening (Rule-Based)")
print("=" * 70)

print(f"\n{'Description':<45} {'Result':<22}  Regulation")
print(f"{'-'*45} {'-'*22}  {'-'*20}")
for item in items:
    r = prescreen_unallowable(item["description"], item["amount"])
    if r["prescreened"]:
        if r["unallowable"]:
            result = "UNALLOWABLE"
        else:
            result = "COND. ALLOWABLE"
        print(f"  {item['description'][:43]:<43} {result:<22}  {r['regulation']}")

# ── Enhancement 2c: Budget Cross-Check ───────────────────────────────────────

print("\n" + "=" * 70)
print("ENHANCEMENT 2c — Budget Cross-Check vs Grant Agreement")
print("=" * 70)

from tools.nlp_utils import extract_grant_budget

grant_budget = extract_grant_budget(GRANT_TEXT)
print(f"\nExtracted budget limits: {grant_budget}")

budget_analysis = cross_check_budget(items, grant_budget)
print(f"\n{'Category':<14} {'Spent':>10}  {'Budget':>10}  {'%Used':>7}  Status")
print(f"{'-'*14} {'-'*10}  {'-'*10}  {'-'*7}  {'-'*10}")
for cat, info in sorted(budget_analysis.items()):
    pct = f"{info['pct_used']:.1f}%" if info["pct_used"] is not None else "  N/A"
    budget_str = f"${info['budget']:,.2f}" if info["budget"] else "no limit"
    status = "EXCEEDED" if info["exceeded"] else ("  OK" if info["budget"] else "  N/A")
    print(f"  {cat:<12}  ${info['spent']:>9,.2f}  {budget_str:>10}  {pct:>7}  {status}")

print("\n" + "=" * 70)
print("Demo complete — all three enhancements operational")
print("=" * 70)
