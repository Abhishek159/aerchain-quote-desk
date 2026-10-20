import io
import json

import pandas as pd
import streamlit as st
from PIL import Image

from core import config, extract, ingest, llm, normalize

STATUS_STYLE = {
    "ok": ("", "Firm"),
    "buyer_override": ("background-color:#e3f0ff", "Buyer override"),
    "assumption": ("background-color:#fff4d6", "Rests on an assumption"),
    "needs_review": ("background-color:#ffe0e0", "Needs review (blocker)"),
    "not_quoted": ("background-color:#f0f0f0;color:#999", "Not quoted"),
    "unresolved": ("background-color:#ffe0e0;color:#a00", "Unresolved"),
    "excluded": ("background-color:#f0f0f0;color:#999;text-decoration:line-through", "Excluded by buyer"),
}
SEV_ICON = {"blocker": "🛑", "warning": "⚠️", "info": "ℹ️"}
QUAL_ICON = {"cleared": "✅ cleared", "failed": "❌ failed", "unverified": "❔ unverified"}


def settings():
    if "settings" not in st.session_state:
        st.session_state.settings = normalize.Settings()
    return st.session_state.settings


def _stamp():
    files = list(config.EXTRACTIONS.glob("V*.json")) + [config.OVERRIDES, config.RFX_FILE]
    return tuple((p.name, p.stat().st_mtime) for p in files if p.exists())


@st.cache_data(show_spinner=False)
def _build(stamp, fx_json, gst, start):
    s = normalize.Settings(fx=json.loads(fx_json), default_gst_pct=gst, contract_start=start)
    R = normalize.build(extract.load_extractions(), s)
    return R, normalize.tables(R)


def result():
    s = settings()
    return _build(_stamp(), json.dumps(s.fx, sort_keys=True), s.default_gst_pct, s.contract_start)


def rfx():
    return normalize.load_rfx()


def money(x, unit=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "-"
    if x < 0:
        return "−" + money(-x, unit)
    if unit:
        return f"₹{x:,.2f}"
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:,.2f} cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:,.1f} lakh"
    return f"₹{x:,.0f}"


def sidebar():
    s = settings()
    with st.sidebar:
        r = rfx()
        st.caption(f"**{r['rfx_id']}**  \n{r['title']}")
        ex = extract.load_extractions()
        st.progress(len(ex) / max(len(ingest.vendor_folders()), 1),
                    text=f"{len(ex)}/{len(ingest.vendor_folders())} vendor responses read")
        with st.expander("Buyer assumptions", expanded=False):
            st.caption("Applied to every number on screen. Changing them recomputes everything.")
            usd = st.number_input("USD → INR", value=float(s.fx["USD"]), step=0.25, format="%.2f")
            gst = st.number_input("Default GST % (if vendor says 'incl.' without a rate)", value=float(s.default_gst_pct), step=1.0)
            start = st.text_input("Contract start (certificates must be valid)", value=s.contract_start)
            if (usd, gst, start) != (s.fx["USD"], s.default_gst_pct, s.contract_start):
                s.fx["USD"], s.default_gst_pct, s.contract_start = usd, gst, start
                st.rerun()
        u = llm.usage_summary()
        cap = f" of ₹{config.BUDGET_INR:g} demo budget" if config.BUDGET_INR else ""
        st.caption(f"AI calls: {u['ok']} · est. spend ₹{u['est_inr']:g}{cap}  \n"
                   f"tokens in {u['in_tokens']:,} · out {u['out_tokens']:,}")
        if not config.GEMINI_API_KEY:
            st.error("GEMINI_API_KEY missing in .env")


def show_source(cell_or_quote_source, folder_name, key=""):
    """Show the evidence for a number: the photo crop, the PDF/Excel/Word text it came from."""
    src = cell_or_quote_source or {}
    if not src:
        st.caption("No source recorded.")
        return
    st.markdown(f"**Source:** `{src.get('file')}` · {src.get('locator', '')}")
    if src.get("verbatim"):
        st.markdown(f"> {src['verbatim']}")
    folder = config.INBOX / folder_name
    _, docs = ingest.load_vendor(folder)
    d = next((x for x in docs if x.file == src.get("file")), None)
    if d is None:
        return
    if d.kind == "image":
        img = Image.open(d.path)
        bb = src.get("bbox")
        if bb and len(bb) == 4:
            W, H = img.size
            y0, x0, y1, x1 = bb
            pad = 40
            box = (max(0, x0 * W / 1000 - pad), max(0, y0 * H / 1000 - pad),
                   min(W, x1 * W / 1000 + pad), min(H, y1 * H / 1000 + pad))
            if box[2] > box[0] and box[3] > box[1]:
                st.image(img.crop(box), caption="Region the reader cited (model-supplied box)")
        with st.expander("Full photo"):
            st.image(img)
    elif d.text:
        loc = (src.get("locator") or "").lower()
        hits = [ln for ln in d.text.splitlines()
                if (loc and loc.split(",")[0].strip() in ln.lower()) or
                (src.get("verbatim") and src["verbatim"][:25].lower() in ln.lower())]
        if hits:
            st.code("\n".join(hits[:6]), language=None, wrap_lines=True)
        with st.expander(f"Full text of {d.file}"):
            st.text(d.text[:12000])
    if d.path and d.kind in ("pdf", "xlsx", "docx"):
        st.download_button(f"Open original ({d.file})", d.path.read_bytes(), file_name=d.file,
                           key=f"dl-{folder_name}-{d.file}-{src.get('locator')}-{key}")


def need_extractions():
    if not extract.load_extractions():
        st.info("No vendor responses have been read yet. Go to **Vendor inbox** and run extraction.")
        st.stop()


def df_download(df, name, label="Download CSV"):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label, buf.getvalue(), file_name=name, mime="text/csv")
