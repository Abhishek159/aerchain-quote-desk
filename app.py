"""Kill the Quote Spreadsheet - Aerchain take-home.

Run:  uv run streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Quote Desk", page_icon="📦", layout="wide")
st.markdown("""<style>
  .block-container {padding-top: 1.6rem; max-width: 1500px;}
  [data-testid="stMetricValue"] {font-size: 1.5rem;}
</style>""", unsafe_allow_html=True)

from ui import common  # noqa: E402

pages = st.navigation({
    "Source": [
        st.Page("ui/p_copilot.py", title="1 · Draft RFx", icon="✍️"),
        st.Page("ui/p_inbox.py", title="2 · Vendor inbox", icon="📥"),
    ],
    "Evaluate": [
        st.Page("ui/p_compare.py", title="3 · Comparison", icon="📊", default=True),
        st.Page("ui/p_review.py", title="4 · Review & clarify", icon="🔎"),
        st.Page("ui/p_analyst.py", title="5 · Ask the data", icon="💬"),
    ],
    "Decide": [
        st.Page("ui/p_award.py", title="6 · Award", icon="🏁"),
        st.Page("ui/p_accuracy.py", title="Extraction accuracy", icon="🎯"),
    ],
})
common.sidebar()
pages.run()
