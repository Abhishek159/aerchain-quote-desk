import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
RFX_FILE = DATA / "rfx" / "rfx.json"
INBOX = DATA / "inbox"
HISTORY_CSV = DATA / "history" / "po_history_FY2025-26.csv"
GROUND_TRUTH = DATA / "eval" / "ground_truth.json"

# AERCHAIN_RUNTIME lets tests use a separate folder so test data never mixes with real reads.
RUNTIME = Path(os.getenv("AERCHAIN_RUNTIME", DATA / "runtime"))
EXTRACTIONS = RUNTIME / "extractions"
OUTBOX = RUNTIME / "outbox"
EXPORTS = RUNTIME / "exports"
OVERRIDES = RUNTIME / "overrides.json"
AUDIT_LOG = RUNTIME / "audit.jsonl"
LLM_LOG = RUNTIME / "llm_calls.jsonl"
RFX_DRAFT = RUNTIME / "rfx_draft.json"
for p in (EXTRACTIONS, OUTBOX, EXPORTS):
    p.mkdir(parents=True, exist_ok=True)



def setting(name, default=""):
    """.env / environment first, then Streamlit Cloud secrets."""
    v = os.getenv(name)
    if v is None:
        try:
            import streamlit as st
            v = st.secrets.get(name)
        except Exception:  # no secrets file outside Streamlit Cloud
            v = None
    return default if v is None else str(v).strip()


def gemini_key():
    """Read at call time, so a key added in Streamlit Cloud secrets works without a reboot."""
    return setting("GEMINI_API_KEY")


GEMINI_API_KEY = gemini_key()

# Hosted demo protection. DEMO_MODE=1 locks re-reading the original vendors;
# BUDGET_INR stops all model calls once estimated spend reaches it.
def demo_mode():
    return setting("DEMO_MODE", "0") == "1"


def budget_inr():
    return float(setting("BUDGET_INR", "0") or 0)  # 0 = no cap
# Rupees per 1,000 tokens, calibrated from this project's own AI Studio bill
# (thinking tokens are billed as output).
COST_IN_PER_1K = float(setting("COST_IN_PER_1K", "0.05"))
COST_OUT_PER_1K = float(setting("COST_OUT_PER_1K", "0.40"))


def _models(var, default):
    return [m.strip() for m in setting(var, default).split(",") if m.strip()]


# First model is preferred; the rest are fallbacks on rate-limit / outage.
EXTRACT_MODELS = _models("EXTRACT_MODELS", "gemini-3.8-flash,gemini-3.5-flash,gemini-flash-latest")
ANALYST_MODELS = _models("ANALYST_MODELS", "gemini-3.8-flash,gemini-3.5-flash,gemini-flash-latest")

# Buyer-side assumptions. Shown in the UI and editable there, never hidden.
DEFAULT_FX = {"USD": 88.0, "EUR": 102.0, "INR": 1.0}
DEFAULT_GST_PCT = 5.0
CONTRACT_START = "2026-11-01"  # certificates must be valid on this date

# A price this far from the median of the other vendors on the same line is
# more likely a unit / basis error than a real price.
OUTLIER_HIGH = 1.6
OUTLIER_LOW = 0.6
