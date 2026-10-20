"""One-command health check. Uses NO Gemini credit.

Run:  uv run python scripts/healthcheck.py
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail or ""))
    except Exception as e:  # report every failure, keep going
        results.append((False, name, f"{type(e).__name__}: {e}"))
        traceback.print_exc(limit=1)


def api_key():
    from core import config
    assert config.GEMINI_API_KEY, "GEMINI_API_KEY missing in .env"
    return "present in .env"


def input_files():
    from core import config, ingest
    assert config.RFX_FILE.exists(), "data/rfx/rfx.json missing"
    folders = ingest.vendor_folders()
    assert len(folders) == 5, f"expected 5 vendor folders, found {len(folders)}"
    return f"RFx + {len(folders)} vendor folders"


def extractions():
    from core import extract
    ex = extract.load_extractions()
    assert len(ex) == 5, f"only {len(ex)}/5 vendors read - use 'Read all responses' in the app"
    return "5/5 vendors read: " + ", ".join(f"{k}={v['model']}" for k, v in sorted(ex.items()))


def maths():
    import subprocess
    out = subprocess.run([sys.executable, "tests/test_normalize.py"], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stdout[-300:] + out.stderr[-300:]
    return "150/150 against answer key with a perfect reading"


def pipeline():
    from core import evaluate, extract, normalize
    R = normalize.build(extract.load_extractions())
    s = evaluate.score(R)
    assert not s["silent_errors"], f"{len(s['silent_errors'])} silent errors"
    return f"{s['correct']}/{s['total']} correct, {s['wrong_but_flagged']} wrong-but-flagged, 0 silent errors"


def award_and_export():
    from core import award, extract, normalize, report
    T = normalize.tables(normalize.build(extract.load_extractions()))
    r = award.simulate(T, require_qualified=True)
    assert r["lines_awarded"] == 30
    p = report.workbook(T, r, normalize.Settings())
    return f"qualified split Rs {r['total_net'] / 1e7:.2f} cr, Excel pack written ({p.name})"


def analyst_tools():
    from core import analyst, extract, normalize
    s = analyst.Session(normalize.tables(normalize.build(extract.load_extractions())))
    out = s.run_tool("run_sql", {"sql": "select count(*) n from quotes", "purpose": "t"}, [])
    assert out["rows"][0]["n"] == 150
    blocked = s.run_tool("run_sql", {"sql": "drop table quotes", "purpose": "t"}, [])
    assert "error" in blocked, "write query was not blocked"
    return "SQL works, writes blocked"


def app_pages():
    from streamlit.testing.v1 import AppTest
    bad = []
    for page in ["p_compare", "p_review", "p_award", "p_accuracy", "p_inbox", "p_copilot", "p_analyst"]:
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui" / f"{page}.py"), default_timeout=60).run()
        if at.exception:
            bad.append(f"{page}: {at.exception[0].message[:120]}")
    assert not bad, "; ".join(bad)
    return "all 7 pages render without errors"


for name, fn in [("Gemini key", api_key), ("Input files", input_files), ("Vendor reads", extractions),
                 ("Price maths", maths), ("Live accuracy", pipeline), ("Award + Excel", award_and_export),
                 ("Analyst tools", analyst_tools), ("App pages", app_pages)]:
    check(name, fn)

print("\n" + "=" * 60)
for ok, name, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:15} {detail}")
print("=" * 60)
failed = sum(not ok for ok, *_ in results)
print("ALL GOOD" if not failed else f"{failed} check(s) failed")
sys.exit(1 if failed else 0)
