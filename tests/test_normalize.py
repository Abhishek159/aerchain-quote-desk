"""Unit test for the deterministic layer only.

Builds a *perfect* reading of each vendor from ground truth (what an ideal
extractor would return) and checks normalisation lands on the true numbers
and raises the right flags. This never touches the demo: the real app only
ever uses real LLM extractions.

Run: uv run python tests/test_normalize.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config, evaluate, normalize  # noqa: E402

truth = json.loads(config.GROUND_TRUTH.read_text())
rfx = json.loads(config.RFX_FILE.read_text())
LINES = {l["line_id"]: l for l in rfx["lines"]}
BASIS = {"Per 100 Nos": "per_100", "Per 1000 Nos": "per_1000", "Per 1000 Sets": "per_1000", "per piece": "per_piece",
         "per box": "per_piece", "per 1000": "per_1000", "per 100 (incl. GST)": "per_100",
         "per set (incl. GST)": "per_set", "per box (incl. GST)": "per_piece", "per kg": "per_kg"}
FOLDERS = {"V1": "V1_Pacifica", "V2": "V2_ShreeGanesh", "V3": "V3_KonkanKraft", "V4": "V4_Pioneer", "V5": "V5_Maruti"}
TERMS = {
    "V1": {"freight_basis": "included", "gst_text": "5% extra", "discounts": []},
    "V2": {"freight_basis": "percent_extra", "freight_value": 2, "gst_text": "GST @ 5% extra",
           "discounts": [{"description": "trade discount", "pct": 4, "is_conditional": True,
                          "condition_text": "annual business exceeds Rs. 50 lakh", "min_annual_value_inr": 5_000_000,
                          "source": {"file": "x", "locator": "footnote", "verbatim": "4%"}}]},
    "V3": {"freight_basis": "included", "gst_text": "5% extra", "discounts": []},
    "V4": {"freight_basis": "included", "gst_text": "incl. GST 5%", "discounts": []},
    "V5": {"freight_basis": "extra_unspecified", "freight_text": "freight extra", "discounts": []},
}


def q_answers(vid):
    tq = truth["vendors"][vid]["questionnaire"]
    out = []
    for q in rfx["questionnaire"]:
        v = tq.get(q["qid"])
        if v is None:
            out.append({"qid": q["qid"], "answered": False, "is_range": False, "is_vague": False})
            continue
        a = {"qid": q["qid"], "answered": True, "answer_text": str(v), "is_range": False, "is_vague": False}
        if isinstance(v, (int, float)):
            a["value_number"] = v
        elif "range" in str(v):
            a.update(is_range=True, range_low=150, range_high=200)
        elif "not a number" in str(v):
            a["is_vague"] = True
        out.append(a)
    return out


def perfect_extraction(vid):
    tv = truth["vendors"][vid]
    quotes = []
    for lid, t in tv["lines"].items():
        if t["status"] == "not_quoted":
            continue
        line = LINES[lid]
        q = {"vendor_item_text": line["description"], "vendor_dims": None, "rfx_line_id": lid,
             "match_confidence": "high", "match_reason": "test", "currency": t["currency"],
             "price_value": t["native_price"], "price_basis": BASIS.get(t["native_unit"], "per_piece"),
             "gst_treatment": "inclusive" if "incl" in (t["native_unit"] or "") else "not_stated",
             "price_reference": "explicit", "is_alternate_offer": False, "extraction_confidence": "high",
             "source": {"file": "email body", "locator": "-", "verbatim": ""}}
        if t["status"] in ("same_as_last_year", "unresolved"):
            q.update(price_reference="same_as_last_year", price_value=None)
        if "same rate as L16" in t["note"]:
            q.update(price_reference="same_as_other_line", reference_line_id="L16", price_value=None)
        if t.get("deviation"):
            q["spec_deviation"] = "140 GSM top liner"
        quotes.append(q)
    certs = []
    if tv["questionnaire"].get("iso_valid_until"):
        certs.append({"standard": "ISO 9001:2015", "valid_until": tv["questionnaire"]["iso_valid_until"], "file": "cert.pdf"})
    return {"vendor_id": vid, "vendor_name": vid, "folder": FOLDERS[vid], "model": "perfect-reader(test)",
            "extracted_at": "-", "files": [], "second_read": None,
            "result": {"line_quotes": quotes, "bulk_rules": [], "terms": TERMS[vid],
                       "questionnaire": q_answers(vid), "certificates": certs, "reader_notes": []}}


def main():
    ex = {vid: perfect_extraction(vid) for vid in truth["vendors"]}
    for vid in ex:  # use real vendor names for the history lookup
        ex[vid]["vendor_name"] = json.loads((config.INBOX / FOLDERS[vid] / "email.json").read_text())["from_company"]
    R = normalize.build(ex)
    s = evaluate.score(R)
    print(f"cells correct: {s['correct']}/{s['total']}  wrong: {s['wrong']}  wrong-but-flagged: {s['wrong_but_flagged']}")
    for r in s["cells"]:
        if r["verdict"] != "correct":
            print("  MISS", r)
    for q in s["qualification"]:
        print("  qual", q["vendor_id"], q["got"], q["verdict"])
    codes = {}
    for f in R.flags:
        codes[f["code"]] = codes.get(f["code"], 0) + 1
    print("flags:", dict(sorted(codes.items())))
    assert s["correct"] == s["total"], "normalisation disagrees with ground truth"
    assert all(q["verdict"] == "correct" for q in s["qualification"])
    print("OK")


if __name__ == "__main__":
    main()


def write_fixture_runtime(target):
    """For UI smoke tests only: AERCHAIN_RUNTIME=<target> streamlit run app.py"""
    out = Path(target) / "extractions"
    out.mkdir(parents=True, exist_ok=True)
    for vid in truth["vendors"]:
        rec = perfect_extraction(vid)
        rec["vendor_name"] = json.loads((config.INBOX / FOLDERS[vid] / "email.json").read_text())["from_company"]
        (out / f"{vid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
