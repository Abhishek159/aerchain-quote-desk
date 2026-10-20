import plotly.express as px
import streamlit as st

from core import analyst, llm
from ui import common

common.need_extractions()
R, T = common.result()

st.title("Ask the data")
st.caption("Plain-language questions over the normalised comparison. The model can only answer through "
           "read-only SQL and the award simulator; open *How I got this* under any answer to audit it.")

stamp = tuple(len(v) for v in T.values()) + (T["quotes"]["comparable_price"].sum(),)
if st.session_state.get("analyst_stamp") != stamp:
    st.session_state.analyst = analyst.Session(T)
    st.session_state.analyst_stamp = stamp
    st.session_state.setdefault("analyst_log", [])
sess = st.session_state.analyst
log = st.session_state.setdefault("analyst_log", [])

SUGGEST = [
    "What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?",
    "Which vendor is cheapest overall, and how much of that is real versus assumptions?",
    "Which lines would cost more than last year under the best qualified award? Chart it.",
    "How exposed are we if Maruti's freight turns out to be 4%?",
    "Cap any single vendor at 50% of value - what does it cost us vs the unconstrained split?",
    "Export the qualified split award to Excel.",
]


def render_artifacts(arts):
    for a in arts:
        if a["type"] == "chart":
            df = a["df"]
            kind = a["chart_type"]
            try:
                kw = dict(x=a["x"], y=a["y"], title=a["title"])
                if a.get("color") and a["color"] in df.columns:
                    kw["color"] = a["color"]
                if kind == "pie":
                    fig = px.pie(df, names=a["x"], values=a["y"], title=a["title"])
                elif kind in ("bar", "grouped_bar", "stacked_bar"):
                    fig = px.bar(df, barmode="stack" if kind == "stacked_bar" else "group", **kw)
                elif kind == "line":
                    fig = px.line(df, markers=True, **kw)
                elif kind == "box":
                    fig = px.box(df, **kw)
                else:
                    fig = px.scatter(df, **kw)
                st.plotly_chart(fig, width="stretch")
            except Exception as e:
                st.warning(f"Could not draw chart: {e}")
                st.dataframe(df)
        elif a["type"] == "file":
            with open(a["path"], "rb") as fh:
                st.download_button(f"⬇️ {a['name']}", fh.read(), file_name=a["name"], key=f"f-{a['path']}-{id(a)}")
        elif a["type"] == "award":
            res = a["result"]
            st.markdown(f"**Award scenario** · {common.money(res['total_net'])}/yr net · "
                        f"{res['lines_awarded']} lines awarded"
                        + (f" · uncovered: {', '.join(res['lines_uncovered'])}" if res["lines_uncovered"] else ""))
            st.dataframe(res["by_vendor"], hide_index=True)
    trace = [a for a in arts if a["type"] in ("table", "award", "error", "chart")]
    if trace:
        with st.expander("How I got this"):
            for a in trace:
                if a["type"] in ("table", "chart"):
                    st.markdown(f"**SQL** — {a.get('title') or a.get('purpose', '')}")
                    st.code(a["sql"], language="sql")
                    st.dataframe(a["df"].head(50), hide_index=True)
                elif a["type"] == "award":
                    st.markdown("**simulate_award**")
                    st.json(a["params"])
                    st.dataframe(a["result"]["rows"], hide_index=True)
                    for c in a["result"]["caveats"] + a["result"]["discount_notes"]:
                        st.caption("• " + c)
                else:
                    st.error(f"{a['tool']} failed (the model saw this and retried): {a['error']}")


for turn in log:
    with st.chat_message("user"):
        st.markdown(turn["q"])
    with st.chat_message("assistant"):
        st.markdown(turn["answer"])
        render_artifacts(turn["artifacts"])

if not log:
    st.markdown("**Try:**")
    cols = st.columns(2)
    for i, s in enumerate(SUGGEST):
        if cols[i % 2].button(s, key=f"s{i}", width="stretch"):
            st.session_state.pending = s
            st.rerun()

q = st.chat_input("Ask anything about the quotes …") or st.session_state.pop("pending", None)
if q:
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("Working through the data …"):
            try:
                out = sess.ask(q)
            except llm.LLMError as e:
                st.error(str(e))
                st.stop()
        st.markdown(out["answer"])
        render_artifacts(out["artifacts"])
    log.append({"q": q, **out})
if log and st.button("Clear conversation"):
    st.session_state.analyst_log = []
    st.session_state.analyst = analyst.Session(T)
    st.rerun()
