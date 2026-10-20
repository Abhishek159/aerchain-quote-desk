import pandas as pd
import streamlit as st

from core import copilot, llm
from ui import common

st.title("Draft the RFx")
st.caption("Talk the RFx into existence. The co-pilot edits a structured draft (right) through tools, so what "
           "goes out stays machine-readable for the comparison later.")

d = copilot.load_draft()
t1, t2, t3 = st.columns(3)
if t1.button("Start blank"):
    copilot.save_draft(dict(copilot.EMPTY_DRAFT, lines=[], questionnaire=[], terms={}, vendors_invited=[]))
    st.session_state.copilot_log = []
    st.rerun()
if t2.button("Open the live demo RFx"):
    copilot.load_published_as_draft()
    st.session_state.copilot_log = []
    st.rerun()
log = st.session_state.setdefault("copilot_log", [])

left, right = st.columns([2, 3])
with left:
    for role, text in log:
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(text)
    if not log:
        st.info("e.g. *\"I need an annual rate contract for corrugated boxes for Chakan - 3, 5 and 7-ply shippers, "
                "some partitions and pads. ISO 9001 is a must and rejection under 1.5%.\"*")
    msg = st.chat_input("Describe what you need …")
    if msg:
        with st.spinner("Updating the draft …"):
            try:
                reply, changes = copilot.chat(log, msg)
            except llm.LLMError as e:
                st.error(str(e))
                st.stop()
        log += [("user", msg), ("model", reply + (f"\n\n*({', '.join(changes)})*" if changes else ""))]
        st.rerun()

with right:
    st.markdown(f"### {d.get('title') or 'Untitled RFx'}")
    st.caption(f"{d.get('rfx_id') or 'no id'} · {d.get('category') or 'no category'} · due {d.get('due_on') or '-'}")
    if d.get("scope"):
        st.markdown(d["scope"])
    st.markdown(f"**Lines ({len(d['lines'])})**")
    if d["lines"]:
        cols = ["line_id", "description", "dimensions_mm", "ply", "print", "uom", "annual_qty", "nominal_weight_kg"]
        ldf = pd.DataFrame(d["lines"])
        st.dataframe(ldf[[c for c in cols if c in ldf.columns]], hide_index=True, height=300)
    st.markdown(f"**Questionnaire ({len(d['questionnaire'])})**")
    for q in d["questionnaire"]:
        st.markdown(f"- `{q['qid']}` {q['text']}" + (f" — *{q.get('criterion')}*" if q.get("criterion") else "")
                    + (" 🔒 knock-out" if q.get("knockout") else ""))
    if d.get("terms"):
        st.markdown("**Terms**")
        st.json(d["terms"], expanded=False)
    st.markdown(f"**Vendors ({len(d.get('vendors_invited', []))})**: " +
                ", ".join(v["name"] for v in d.get("vendors_invited", [])))
    missing = [k for k, ok in [("lines", d["lines"]), ("questionnaire", d["questionnaire"]), ("terms", d.get("terms")),
                               ("vendors", d.get("vendors_invited")), ("RFx id", d.get("rfx_id"))] if not ok]
    if missing:
        st.warning("Before sending: add " + ", ".join(missing))
    if t3.button("Publish & send (stub)", type="primary", disabled=bool(missing)):
        sent = copilot.publish(d)
        st.success(f"Published. {len(sent)} emails written to data/runtime/outbox.")
