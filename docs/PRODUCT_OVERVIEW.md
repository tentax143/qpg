A# QPG — Question Paper Generator
## Product & Feature Guide

**Who this document is for:** sales, pre-sales, product management, and anyone who has to explain
QPG to a customer without opening the code. It describes what the product does, who it's for, what
it is genuinely good at, and where its edges are. No technical background assumed.

**Last reviewed against the live codebase:** August 2026.

---

## 1. What QPG is, in one paragraph

QPG is a web application that turns study material into exam-ready question papers. You point it at
content — your own textbooks, notes, question banks and past papers, or a ready-made library the
platform supplies — then define the shape of the exam you want (sections, question types, marks),
pick the topics and a difficulty level, and click Generate. Two to three minutes later a formatted
Microsoft Word paper is waiting, complete with your institution's name in the header, marks against
every question, diagrams where a question needs one, and — on request — a separate answer key. The
paper is not scraped off the internet and not invented from thin air: it is written from the source
material you chose, then put through a dozen automated checks before anyone sees it.

It works for a Class 8 unit test, a Class 12 board paper, a JEE or NEET mock, a CUET practice set, a
university semester exam, or a professional certification test. The engine does not care what the
exam is called — it cares about the structure you defined and the material you gave it.

---

## 1a. Status: this is live, not a prototype

> **More than five institutions are running QPG in beta right now, and real exams are being sat on
> papers this system generated.** Not pilots that stalled at the demo stage — live exam cycles, with
> the papers going in front of students.

This is the most valuable sentence in the entire document. Lead with it.

**Why it matters more than any feature:**

- **It de-risks the buying decision.** Nobody wants to be the first institution to put an untested
  system in front of an exam hall. They don't have to be — someone else already took that risk and
  the exams went ahead.
- **It proves the unglamorous parts work.** Anyone can demo a generated paper. Surviving a live exam
  cycle means the marks added up, the printing worked, the answer keys matched, the Indic scripts
  rendered, and nothing fell over on the morning the paper was needed. That is a completely different
  claim from "the AI produces questions".
- **It reframes objections as solved problems.** "What if the questions are wrong?" becomes "here is
  how the institutions currently using it review papers before issuing them."

**How to use it honestly:**

- Say **beta**, and say it plainly. These are early institutions on a product still being actively
  developed, and being straight about that buys more credibility than implying a mature installed
  base. A prospect who feels oversold at this stage will not renew.
- Do **not** extrapolate. Five-plus institutions in beta validates the product at pilot scale. It does
  not validate hundreds of concurrent institutions — see §10 on infrastructure before promising scale.
- **Get the specifics before the deck goes out.** Papers generated, subjects and classes covered,
  exam cycles completed, and — most valuable of all — one named reference willing to take a call.
  A named reference from a live beta is worth more than every feature in §6.
- **Ask for a testimonial while the exam cycle is fresh.** "We ran our half-yearly exams on it" from
  a real coordinator closes deals that a feature list cannot.

---

## 2. The problem it solves

**Today, without QPG.** A senior faculty member spends three to six hours per paper. They hunt
through past papers and reference books, retype questions, count marks by hand, discover at the end
that Section C is two marks short, notice that Q4 gives away the answer to Q17, and rebuild the
answer key separately. Every test cycle — weekly tests, periodic tests, mock exams, semester
exams — the whole thing repeats, per subject, per batch, per section. Quality depends entirely on
which faculty member drew the short straw.

For a coaching institute the problem is worse, not better: they need *volume*. Fresh mock papers
every week, for multiple batches, across multiple subjects, without repeating last month's
questions — and the moment they reuse questions, students notice and the product loses credibility.

**With QPG.** The structure is defined once and reused forever. The content comes from source
material you control. The arithmetic, the duplicate-checking and the answer-leak checking are done by
the system, every time, identically. The human job shifts from *authoring* to *reviewing and
adjusting* — and the adjustment is done in plain English ("make Q7 harder", "move Q5 to Section B").

**The five claims worth making in a sales conversation:**

1. **It already works in the real world.** More than five institutions are in beta and live exams are
   running on its papers (§1a). Lead with this one.
2. **Hours to minutes.** A paper that took an afternoon takes about ninety seconds of machine time
   plus a review.
3. **Grounded in the material you chose.** Questions are drawn from actual source content, not from
   a generic national question bank. Two institutions using different books get different papers.
4. **Volume without repetition.** The system remembers what it has already generated and actively
   avoids repeating concepts — within a paper, across sections, and against recent papers.
5. **A consistent quality floor.** Every paper gets the same twelve checks — marks arithmetic,
   duplicate questions, answer-key bias, answer leakage between questions, competency mix — whether
   it was made by a department head or a first-year junior faculty member.

---

## 3. Who it's for

The same engine serves very different buyers. The pitch changes; the product doesn't.

