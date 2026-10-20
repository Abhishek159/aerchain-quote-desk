import pandas as pd
import streamlit as st

from core import store
from ui import common

common.need_extractions()
R, T = common.result()
rfx = common.rfx()
q, V, L = T["quotes"], T["vendors"].set_index("vendor_id"), T["lines"].set_index("line_id")
vids = sorted(V.index)

st.title("Side-by-side comparison")
st.caption("Every cell: ₹ per piece (or set), ex-GST, delivered Chakan where freight is known. "
           "Colour = how much you can trust it. Pick a cell below to see exactly where the number came from.")

# ---- header strip: vendor health ---------------------------------------------------
cols = st.columns(len(vids))
for c, v in zip(cols, vids):
    vv = V.loc[v]
    sub = q[q["vendor_id"] == v]
    firm = int((sub["status"].isin(["ok", "buyer_override"])).sum())
    with c.container(border=True):
        st.markdown(f"**{v} · {vv['vendor_name'].split(' Pvt')[0].split(' LLP')[0]}**")
        st.caption(common.QUAL_ICON.get(vv["qualification"], vv["qualification"]))
        st.caption(f"{int(vv['lines_quoted'])}/30 priced · {firm} firm")
        ft = vv["freight_text"] if isinstance(vv["freight_text"], str) and vv["freight_text"] else vv["freight_basis"].replace("_", " ")
        st.caption(f"Freight: {ft}")
        tot = sub["annual_value"].sum()
        st.caption(f"Quoted lines: {common.money(tot)}/yr")

view = st.radio("Show", ["Unit price", "Annual value", "vs last year"], horizontal=True)
only_cleared = st.toggle("Only vendors who cleared the questionnaire", value=False)
show_v = [v for v in vids if not only_cleared or V.loc[v, "qualification"] == "cleared"]

# ---- grid ------------------------------------------------------------------------------
val_col = {"Unit price": "comparable_price", "Annual value": "annual_value", "vs last year": "comparable_price"}[view]
grid = q.pivot(index="line_id", columns="vendor_id", values=val_col)[show_v]
status = q.pivot(index="line_id", columns="vendor_id", values="status")[show_v]
if view == "vs last year":
    grid = grid.div(L["last_year_price"], axis=0).sub(1).mul(100)
fmt = {"Unit price": lambda x: "" if pd.isna(x) else f"{x:,.2f}",
       "Annual value": lambda x: "" if pd.isna(x) else f"{x / 1e5:,.2f} L",
       "vs last year": lambda x: "" if pd.isna(x) else f"{x:+.1f}%"}[view]
not_failed = [v for v in show_v if V.loc[v, "qualification"] != "failed"]
best = q[q["vendor_id"].isin(not_failed) & q["status"].isin(["ok", "buyer_override"])]
best = best.loc[best.groupby("line_id")["comparable_price"].idxmin()].set_index("line_id")["vendor_id"] if len(best) else pd.Series(dtype=str)

disp = pd.DataFrame(index=grid.index)
disp["Line"] = [f"{i} · {L.loc[i, 'description'][:38]}" for i in grid.index]
disp["Qty/yr"] = L.loc[grid.index, "annual_qty"].map(lambda x: f"{x:,}")
disp["Last yr ₹"] = L.loc[grid.index, "last_year_price"].map(lambda x: "" if pd.isna(x) else f"{x:,.2f}")
for v in show_v:
    disp[v] = grid[v].map(fmt)
    disp.loc[status[v] == "not_quoted", v] = "—"
    disp.loc[status[v] == "unresolved", v] = "?"


def style(df):
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for v in show_v:
        out[v] = status[v].map(lambda s: common.STATUS_STYLE.get(s, ("", ""))[0])
        for lid in df.index:
            if best.get(lid) == v:
                out.loc[lid, v] = "background-color:#c8ecd0;font-weight:700"
    return out


st.dataframe(disp.style.apply(style, axis=None), height=1090, width="stretch", hide_index=True)
legend = " ".join(f"<span style='{s};padding:2px 8px;border-radius:4px;margin-right:6px'>{t}</span>"
                  for k, (s, t) in common.STATUS_STYLE.items())
st.markdown(legend + " <b style='background-color:#c8ecd0;padding:2px 8px;border-radius:4px'>cheapest firm price</b>", unsafe_allow_html=True)
st.caption("A cheaper number in amber is not the same as a cheaper firm price: it rests on an assumption "
           "(per-kg weight, 'same as last year', unknown freight). Open it below to see which.")

# ---- inspector -------------------------------------------------------------------------
st.divider()
st.subheader("Why this number?")
a, b = st.columns(2)
lid = a.selectbox("Line", list(L.index), format_func=lambda i: f"{i} · {L.loc[i, 'description']}")
vid = b.selectbox("Vendor", vids, format_func=lambda v: f"{v} · {V.loc[v, 'vendor_name']}")
cell = next(c for c in R.cells if c["vendor_id"] == vid and c["line_id"] == lid)
line = L.loc[lid]
left, right = st.columns([3, 2])
with left:
    st.markdown(f"**{lid}** {line['description']} · {line['dimensions_mm']} mm · {line['ply']}-ply · {line['print']}")
    st.markdown(f"Status: **{common.STATUS_STYLE.get(cell['status'], ('', cell['status']))[1]}** · "
                f"comparable: **{common.money(cell['comparable'], unit=True)}** ({cell['comparable_basis'] or '-'})")
    for i, s in enumerate(cell["steps"], 1):
        st.markdown(f"{i}. {s}")
    fl = [f for f in R.flags if f["vendor_id"] == vid and (f["line_id"] == lid or f["line_id"] is None) and f["severity"] != "info"]
    for f in fl:
        st.markdown(f"{common.SEV_ICON[f['severity']]} `{f['code']}` {f['message']}"
                    + (" *(resolved)*" if f["status"] == "resolved" else ""))
with right:
    common.show_source(cell.get("source"), R.vendors[vid]["folder"])
    with st.expander("Correct or exclude this number"):
        newp = st.number_input("Correct price (₹ per unit, ex-GST, before freight)", value=float(cell.get("ex_works") or 0.0),
                               step=0.01, format="%.4f", key=f"np-{vid}-{lid}")
        note = st.text_input("Reason (goes to the audit trail)", key=f"nt-{vid}-{lid}")
        c1, c2, c3 = st.columns(3)
        if c1.button("Save correction", disabled=not note, key=f"sv-{vid}-{lid}"):
            store.save_override("cells", f"{vid}:{lid}", {"price_inr": newp}, note)
            st.cache_data.clear()
            st.rerun()
        if c2.button("Exclude", disabled=not note, key=f"ex-{vid}-{lid}"):
            store.save_override("cells", f"{vid}:{lid}", {"exclude": True}, note)
            st.cache_data.clear()
            st.rerun()
        if c3.button("Clear override", key=f"cl-{vid}-{lid}"):
            store.save_override("cells", f"{vid}:{lid}", None, "cleared")
            st.cache_data.clear()
            st.rerun()

with st.expander("Vendor terms & questionnaire"):
    st.dataframe(T["vendors"], hide_index=True)
    st.dataframe(T["questionnaire"].pivot(index="qid", columns="vendor_id", values="result"))
