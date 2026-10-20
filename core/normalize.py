"""Deterministic normalisation: vendor's words -> one comparable number.

Target basis for every cell: INR per RFx unit (piece / set), ex-GST,
delivered Chakan ("landed"). Each conversion is written down as a step,
and every doubt becomes a flag with a severity:

  blocker  - do not award on this number until a human has looked at it
  warning  - number is usable but rests on an assumption the buyer should see
  info     - transformation applied, nothing to decide
"""
import json
import re
from dataclasses import dataclass, field

import pandas as pd

from . import config, ingest, store

SEV_RANK = {"blocker": 0, "warning": 1, "info": 2}
# A spec deviation must be about the physical product, not commercial terms.
SPEC_WORDS = re.compile(r"gsm|liner|flute|ply|\bbf\b|burst|board|print|colou?r|size|dimension|kraft|bct|ect|grade", re.I)


@dataclass
class Settings:
    fx: dict = field(default_factory=lambda: dict(config.DEFAULT_FX))
    default_gst_pct: float = config.DEFAULT_GST_PCT
    contract_start: str = config.CONTRACT_START


def _num(s):
    m = re.findall(r"\d[\d,]*\.?\d*", str(s or ""))
    return [float(x.replace(",", "")) for x in m]


def _norm_text(s):
    return re.sub(r"[\s,₹]|rs\.?", "", str(s).lower())


def _fmt(x):
    return f"₹{x:,.2f}" if x is not None else "-"


class Result:
    def __init__(self):
        self.cells = []  # one dict per vendor x line
        self.flags = []
        self.vendors = {}
        self.questionnaire = []
        self.alternates = []
        self.unsolicited = []

    def flag(self, vid, lid, code, sev, msg, overrides):
        fid = f"{vid}:{lid or '-'}:{code}"
        res = overrides["flags"].get(fid)
        f = {"flag_id": fid, "vendor_id": vid, "line_id": lid, "code": code, "severity": sev, "message": msg,
             "status": "resolved" if res else "open", "resolution_note": res["note"] if res else None}
        self.flags.append(f)
        return f


def load_rfx():
    return json.loads(config.RFX_FILE.read_text())


def load_history():
    return pd.read_csv(config.HISTORY_CSV) if config.HISTORY_CSV.exists() else pd.DataFrame()


def _last_year(history, vendor_name, item_code):
    if history.empty:
        return None
    key = vendor_name.split()[0].lower()
    h = history[(history["item_code"] == item_code) & history["vendor"].str.lower().str.contains(key)]
    if h.empty:
        return None
    r = h.sort_values("po_date").iloc[-1]
    return {"price": float(r["unit_price_inr"]), "po": int(r["po_number"]), "date": r["po_date"]}


def _doc_gst(terms):
    t = (terms.get("gst_text") or "").lower()
    if "incl" in t:
        return "inclusive", (_num(t) or [None])[0]
    if any(w in t for w in ("extra", "exclusive", "excl", "additional", "as applicable")):
        return "exclusive", (_num(t) or [None])[0]
    return None, None


def _evidence_ok(q, docs_by_file):
    src = q.get("source") or {}
    d = docs_by_file.get(src.get("file"))
    if d is None or d.kind == "image":
        return None  # cannot check text for photos; second read covers them
    hay = _norm_text(d.text)
    verb = _norm_text(src.get("verbatim", ""))
    if verb and verb in hay:
        return True
    pv = q.get("price_value")
    if pv is not None:
        for cand in {f"{pv:.2f}", f"{pv:.1f}", f"{pv:g}", f"{pv:,.2f}", f"{pv:,.0f}"}:
            if _norm_text(cand) in hay:
                return True
    return False


def _second_read_price(second, lid):
    if not second:
        return None, None
    for r in second.get("rows", []):
        if r.get("rfx_line_id") == lid:
            n = _num(r.get("printed_price"))
            return (n[0] if n else None), r.get("printed_price")
    return None, None


