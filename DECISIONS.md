# What I decided, and what I left out

**The thesis.** Reading messy quotes is now the easy part; a good model reads an angled photo. The hard
part is *comparability* and *trust*: knowing that "₹42/kg" is not comparable to "₹23.9 incl. GST" until
three assumptions are made, and showing the buyer which assumptions a number rests on. So the product
is built around one rule: **the model transcribes, code converts, and every doubt is visible.**

## Decisions

1. **The LLM never does arithmetic.** Extraction returns what the vendor *wrote* (value, currency, basis,
   GST treatment, citation). FX, per-100/1000/kg, GST back-out, freight, "same as L16", "same as last
   year" are applied by plain code that writes each step down. It's testable: given a perfect reading,
   normalisation hits the answer key on 150/150 cells.
2. **Three levels of doubt, not a confidence score.** *Blocker* (don't award on this), *warning* (usable,
   rests on an assumption), *info* (transformation applied). Buyers act on categories, not on 0.73.
3. **"Cheapest" means cheapest *firm* price.** The incumbent's per-kg email looks cheapest on 22 lines.
   It rests on our weight estimate, unknown freight and no questionnaire. The grid shows it in amber and
   never crowns it.
4. **Provenance on every cell.** Click → the photo crop / Excel row / PDF line it came from + the chain of
   conversions. Photos are read twice independently (double-keyed entry); disagreement is a blocker.
5. **Deterministic cross-checks catch model errors**: cited text must exist in the file, vendor dimensions
   must equal the RFx line, a price > 1.6× peer median is flagged as a likely unit error.
6. **Qualification is a rule, not a vibe.** Knock-outs are machine-checkable; the certificate's *expiry
   date* is read and checked against contract start. Pioneer says "ISO: yes" — the attachment expired
   in 2025. Ranges use the conservative end; vague answers ("below 2%") are *unknown*, not pass.
7. **The analyst can only answer through tools** (read-only SQL + an award simulator). Every answer has
   "How I got this" with the SQL. Conditional discounts are evaluated against the scenario
   (Shree Ganesh's 4% applies only if awarded > ₹50 lakh).
8. **When unsure, ask the vendor.** Clarification questions are generated from open flags by code
   (nothing missed, nothing invented); the model only writes the email.
9. **Buyer overrides are first-class and audited.** Correct / exclude / accept-with-note, all in the
   export's audit sheet.
10. **Measure what matters**: accuracy against a hidden answer key, and above all *silent errors* —
    wrong numbers shown as firm.

## Results on the demo dataset (Gemini Flash, live)

- **146 / 150 cells correct; the 4 misses are all flagged; 0 silent errors.** Excel in USD per 100,
  27-line PDF, prose Word letter and the angled photo: 30/30 each (the photo's two independent reads
  agreed on every row).
- The 4 misses are a genuine ambiguity: does "38 for the 3-ply" cover 3-ply *partitions and pads*, or
  are those "rest same as last year"? Neither reading is safe, so the system raises a blocker and asks.
- Qualification 5/5: caught Pioneer's expired certificate behind a "yes", and the vague "below 2%".
- VP's question: qualified-only split = **₹3.95 cr** across 3 vendors, Shree Ganesh's 4% discount
  triggered; the analyst volunteered that 2 awarded lines rest on a GSM deviation (₹11k to avoid).
- Whole build and testing: ~50 model calls, about ₹50 of Gemini credit. Extractions are cached, so a live demo costs only the questions asked (~₹3 each).

## Deliberately left out

- Real email/SMTP and a vendor portal (stubbed: outbox folder; responses dropped into the inbox).
- Auth, roles, multi-RFx, multi-round negotiation / reverse auction.
- Live FX and a GST rate table (one editable buyer assumption each, shown in the sidebar).
- Optimal (MILP) award under constraints — the share cap is a greedy heuristic and says so.
- Should-cost modelling (board price × weight) — would be the next lever on per-kg quotes.
- Cross-provider LLM fallback (model fallback is within Gemini only).

## The better problem

The extraction is not where buyers lose the week — the **clarification loop** is. Every response above
needs a follow-up (missing lines, per-kg weight, freight, expired certificate, "same as last year" for a
SKU never bought). Today that is days of email ping-pong. The bigger product is a system that turns
uncertainty into precise vendor questions automatically, ingests the replies into the same cells, and
tells the buyer "this award is ready" only when every blocker is closed.
