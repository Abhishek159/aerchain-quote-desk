"""LLM extraction: read every file a vendor sent, return what they *wrote*.

Design rule: the model transcribes and matches; it never converts.
Units, currency, GST, freight and discounts are applied later in
normalize.py by plain code, where every step is visible and testable.
"""
import json
from datetime import datetime

from . import config, ingest, llm

S = lambda *t: {"type": list(t)}  # noqa: E731  nullable helper

SOURCE = {
    "type": "object",
    "properties": {
        "file": {"type": "string"},
        "locator": {"type": "string", "description": "Sheet!Row, 'page N', 'para N', or 'photo row N'"},
        "verbatim": {"type": "string", "description": "Exact short text copied from the source"},
        "bbox": {"type": ["array", "null"], "items": {"type": "number"},
                 "description": "Photos only: [ymin, xmin, ymax, xmax] normalised 0-1000 around the row"},
    },
    "required": ["file", "locator", "verbatim"],
}

LINE_QUOTE = {
    "type": "object",
    "properties": {
        "vendor_item_text": {"type": "string"},
        "vendor_dims": S("string", "null"),
        "vendor_ply": S("integer", "null"),
        "rfx_line_id": {"type": ["string", "null"], "description": "Matched RFx line id, null if not an RFx item"},
        "match_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "match_reason": {"type": "string"},
        "price_value": {"type": ["number", "null"], "description": "Number exactly as written; null if given by reference"},
        "currency": {"type": "string", "description": "ISO code as stated or clearly implied, e.g. INR, USD"},
        "price_basis": {"type": "string",
                        "enum": ["per_piece", "per_set", "per_100", "per_1000", "per_dozen", "per_kg", "per_bundle", "other"]},
        "bundle_size": S("integer", "null"),
        "gst_treatment": {"type": "string", "enum": ["exclusive", "inclusive", "not_stated"]},
        "gst_rate_pct": S("number", "null"),
        "price_reference": {"type": "string", "enum": ["explicit", "same_as_other_line", "same_as_last_year"]},
        "reference_line_id": S("string", "null"),
        "is_alternate_offer": {"type": "boolean"},
        "spec_deviation": {"type": ["string", "null"], "description": "Any change vs the RFx spec the vendor proposes"},
        "extraction_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "uncertainty_note": S("string", "null"),
        "source": SOURCE,
    },
    "required": ["vendor_item_text", "rfx_line_id", "match_confidence", "match_reason", "price_value", "currency",
                 "price_basis", "gst_treatment", "price_reference", "is_alternate_offer",
                 "extraction_confidence", "source"],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "quote_reference": S("string", "null"),
        "quote_date": S("string", "null"),
        "line_quotes": {"type": "array", "items": LINE_QUOTE},
        "bulk_rules": {
            "type": "array",
            "description": "Statements that price MANY lines at once, e.g. 'Rs 42/kg for all 5-ply' or "
                           "'rest same as last year'. Also expand them into line_quotes.",
            "items": {"type": "object", "properties": {
                "statement": {"type": "string"}, "applies_to_line_ids": {"type": "array", "items": {"type": "string"}},
                "source": SOURCE}, "required": ["statement", "applies_to_line_ids", "source"]},
        },
        "terms": {
            "type": "object",
            "properties": {
                "freight_basis": {"type": "string",
                                  "enum": ["included", "percent_extra", "fixed_amount_extra", "extra_unspecified", "not_stated"]},
                "freight_value": S("number", "null"),
                "freight_text": S("string", "null"),
                "gst_text": S("string", "null"),
                "payment_terms_days": S("integer", "null"),
                "payment_text": S("string", "null"),
                "advance_payment_pct": S("number", "null"),
                "validity_text": S("string", "null"),
                "lead_time_days": S("integer", "null"),
                "price_variation_clause": S("string", "null"),
                "discounts": {"type": "array", "items": {"type": "object", "properties": {
                    "description": {"type": "string"},
                    "pct": S("number", "null"),
                    "is_conditional": {"type": "boolean"},
                    "condition_text": S("string", "null"),
                    "min_annual_value_inr": {"type": ["number", "null"],
                                             "description": "If the condition is a minimum annual business value, the INR amount"},
                    "source": SOURCE}, "required": ["description", "is_conditional", "source"]}},
                "other_notes": {"type": "array", "items": {"type": "string"}},
                "source_notes": {"type": "array", "items": SOURCE},
            },
            "required": ["freight_basis", "discounts"],
        },
        "questionnaire": {"type": "array", "items": {"type": "object", "properties": {
            "qid": {"type": "string"},
            "answered": {"type": "boolean"},
            "answer_text": S("string", "null"),
            "value_bool": S("boolean", "null"),
            "value_number": S("number", "null"),
            "is_range": {"type": "boolean"},
            "range_low": S("number", "null"),
            "range_high": S("number", "null"),
            "is_vague": {"type": "boolean", "description": "e.g. 'below 2%', 'many', 'approx'"},
            "source": {"anyOf": [SOURCE, {"type": "null"}]}},
            "required": ["qid", "answered", "is_range", "is_vague"]}},
        "certificates": {"type": "array", "items": {"type": "object", "properties": {
            "standard": {"type": "string"}, "holder": S("string", "null"), "certificate_no": S("string", "null"),
            "valid_until": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "file": {"type": "string"}}, "required": ["standard", "valid_until", "file"]}},
        "reader_notes": {"type": "array", "items": {"type": "string"},
                         "description": "Anything a careful buyer should know that does not fit above"},
    },
    "required": ["line_quotes", "bulk_rules", "terms", "questionnaire", "certificates", "reader_notes"],
}

