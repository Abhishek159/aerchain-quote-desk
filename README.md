# Quote Desk — Kill the Quote Spreadsheet

Aerchain product take-home. A buyer drafts an RFx with a co-pilot, five vendors reply however they like,
the system reads every response, lands them in one comparable grid with provenance and doubt made
visible, and the buyer interrogates it in plain language down to an auditable award.

## Run it

```bash
uv run streamlit run app.py
```

Needs `GEMINI_API_KEY` in `.env` (Gemini Flash; ~₹ tens for the whole demo).
Regenerate the fabricated dataset any time: `uv run python scripts/generate_dataset.py`.
Unit test for the deterministic layer: `uv run python tests/test_normalize.py`.

## The dataset (fabricated, `data/`)

Meghna Foods (fictional FMCG, Chakan plant) · RFx `MFPL/PKG/RFQ/2026-27/014` · 30 corrugated lines
(3/5/7-ply RSC, partitions, pads, die-cut tray) · ~₹4.0 crore/yr at last year's prices · 10-question
supplier questionnaire with 4 knock-outs · FY25-26 PO history.

| Vendor | Sent | Ugly edge planted |
|---|---|---|
| V1 Pacifica | Own-format Excel, 3 tabs | **USD**, priced **per 100** (per 1000 for accessories), RFx order ignored, alternate offer on L12 |
| V2 Shree Ganesh | Letterhead PDF + annexure | **27 of 30** lines, **4% discount in a footnote** conditional on > ₹50 lakh, freight 2% extra |
| V3 Konkan Kraft | Word letter, prose | prices in paragraphs, **"L17 and L18 same as L16"**, per-thousand accessories, **spec deviation** 140 vs 150 GSM, capacity given as a **range** |
| V4 Pioneer | **Angled phone photo** of a rate card + 2-line email | matched by **size not line id**, **GST-inclusive**, pads **per 100**, 2 sizes we never asked for, **ISO certificate expired** although they answered "yes", rejection "below 2%" |
| V5 Maruti (incumbent) | One-line email | "₹42/kg for the 5-ply, 38 for the 3-ply, **rest same as last year, freight extra**" — per-kg, history lookup, two SKUs never bought before, no questionnaire |

Every file is rendered from a hidden answer key (`data/eval/ground_truth.json`) that the app never reads
while working; the *Extraction accuracy* page scores the live pipeline against it.

## How it works

```
vendor files ──► ingest (text + cell/para/page addresses; PDFs & photos sent natively)
             ──► LLM extraction: transcribe + match, never convert   (photos read twice, independently)
             ──► normalise in code: FX · per-100/1000/kg · GST back-out · freight · references · history
             ──► flags (blocker / warning / info) + qualification rules
             ──► grid with provenance · review queue · clarification emails
             ──► analyst agent (read-only SQL + award simulator + charts + exports) ──► award pack
```

| Folder | |
|---|---|
| `core/extract.py` | Gemini structured extraction + photo double-read |
| `core/normalize.py` | every conversion as a written step, every doubt as a flag |
| `core/award.py` | deterministic scenarios: split, single, share cap, qualified-only, conditional discounts |
| `core/analyst.py` | tool-using agent; can only answer through SQL / simulator |
| `core/copilot.py` | RFx drafting through tools on a structured draft |
| `core/clarify.py` | questions built from flags by code; model only writes the email |
| `core/evaluate.py` | scores against the answer key; reports *silent errors* |

## Demo script (recorded walkthrough)

1. **Inbox** — show the photo, the one-line email. "Read all responses."
2. **Comparison** — the grid. Point at V5: cheapest everywhere, all amber. Open a V5 cell → per-kg ×
   nominal weight, freight unknown. Open V4 L29 → photo crop, "/100 incl. GST" → ÷100 ÷1.05.
3. **Review** — blockers first. "Same as last year" for a SKU never bought. Draft the clarification email.
4. **Ask the data**
   - *What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?*
   - *Why isn't Pioneer in that? They're the cheapest.*
   - *How much of Maruti's apparent saving survives if freight is 4% and their boxes weigh 10% more than our spec?*
   - *Cap any vendor at 50% — what does supply security cost us?*
   - *Which lines go up vs last year under the qualified split? Chart it.*
   - *Export the award to Excel.*
5. **Award** — toggles, discount condition evaluated live, award pack + memo.
6. **Accuracy** — cells correct, and the number that matters: silent errors.

## Hosting (Streamlit Community Cloud)

1. Push this folder to GitHub (`.env` and the confidential brief are git-ignored).
2. share.streamlit.io → **Create app** → pick the repo, branch `main`, main file `app.py`,
   **Advanced settings → Python 3.12**.
3. **Secrets** (see `.streamlit/secrets.toml.example`):
   ```toml
   GEMINI_API_KEY = "..."
   DEMO_MODE = "1"      # original 5 vendors already read and locked; new uploads can be read
   BUDGET_INR = "150"   # all AI calls stop at this estimated spend
   ```
The saved extractions for V1-V5 are committed, so the hosted app opens fully populated.
Uploaded responses live on the container's disk and reset when the app restarts.

## Health check (no AI credit)

```bash
uv run python scripts/healthcheck.py
```