def build(extractions: dict, settings: Settings | None = None):
    settings = settings or Settings()
    rfx = load_rfx()
    lines = {l["line_id"]: l for l in rfx["lines"]}
    history = load_history()
    ov = store.load_overrides()
    R = Result()

    for vid, rec in sorted(extractions.items()):
        res = rec["result"]
        vname = rec["vendor_name"]
        terms = res.get("terms", {}) or {}
        folder = config.INBOX / rec["folder"]
        _, docs = ingest.load_vendor(folder)
        docs_by_file = {d.file: d for d in docs}
        doc_gst, doc_gst_rate = _doc_gst(terms)

        # ---- vendor-level terms -------------------------------------------------
        fb = terms.get("freight_basis", "not_stated")
        fv = terms.get("freight_value")
        freight_factor = 1.0 if fb == "included" else (1 + fv / 100 if fb == "percent_extra" and fv is not None else None)
        if fb == "percent_extra" and fv is not None:
            R.flag(vid, None, "FREIGHT_PERCENT", "info", f"Freight {fv:g}% extra, added to get landed price.", ov)
        elif freight_factor is None:
            R.flag(vid, None, "FREIGHT_UNKNOWN", "warning",
                   f"Freight is '{terms.get('freight_text') or fb}'. Landed cost cannot be computed; "
                   "comparison uses ex-works price for this vendor, which flatters them.", ov)
        uncond = [d for d in terms.get("discounts", []) if not d.get("is_conditional") and d.get("pct")]
        cond = [d for d in terms.get("discounts", []) if d.get("is_conditional") and d.get("pct")]
        for d in cond:
            where = (d.get("source") or {}).get("locator", "")
            R.flag(vid, None, "CONDITIONAL_DISCOUNT", "warning",
                   f"{d['pct']:g}% discount, conditional: \"{d.get('condition_text') or d['description']}\" "
                   f"({(d.get('source') or {}).get('file', '')} {where}). Not applied to line prices; "
                   "the award simulator applies it only if the condition is met.", ov)
        if doc_gst is None and not any(q.get("gst_treatment") != "not_stated" for q in res.get("line_quotes", [])):
            R.flag(vid, None, "GST_UNSTATED", "warning",
                   "Vendor did not say whether prices include GST. Treated as ex-GST.", ov)
        if terms.get("price_variation_clause"):
            R.flag(vid, None, "PRICE_VARIATION", "info", f"Price variation clause: {terms['price_variation_clause']}", ov)
        if terms.get("advance_payment_pct"):
            R.flag(vid, None, "ADVANCE_PAYMENT", "warning",
                   f"Asks for {terms['advance_payment_pct']:g}% advance ({terms.get('payment_text') or ''}).", ov)

        R.vendors[vid] = {
            "vendor_id": vid, "vendor_name": vname, "folder": rec["folder"], "model": rec["model"], "extracted_at": rec["extracted_at"],
            "freight_basis": fb, "freight_value": fv, "freight_text": terms.get("freight_text"),
            "freight_factor": freight_factor, "gst_text": terms.get("gst_text"),
            "payment_terms_days": terms.get("payment_terms_days"), "payment_text": terms.get("payment_text"),
            "validity_text": terms.get("validity_text"), "lead_time_days": terms.get("lead_time_days"),
            "conditional_discounts": cond, "unconditional_discounts": uncond,
            "price_variation_clause": terms.get("price_variation_clause"),
            "reader_notes": res.get("reader_notes", []), "files": rec["files"],
        }

        # ---- line quotes ------------------------------------------------------
        by_line = {}
        for q in res.get("line_quotes", []):
            lid = q.get("rfx_line_id")
            if lid and lid not in lines:
                lid = None
            if not lid:
                R.unsolicited.append({"vendor_id": vid, **q})
                continue
            if q.get("is_alternate_offer"):
                R.alternates.append({"vendor_id": vid, "line_id": lid, **q})
                R.flag(vid, lid, "ALTERNATE_OFFER", "info",
                       f"Alternate offer also received: {q.get('vendor_item_text')} at {q.get('currency')} "
                       f"{q.get('price_value')} {q.get('price_basis')} - not used in comparison.", ov)
                continue
            if lid in by_line:
                R.flag(vid, lid, "DUPLICATE_QUOTE", "warning",
                       "Vendor quoted this line more than once; the first quote is used.", ov)
                continue
            by_line[lid] = q
        if R.unsolicited and any(u["vendor_id"] == vid for u in R.unsolicited):
            n = sum(u["vendor_id"] == vid for u in R.unsolicited)
            R.flag(vid, None, "UNSOLICITED_ITEMS", "info", f"{n} priced item(s) do not match any RFx line; ignored.", ov)

        resolved_price = {}
        pending_refs = []
        for lid, line in lines.items():
            q = by_line.get(lid)
            cell = {"vendor_id": vid, "vendor_name": vname, "line_id": lid, "steps": [], "source": None,
                    "native": None, "ex_works": None, "landed": None, "quote": q}
            ck = f"{vid}:{lid}"
            if ck in ov["cells"]:
                o = ov["cells"][ck]
                if o.get("exclude"):
                    cell.update(status="excluded", steps=[f"Excluded by buyer: {o['note']}"])
                else:
                    p = float(o["price_inr"])
                    cell.update(status="buyer_override", ex_works=p,
                                landed=p * freight_factor if freight_factor else None,
                                steps=[f"Buyer entered {_fmt(p)} per {line['uom']} ex-GST ({o['note']})"])
                if q:
                    cell["source"] = q.get("source")
                R.cells.append(cell)
                if cell.get("ex_works") is not None:
                    resolved_price[lid] = cell["ex_works"]
                continue
            if q is None:
                cell["status"] = "not_quoted"
                R.flag(vid, lid, "NOT_QUOTED", "warning", f"{vname} did not quote {lid}.", ov)
                R.cells.append(cell)
                continue
            cell["source"] = q.get("source")
            src = q.get("source") or {}
            where = f"{src.get('file', '?')}, {src.get('locator', '?')}"

            # match checks
            if q.get("match_confidence") == "low":
                R.flag(vid, lid, "MATCH_UNCERTAIN", "blocker",
                       f"Not sure '{q.get('vendor_item_text')}' is {lid}: {q.get('match_reason')}", ov)
            elif q.get("match_confidence") == "medium":
                R.flag(vid, lid, "MATCH_MEDIUM", "warning",
                       f"Matched '{q.get('vendor_item_text')}' to {lid} with medium confidence: {q.get('match_reason')}", ov)
            if line["kind"] in ("RSC", "TRAY"):
                vd = _num(q.get("vendor_dims") or "")
                want = sorted([line["dimensions_mm"].split(" x ")[i] for i in range(3)], key=float)
                if len(vd) >= 3 and sorted(f"{x:g}" for x in vd[:3]) != sorted(f"{float(x):g}" for x in want):
                    R.flag(vid, lid, "MATCH_MISMATCH", "blocker",
                           f"Vendor size {q.get('vendor_dims')} does not equal RFx size {line['dimensions_mm']}.", ov)
            if q.get("vendor_ply") and q["vendor_ply"] != line["ply"]:
                R.flag(vid, lid, "PLY_MISMATCH", "blocker",
                       f"Vendor quoted {q['vendor_ply']}-ply; RFx asks for {line['ply']}-ply.", ov)
            if q.get("spec_deviation") and SPEC_WORDS.search(q["spec_deviation"]):
                R.flag(vid, lid, "SPEC_DEVIATION", "warning",
                       f"Not like-for-like: {q['spec_deviation']}", ov)
            if q.get("price_basis") == "per_kg" and line["kind"] != "RSC":
                R.flag(vid, lid, "AMBIGUOUS_SCOPE", "blocker",
                       f"A blanket per-kg rate was applied to a {line['kind'].lower()} ({line['description']}). "
                       "The vendor may have meant cartons only, with this item under 'rest same as last year'. Ask.", ov)
            conf = q.get("extraction_confidence")
            if conf == "low":
                R.flag(vid, lid, "LOW_CONFIDENCE", "blocker",
                       f"Reader was unsure: {q.get('uncertainty_note') or 'low confidence'} ({where})", ov)
            elif conf == "medium":
                R.flag(vid, lid, "MEDIUM_CONFIDENCE", "warning",
                       f"Reader had some doubt: {q.get('uncertainty_note') or 'medium confidence'} ({where})", ov)

            ref = q.get("price_reference", "explicit")
            if ref == "same_as_other_line":
                pending_refs.append((cell, q, line))
                R.cells.append(cell)
                continue
            if ref == "same_as_last_year":
                ly = _last_year(history, vname, line["item_code"])
                if ly is None:
                    cell["status"] = "unresolved"
                    cell["steps"] = [f"Vendor wrote \"{src.get('verbatim', 'same as last year')}\" ({where})",
                                     f"No FY25-26 purchase order from {vname} for {line['item_code']} - no basis."]
                    R.flag(vid, lid, "UNRESOLVED_REFERENCE", "blocker",
                           f"'Same as last year' but we never bought {lid} from {vname}. Needs a price.", ov)
                    R.cells.append(cell)
                    continue
                cell["native"] = {"value": ly["price"], "currency": "INR", "basis": "per_piece"}
                cell["steps"].append(f"Vendor wrote \"{src.get('verbatim', 'same as last year')}\" ({where})")
                cell["steps"].append(f"Looked up last PO from {vname}: PO {ly['po']} dated {ly['date']} at "
                                     f"{_fmt(ly['price'])} per {line['uom']}")
                R.flag(vid, lid, "LAST_YEAR_PRICE", "warning",
                       f"Price inferred from PO {ly['po']} ({ly['date']}). The vendor did not restate it - confirm in writing.", ov)
                price, cur, basis, gst = ly["price"], "INR", "per_piece", "exclusive"
            else:
                price = q.get("price_value")
                if price is None:
                    cell["status"] = "unresolved"
                    cell["steps"] = [f"No readable price ({where})"]
                    R.flag(vid, lid, "PRICE_MISSING", "blocker", "Line matched but no price could be read.", ov)
                    R.cells.append(cell)
                    continue
                cur = (q.get("currency") or "INR").upper()
                basis = q.get("price_basis")
                gst = q.get("gst_treatment")
                cell["native"] = {"value": price, "currency": cur, "basis": basis}
                cell["steps"].append(f"Vendor wrote: {cur} {price:,.4g} {basis.replace('_', ' ')} "
                                     f"(\"{src.get('verbatim', '')}\", {where})")
                ev = _evidence_ok(q, docs_by_file)
                if ev is False:
                    R.flag(vid, lid, "EVIDENCE_NOT_FOUND", "warning",
                           f"Could not find the cited text in {src.get('file')}. Check the source.", ov)
                if ev is None and rec.get("second_read"):
                    p2, raw2 = _second_read_price(rec["second_read"], lid)
                    if p2 is None:
                        R.flag(vid, lid, "SECOND_READ_MISSING", "warning",
                               "The independent second read of the photo did not find this row.", ov)
                    elif abs(p2 - price) > 0.005 * max(price, 1):
                        R.flag(vid, lid, "DOUBLE_READ_MISMATCH", "blocker",
                               f"Two independent reads of the photo disagree: {price:g} vs '{raw2}'.", ov)
                    else:
                        cell["steps"].append(f"Second independent read of the photo agrees ('{raw2}')")

            p = _apply_units(cell, R, ov, vid, lid, line, price, cur, basis, gst, doc_gst, doc_gst_rate, settings)
            if p is None:
                R.cells.append(cell)
                continue
            for d in uncond:
                p = p * (1 - d["pct"] / 100)
                cell["steps"].append(f"Less unconditional discount {d['pct']:g}% -> {_fmt(p)}")
            cell["ex_works"] = p
            resolved_price[lid] = p
            _apply_freight(cell, freight_factor, fb, fv)
            cell["status"] = "ok"
            R.cells.append(cell)

        for cell, q, line in pending_refs:
            lid = line["line_id"]
            ref_id = q.get("reference_line_id")
            src = q.get("source") or {}
            base = resolved_price.get(ref_id)
            cell["steps"].append(f"Vendor wrote \"{src.get('verbatim', '')}\" ({src.get('file')}, {src.get('locator')})")
            if base is None:
                cell["status"] = "unresolved"
                R.flag(vid, lid, "UNRESOLVED_REFERENCE", "blocker", f"Priced 'same as {ref_id}', but {ref_id} has no price.", ov)
                continue
            cell["steps"].append(f"Same rate as {ref_id}: {_fmt(base)} per {line['uom']} ex-GST")
            R.flag(vid, lid, "REFERENCED_PRICE", "info", f"Priced by reference to {ref_id}.", ov)
            cell["ex_works"] = base
            cell["native"] = {"value": base, "currency": "INR", "basis": f"same as {ref_id}"}
            _apply_freight(cell, freight_factor, fb, fv)
            cell["status"] = "ok"

        # ---- questionnaire ---------------------------------------------------
        _qualify(R, vid, vname, res, rfx, settings, ov)

    _outliers(R, lines, ov)
    _finalise(R, lines)
    return R


