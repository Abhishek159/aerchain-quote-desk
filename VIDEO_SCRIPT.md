# Walkthrough video script (about 6 minutes)

Record with Loom (screen + camera bubble). Have the app open on **3 · Comparison** before you start.
Spoken lines are in quotes; *italics* are what to click. Don't read word for word - say it your way.

---

## 0:00 - 0:30 · The problem (Vendor inbox)
*Open 2 · Vendor inbox. Scroll slowly past the five vendors; pause on the photo and Maruti's email.*

"A buyer needs 30 lines of corrugated packaging - about four crore a year. Five vendors reply in five
formats: an Excel in US dollars per hundred boxes, a PDF with the discount in a footnote, a Word letter
with prices in paragraphs, a phone photo of a rate card at an angle, and one email that says
'42 per kg, rest same as last year, freight extra'. Today someone re-types all of that for three days."

## 0:30 - 1:00 · The idea
"Reading these is now the easy part - a good model reads the photo. The hard part is making them
comparable and making the buyer trust the result. So I split the work: the AI only transcribes what
each vendor wrote and where; plain code does every conversion; and every doubt is shown, never hidden."

## 1:00 - 2:15 · The comparison (the main output)
*Open 3 · Comparison. Point at the colours.*

"Thirty lines, five vendors, all in rupees per box, ex-GST, delivered. Green is the cheapest firm price.
Amber means the number rests on an assumption. Maruti looks cheapest almost everywhere - but it's all
amber."

*Why this number? → L01 + V5 Maruti.*
"Per-kg rate times our estimated weight, and freight is unknown. Cheaper on paper isn't cheaper firm."

*Switch to L29 + V4 Pioneer.*
"Here's the photo. The system cut out the exact row it read, read it twice independently - both say
516 per hundred - then divided by 100 and took out GST: 4.91. And beside it: Pioneer said 'ISO: yes',
but the certificate they attached expired in 2025. So they fail qualification."

## 2:15 - 3:00 · When it isn't sure
*Open 4 · Review & clarify. Show blockers at the top.*

"Blockers first. Maruti said 'same as last year' for a SKU we've never bought - there's no last year.
Rather than guess, the system asks."
*Ask vendors tab → Maruti → Draft email.*
"Seven grouped questions, built from the flags by code, so nothing is missed or invented. The AI only
writes the email."

## 3:00 - 4:30 · Ask the data
*Open 5 · Ask the data. Click the first suggested question.*

"Now the VP's question: split it, cheapest per line, only among vendors who cleared the questionnaire."
*Wait for the answer.*
"3.95 crore across three vendors. Shree Ganesh's 4% footnote discount kicks in because their share is
over 50 lakh. Pioneer and Maruti are out, with the reason."
*Open 'How I got this'.*
"It can't make numbers up - every figure comes from these SQL queries and a deterministic simulator."

*Ask one of your own, e.g.:* "How much of Maruti's saving survives if freight is 4% and their boxes weigh
10% more than our spec?"

## 4:30 - 5:15 · Award
*Open 6 · Award. Flip 'only cleared vendors' off, then back on. Move the share cap to 40%.*

"The rules are switches. Capping any vendor at 40% costs about five lakh - that's the price of supply
security, in one move."
*Build award pack → Download, open it briefly.*
"The award pack: summary, award by line, the full comparison, every flag and assumption, the
questionnaire, terms and an audit trail."

## 5:15 - 5:45 · Can you trust it?
*Open Extraction accuracy.*

"Every vendor file was generated from a hidden answer key, so I can measure it. 146 of 150 prices
correct - and the four misses are all flagged. Zero silent errors: that's the number that matters."

## 5:45 - 6:15 · The better problem
"What I'd build next: buyers don't lose the week to reading quotes, they lose it to follow-ups. Every
reply here needed a clarification. The bigger product closes that loop automatically - and only says
'ready to award' when every blocker is closed. Thanks."

---

### Before you record
- Run the app locally or use the live link; don't click **Read** / **Re-read** (each full re-read ~₹30).
- Each analyst question costs ~₹3. The award page, comparison and Excel cost nothing.
- Close other tabs and notifications; zoom the browser to ~110% so text is readable.
