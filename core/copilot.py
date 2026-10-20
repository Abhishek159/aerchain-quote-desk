"""RFx co-pilot: the buyer talks, the draft RFx updates.

The model edits a structured draft through tools (never free text), so the
RFx stays machine-readable for extraction and comparison later.
"""
import json
import shutil
from datetime import datetime

from google.genai import types

from . import config, llm, store

EMPTY_DRAFT = {"rfx_id": "", "title": "", "category": "", "scope": "", "buyer": {}, "issued_on": "", "due_on": "",
               "lines": [], "questionnaire": [], "terms": {}, "vendors_invited": []}

SYSTEM = """You are an RFx co-pilot for a category buyer at Meghna Foods Pvt. Ltd. (Chakan plant, Pune; FMCG snacks,
biscuits, beverages). You turn a conversation into a complete, unambiguous RFx by calling tools that edit the
draft. Behave like an experienced sourcing manager:
- Ask for what is missing, but propose sensible defaults instead of interrogating (e.g. ex-GST, delivered plant,
  60-day payment, 12-month validity).
- Line items need: description, dimensions (L x W x H mm, internal), ply, board spec, print, unit of measure,
  annual quantity. Use ids L01, L02, ... For corrugated boxes estimate nominal_weight_kg if you can, and say so.
- Write a supplier questionnaire with clear pass criteria; mark true knock-outs (knockout=true) and give
  machine-checkable rules where possible: {"op":"yes"}, {"op":">=","value":N}, {"op":"<=","value":N},
  {"op":"yes_and_valid_cert","cert":"ISO 9001"}.
- Terms must state currency, price basis, GST treatment, freight, payment, validity, quote due date.
- Point out anything that will make quotes hard to compare later (missing units, vague specs).
Keep replies short. After editing, summarise what changed in one or two lines.
You only draft RFx documents. If the buyer asks about quotes already received (prices, vendors, certificates,
who passed, award), do not guess: tell them to use the "5 · Ask the data" page, which has the vendors' data."""

LINE = {"type": "object", "properties": {
    "line_id": {"type": "string"}, "item_code": {"type": "string"}, "description": {"type": "string"},
    "kind": {"type": "string"}, "dimensions_mm": {"type": "string"}, "ply": {"type": "integer"},
    "board_spec": {"type": "string"}, "print": {"type": "string"}, "uom": {"type": "string"},
    "annual_qty": {"type": "integer"}, "nominal_weight_kg": {"type": "number"}}, "required": ["line_id", "description"]}
QUESTION = {"type": "object", "properties": {
    "qid": {"type": "string"}, "text": {"type": "string"}, "type": {"type": "string"},
    "criterion": {"type": "string"}, "knockout": {"type": "boolean"},
    "rule": {"type": "object", "properties": {"op": {"type": "string"}, "value": {"type": "number"}, "cert": {"type": "string"}}}},
    "required": ["qid", "text"]}

TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(name="set_header", description="Set RFx header fields (only those given are changed).",
                              parameters_json_schema={"type": "object", "properties": {
                                  "rfx_id": {"type": "string"}, "title": {"type": "string"}, "category": {"type": "string"},
                                  "scope": {"type": "string"}, "issued_on": {"type": "string"}, "due_on": {"type": "string"}}}),
    types.FunctionDeclaration(name="upsert_lines", description="Add or replace line items by line_id.",
                              parameters_json_schema={"type": "object", "properties": {"lines": {"type": "array", "items": LINE}},
                                                      "required": ["lines"]}),
    types.FunctionDeclaration(name="remove_lines", description="Remove line items.",
                              parameters_json_schema={"type": "object", "properties": {"line_ids": {"type": "array", "items": {"type": "string"}}},
                                                      "required": ["line_ids"]}),
    types.FunctionDeclaration(name="upsert_questions", description="Add or replace questionnaire questions by qid.",
                              parameters_json_schema={"type": "object", "properties": {"questions": {"type": "array", "items": QUESTION}},
                                                      "required": ["questions"]}),
    types.FunctionDeclaration(name="set_terms", description="Set commercial terms (merged into existing).",
                              parameters_json_schema={"type": "object", "properties": {"terms": {"type": "object", "properties": {
                                  "currency": {"type": "string"}, "price_basis": {"type": "string"}, "payment_terms": {"type": "string"},
                                  "validity": {"type": "string"}, "delivery": {"type": "string"}, "quote_due": {"type": "string"},
                                  "gst": {"type": "string"}, "freight": {"type": "string"}}}}, "required": ["terms"]}),
    types.FunctionDeclaration(name="set_vendors", description="Set the vendors to invite.",
                              parameters_json_schema={"type": "object", "properties": {"vendors": {"type": "array", "items": {
                                  "type": "object", "properties": {"vendor_id": {"type": "string"}, "name": {"type": "string"},
                                                                   "email": {"type": "string"}}, "required": ["name"]}}},
                                  "required": ["vendors"]}),
])]