| Segment | What they generate | What they buy it for |
|---|---|---|
| **Schools (K–12)** | Unit tests, periodic tests, half-yearly, pre-boards, annual exams | Saving senior faculty time; consistent quality across the staff room; board-pattern compliance |
| **Coaching institutes** (JEE, NEET, CUET, state entrance) | Weekly tests, topic-wise tests, full-length mocks, DPPs | **Volume.** Fresh non-repeating papers every week across many batches, produced by junior staff at senior quality |
| **Colleges & universities** | Internal assessments, mid-semester and end-semester papers, unit tests | Standardising paper quality across departments; removing the arithmetic and moderation grind |
| **Test-prep & ed-tech businesses** | Practice sets, question banks, mock series | Content production at a cost per paper that makes a subscription product viable |
| **Private tutors & small centres** | Practice sheets, revision tests, parent-facing assessments | Looking institutional without an institution's staff |
| **Publishers & content teams** | Workbook and question-bank content | Drafting at scale from their own catalogue, with an audit trail per paper |
| **Corporate & professional training** | Certification tests, compliance and internal assessments | Turning internal manuals and SOPs into assessments without hiring an assessment designer |

**Segment-independent truth:** if you can describe the exam's structure and supply the source
material, QPG can produce it. Everything above is the same product with different content loaded and
different labels on the sections.

---

## 4. Content: your material, our library, or both

This is a genuine choice at the point of purchase, and it decides how fast a customer gets to value.

**Option A — bring your own material.** Upload the books, notes, question banks and past papers you
actually teach from. Papers are then written from *your* content, in your sequence, matching your
faculty's coverage. This is what institutions with established material want, and it is the honest
answer to "will this match what we teach?" — yes, because it's reading what you teach.

**Option B — use the ready-made library.** The platform maintains its own indexed content, which can
be switched on for an account instantly. A brand-new customer with nothing uploaded can generate a
real paper on day one of the trial. Content can be supplied as:

- a **general shared library** — turned on for an account with a single switch, or
- **named, curated collections** — for example "Class 10 Science", "NEET Biology", "Semester 3
  Mechanical" — each allocatable to specific accounts.

**Option C — both, which is what most customers end up doing.** Start on the ready-made library so
the trial produces papers immediately, and layer the institution's own notes and question banks on
top as they get uploaded. Both sources are searched together at generation time.

**Why this matters commercially:**

- It removes the classic pilot-killer: *"we'll evaluate it once we've uploaded everything"*. With the
  ready-made library, evaluation starts the same day.
- Curated collections are a **sellable content product**, not just a support cost — allocate a
  collection and the customer sees it instantly; de-allocate it and access ends instantly.
- Nothing is ever copied between accounts. Access is granted by permission, so grants and
  revocations are immediate and there are no stale duplicates to clean up.
- Accounts can also share content with each other — one direction or mutually — which is how a chain
  of branches or a group of colleges pools its material.

---

## 5. The journey — five steps

```
1. GET CONTENT IN         →  2. DEFINE THE EXAM SHAPE  →  3. GENERATE
   upload your own,           sections, question types,     pick topics +
   switch on the ready-       marks, instructions           difficulty, click go
   made library, or both
                                                              ↓
5. DOWNLOAD               ←  4. REVIEW & ADJUST         ←  paper appears in
   Word paper +              read it, edit in plain         "My Papers"
   answer key               English or by hand
```

**Steps 1 and 2 are one-time-ish.** Step 2 especially: a structure named "Weekly Test · 40 marks" or
"NEET Mock · 180 Q" is built once and reused for every subject and every batch, forever. After the
first week a user lives entirely in steps 3–5.

**Step 1 determines everything else.** If an account has no content for a subject, there are no
topics to choose from and the paper is written from the model's general knowledge instead of real
source material. The product is explicit about this rather than hiding it — a warning is stamped on
the finished paper: *"Generated without uploaded materials for this class/subject — verify the
questions against the syllabus."* In a pilot, getting content in place on day one (whether uploaded
or switched on from the library) is the single highest-leverage onboarding task.

---

## 6. Feature catalogue

### 6.1 The content library — getting material in

Five kinds of material can be loaded, and the kind determines who can see it:

| Material type | Typical use | Default visibility |
|---|---|---|
| Textbook | Official or publisher textbook | The account's own + contributed to the shared library |
| Notes | Faculty-prepared notes, summaries, lecture handouts | Private to the account |
| Question Bank | Past papers, practice sets, DPPs | Private to the account |
| Syllabus | Curriculum or syllabus document | Private to the account |
| Reference Book | Supplementary reading, manuals | Private to the account |

Accepted files: **PDF, DOCX, DOC, TXT**.

**Five ways to get material in — this is a genuinely strong part of the product:**

1. **One file at a time.** Class/batch, subject, topic name, title, file. Done.
2. **Bulk upload.** Drop fifty topic PDFs at once. Before committing, QPG reads each file and
   *proposes the topic name from the file's content* — so `scan_final_v2.pdf` becomes "Chemical
   Reactions and Equations". The user reviews the proposed names in a list and corrects any before
   saving. This kills the most tedious part of onboarding.
