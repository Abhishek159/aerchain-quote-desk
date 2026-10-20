from datetime import datetime

import streamlit as st
from PIL import Image

from core import config, extract, ingest, llm, store
from ui import common

st.title("Vendor inbox")
st.caption("Vendors replied however they liked. Nothing here was re-typed. Each response is read by the model "
           "exactly as received; photos are read twice, independently.")

folders = ingest.vendor_folders()
ex = extract.load_extractions()


def can_read(f):
    """In the hosted demo the original five are already read; only new or edited responses cost credit."""
    return not config.demo_mode() or ingest.user_changed(f) or ingest.vendor_id(f) not in ex


def stale(f):
    """Never read, or files changed after the last read."""
    exf = config.EXTRACTIONS / f"{ingest.vendor_id(f)}.json"
    if not exf.exists():
        return True
    return max(p.stat().st_mtime for p in f.iterdir()) > exf.stat().st_mtime


def read(f):
    with st.spinner(f"Reading {f.name} … (about a minute)"):
        try:
            extract.extract_vendor(f)
            store.audit("extracted", {"vendor": f.name}, "system")
            st.cache_data.clear()
            return True
        except llm.LLMError as e:
            st.error(f"{f.name}: {e}")
            return False


# ---- add a new response -----------------------------------------------------------
with st.expander("➕ Add a vendor response (any format)", expanded=False):
    st.caption("Paste the email text and/or attach whatever the vendor sent: Excel, PDF, Word, a phone photo, a text file. "
               "It must be a quote against the current RFx. Reading it takes about a minute.")
    with st.form("add_vendor", clear_on_submit=True):
        a, b = st.columns(2)
        company = a.text_input("Vendor company *")
        contact = b.text_input("Contact name")
        email = a.text_input("Vendor email")
        subject = b.text_input("Email subject", value=f"Quote for {common.rfx()['rfx_id']}")
        body = st.text_area("Email text", placeholder="e.g. Rs 44/kg for all 5-ply, Rs 39 for 3-ply, freight included, 45 days credit.")
        files = st.file_uploader("Attachments", type=ingest.UPLOAD_TYPES, accept_multiple_files=True)
        read_now = st.checkbox("Read it straight away", value=True)
        submitted = st.form_submit_button("Add response", type="primary")
    if submitted:
        if not company.strip():
            st.error("Enter the vendor company name.")
        elif not body.strip() and not files:
            st.error("Add the email text or at least one attachment.")
        else:
            f = ingest.add_vendor(company.strip(), contact.strip(), email.strip(), subject.strip(), body.strip(),
                                  [(u.name, u.getvalue()) for u in files or []],
                                  datetime.now().isoformat(timespec="minutes"))
            store.audit("response_added", {"vendor": f.name, "files": [u.name for u in files or []]}, "buyer")
            if read_now:
                read(f)
            st.rerun()

# ---- read all ---------------------------------------------------------------------------
pending = [f for f in folders if can_read(f) and stale(f)]
c1, c2 = st.columns([1, 3])
label = "Read new / changed responses" if config.demo_mode() else "Read all responses"
targets = pending if config.demo_mode() else folders
if c1.button(label, type="primary", disabled=not targets):
    bar = st.progress(0.0)
    for i, f in enumerate(targets, 1):
        bar.progress((i - 1) / len(targets), text=f"Reading {f.name} …")
        if not read(f):
            break
    bar.progress(1.0, text="Done")
    st.rerun()
c2.caption(("Demo mode: the five original responses are already read and locked. New or edited responses can be read. "
            if config.demo_mode() else "") +
           "Results are cached in data/runtime/extractions, so nothing is re-read unless you ask.")

# ---- each vendor -------------------------------------------------------------------------
for f in folders:
    meta, docs = ingest.load_vendor(f)
    vid = ingest.vendor_id(f)
    rec = ex.get(vid)
    with st.container(border=True):
        h1, h2 = st.columns([4, 1])
        tag = " · *added in the app*" if ingest.user_changed(f) else ""
        h1.markdown(f"#### {vid} · {meta['from_company']}{tag}")
        h1.caption(f"From **{meta['from_name']}** <{meta['from_email']}> · {meta['received_at'][:16].replace('T', ' ')} · "
                   f"Subject: *{meta['subject']}*")
        if h2.button("Re-read" if rec else "Read", key=f"x-{vid}", disabled=not can_read(f),
                     help=None if can_read(f) else "Locked in the hosted demo - already read"):
            if read(f):
                st.rerun()
        st.text(meta["body"])
        atts = [d for d in docs if d.kind != "email"]
        if atts:
            cols = st.columns(len(atts))
            for col, d in zip(cols, atts):
                with col:
                    st.markdown(f"📎 `{d.file}`")
                    if d.kind == "image":
                        st.image(Image.open(d.path), width=260)
                    else:
                        st.download_button("Open", d.path.read_bytes(), file_name=d.file, key=f"o-{vid}-{d.file}")
        else:
            st.caption("No attachments.")
        with st.expander("Add or replace a file"):
            up = st.file_uploader("File", type=ingest.UPLOAD_TYPES, key=f"up-{vid}")
            st.caption("Same file name replaces the old one (e.g. a real phone photo of the rate card). Then click Re-read.")
            if up and st.button("Save file", key=f"sv-{vid}"):
                n = ingest.add_attachment(f, up.name, up.getvalue())
                store.audit("attachment_added", {"vendor": f.name, "file": n}, "buyer")
                st.rerun()
            if ingest.user_changed(f) and meta["from_company"] and vid not in ("V1", "V2", "V3", "V4", "V5"):
                if st.button("Delete this vendor", key=f"del-{vid}"):
                    ingest.delete_vendor(f)
                    store.audit("response_deleted", {"vendor": f.name}, "buyer")
                    st.cache_data.clear()
                    st.rerun()
        if rec:
            r = rec["result"]
            n = sum(1 for q in r["line_quotes"] if q.get("rfx_line_id") and not q.get("is_alternate_offer"))
            st.success(f"Read by `{rec['model']}` at {rec['extracted_at'].replace('T', ' ')} — "
                       f"{n} RFx lines priced, {len(r['questionnaire'])} questionnaire answers, "
                       f"{len(r['certificates'])} certificate(s)"
                       + (f", photo double-read: {len(rec['second_read']['rows'])} rows" if rec.get("second_read") else ""))
            if r.get("reader_notes"):
                st.markdown("**Reader notes:** " + " · ".join(r["reader_notes"]))
            with st.expander("Raw extraction (what the model returned)"):
                st.json(r, expanded=False)
        else:
            st.warning("Not read yet.")
        if rec and stale(f):
            st.info("Files changed since the last read - click Re-read to update the comparison.")
