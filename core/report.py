"""Award pack: an Excel workbook a reviewer can audit, and a short memo."""
import json
from datetime import datetime

import pandas as pd

from . import award, config, llm, store


def comparison_matrix(t):
    q = t["quotes"]
    m = q.pivot(index="line_id", columns="vendor_id", values="comparable_price")
    s = q.pivot(index="line_id", columns="vendor_id", values="status")
    L = t["lines"].set_index("line_id")[["description", "annual_qty", "last_year_price"]]
    out = L.join(m.round(2))
    for v in s.columns:
        out[f"{v} status"] = s[v]
    return out.reset_index()


INR = '[>=10000000]"₹"##\\,##\\,##\\,##0;[>=100000]"₹"##\\,##\\,##0;"₹"##,##0'
QTY = '[>=10000000]##\\,##\\,##\\,##0;[>=100000]##\\,##\\,##0;##,##0'
MONEY_COLS = {"annual_value", "net_value", "value", "conditional_discount_min_value_inr"}
PRICE_COLS = {"unit_price", "runner_up_price", "last_year_price", "unit_price_ex_works", "landed_unit_price",
              "comparable_price"}
QTY_COLS = {"annual_qty", "qty", "lines", "lines_quoted"}
STATUS_FILL = {"ok": None, "buyer_override": "#E3F0FF", "assumption": "#FFF4D6", "needs_review": "#FFE0E0",
               "not_quoted": "#F0F0F0", "unresolved": "#FFE0E0", "excluded": "#F0F0F0",
               "blocker": "#FFE0E0", "warning": "#FFF4D6", "pass": "#E3F5E8", "fail": "#FFE0E0",
               "unknown": "#FFF4D6", "cleared": "#E3F5E8", "failed": "#FFE0E0", "unverified": "#FFF4D6",
               "NO ELIGIBLE QUOTE": "#FFE0E0"}


def _strategy_text(p):
    parts = ["Cheapest price per line (split award)" if p["strategy"] == "cheapest_per_line"
             else f"Single vendor: {p.get('single_vendor')}"]
    parts.append("only vendors who cleared the questionnaire" if p.get("require_qualified") else "all vendors")
    if p.get("exclude_blockers", True):
        parts.append("quotes with open blockers left out")
    if p.get("max_share_pct"):
        parts.append(f"max {p['max_share_pct']:g}% of value per vendor")
    parts.append("conditional discounts applied when earned" if p.get("apply_conditional_discounts", True)
                 else "conditional discounts ignored")
    if p.get("vendors"):
        parts.append("vendor pool: " + ", ".join(p["vendors"]))
    return "; ".join(parts)


def _sheet(xw, df, name, fmt):
    df = df.copy()
    df.to_excel(xw, sheet_name=name, index=False)
    ws = xw.sheets[name]
    for i, col in enumerate(df.columns):
        ws.write(0, i, col, fmt["head"])
        c = str(col)
        f = (fmt["inr"] if c in MONEY_COLS else fmt["price"] if c in PRICE_COLS or (name == "Comparison" and c.startswith("V") and " " not in c)
             else fmt["qty"] if c in QTY_COLS else None)
        sample = df[col].fillna("").astype(str).str.len().quantile(0.9) if len(df) else 10
        sample = 10 if pd.isna(sample) else sample
        width = min(max(len(c) + 2, int(sample) + 2, 10), 60)
        ws.set_column(i, i, width, f)
        if c.endswith("status") or c in ("severity", "result", "qualification"):
            for val, color in STATUS_FILL.items():
                if color:
                    ws.conditional_format(1, i, len(df), i, {"type": "cell", "criteria": "==", "value": f'"{val}"',
                                                             "format": fmt[color]})
    ws.freeze_panes(1, 1)
    if len(df):
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)


