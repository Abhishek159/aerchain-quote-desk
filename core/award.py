"""Award scenarios. Pure code: the analyst agent chooses the parameters,
this module does the arithmetic, so totals are reproducible."""
import pandas as pd


def simulate(t, strategy="cheapest_per_line", vendors=None, require_qualified=False,
             exclude_blockers=True, max_share_pct=None, single_vendor=None,
             apply_conditional_discounts=True, lines=None):
    q = t["quotes"].copy()
    v = t["vendors"].set_index("vendor_id")
    L = t["lines"].set_index("line_id")
    caveats = []

    cand = q[q["comparable_price"].notna() & ~q["status"].isin(["excluded", "not_quoted", "unresolved"])]
    if lines:
        cand = cand[cand["line_id"].isin(lines)]
    if vendors:
        cand = cand[cand["vendor_id"].isin(vendors)]
    if require_qualified:
        ok = v.index[v["qualification"] == "cleared"].tolist()
        dropped = sorted(set(cand["vendor_id"]) - set(ok))
        if dropped:
            caveats.append("Excluded as not cleared on the questionnaire: " + ", ".join(
                f"{d} {v.loc[d, 'vendor_name']} ({v.loc[d, 'qualification']})" for d in dropped))
        cand = cand[cand["vendor_id"].isin(ok)]
    if exclude_blockers:
        blocked = cand[cand["has_blocker"]]
        if len(blocked):
            caveats.append(f"{len(blocked)} quote(s) with unreviewed blockers left out: " +
                           ", ".join(f"{r.vendor_id}/{r.line_id}" for r in blocked.itertuples()))
        cand = cand[~cand["has_blocker"]]
    if strategy == "single_vendor":
        if not single_vendor:
            raise ValueError("single_vendor strategy needs single_vendor")
        cand = cand[cand["vendor_id"] == single_vendor]

    scope = lines or L.index.tolist()
    ranked = cand.sort_values(["line_id", "comparable_price"])
    award = {}
    if strategy in ("cheapest_per_line", "single_vendor") or not max_share_pct:
        for lid, g in ranked.groupby("line_id"):
            award[lid] = g.iloc[0]
    if strategy == "cheapest_per_line" and max_share_pct:
        award = {}
        total_est = ranked.groupby("line_id")["annual_value"].min().sum()
        cap = total_est * max_share_pct / 100
        share = {}
        order = ranked.groupby("line_id")["annual_value"].min().sort_values(ascending=False).index
        for lid in order:
            for _, r in ranked[ranked["line_id"] == lid].iterrows():
                if share.get(r["vendor_id"], 0) + r["annual_value"] <= cap:
                    award[lid] = r
                    share[r["vendor_id"]] = share.get(r["vendor_id"], 0) + r["annual_value"]
                    break
            else:
                g = ranked[ranked["line_id"] == lid]
                if len(g):
                    award[lid] = g.iloc[0]
                    caveats.append(f"{lid}: no vendor fits under the {max_share_pct:g}% cap; gave it to the cheapest.")
        caveats.append(f"Share cap applied greedily, biggest lines first (cap {max_share_pct:g}% of "
                       f"~Rs {total_est / 1e7:.2f} cr). Good, not guaranteed optimal.")

    rows = []
    for lid in scope:
        line = L.loc[lid]
        if lid not in award:
            rows.append({"line_id": lid, "description": line["description"], "vendor_id": None, "vendor_name": None,
                         "unit_price": None, "annual_qty": int(line["annual_qty"]), "annual_value": None,
                         "basis": None, "runner_up": None, "runner_up_price": None,
                         "last_year_price": line["last_year_price"], "status": "NO ELIGIBLE QUOTE"})
            continue
        r = award[lid]
        others = ranked[(ranked["line_id"] == lid) & (ranked["vendor_id"] != r["vendor_id"])]
        ru = others.iloc[0] if len(others) else None
        rows.append({"line_id": lid, "description": line["description"], "vendor_id": r["vendor_id"],
                     "vendor_name": r["vendor_name"], "unit_price": round(r["comparable_price"], 4),
                     "annual_qty": int(line["annual_qty"]), "annual_value": r["annual_value"],
                     "basis": r["comparable_basis"], "runner_up": None if ru is None else ru["vendor_id"],
                     "runner_up_price": None if ru is None else round(ru["comparable_price"], 4),
                     "last_year_price": line["last_year_price"], "status": r["status"]})
    df = pd.DataFrame(rows)
    by_vendor = df.dropna(subset=["vendor_id"]).groupby(["vendor_id", "vendor_name"]).agg(
        lines=("line_id", "count"), value=("annual_value", "sum")).reset_index()

    disc_total = 0.0
    disc_notes = []
    df["net_value"] = df["annual_value"]
    for _, b in by_vendor.iterrows():
        vv = v.loc[b["vendor_id"]]
        pct = vv.get("conditional_discount_pct")
        if pd.isna(pct) if pct is not None else True:
            continue
        thr = vv.get("conditional_discount_min_value_inr")
        if not apply_conditional_discounts:
            disc_notes.append(f"{b['vendor_id']}: {pct:g}% conditional discount not applied (switched off).")
        elif thr is None or pd.isna(thr):
            disc_notes.append(f"{b['vendor_id']}: {pct:g}% discount condition could not be evaluated "
                              f"('{vv.get('conditional_discount_text')}') - not applied.")
        elif b["value"] >= thr:
            d = b["value"] * pct / 100
            disc_total += d
            m = df["vendor_id"] == b["vendor_id"]
            df.loc[m, "net_value"] = df.loc[m, "annual_value"] * (1 - pct / 100)
            disc_notes.append(f"{b['vendor_id']}: awarded Rs {b['value'] / 1e5:.1f} lakh >= Rs {thr / 1e5:.0f} lakh, "
                              f"so the {pct:g}% discount applies (-Rs {d / 1e5:.2f} lakh).")
        else:
            disc_notes.append(f"{b['vendor_id']}: awarded Rs {b['value'] / 1e5:.1f} lakh < Rs {thr / 1e5:.0f} lakh - "
                              f"{pct:g}% discount does NOT apply.")
    exw = df[df["basis"] == "ex-works"]
    if len(exw):
        caveats.append(f"{len(exw)} awarded line(s) priced ex-works because freight is unknown "
                       f"({', '.join(sorted(set(exw['vendor_id'])))}); true landed cost is higher.")
    assumed = df[df["status"].isin(["assumption"])]
    if len(assumed):
        caveats.append(f"{len(assumed)} awarded line(s) rest on assumptions (warnings) - see flags.")
    gross = df["annual_value"].sum()
    ly = df.dropna(subset=["annual_value", "last_year_price"])
    ly_value = (ly["last_year_price"] * ly["annual_qty"]).sum()
    return {
        "params": {"strategy": strategy, "vendors": vendors, "require_qualified": require_qualified,
                   "exclude_blockers": exclude_blockers, "max_share_pct": max_share_pct,
                   "single_vendor": single_vendor, "apply_conditional_discounts": apply_conditional_discounts},
        "rows": df, "by_vendor": by_vendor,
        "total_gross": gross, "conditional_discounts": disc_total, "total_net": gross - disc_total,
        "lines_awarded": int(df["vendor_id"].notna().sum()), "lines_uncovered": df[df["vendor_id"].isna()]["line_id"].tolist(),
        "last_year_value_same_lines": ly_value, "this_year_value_same_lines": ly["annual_value"].sum(),
        "this_year_net_value_same_lines": df.loc[ly.index, "net_value"].sum(),
        "discount_notes": disc_notes, "caveats": caveats,
    }


def summary(res, max_rows=40):
    """JSON-safe summary for the analyst agent."""
    df = res["rows"]
    return {
        "params": res["params"],
        "total_gross_inr": round(res["total_gross"], 0), "conditional_discounts_inr": round(res["conditional_discounts"], 0),
        "total_net_inr": round(res["total_net"], 0), "lines_awarded": res["lines_awarded"],
        "lines_uncovered": res["lines_uncovered"],
        "last_year_value_same_lines_inr": round(res["last_year_value_same_lines"], 0),
        "this_year_value_same_lines_inr": round(res["this_year_value_same_lines"], 0),
        "this_year_net_value_same_lines_inr": round(res["this_year_net_value_same_lines"], 0),
        "note_on_last_year_comparison": "Compare last year against the NET figure (after conditional discounts); "
                                         "lines without a last-year price (new SKUs) are excluded from both.",
        "by_vendor": res["by_vendor"].round(0).to_dict("records"),
        "discount_notes": res["discount_notes"], "caveats": res["caveats"],
        "rows": df.head(max_rows).where(df.notna(), None).to_dict("records"),
    }