SYSTEM = """You are a meticulous procurement data-entry specialist. A vendor has replied to an RFx in
whatever format they liked. Read EVERY file (email body, spreadsheets, PDFs, Word letters, photos)
and record exactly what the vendor wrote.

Hard rules:
- TRANSCRIBE, DO NOT CONVERT. Copy prices exactly as written with their currency and basis
  (per piece / per 100 / per 1000 / per kg ...). Never multiply, divide, add GST or convert currency.
- Match each priced item to an RFx line: use the buyer's item code or line id if the vendor gives it,
  otherwise internal dimensions + ply + description. Dimensions match if the same three numbers appear.
  If no RFx line fits, set rfx_line_id to null (the vendor offered something we did not ask for).
- If one statement prices many lines ("Rs 42/kg for the 5-ply", "rest same as last year",
  "L17 and L18 same as L16"), record it in bulk_rules AND expand it into one line_quote per RFx line it
  covers, using price_reference / reference_line_id. For "same as last year" set price_value to null.
- Alternate or optional offers: separate line_quote with is_alternate_offer = true.
- spec_deviation is ONLY for changes to the physical product (board grade, GSM, flute, ply, size, print).
  Commercial departures (per-kg pricing, freight extra, payment terms) go in reader_notes, never there.
- Read footnotes, small print, terms tabs and annexures: discounts, freight, GST, payment terms,
  price-variation clauses are often hidden there.
- Never invent a price for a line the vendor did not quote. Missing is a valid answer.
- source.verbatim must be text copied from the file. For photos also give bbox around the row.
- Use extraction_confidence = low whenever the reading is uncertain (blur, skew, row alignment,
  handwriting, ambiguous unit) and explain in uncertainty_note. Being honest about doubt is more
  valuable than a confident guess.
- Questionnaire: one entry per RFx question id. Answers may be in an annexure, a tab, prose or the
  email body. Unanswered -> answered=false. Vague answers ('below 2%', 'many') -> is_vague=true.
- Certificates: read the validity / expiry date from each attached certificate."""


def _rfx_brief(rfx):
    lines = "\n".join(
        f"{l['line_id']} | {l['item_code']} | {l['description']} | {l['dimensions_mm']} mm | {l['ply']}-ply | "
        f"{l['print']} | UOM {l['uom']}" for l in rfx["lines"])
    qs = "\n".join(f"{q['qid']}: {q['text']}" for q in rfx["questionnaire"])
    return (f"RFx {rfx['rfx_id']} from {rfx['buyer']['name']}.\nRequested basis: {rfx['terms']['price_basis']}.\n\n"
            f"RFx LINES (id | item code | description | internal size | ply | print | uom):\n{lines}\n\n"
            f"QUESTIONNAIRE:\n{qs}")


SECOND_READ_SCHEMA = {
    "type": "object",
    "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": {
        "printed_item": {"type": "string"}, "printed_ply": S("string", "null"),
        "printed_price": {"type": "string", "description": "exactly as printed, including any '/100' suffix"},
        "rfx_line_id": S("string", "null")}, "required": ["printed_item", "printed_price", "rfx_line_id"]}}},
    "required": ["rows"],
}


def _second_read(rfx, img_docs):
    """Independent re-read of photos, like double-keyed data entry."""
    parts = [_rfx_brief(rfx)]
    for d in img_docs:
        parts += d.parts()
    parts.append("Transcribe every priced row of the photographed rate card, top to bottom. Follow each row "
                 "carefully across the page - the sheet is photographed at an angle, so rows slope. "
                 "Then match each row to an RFx line id (or null).")
    out, model = llm.generate_json(parts, purpose="second_read", schema=SECOND_READ_SCHEMA)
    return {"model": model, "rows": out.get("rows", [])}


def extract_vendor(folder):
    rfx = json.loads(config.RFX_FILE.read_text())
    meta, docs = ingest.load_vendor(folder)
    parts = [_rfx_brief(rfx), f"\nVENDOR RESPONSE from {meta['from_company']}:"]
    for d in docs:
        parts += d.parts()
    parts.append("Extract the full response now.")
    result, model = llm.generate_json(parts, purpose=f"extract:{folder.name}", schema=EXTRACTION_SCHEMA,
                                      system=SYSTEM)
    img_docs = [d for d in docs if d.kind == "image"]
    second = _second_read(rfx, img_docs) if img_docs else None
    rec = {
        "vendor_id": ingest.vendor_id(folder), "vendor_name": meta["from_company"], "folder": folder.name,
        "extracted_at": datetime.now().isoformat(timespec="seconds"), "model": model,
        "files": [{"file": d.file, "kind": d.kind} for d in docs],
        "result": result, "second_read": second,
    }
    (config.EXTRACTIONS / f"{rec['vendor_id']}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    return rec


def load_extractions():
    out = {}
    for p in sorted(config.EXTRACTIONS.glob("V*.json")):
        rec = json.loads(p.read_text())
        out[rec["vendor_id"]] = rec
    return out
