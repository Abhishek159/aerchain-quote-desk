import pandas as pd
import streamlit as st

from core import evaluate
from ui import common

common.need_extractions()
R, T = common.result()

st.title("Extraction accuracy")
st.caption("The dataset was fabricated from a hidden answer key (data/eval/ground_truth.json) that the app never "
           "reads while working. This page scores the live pipeline - real model reads + normalisation - against it. "
           "The number that matters for trust is *silent errors*: wrong and not flagged.")

s = evaluate.score(R)
if not s:
    st.info("No ground truth file found.")
    st.stop()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Cells correct", f"{s['correct']}/{s['total']}", f"{s['accuracy'] * 100:.1f}%", delta_color="off")
m2.metric("Wrong", s["wrong"])
m3.metric("Wrong but flagged", s["wrong_but_flagged"])
m4.metric("Silent errors", len(s["silent_errors"]), delta_color="inverse")

df = pd.DataFrame(s["cells"])
st.subheader("Misses")
miss = df[df["verdict"] != "correct"]
if miss.empty:
    st.success("Every cell matches the answer key (within 0.5%).")
else:
    st.dataframe(miss, hide_index=True)
st.subheader("Qualification")
st.dataframe(pd.DataFrame(s["qualification"]), hide_index=True)
with st.expander("All cells"):
    st.dataframe(df, hide_index=True)