def _apply_units(cell, R, ov, vid, lid, line, price, cur, basis, gst, doc_gst, doc_gst_rate, settings):
    p = float(price)
    if cur != "INR":
        rate = settings.fx.get(cur)
        if rate is None:
            cell["status"] = "unresolved"
            R.flag(vid, lid, "UNKNOWN_CURRENCY", "blocker", f"No FX rate set for {cur}.", ov)
            return None
        p *= rate
        cell["steps"].append(f"x {rate:g} INR/{cur} (buyer's assumed rate - change it in Settings) -> {_fmt(p)}")
        R.flag(vid, lid, "FX_CONVERTED", "info", f"Converted from {cur} at {rate:g}.", ov)
    div = {"per_piece": 1, "per_set": 1, "per_100": 100, "per_1000": 1000, "per_dozen": 12}.get(basis)
    if basis == "per_bundle":
        div = cell["quote"].get("bundle_size")
    if basis == "per_kg":
        w = line["nominal_weight_kg"]
        p *= w
        cell["steps"].append(f"Per-kg rate x RFx nominal weight {w} kg -> {_fmt(p)} per {line['uom']}")
        R.flag(vid, lid, "PER_KG_ASSUMED_WEIGHT", "warning",
               f"Quoted per kg. Converted with our nominal weight ({w} kg); the vendor's actual box weight "
               "decides the invoice. Ask for weight per box.", ov)
    elif div:
        if div != 1:
            p /= div
            cell["steps"].append(f"/ {div} ({basis.replace('_', ' ')} -> per {line['uom']}) -> {_fmt(p)}")
    else:
        cell["status"] = "unresolved"
        R.flag(vid, lid, "UNKNOWN_BASIS", "blocker",
               f"Price basis '{basis}' cannot be converted to per {line['uom']} automatically.", ov)
        return None
    if gst == "not_stated" and doc_gst:
        gst = doc_gst
    if gst == "inclusive":
        rate = cell["quote"].get("gst_rate_pct") or doc_gst_rate or settings.default_gst_pct
        p /= 1 + rate / 100
        cell["steps"].append(f"Remove GST included at {rate:g}% -> {_fmt(p)} ex-GST")
        R.flag(vid, lid, "GST_REMOVED", "info", f"Quoted GST-inclusive; {rate:g}% backed out.", ov)
    return p


