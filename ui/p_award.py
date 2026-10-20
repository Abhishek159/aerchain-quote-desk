import plotly.express as px
import streamlit as st

from core import award, report
from ui import common

common.need_extractions()
R, T = common.result()
V = T["vendors"].set_index("vendor_id")

st.title("Award")
st.caption("Pick the rules; the simulator does the arithmetic. Everything you see here is what goes into the export.")

c1, c2, c3, c4 = st.columns(4)
strategy = c1.selectbox("Strategy", ["cheapest_per_line", "single_vendor"],
                        format_func=lambda s: {"cheapest_per_line": "Cheapest per line (split)", "single_vendor": "Single vendor"}[s])
single = c1.selectbox("Vendor", list(V.index), disabled=strategy != "single_vendor") if strategy == "single_vendor" else None
qual = c2.toggle("Only vendors who cleared questionnaire", value=True)
blk = c2.toggle("Leave out quotes with open blockers", value=True)
cap = c3.slider("Max share per vendor (%)", 0, 100, 0, step=5, help="0 = no cap", disabled=strategy != "cheapest_per_line")
disc = c4.toggle("Apply conditional discounts when the condition is met", value=True)
pool = c4.multiselect("Vendor pool", list(V.index), default=list(V.index))

res = award.simulate(T, strategy=strategy, vendors=pool, require_qualified=qual, exclude_blockers=blk,
                     max_share_pct=cap or None, single_vendor=single, apply_conditional_discounts=disc)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Annual value (net)", common.money(res["total_net"]))
m2.metric("Lines awarded", f"{res['lines_awarded']}/30")
lyv, tyv, gyv = res["last_year_value_same_lines"], res["this_year_net_value_same_lines"], res["this_year_value_same_lines"]
m3.metric("vs last year (same lines, net)", common.money(tyv - lyv), delta=f"{(tyv / lyv - 1) * 100:+.1f}%" if lyv else None,
          delta_color="inverse",
          help=f"After conditional discounts. Before discounts: {common.money(gyv - lyv)} ({(gyv / lyv - 1) * 100:+.1f}%). "
               "New SKUs with no last-year price are excluded from both sides.")
m4.metric("Conditional discounts", common.money(res["conditional_discounts"]))

for c in res["caveats"] + res["discount_notes"]:
    if any(w in c.lower() for w in ("not", "excluded", "left out", "ex-works", "assumption")):
        st.warning(c)
    else:
        st.info(c)
if res["lines_uncovered"]:
    st.error(f"No eligible quote for: {', '.join(res['lines_uncovered'])}. Ask vendors, relax a rule, or source separately.")

a, b = st.columns([3, 2])
a.dataframe(res["rows"], hide_index=True, height=600)
bv = res["by_vendor"]
if len(bv):
    b.plotly_chart(px.pie(bv, names="vendor_name", values="value", title="Share of annual value", hole=0.45), width="stretch")
    b.dataframe(bv.assign(value=bv["value"].map(common.money)), hide_index=True)

st.divider()
x1, x2 = st.columns(2)
if x1.button("Build award pack (Excel)", type="primary"):
    p = report.workbook(T, res, common.settings())
    st.session_state.pack = str(p)
if st.session_state.get("pack"):
    with open(st.session_state.pack, "rb") as fh:
        x1.download_button("⬇️ Download award pack", fh.read(), file_name=st.session_state.pack.split("/")[-1])
    x1.caption("Sheets: summary & caveats, award by line / vendor, full comparison, flags & assumptions, "
               "questionnaire, vendor terms, audit trail.")
if x2.button("Draft recommendation memo"):
    with st.spinner("Writing …"):
        st.session_state.memo = report.memo(T, res)
if st.session_state.get("memo"):
    with st.container(border=True):
        st.markdown(st.session_state.memo)
    st.download_button("⬇️ memo.md", st.session_state.memo, file_name="award_memo.md")
