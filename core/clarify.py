"""When the system isn't sure, the best fix is usually to ask the vendor.

The list of questions is built by code from open flags (so nothing is
missed or invented); the model only writes it up as a polite email.
"""
from datetime import datetime

from . import config, llm, store

# One question per issue type, listing every line it affects - a vendor will
# answer six clear questions, not forty.
ASK = {
    "UNRESOLVED_REFERENCE": "You indicated {lines} at last year's rate, but we have never bought {them} from you. Please quote a price per unit.",
    "AMBIGUOUS_SCOPE": "Does your per-kg rate also cover {lines_desc}, or do these fall under 'same as last year'? Please quote them per unit.",
    "NOT_QUOTED": "Please quote {lines_desc}, or confirm you are not bidding for {them}.",
    "LOW_CONFIDENCE": "We could not read your price clearly for {lines}. Please confirm.",
    "DOUBLE_READ_MISMATCH": "We could not read your price clearly for {lines}. Please confirm.",
    "PRICE_OUTLIER": "Your price for {lines} is far from the market range. Please confirm the unit (per piece / per 100 / per 1000).",
    "PER_KG_ASSUMED_WEIGHT": "Your rates are per kg. Please confirm the finished weight per box for {lines} (or quote per piece) - we have estimated weights from our specification.",
    "LAST_YEAR_PRICE": "Please confirm in writing that {lines} stay at the prices on our last purchase orders.",
    "SPEC_DEVIATION": "For {lines} you propose a different specification. Please confirm the exact board spec and BCT value, and also quote the specified board.",
    "MATCH_UNCERTAIN": "Please confirm which of our items your quote refers to for {lines}.",
}
# If a line already has a more fundamental question, don't also ask these.
SUPERSEDED_BY = {"PRICE_OUTLIER", "MATCH_UNCERTAIN", "MATCH_MEDIUM", "PER_KG_ASSUMED_WEIGHT", "LAST_YEAR_PRICE"}
FUNDAMENTAL = {"UNRESOLVED_REFERENCE", "AMBIGUOUS_SCOPE"}
VENDOR_ASK = {
    "FREIGHT_UNKNOWN": "Please state freight to our Chakan plant (included, % of value, or Rs per trip).",
    "GST_UNSTATED": "Please confirm whether your prices include GST, and the GST rate.",
    "CONDITIONAL_DISCOUNT": "Please confirm how your conditional discount is calculated and when it applies.",
}


def _span(ids):
    """L01, L02, L03, L05 -> 'L01-L03, L05'"""
    nums = sorted(int(i[1:]) for i in ids)
    out, run = [], [nums[0]]
    for n in nums[1:]:
        if n == run[-1] + 1:
            run.append(n)
        else:
            out.append(run)
            run = [n]
    out.append(run)
    return ", ".join(f"L{r[0]:02d}" if len(r) == 1 else f"L{r[0]:02d}-L{r[-1]:02d}" for r in out)


def questions_for(vid, R, rfx):
    lines = {l["line_id"]: l for l in rfx["lines"]}
    open_ = [f for f in R.flags if f["vendor_id"] == vid and f["status"] == "open"]
    fundamental = {f["line_id"] for f in open_ if f["code"] in FUNDAMENTAL}
    by_code = {}
    for f in open_:
        if f["line_id"] and f["code"] in ASK:
            if f["code"] in SUPERSEDED_BY and f["line_id"] in fundamental:
                continue
            by_code.setdefault(f["code"], []).append(f)
    qs = []
    for code in ASK:  # stable, most important first
        fl = by_code.get(code)
        if not fl:
            continue
        ids = sorted({f["line_id"] for f in fl})
        desc = ", ".join(f"{i} ({lines[i]['description']})" for i in ids) if len(ids) <= 4 else _span(ids)
        qs.append({"flag_ids": [f["flag_id"] for f in fl],
                   "text": ASK[code].format(lines=_span(ids), lines_desc=desc, them="it" if len(ids) == 1 else "them")})
    for f in open_:
        if not f["line_id"] and f["code"] in VENDOR_ASK:
            qs.append({"flag_ids": [f["flag_id"]], "text": VENDOR_ASK[f["code"]]})
    qual = [f for f in open_ if not f["line_id"] and f["code"].startswith("QUAL_")]
    unanswered = [f["code"].split("_")[1] for f in qual if "not answered" in f["message"]]
    if unanswered:
        qs.append({"flag_ids": [f["flag_id"] for f in qual if "not answered" in f["message"]],
                   "text": f"Please complete our supplier questionnaire - {', '.join(unanswered)} are mandatory for award "
                           "(ISO 9001 certificate copy, lot testing, capacity, rejection rate)."})
    for f in qual:
        if "not answered" in f["message"]:
            continue
        qid = f["code"].split("_")[1]
        q = next((x for x in rfx["questionnaire"] if x["qid"] == qid), None)
        qs.append({"flag_ids": [f["flag_id"]],
                   "text": f"Questionnaire {qid} ({q['text'] if q else ''}): {f['message'].split(': ', 1)[-1]}. Please clarify."})
    return qs


def draft_email(vid, R, rfx):
    v = R.vendors[vid]
    qs = questions_for(vid, R, rfx)
    if not qs:
        return None
    bullet = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(qs, 1))
    prompt = (f"Write a short, courteous clarification email from Ritika Deshmukh (Category Manager - Packaging, "
              f"Meghna Foods) to {v['vendor_name']} about their quote for RFx {rfx['rfx_id']}. Ask for a reply within "
              f"2 working days. Include EVERY numbered point below verbatim as a numbered list - do not add, merge or "
              f"drop points. Return only the email body, no subject line.\n\nPOINTS:\n{bullet}")
    try:
        body = llm.generate([prompt], purpose=f"clarify:{vid}", models=config.ANALYST_MODELS, temperature=0.4).text
    except llm.LLMError:
        body = (f"Dear {v['vendor_name']} team,\n\nThank you for your quotation against {rfx['rfx_id']}. "
                f"Before we can evaluate it, please clarify the following within 2 working days:\n\n{bullet}\n\n"
                "Regards,\nRitika Deshmukh\nCategory Manager - Packaging, Meghna Foods")
    return {"vendor_id": vid, "subject": f"Clarifications on your quote - {rfx['rfx_id']}", "body": body, "questions": qs}


def send(email):
    p = config.OUTBOX / f"{datetime.now():%Y%m%d-%H%M%S}_clarify_{email['vendor_id']}.eml"
    p.write_text(f"Subject: {email['subject']}\n\n{email['body']}")
    store.audit("clarification_sent", {"vendor_id": email["vendor_id"], "questions": len(email["questions"])}, "buyer")
    return p.name