def _apply_freight(cell, factor, fb, fv):
    if factor is None:
        cell["landed"] = None
        cell["steps"].append("Freight not known -> landed price unavailable; ex-works used for comparison")
    elif factor == 1.0:
        cell["landed"] = cell["ex_works"]
        cell["steps"].append("Freight included -> landed = ex-works")
    else:
        cell["landed"] = cell["ex_works"] * factor
        cell["steps"].append(f"+ {fv:g}% freight -> landed {_fmt(cell['landed'])}")


def _qualify(R, vid, vname, res, rfx, settings, ov):
    answers = {a["qid"]: a for a in res.get("questionnaire", [])}
    certs = res.get("certificates", [])
    overall = []
    for q in rfx["questionnaire"]:
        a = answers.get(q["qid"])
        rule = q.get("rule")
        result, reason = "info", ""
        if rule:
            result, reason = _eval_rule(rule, a, certs, settings)
        qk = f"{vid}:Q:{q['qid']}"
        if qk in ov["qual"]:
            result, reason = ov["qual"][qk]["result"], f"Buyer override: {ov['qual'][qk]['note']}"
        R.questionnaire.append({
            "vendor_id": vid, "vendor_name": vname, "qid": q["qid"], "question": q["text"],
            "knockout": q.get("knockout", False), "criterion": q.get("criterion"),
            "answered": bool(a and a.get("answered")), "answer_text": (a or {}).get("answer_text"),
            "value_number": (a or {}).get("value_number"), "result": result, "reason": reason,
            "source": (a or {}).get("source")})
        if q.get("knockout"):
            overall.append((q["qid"], result, reason))
            if result in ("fail", "unknown"):
                R.flag(vid, None, f"QUAL_{q['qid']}_{result.upper()}", "warning", f"{q['qid']} {result}: {reason}", ov)
            elif "BORDERLINE" in reason:
                R.flag(vid, None, f"QUAL_{q['qid']}_BORDERLINE", "warning", f"{q['qid']} passes only at the edge: {reason}", ov)
    fails = [o for o in overall if o[1] == "fail"]
    unknown = [o for o in overall if o[1] == "unknown"]
    status = "failed" if fails else ("unverified" if unknown else "cleared")
    R.vendors[vid].update(qualification=status,
                          qualification_reasons=[f"{o[0]}: {o[2]}" for o in fails + unknown],
                          certificates=certs)


