"""Score the pipeline against the hidden ground truth (data/eval).

The question that matters for trust is not just "how many cells are right"
but "of the cells that are wrong, how many did we flag?" A wrong number
with a red flag costs the buyer a minute; a wrong number shown as firm
costs them money.
"""
import json

from . import config

TOL = 0.005  # 0.5%


def score(R):
    if not config.GROUND_TRUTH.exists():
        return None
    truth = json.loads(config.GROUND_TRUTH.read_text())
    cells = {(c["vendor_id"], c["line_id"]): c for c in R.cells}
    rows = []
    for vid, tv in truth["vendors"].items():
        for lid, t in tv["lines"].items():
            c = cells.get((vid, lid))
            want = t["inr_per_unit_ex_gst"]
            got = None if c is None else c.get("ex_works")
            flagged = bool(c and (c.get("has_blocker") or c.get("has_warning")))
            if c is None:
                verdict = "not extracted"
            elif want is None and got is None:
                verdict = "correct"
            elif want is None or got is None:
                verdict = "wrong"
            else:
                verdict = "correct" if abs(got - want) <= TOL * want else "wrong"
            rows.append({"vendor_id": vid, "line_id": lid, "truth_status": t["status"], "truth_inr": want,
                         "got_inr": got, "status": None if c is None else c["status"], "verdict": verdict,
                         "flagged": flagged, "truth_note": t.get("note", "")})
    qual = []
    for vid, tv in truth["vendors"].items():
        want = tv["questionnaire"].get("knockout_pass")
        got = R.vendors.get(vid, {}).get("qualification")
        qual.append({"vendor_id": vid, "truth_pass": want, "got": got,
                     "verdict": "correct" if (got == "cleared") == bool(want) else "wrong",
                     "truth_note": tv["questionnaire"].get("note", "")})
    n = len(rows)
    correct = sum(r["verdict"] == "correct" for r in rows)
    wrong = [r for r in rows if r["verdict"] != "correct"]
    return {
        "cells": rows, "qualification": qual, "total": n, "correct": correct,
        "accuracy": correct / n if n else 0, "wrong": len(wrong),
        "wrong_but_flagged": sum(r["flagged"] for r in wrong),
        "silent_errors": [r for r in wrong if not r["flagged"]],
    }