def load_draft():
    if config.RFX_DRAFT.exists():
        return json.loads(config.RFX_DRAFT.read_text())
    return json.loads(json.dumps(EMPTY_DRAFT))


def save_draft(d):
    config.RFX_DRAFT.write_text(json.dumps(d, indent=2, ensure_ascii=False))


def load_published_as_draft():
    d = json.loads(config.RFX_FILE.read_text())
    save_draft(d)
    return d


def _apply(d, name, a):
    if name == "set_header":
        d.update({k: v for k, v in a.items() if v})
    elif name == "upsert_lines":
        idx = {l["line_id"]: i for i, l in enumerate(d["lines"])}
        for l in a["lines"]:
            if l["line_id"] in idx:
                d["lines"][idx[l["line_id"]]].update(l)
            else:
                d["lines"].append(l)
        d["lines"].sort(key=lambda l: l["line_id"])
    elif name == "remove_lines":
        d["lines"] = [l for l in d["lines"] if l["line_id"] not in set(a["line_ids"])]
    elif name == "upsert_questions":
        idx = {q["qid"]: i for i, q in enumerate(d["questionnaire"])}
        for q in a["questions"]:
            if q["qid"] in idx:
                d["questionnaire"][idx[q["qid"]]].update(q)
            else:
                d["questionnaire"].append(q)
    elif name == "set_terms":
        d.setdefault("terms", {}).update(a["terms"])
    elif name == "set_vendors":
        d["vendors_invited"] = [{"vendor_id": v.get("vendor_id") or f"V{i}", **v} for i, v in enumerate(a["vendors"], 1)]
    return {"ok": True, "lines": len(d["lines"]), "questions": len(d["questionnaire"])}


def chat(history, message):
    """history: list of (role, text). Returns (reply, changes)."""
    d = load_draft()
    state = json.dumps({k: d[k] for k in d if k != "lines"} | {"lines": d["lines"][:60]}, ensure_ascii=False)
    contents = [types.Content(role=r, parts=[types.Part.from_text(text=t)]) for r, t in history[-10:]]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(
        text=f"CURRENT DRAFT (JSON):\n{state}\n\nBUYER: {message}")]))
    changes = []
    for _ in range(6):
        resp = llm.generate(contents, purpose="copilot", models=config.ANALYST_MODELS, system=SYSTEM,
                            tools=TOOLS, temperature=0.3)
        calls = resp.function_calls or []
        if not calls:
            save_draft(d)
            return resp.text or "", changes
        contents.append(resp.candidates[0].content)
        parts = []
        for fc in calls:
            out = _apply(d, fc.name, dict(fc.args or {}))
            changes.append(fc.name)
            parts.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=parts))
    save_draft(d)
    return "Draft updated.", changes


def publish(draft):
    """Stubbed send: writes one .eml-style file per vendor to the outbox and
    makes the draft the live RFx that extraction uses."""
    if config.RFX_FILE.exists():
        backup = config.RFX_FILE.with_name("rfx.before_publish.json")
        if not backup.exists():
            shutil.copy(config.RFX_FILE, backup)
    config.RFX_FILE.write_text(json.dumps(draft, indent=2, ensure_ascii=False))
    sent = []
    for v in draft.get("vendors_invited", []):
        body = (f"To: {v.get('email', '')}\nSubject: RFx {draft['rfx_id']} - {draft['title']}\n\n"
                f"Dear {v['name']},\n\nMeghna Foods invites your quotation for {draft['title']}.\n"
                f"Scope: {draft.get('scope', '')}\nQuote due: {draft.get('due_on', '')}\n"
                f"Price basis: {draft.get('terms', {}).get('price_basis', '')}\n\n"
                f"{len(draft['lines'])} line items and {len(draft['questionnaire'])} questionnaire items are in the "
                "attached template. You may reply in any format you prefer.\n\nRegards,\n"
                f"{draft.get('buyer', {}).get('contact', 'Category Manager - Packaging')}\n")
        p = config.OUTBOX / f"{datetime.now():%Y%m%d-%H%M%S}_{v.get('vendor_id', 'V')}.eml"
        p.write_text(body)
        sent.append(p.name)
    store.audit("rfx_published", {"rfx_id": draft["rfx_id"], "vendors": len(sent)}, "buyer")
    return sent