def _eval_rule(rule, a, certs, settings):
    if not a or not a.get("answered"):
        return "unknown", "not answered"
    op = rule["op"]
    txt = (a.get("answer_text") or "").strip().lower()
    yes = a.get("value_bool")
    if yes is None:
        yes = True if txt.startswith(("yes", "y ")) or txt == "y" else (False if txt.startswith("no") else None)
    if op == "yes":
        return ("pass", "answered yes") if yes else (("fail", "answered no") if yes is False else ("unknown", f"unclear: '{a.get('answer_text')}'"))
    if op == "yes_and_valid_cert":
        if not yes:
            return ("fail", "answered no") if yes is False else ("unknown", "unclear answer")
        std = rule.get("cert", "").replace("ISO", "").strip()
        match = [c for c in certs if std in (c.get("standard") or "") and c.get("valid_until")]
        if not match:
            return "unknown", "says yes, but no certificate copy with a validity date was attached"
        valid = [c for c in match if (c.get("valid_until") or "") >= settings.contract_start]
        if valid:
            return "pass", f"certificate valid until {valid[0]['valid_until']}"
        return "fail", (f"says yes, but the attached certificate expired on {match[0].get('valid_until')} "
                        f"(contract starts {settings.contract_start})")
    if op in (">=", "<="):
        if a.get("is_range") and a.get("range_low") is not None:
            v = a["range_low"] if op == ">=" else (a.get("range_high") or a["range_low"])
            note = f"range {a.get('range_low'):g}-{a.get('range_high') or '?'}; used the conservative end {v:g}"
            ok = v >= rule["value"] if op == ">=" else v <= rule["value"]
            border = v == rule["value"] or a.get("is_vague")
            return ("pass" if ok else "fail"), (f"{v:g} {'meets' if ok else 'misses'} {op} {rule['value']} ({note})"
                                                + ("; BORDERLINE - stated as approximate, confirm" if ok and border else ""))
        else:
            v, note = a.get("value_number"), ""
        if v is None or a.get("is_vague"):
            return "unknown", f"vague answer '{a.get('answer_text')}', cannot verify {op} {rule['value']}"
        ok = v >= rule["value"] if op == ">=" else v <= rule["value"]
        return ("pass" if ok else "fail"), (f"{v:g} {'meets' if ok else 'misses'} {op} {rule['value']}" + (f" ({note})" if note else ""))
    return "info", ""


