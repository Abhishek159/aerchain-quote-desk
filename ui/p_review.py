import streamlit as st

from core import clarify, store
from ui import common

common.need_extractions()
R, T = common.result()
rfx = common.rfx()
F = T["flags"]

st.title("Review & clarify")
open_ = F[F["status"] == "open"]
b, w = (open_["severity"] == "blocker").sum(), (open_["severity"] == "warning").sum()
m1, m2, m3 = st.columns(3)
m1.metric("Open blockers", int(b), help="Numbers you should not award on until someone looks")
m2.metric("Open warnings", int(w), help="Usable, but resting on an assumption")
m3.metric("Resolved by buyer", int((F["status"] == "resolved").sum()))

tab_review, tab_ask = st.tabs(["Review queue", "Ask vendors"])

with tab_review:
    c1, c2, c3 = st.columns(3)
    sev = c1.multiselect("Severity", ["blocker", "warning", "info"], default=["blocker", "warning"])
    vend = c2.multiselect("Vendor", sorted(F["vendor_id"].unique()), default=sorted(F["vendor_id"].unique()))
    show_resolved = c3.toggle("Show resolved", value=False)
    view = F[F["severity"].isin(sev) & F["vendor_id"].isin(vend)]
    if not show_resolved:
        view = view[view["status"] == "open"]
    st.caption(f"{len(view)} item(s). Blockers first.")
    for f in view.head(150).to_dict("records"):
        f["line_id"] = f["line_id"] if isinstance(f["line_id"], str) else None  # pandas turns None into NaN
        title = f"{common.SEV_ICON[f['severity']]} {f['vendor_id']} · {f['line_id'] or 'vendor-level'} · {f['code']} — {f['message'][:110]}"
        with st.expander(title, expanded=False):
            st.markdown(f["message"])
            if f["line_id"]:
                cell = next(c for c in R.cells if c["vendor_id"] == f["vendor_id"] and c["line_id"] == f["line_id"])
                st.markdown("**How the number was built:**  \n" + "  \n".join(f"{i}. {s}" for i, s in enumerate(cell["steps"], 1)))
                common.show_source(cell.get("source"), R.vendors[f["vendor_id"]]["folder"], key=f["flag_id"])
            if f["status"] == "resolved":
                st.info(f"Resolved: {f['resolution_note']}")
                if st.button("Re-open", key=f"ro-{f['flag_id']}"):
                    store.save_override("flags", f["flag_id"], None, "re-opened")
                    st.cache_data.clear()
                    st.rerun()
            else:
                note = st.text_input("Decision note (required, goes to audit trail)", key=f"n-{f['flag_id']}",
                                     placeholder="e.g. Checked the photo myself - 23.9 is correct")
                if st.button("Accept / mark reviewed", key=f"a-{f['flag_id']}", disabled=not note):
                    store.save_override("flags", f["flag_id"], {"resolution": "accepted"}, note)
                    st.cache_data.clear()
                    st.rerun()
                if f["line_id"]:
                    st.caption("To correct or exclude the number itself, use *Why this number?* on the Comparison page.")

with tab_ask:
    st.caption("Questions are generated from open flags by code (nothing missed, nothing invented); "
               "the model only writes the email. Sending is stubbed to data/runtime/outbox.")
    vid = st.selectbox("Vendor", sorted(R.vendors), format_func=lambda v: f"{v} · {R.vendors[v]['vendor_name']}")
    qs = clarify.questions_for(vid, R, rfx)
    if not qs:
        st.success("Nothing to ask this vendor.")
    else:
        st.markdown(f"**{len(qs)} open question(s):**")
        for i, x in enumerate(qs, 1):
            st.markdown(f"{i}. {x['text']}")
        key = f"mail-{vid}"
        if st.button("Draft email", type="primary"):
            with st.spinner("Drafting …"):
                st.session_state[key] = clarify.draft_email(vid, R, rfx)
        if st.session_state.get(key):
            e = st.session_state[key]
            subj = st.text_input("Subject", e["subject"])
            body = st.text_area("Body", e["body"], height=380)
            if st.button("Send (stub → outbox)"):
                name = clarify.send({**e, "subject": subj, "body": body})
                st.success(f"Written to outbox as {name}")