3. **Whole-book split.** Upload one 300-page textbook PDF. QPG detects the chapter boundaries (using
   the PDF's own bookmarks, then printed chapter headings) and creates one entry per chapter,
   automatically. A preview shows how the book *will* split before anything is saved.
4. **Table-of-contents upload.** Upload the book's contents pages separately. QPG parses unit →
   lesson → page number and then splits content PDFs at exact page offsets using the book's
   **official printed titles** rather than guessing. This is what makes multi-lesson readers (a unit
   containing four poems and two prose pieces) split correctly.
5. **Import from a URL.** Paste the address of an online textbook page and QPG fetches it, splits it
   into chapters and imports the lot. A live preview shows the detected chapters and their sizes
   before importing. This is the practical route for Indic-script books where PDF text extraction
   produces garbage.

**What happens after upload.** Material is broken into passages, indexed for meaning-based search,
and passed through an **enrichment** pass that:

- works out which topic each passage *actually* belongs to (important when one uploaded file spans
  several chapters),
- writes a 300–500 word summary of each chapter,
- flags passages that came out garbled from a bad PDF extraction, so content quality is visible
  rather than silently poisoning papers,
- produces a cleaned copy of noisy passages (page furniture, headers, exercise questions glued on by
  the extractor) — **without ever altering the original text**, because verbatim quoting for
  literature extract questions depends on it,
- for language subjects, classifies each chapter as **prose / poem / drama / grammar /
  supplementary** — which is how the system knows to quote a poem when the paper asks for a poetry
  extract.

**Editing later.** A material's topic tagging can be changed after the fact and QPG re-indexes it
under the new topics. Visibility can be changed at any time and takes effect immediately, with no
re-processing.

---

### 6.2 Exam patterns — the shape of the paper

An **exam pattern** is a reusable definition of a paper: its sections, how many questions each has,
what type they are, how many marks each carries, the printed instructions, choice rules ("attempt
any five of seven"), word limits, and so on. Patterns are the reusable asset that makes the second
paper ten times faster than the first.

Patterns are completely free-form. There is no fixed catalogue of allowed exam formats — a 180-question
three-hour NEET mock, a 20-mark weekly test, a semester paper with Part A/B/C and internal choice,
and a 50-question objective screening test are all just different patterns.

**Four ways to create one:**

1. **Manual builder.** Fill in sections and their fields. Full control.
2. **Plain-English AI generation.** Type what you want:
   > *"Create a 40-mark Biology paper for Class 10 with 10 MCQs of 1 mark each, 5 short answers of
   > 2 marks, and 3 long answers of 5 marks each."*

   QPG turns that into a structured pattern, one entry per printed question. It handles messy real
   input — question-number ranges ("Q1–4 MCQs"), internal choice ("attempt one of two"), open choice
   ("answer any four of six, each 2 marks"), sub-parts ("Q21 A to E").
3. **Import from a sample paper PDF.** Upload last year's paper, a board sample paper, or a previous
   mock. QPG reads it and extracts *the structure only* — it is explicitly instructed never to copy
   the sample's passages, question wording or options, so future papers share the shape and not the
   content. (Scanned image-only PDFs are rejected up-front with a clear message.)
4. **Clone a pre-built pattern.** The platform ships a library of official board patterns (see §7).
   A user previews one and clones it into their own editable copy.

**Quality control on patterns themselves.** Every AI-built pattern is validated: do the per-question
marks add up to the section total; does the section total add up to the paper total; do open-choice
questions carry the right total; are marks sensible whole/half numbers rather than 3.33 repeating. If
checks fail, QPG runs **one repair round** — and critically, it *rejects a repair that "fixed" the
arithmetic by deleting the user's questions or reducing their marks*. What cannot be reconciled is
surfaced as a visible warning on the section instead of being silently papered over.

**Also available:** a per-question editor (edit question 12's type, marks, topic and choice rules
individually), regenerate-from-prompt, bulk regenerate every AI pattern in the account, bulk delete,
and protection so shared official patterns can only be deleted by the platform operator.

**Blueprints (optional, secondary).** A blueprint adds topic-wise mark weighting on top of a
pattern — "these 10 marks must come from Chapter 4". Useful where a mandated weightage sheet exists.
Most users never need it.

---

### 6.3 Generating a paper

The user picks: **class/batch → subject → topics → pattern → difficulty (Easy / Medium / Hard)**,
optionally attaches extra reference documents for this one paper, optionally sets duration and total
marks for the printed header, and clicks Generate.

The request returns immediately and the paper appears in the dashboard as "Generating", refreshing
itself every few seconds. The user can navigate away, close the tab, come back later.

**What happens behind the scenes, in plain terms:**

1. QPG searches the indexed material for the passages most relevant to each section of the paper,
   weighted by topic importance.
2. It plans which topic each individual question slot will come from, coordinated across the whole
   paper, so coverage is spread rather than clustered.
3. It writes each section **in parallel** — sections are generated simultaneously, which is why a
   full paper takes ninety seconds and not ten minutes.
4. Every section is validated, repaired and re-validated (see §6.4).
5. The assembled paper is audited as a whole, then rendered into Word.

**Graceful degradation is a deliberate design feature and worth mentioning to a nervous customer.**
If one section fails, the paper is still produced (with a note about the shortfall). If several fail,
the system automatically falls back to a simpler whole-paper generation strategy, and then to an
older one again. A paper is marked "failed" only if every strategy fails. Nothing is silently
dropped: shortfalls and mismatches always become visible notes on the paper.

**Concurrency and queueing.** Each user runs **one generation at a time**; a second request waits in
line and starts automatically when the first finishes — shown as "queued" rather than an error.
Different users generate simultaneously. Dead or lost generations are detected and auto-failed so a
user's queue can never get permanently wedged.

**Also available:** Cancel a running generation. Retry a failed one (reusing its original settings).
Regenerate a finished paper from scratch for a fresh set of questions on the same configuration —
this is the button a coaching institute uses to turn one configuration into a series of different
mocks. Delete papers individually or in bulk.

**One Mark Test — a small feature that gets used a lot.** A special pattern type that produces a
quick objective test: choose how many one-mark MCQs you want (1–200) and go. No section-building
required. Ideal for daily practice tests and rapid-fire revision. QPG deliberately spreads the
correct answers evenly across a/b/c/d and never lets two consecutive questions share the same answer
letter — which matters, because students learn to game a paper where the answer is always (c).

---

### 6.4 Built-in quality control — the strongest differentiator

Most "AI question paper" tools stop at "the model produced JSON". QPG runs a stack of checks on every
paper. This is the part to lead with against competitors, and the part to be honest about: **one
check blocks and the rest advise.**

**The blocking check (runs on every section, up to three attempts):**

- Exact question count. Non-empty question text. Marks match the pattern.
- MCQs: exactly four non-empty options a/b/c/d and a valid answer.
- Assertion-Reason: both the assertion and the reason present, plus the four standard options
  verbatim.
- Short/Long answer: an answer explanation present; Long Answer also needs its internal-choice
  alternative.
- Case-based questions: sub-questions present, and their marks add up to the parent question's marks.
- **Answer-key bias:** if more than 65% of the MCQs in a section share the same correct option
  letter, the section is rejected and rewritten.
- Section marks total matches the pattern.

When this check fails, the exact errors are fed back to the model and the section is rewritten — up
to twice. If it still fails, the section ships with whatever good questions it has, flagged as
partial, rather than being thrown away.

**The advisory checks (they warn, auto-correct or re-tag; they never block):**

| Check | What it does |
|---|---|
| Quality critic | Scores every question 1–5 on clarity, syllabus alignment, difficulty match and teaching value; flags the weak ones. |
| Grounding | Confirms short/long answer questions are actually answerable from the source material, not invented. |
| **MCQ answer verification** | A second, independent model answers every MCQ *blind*. Where it confidently disagrees with the stored key twice over, **the key is corrected automatically**. A single disagreement only raises a flag — one model's opinion can never overturn a correct key. |
| **Duplicate removal** | Finds questions testing the same concept twice, confirms with a second model, and **regenerates the weaker of the pair**. Also checks across sections and against the account's recently generated questions — this is the anti-repetition machinery that makes a weekly mock series viable. |
| Passage validation | For case-study questions, confirms the passage is accurate and that every sub-question can be answered from the passage alone. |
| Type enforcement | Removes any question whose type doesn't belong in its section. |
| Renumbering | Numbers every question sequentially across the whole paper. |
| **Competency mix** | Audits the paper against the 50/20/30 competency policy (application ≥45%, recall ≤25%, constructed-response ≥25%) and re-tags mislabelled questions. |
| **Answer-leak audit** | Reads the assembled paper looking for one question that gives away another's answer — the classic manual-authoring mistake — and rewrites the offender. |
| Coherence audit | Checks no topic dominates, all requested topics appear, section progression is sane. |
| Numerical balance | For quantitative subjects, detects which questions are genuine computational problems (a computation instruction plus workable figures) versus theory, and enforces the right marks split — so a Maths or Accountancy paper can't quietly become all theory. |
| Final audit | A strong model reads the whole paper plus every accumulated warning and returns a holistic verdict: quality score out of 10 and "ready to issue: yes / no / needs minor fix". |
| Marks & coverage audit | Deterministic arithmetic: does every section's marks total match the pattern (counting an OR pair once), and did every planned topic get a question? |

**The honest framing for a customer:** *"The system will not hand you a paper with three options on
an MCQ, mismatched marks, or the same question twice. It will flag a question whose phrasing is weak
or whose grounding is thin, and it tells you exactly what it flagged. It is a very good first draft
with an audit trail, not a replacement for a subject expert's signature."*

---

### 6.5 The paper editor

The user opens the paper and sees the **actual Word document rendered in the browser**, page breaks
and all — not a text box approximation. From there:

- **Plain-English editing.** Type an instruction and QPG performs it: *"Make Q7 harder"*, *"Replace
  Q2 with a new question on decimals"*, *"Add a 2-mark question on fractions to Section A"*, *"Move
  Q5 to Section B"*, *"Delete Q3"*, *"Swap Q2 and Q4"*, *"Change Q3 marks to 5"*, *"Set Section B
  instructions to 'Attempt any five questions'"*, *"Make all the questions in Section A easier"*. The
  instruction is turned into a list of precise operations, applied, the paper is renumbered, and the
  document re-renders. Diagrams, per-question marks and section grouping survive the edit. Suggested
  example commands are shown as clickable chips, so the feature is discoverable.
- **Direct typing.** Switch to edit mode and type into the document itself.
- **Change log with one-click revert.** Every AI edit is logged with its instruction, and any step can
  be rolled back. The log survives a page reload.
- **Warnings after edits.** If an edit breaks the marks total, QPG says so rather than refusing the
  edit. The user asked for it; they get it, plus the truth about its consequence.
- **Insert your own image.** Upload a diagram and place it in a question.
- **Regenerate** the whole paper from the editor if the draft isn't worth saving.
- **Export** the Word file, or download the answer key.

---

### 6.6 Answer keys

Generated on request, per paper, as a separate Word document. QPG answers every part of every
question — including each sub-question of a case study and each alternative of an OR choice — and
grounds each answer in the source material rather than free-associating.

Two details that show product maturity:

- **Staleness detection.** If the paper is edited after the key was made, the key is automatically
  marked **stale** and badged in the interface. It still downloads (the user decides), but nobody
  distributes a key that no longer matches the paper by accident.
- Requesting a key twice while one is already generating does nothing harmful — the system reports
  the in-flight job instead of paying for the work twice.

---

### 6.7 Diagrams and images

When a question needs a visual — a labelled leaf cross-section, an electrical circuit, a molecular
structure — QPG produces one:

- A router decides what kind of image is needed.
- **Chemistry molecules** are drawn properly from their chemical structure, not "AI art".
- **Scientific diagrams** are first searched for in Wikimedia Commons; if nothing suitable exists, one
  is generated with a style instruction enforcing clean textbook line art — white background, black
  ink, labelled with arrows, no decorative rendering.
- A **vision model then looks at the resulting image** and checks it actually supports the
  sub-questions asked about it, correcting the sub-questions if needed.
- Images are cached, so re-rendering a paper doesn't pay for them again.

**Commercially important:** image generation is the most expensive part of a paper, so it has a
per-account off switch. Turn it off for a price-sensitive customer and papers still generate
normally — image-based questions simply skip the picture. The platform counts images generated per
account, so this is billable if you want it to be.

---

### 6.8 Languages and scripts

QPG is built for Indian multilingual reality, not just English:

- Papers are generated in the subject's own language — **Tamil, Hindi, Sanskrit, Urdu, Telugu,
  Kannada, Malayalam, Marathi, Punjabi**, and the foreign languages, alongside English.
- Word output uses proper Tamil and Devanagari font handling so the printed paper doesn't come out as
  boxes.
- **Legacy-font rescue:** many Hindi and Sanskrit textbook PDFs are typeset in pre-Unicode fonts, and
  normal extraction turns भाषा into gibberish. QPG detects those fonts and transcodes the text back to
  real Unicode — so Hindi textbooks that are unusable in other tools become usable here.
- Where a PDF genuinely cannot be extracted, the URL-import route brings the same book in as clean
  text.
- Language papers are structurally harder (60+ questions, extracts, grammar tables), and the system
  gives them a longer time budget accordingly.

---

### 6.9 Accounts, access and administration

Access is organised in three tiers, and the tier names matter less than what each can do.

**Individual users** work inside their own account: they load material, build and reuse patterns,
generate papers, edit them, and download papers and answer keys. **A user's papers are private to
them** — their administrator can see them, a peer cannot. This removes the "I don't want colleagues
copying my paper" objection. Patterns, by contrast, are deliberately shared account-wide: the
structures are the institution's asset and are meant to be reused.

**Institution administrators** do everything a user does, plus:

- Create and remove user accounts.
- **Restrict a user to a single subject** — they then can neither load material for, nor generate
  papers in, any other subject. Useful for large departments and for tightly-scoped pilots.
- Promote a user to administrator, or demote one back.
- See the whole institution's papers, and a per-user breakdown of consumption and cost, both all-time
  and current month.

**The platform operator** runs the platform across all accounts:

- Create, edit, deactivate and delete accounts, with address, phone and email on record.
- Per-account switches: **monthly usage budget** (0 = unlimited), **billing period over**, **disable
  image generation**, **shared library access**.
- Create an account's first administrator; view and manage all users.
- Per-account dashboard: user count, papers generated all-time, images generated, volume consumed,
  cost accumulated, budget headroom.
- Browse any account's recent papers and per-user consumption.
- Manage the ready-made content library and its named collections (§4).

**Security and account hygiene, in plain terms:**

- New users are **forced to set their own password on first login** (or explicitly skip).
- Downloads use signed links that **expire after 24 hours**, so a paper URL can't be forwarded
  indefinitely or guessed by another account.
- Sessions expire when the browser closes and after 24 hours.
- An account can only ever see and modify its own material; content shared with it is readable but
  never editable.

---

### 6.10 Usage, cost and billing controls

Every AI operation is metered. The unit is **tokens** (the AI industry's unit of text volume), and
cost is computed in rupees at **₹0.49 per 1,000 tokens in, ₹1.47 per 1,000 tokens out**.

- Every paper stores its own token count and rupee cost.
- Every chargeable action — generate, regenerate, re-render, AI edit, answer key, pattern generation,
  library enrichment — is written to a **permanent usage log**. Deleting a paper does **not** erase
  its cost. A user cannot reduce their recorded consumption by tidying up.
- Each account carries running cumulative totals: papers generated, volume used, cost accumulated,
  images generated.
- **Monthly usage budget.** Set a cap per account. When it is hit, generation is refused with a clear
  message telling the user to contact their administrator.
- **Billing period over.** A single switch that keeps users able to log in and read their existing
  papers, shows them a banner explaining the situation, and refuses every new AI action. This is a
  polite dunning tool, not a hard lockout — considerably better for renewals than disabling accounts.
- **Image generation off** per account, as above.

**A real measured example** (from production logs, a Class 11 Mathematics periodic test covering two
chapters): **85 seconds**, 49 model calls, 36,163 tokens in / 9,370 out, **₹31.49**. Treat that as
representative of a mid-sized paper, not a guarantee — a 60-question language paper with extracts
costs and takes considerably more; a 20-question One Mark Test considerably less.

**The margin conversation:** at roughly ₹30 of machine cost for a mid-sized paper, an institute
producing 200 papers a month spends about ₹6,000 in generation cost. Price against the faculty hours
displaced, not against the token cost.

---

### 6.11 Platform operations

Features that exist because the product is actually run in production, and which are worth showing to
an institutional buyer as evidence of operational seriousness:

- **Board pattern refresher.** One button re-checks the official board patterns: it goes to the board
  website, downloads the current sample question paper, extracts its text, and updates the stored
  pattern from the real document rather than from model memory. Patterns record which academic year
  they were last verified against (currently 2025-26) and already-current ones are skipped. Progress
  is reported subject by subject.
- **Library enrichment console.** Run enrichment across the whole content library, watch live
  progress (materials done / failed, passages labelled, summaries written, garbled passages found,
  volume and cost spent), and **stop mid-run**. Completed work is kept, so restarting resumes rather
  than redoing — and never re-bills for text already processed. A run whose worker dies is detected
  and closed out automatically instead of hanging forever.
- **Content browser.** Drill into any class → subject → topic and see exactly what is stored: how many
  passages, how many enriched, how many garbled, the chapter summary, and the actual stored text
  passage by passage. When a customer says "the questions are wrong", this is where you find out
  whether their content was the problem.
- **Topic classification backfill.** Cheaply classify language chapters as prose/poem/drama/grammar/
  supplementary without re-reading the library.
- **System notifications.** Banner messages at the top of every page — global or targeted at specific
  accounts, with info / warning / error severity. Used for maintenance windows and release notes.
- **Active users.** Who is logged in right now, colour-coded online / idle / away, with account and
  tier. From here the operator can **force-log-out** a specific user or **send them a direct message**
  that appears as a toast in their app. Genuinely useful for live support during a test week.
- **Issue tracker.** Any user can file "this isn't working" from the sidebar. The operator triages it
  through open → investigating → fixing → fixed and can leave a note the reporter sees. Users see only
  their own reports.
- **Built-in user manual.** A role-aware, printable manual inside the app — each tier sees its own
  version with its own steps. Reduces training load during rollout.

---

## 7. Coverage

**What ships pre-configured**

- **Class / level labels:** 1 to 12.
- **48 seeded subjects:**
  - *Languages:* English Core, English Elective, English Language & Literature, Hindi Core, Hindi
    Elective, Hindi Course A, Hindi Course B, Sanskrit Core, Sanskrit Elective, French, German,
    Spanish, Tamil, Telugu, Kannada, Malayalam, Marathi, Punjabi, Urdu
  - *Mathematics:* Mathematics, Mathematics Standard, Mathematics Basic
  - *Sciences:* Science, Physics, Chemistry, Biology, Biotechnology
  - *Social Sciences:* Social Science, History, Geography, Political Science, Economics, Sociology,
    Psychology
  - *Commerce:* Accountancy, Business Studies
  - *Technology:* Computer Science, Informatics Practices, Information Technology
  - *Primary:* Environmental Studies
  - *Other:* Physical Education, Fine Arts, Painting, Music, Home Science, Entrepreneurship, Legal
    Studies
- **Exam types with their rules encoded** (marks, duration, share of syllabus, when in the year it
  falls, how it counts toward internal assessment): Unit Test, Periodic Test 1 / 2 / 3, Half Yearly,
  Pre-Board, Annual / Board exam — plus the platform's own One Mark Test.
- **Official board patterns** for the major Class 11–12 subjects, with the actual sample papers
  bundled: Accountancy, Biology, Business Studies, Chemistry, Computer Science, Economics, English
  Core, English Elective, Mathematics, Physics.

**Beyond the pre-configured set.** Exam structures are free-form, so competitive-exam and
higher-education formats are authored as patterns rather than waiting on a product update. In
practice a customer maps their programme onto the class/subject fields — a JEE Physics batch is
generated as class "12", subject "Physics", with a "JEE Main Mock · 25Q" pattern; a college course
runs as its nearest level with a "Semester 3 · Part A/B/C" pattern. See §9 for what fully native
labelling would need.

**Question types the generator handles:**

| | |
|---|---|
| Objective | MCQ (four options, single correct), Assertion-Reason, True/False, Fill in the blank, Matching (rendered as a proper two-column table), One-word answer |
| Written | Very Short Answer, Short Answer, Long Answer (with internal choice), Writing tasks (letter, essay, story, paragraph) |
| Competency | Case-based / source-based questions with a passage or diagram, Map-based questions |
| Language-specific | Literature extract questions — prose, poetry and drama, quoted verbatim from the correct chapter; grammar items (error correction, rewriting, punctuation); unseen comprehension passages |
| Quantitative | Numerical and computational problems, balanced against theory by a dedicated audit; molecular structures for Chemistry |

**Output:** Microsoft Word (.docx) with the institution name, subject, class, duration and total
marks in the page header, marks right-aligned against every question, bordered passage boxes, OR
separators, proper script fonts, and embedded diagrams. Answer keys are a separate Word file.

---

## 8. Speed and cost, realistically

| | |
|---|---|
| Typical paper (Science/Maths, 3–5 sections) | ~60–120 seconds |
| Heavy language paper (60 questions, extracts, grammar) | up to ~11 minutes |
| Hard ceiling before a generation is abandoned | 25 minutes |
| Answer key | one model call per question — minutes, runs in the background |
| Concurrency | one generation per user at a time; other users unaffected; extra requests queue automatically |
| Measured cost, mid-sized paper | ~₹30 |
| Pattern from plain English | seconds |
| Bulk upload of 50 topic PDFs with name detection | minutes, in the background |

---

## 9. Why it wins — positioning

**Against a generic AI chatbot:**

- Grounded in real source material, not the model's memory of a textbook.
- Produces a formatted, printable Word paper with a header and correct marks placement — not a chat
  transcript to reformat by hand.
- The marks add up, verified arithmetically, every time.
- Duplicate questions and answer leakage are actively detected and fixed.
- MCQ answer keys are independently verified by a second model.
- An answer key is generated as a separate document.
- Nothing is per-user-improvised: the structure is reused, so paper #40 is as consistent as paper #1.

**Against other question-paper products:**

- **It has survived live exams.** More than five institutions are running it in beta and students have
  sat exams on its papers (§1a). Most competitors in this space are demoware. Ask a prospect whether
  the alternative they're evaluating can name an institution that has completed an exam cycle on it.
- **The audit stack.** Twelve checks including competency ratios and answer-leak detection. Most
  competitors ship whatever the model returned.
- **Plain-English editing of a real document.** "Move Q5 to Section B" actually moves it and
  renumbers the paper.
- **Content flexibility.** Your material, a ready-made library, or both — most tools force one model.
- **Anti-repetition across papers**, which is the difference between a one-off demo and a weekly mock
  series.
- **Multilingual for real** — including the legacy Hindi font problem that defeats most PDF-based
  tools.
- **Multi-tenant content economics.** Named, allocatable content collections mean curated content is a
  product you can sell, not just a support cost.
- **Operator tooling.** Live user visibility, force logout, direct messaging, an issue tracker and a
  content browser. This is a product built by someone who has had to support it during a test week.

**Against doing nothing:** three to six hours of a senior faculty member's time per paper, times
every subject, times every test cycle.

---

## 10. Honest limits — read this before promising anything

Knowing these prevents the two worst sales outcomes: an unwinnable pilot, and a delivered promise you
can't keep.

**Content limits**

- **No OCR.** Scanned, image-only PDFs cannot be read. Material must be text-based PDFs, Word files
  or plain text. Pattern import explicitly rejects scanned papers with a clear message — but this
  *will* come up with older photocopied question banks.
- **Garbage in, garbage out.** Badly extracted content produces weak questions. The content browser
  exists precisely so this is diagnosable, but it still needs a human to look.
- **No content means no topics.** An account with nothing loaded and no library access cannot select
  topics and gets a generic paper with a warning stamped on it.

**Labelling and configuration**

- The interface currently labels levels as **Class 1–12** and offers a fixed list of 48 school
  subjects on the upload and pattern forms. Question wording also leans on school-board conventions by
  default. A coaching institute or college uses the product today by mapping onto those fields (see
  §7), which works — but **do not promise native "Semester 5" or "GATE CS" labels and non-board
  question phrasing as an out-of-the-box feature.** It is a configuration change, not a rebuild;
  scope it with engineering before committing to it in a contract.
- There is no dedicated integer/numerical-answer-type question format of the kind JEE Advanced uses.
  Numerical problems are produced as MCQ or short-answer questions with computational content.

**Product scope**

- QPG produces **question papers and answer keys**. It does **not**: mark or grade student answers,
  track student performance, run online tests, produce report cards, or integrate with an LMS or
  ERP. It is an authoring tool.
- There is no student-facing interface at all.
- Output is **Word**. Customers print from Word or convert to PDF themselves. (A basic PDF path exists
  for edited text but the polished artefact is the .docx.)
- No approval workflow — no "head of department signs off before the paper is final" state.
- No scheduled or bulk generation ("generate all 40 papers for the annual exam overnight" is not a
  button; papers are made one at a time, per user). **This is the main constraint to raise with a
  high-volume coaching customer** — throughput comes from multiple user accounts working in parallel,
  not from a batch job.

**Quality caveats**

- **Only the structural check blocks.** Everything else warns. A subject expert must still read the
  paper before issuing it. Say this out loud in the sales conversation — it is far better than having
  it discovered.
- Papers produced by the emergency fallback path are structurally sound but skip the advisory audit
  chain. Rare, but real.
- Difficulty (Easy/Medium/Hard) steers the model; it is not a calibrated measurement.

**Operational**

- The platform depends on external AI services being reachable. There is retry logic and automatic
  failover between API keys, but a prolonged provider outage stops generation.
- Meaning-based search of the library depends on an embedding service being available.
- The current deployment is a single-server setup. Scaling to many hundreds of concurrent accounts is
  an infrastructure project, not a switch. **Do not promise enterprise-scale concurrency without an
  infrastructure conversation first.**
- The operator "Queue" screen is a placeholder showing sample numbers; don't demo it.

---

## 11. Glossary — for demos and RFP responses

| Term | Plain meaning |
|---|---|
| **Material** | An uploaded file: textbook chapter, notes, question bank, syllabus or reference book. |
| **Topic / chapter / unit** | The label a material is filed under. Topic choices in the generator come from what's been loaded. |
| **Exam pattern** | The reusable shape of a paper: sections, question types, counts, marks, instructions. |
| **Blueprint** | Optional topic-wise mark weighting layered on top of a pattern. |
| **Question slot** | One printed question inside a pattern, with its own number, type and marks. |
| **Content library / collection** | A searchable body of indexed material. Named collections can be allocated to specific accounts. |
| **Enrichment** | The background clean-up pass that attributes passages to topics, writes chapter summaries and flags bad extractions. |
| **Token** | The AI industry's unit of text volume; the basis of cost. Roughly ¾ of a word. |
| **CBQ** | Case-Based Question — a passage or diagram followed by sub-questions. The standard competency format. |
| **Assertion-Reason** | An objective format used by boards and by NEET/JEE: a statement plus a reason, with four fixed options about their truth and relationship. |
| **Internal choice** | The "OR" convention — two full alternative questions under one number; the candidate answers one. |
| **50/20/30** | The mandated competency mix — roughly half competency-based, a fifth objective, the rest constructed-response. QPG audits against it. |
| **Answer leak** | When one question in a paper reveals another's answer. QPG hunts for these. |
| **Stale answer key** | A key generated before the paper was edited. Flagged automatically. |

---

## 12. A ten-minute demo script

0. **(30 sec) Open with the traction, before you show anything.** *"Five-plus institutions are running
   this in beta and students are sitting exams on papers it generated. Let me show you how."* Earn the
   next nine minutes of attention up front.
1. **(1 min) The dashboard.** Papers generated, this month, success rate. Set the scene: this is a
   working account with real history, not a sandbox.
2. **(1 min) Show the content.** Open a subject, topic by topic. Make the content choice explicit:
   *"these are their own uploads — and for a new customer we can switch on our ready-made library so
   you're generating on day one."* Point out the whole-book split and auto-detected topic names —
   "they dropped in fifty PDFs and the system named them".
3. **(1 min) Show a pattern.** Open one. Emphasise: built once, reused forever, shared across the
   whole department. Mention that any format can be authored — board paper, weekly test, full-length
   mock.
4. **(1 min) Generate.** Subject → three topics → pattern → Medium → Generate. It queues. Do not
   wait — go to a pre-generated paper.
5. **(2 min) The paper.** Real Word document in the browser. Header with the institution's name. Marks
   right-aligned. A diagram in the case-study question. Scroll to the end and show the audit notes.
6. **(2 min) The killer moment — plain-English editing.** Type *"Make Q7 harder"*. Watch the document
   re-render. Then *"Move Q5 to Section B"* and show the renumbering. Then revert it from the change
   log.
7. **(1 min) Answer key.** Download it. Then edit the paper and show the key going **stale** — nobody
   hands out a mismatched key by accident.
8. **(1 min) The commercial story.** Per-user consumption and cost, this month and all time. Then the
   operator view: budgets, the billing switch, live users.

**For a coaching-institute audience, swap step 6's second half for the repetition story:** regenerate
the same configuration twice, show that the questions differ, and explain that the system checks new
questions against what it has already produced.

**Close on the honest line:** *"This gives your best faculty member's paper quality to every faculty
member, in ninety seconds instead of an afternoon — and it always tells you what it wasn't sure
about."*