def _outliers(R, lines, ov):
    df = pd.DataFrame([c for c in R.cells if c.get("ex_works") is not None])
    if df.empty:
        return
    for lid, g in df.groupby("line_id"):
        if len(g) < 3:
            continue
        for _, r in g.iterrows():
            others = g[g["vendor_id"] != r["vendor_id"]]["ex_works"]
            med = others.median()
            ratio = r["ex_works"] / med if med else 1
            if ratio > config.OUTLIER_HIGH or ratio < config.OUTLIER_LOW:
                R.flag(r["vendor_id"], lid, "PRICE_OUTLIER", "blocker",
                       f"{_fmt(r['ex_works'])} is {ratio:.1f}x the other vendors' median ({_fmt(med)}). "
                       "Likely a unit or basis error (per box vs per 100?).", ov)


def _finalise(R, lines):
    open_by_cell = {}
    for f in R.flags:
        if f["line_id"] and f["status"] == "open":
            open_by_cell.setdefault((f["vendor_id"], f["line_id"]), []).append(f)
    for c in R.cells:
        fl = open_by_cell.get((c["vendor_id"], c["line_id"]), [])
        c["flags"] = [f["code"] for f in fl]
        c["has_blocker"] = any(f["severity"] == "blocker" for f in fl)
        c["has_warning"] = any(f["severity"] == "warning" for f in fl)
        if c["status"] == "ok":
            c["status"] = "needs_review" if c["has_blocker"] else ("assumption" if c["has_warning"] else "ok")
        c["comparable"] = c["landed"] if c.get("landed") is not None else c.get("ex_works")
        c["comparable_basis"] = "landed" if c.get("landed") is not None else ("ex-works" if c.get("ex_works") is not None else None)
        c["annual_qty"] = lines[c["line_id"]]["annual_qty"]
        c["annual_value"] = c["comparable"] * c["annual_qty"] if c["comparable"] is not None else None
    R.flags.sort(key=lambda f: (f["status"] != "open", SEV_RANK[f["severity"]], f["vendor_id"], f["line_id"] or ""))