def workbook(t, res, settings, path=None):
    path = path or config.EXPORTS / f"award_pack_{datetime.now():%Y%m%d-%H%M}.xlsx"
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        fmt = {"head": wb.add_format({"bold": True, "bg_color": "#F3E8E2", "border": 1, "text_wrap": True, "valign": "top"}),
               "inr": wb.add_format({"num_format": INR}), "price": wb.add_format({"num_format": '"₹"#,##0.00'}),
               "qty": wb.add_format({"num_format": QTY}), "title": wb.add_format({"bold": True, "font_size": 14}),
               "bold": wb.add_format({"bold": True}), "wrap": wb.add_format({"text_wrap": True, "valign": "top"}),
               "inr_bold": wb.add_format({"num_format": INR, "bold": True})}
        for color in set(c for c in STATUS_FILL.values() if c):
            fmt[color] = wb.add_format({"bg_color": color})

        ws = wb.add_worksheet("Summary")
        xw.sheets["Summary"] = ws
        ws.set_column(0, 0, 46)
        ws.set_column(1, 1, 90)
        ws.write(0, 0, f"Award pack - {json.loads(config.RFX_FILE.read_text())['rfx_id']}", fmt["title"])
        rows = [("Award rules", _strategy_text(res["params"]), "wrap"),
                ("Total, before discounts (per year)", round(res["total_gross"]), "inr"),
                ("Conditional discounts earned", round(res["conditional_discounts"]), "inr"),
                ("Total, net (per year)", round(res["total_net"]), "inr_bold"),
                ("Lines awarded", f"{res['lines_awarded']} of {len(res['rows'])}", None),
                ("Lines without an eligible quote", ", ".join(res["lines_uncovered"]) or "none", None),
                ("Same lines at last year's prices", round(res["last_year_value_same_lines"]), "inr"),
                ("Same lines in this award, net (new SKUs excluded)", round(res["this_year_net_value_same_lines"]), "inr"),
                ("Change vs last year", f"{(res['this_year_net_value_same_lines'] / res['last_year_value_same_lines'] - 1) * 100:+.1f}%"
                 if res["last_year_value_same_lines"] else "-", None),
                ("FX assumption", ", ".join(f"1 {k} = Rs {v:g}" for k, v in settings.fx.items() if k != "INR"), None),
                ("GST assumed when a vendor says 'incl.' without a rate", f"{settings.default_gst_pct:g}%", None),
                ("Prices compared as", "INR per piece/set, ex-GST, delivered Chakan (ex-works where freight is unknown)", None),
                ("Generated", datetime.now().strftime("%d %b %Y %H:%M"), None)]
        for i, (k, v, f) in enumerate(rows, start=2):
            ws.write(i, 0, k, fmt["bold"])
            ws.write(i, 1, v, fmt[f] if f else None)
        r0 = len(rows) + 4
        ws.write(r0, 0, "Caveats & discount evaluation", fmt["title"])
        for i, c in enumerate(res["caveats"] + res["discount_notes"], start=r0 + 1):
            ws.write(i, 0, "•")
            ws.write(i, 1, c, fmt["wrap"])

        _sheet(xw, res["rows"], "Award by line", fmt)
        _sheet(xw, res["by_vendor"], "Award by vendor", fmt)
        _sheet(xw, comparison_matrix(t), "Comparison", fmt)
        _sheet(xw, t["flags"], "Flags & assumptions", fmt)
        _sheet(xw, t["questionnaire"], "Questionnaire", fmt)
        _sheet(xw, t["vendors"].drop(columns=["folder", "freight_factor"], errors="ignore"), "Vendor terms", fmt)
        audit = pd.DataFrame(store.read_audit())
        if not audit.empty:
            audit["detail"] = audit["detail"].astype(str)
        _sheet(xw, audit if not audit.empty else pd.DataFrame(columns=["at", "who", "event", "detail"]), "Audit trail", fmt)
    store.audit("award_pack_exported", {"file": path.name, "params": res["params"]}, "buyer")
    return path


def memo(t, res):
    facts = json.dumps(award.summary(res, max_rows=30), default=str, ensure_ascii=False)
    vend = t["vendors"][["vendor_id", "vendor_name", "qualification", "qualification_reasons", "freight_text",
                         "payment_terms_days", "lead_time_days"]].to_json(orient="records")
    today = datetime.now().strftime("%d %B %Y")
    prompt = (f"Today is {today}; date the memo today. "
              "Write a one-page award recommendation memo (markdown) from the Category Manager - Packaging to the VP "
              "Procurement for RFx MFPL/PKG/RFQ/2026-27/014 (corrugated packaging). Sections: Recommendation, "
              "Why, Risks & open items, Next steps. Use ONLY the numbers in FACTS - do not compute new ones. "
              "State every caveat. Money in Indian style rounded sensibly (Rs 3.95 crore, Rs 8.05 lakh) - never raw "
              "integers or decimals like 39530625.0. Plain text symbols only (>=, not LaTeX).\n\n"
              f"FACTS (award simulation):\n{facts}\n\nVENDORS:\n{vend}")
    try:
        return llm.generate([prompt], purpose="memo", models=config.ANALYST_MODELS, temperature=0.3).text
    except llm.LLMError as e:
        lines = [f"- {r['vendor_id']} {r['vendor_name']}: {r['lines']} lines, Rs {r['value'] / 1e5:.1f} lakh"
                 for r in res["by_vendor"].to_dict("records")]
        return ("## Award recommendation (model unavailable - facts only)\n\n"
                f"Total: Rs {res['total_net'] / 1e7:.2f} crore/yr net of conditional discounts.\n\n" + "\n".join(lines) +
                "\n\n**Caveats**\n" + "\n".join(f"- {c}" for c in res["caveats"] + res["discount_notes"]) +
                f"\n\n_{e}_")