def tables(R: Result):
    """Flat DataFrames - the single source for the grid, the analyst and exports."""
    rfx = load_rfx()
    hist = load_history()
    ly = {}
    if not hist.empty:
        last = hist.sort_values("po_date").groupby("item_code").last()
        ly = last["unit_price_inr"].to_dict()
    lines = pd.DataFrame([{**{k: l[k] for k in ("line_id", "item_code", "description", "kind", "dimensions_mm", "ply",
                                                "print", "uom", "annual_qty", "nominal_weight_kg")},
                           "last_year_price": ly.get(l["item_code"])} for l in rfx["lines"]])
    quotes = pd.DataFrame([{
        "vendor_id": c["vendor_id"], "vendor_name": c["vendor_name"], "line_id": c["line_id"], "status": c["status"],
        "native_price": (c["native"] or {}).get("value"), "native_currency": (c["native"] or {}).get("currency"),
        "native_basis": (c["native"] or {}).get("basis"), "unit_price_ex_works": c.get("ex_works"),
        "landed_unit_price": c.get("landed"), "comparable_price": c["comparable"],
        "comparable_basis": c["comparable_basis"], "annual_qty": c["annual_qty"], "annual_value": c["annual_value"],
        "has_blocker": c["has_blocker"], "has_warning": c["has_warning"], "flag_codes": ",".join(c["flags"]),
    } for c in R.cells])
    vendors = pd.DataFrame([{k: v for k, v in x.items() if k not in ("conditional_discounts", "unconditional_discounts",
                                                                       "reader_notes", "files", "certificates",
                                                                       "qualification_reasons")}
                            | {"qualification_reasons": "; ".join(x.get("qualification_reasons", [])),
                               "conditional_discount_pct": (x["conditional_discounts"][0]["pct"] if x["conditional_discounts"] else None),
                               "conditional_discount_min_value_inr": (x["conditional_discounts"][0].get("min_annual_value_inr") if x["conditional_discounts"] else None),
                               "conditional_discount_text": (x["conditional_discounts"][0].get("condition_text") if x["conditional_discounts"] else None),
                               "lines_quoted": int(((quotes["vendor_id"] == x["vendor_id"]) & quotes["comparable_price"].notna()).sum()) if not quotes.empty else 0}
                            for x in R.vendors.values()])
    flags = pd.DataFrame(R.flags) if R.flags else pd.DataFrame(columns=["flag_id", "vendor_id", "line_id", "code", "severity", "message", "status", "resolution_note"])
    quest = pd.DataFrame([{k: v for k, v in q.items() if k != "source"} for q in R.questionnaire])
    hist_df = hist.rename(columns={"unit_price_inr": "unit_price"}) if not hist.empty else hist
    return {"lines": lines, "quotes": quotes, "vendors": vendors, "flags": flags, "questionnaire": quest,
            "po_history": hist_df}
