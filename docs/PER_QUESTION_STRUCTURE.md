# Per-Question Structure (`question_slots`)

Status: v1 — implemented and live-fire verified (2026-07-07). The real LLM run
on the PT-1 example produced all 23 slots with correct global qnums, per-slot
topics, choice conditions and parts; the validator caught both teacher-source
marks conflicts and the repair round resolved all errors.

## Problem

`ExamPattern.sections` stores only section-level aggregates (`marks`,
`questions_count`, `marks_per_question`, flat `question_types`, improvised
`subsections`). The teacher's per-question intent — "Q12 Homophones MCQs",
"Q22 A TO F attempt any 5", "Q23 internal choice" — is destroyed at pattern
time and then guessed back at generation time by the inference chain in
`build_work_orders`. Verified consequences:

- Topics ("Homophones") are discarded: topic-hint subsections return `[]`
  in `_qt_dicts_from_subsections` (core/section_generator.py:3168-3176), or
  get misused as pseudo-*type* labels that classify to `"other"` and disable
  type enforcement (the Tamil-paper failure).
- Free-form types (Error correction, Rewrite…) collapse to `"other"` in
  `_type_category` (core/section_generator.py:1173-1188).
- `marks_per_question` arrives as a list → `_as_float` → 0.0 → fractional
  marks stamped on papers (core/section_generator.py:3283-3293).
- Choice has no representation: `internal_choice` is never read; OR is
  hardcoded for every LA question; "attempt any N" is section-wide only;
  sub-parts (Q21 A–E) don't exist in the schema.
- No marks-sum validation at pattern save; teacher-source arithmetic errors
  (9 questions declared / 7 marks) surface only as silent reconciliation on
  the printed paper.
- The renderer regroups by type category and re-stamps marks per category,
  so an authored per-question order could not round-trip anyway
  (core/generator.py:880-916, 803-837).

## Design

**`question_slots` becomes the source of truth.** Each section in
`ExamPattern.sections` gains a `question_slots` array. Legacy aggregate keys
are **derived** from slots at save time so every existing consumer keeps
working. Slot-less patterns (manual, CBSE-seeded, old AI) behave exactly as
today.

The key is named `question_slots` — NOT `questions` — because the
CBSE-seeded dialect already uses `questions` as an integer count
(core/models.py:121, core/generator.py:2937).

### Slot schema

```jsonc
{
  "qnum": 12,                 // int, printed question number. REQUIRED.
  "type": "mcq",              // canonical enum, see below. REQUIRED.
  "marks": 1,                 // number > 0: marks the student can earn on this qnum. REQUIRED.
  "format": "Homophones MCQ", // free text: how the question is presented (optional)
  "topic": "Homophones",      // free text: topic/skill/grammar point to test (optional)
  "choice": "none",           // "none" (default) | "internal" | "open"
  "alternatives": ["…", "…"], // internal choice: content hints for the OR pair (optional)
  "parts": [                  // sub-parts printed under one qnum (optional)
    {"label": "A", "type": "mcq", "marks": 1, "topic": "…"}
  ],
  "attempt": 5,               // with choice=="open" + parts: answer N of len(parts)
  "source": "textbook",       // "textbook" | "unseen" | "general" | null
  "condition": "…"            // free text special instruction (optional)
}
```

Semantics:

- `marks` is always the **attempted** value for the printed question.
  - `parts` present, `choice != "open"` → `sum(part.marks) == marks`.
  - `parts` present, `choice == "open"` → parts carry uniform marks and
    `attempt * part_marks == marks`.
  - `normalize_slots` enforces the open-choice identity deterministically:
    when `marks` equals the per-part value or the all-parts sum (the two
    LLM confusions observed on the Tamil PT-1, which shipped a 40-mark
    paper at 30), it is rewritten to `attempt * part_marks`. Any other
    conflict is left for the validator; `repair_preserves_slots` exempts
    such conflicted slots so a repair may fix their marks.
- `choice == "internal"` → generation must emit `or_alternative` on this
  question (and ONLY slot-flagged questions get the OR requirement in
  slot-driven sections).
- Ranges in source text ("Q1-4 MCQs") are expanded to one slot per qnum.
- Reading/extract source material stays at section level
  (`passage_instruction` / `extract_instruction`) ONLY when the whole
  section shares one passage; a slot's `source` says where its material
  comes from. A "read the passage/poem and answer" exercise is ONE
  `cbq` (source `unseen`, passage composed into `source_text`) or
  `extract` (source `textbook`, quoted verbatim) slot per passage with
  the questions as `parts` — independent loose slots print no passage.

### Canonical type enum → pipeline category

`type` is a closed enum. `format`/`topic` carry the free text that used to
pollute the type field. Mapping to the existing `_type_category` categories
(which drive validation contracts, prompts, marks logic):

| slot `type`                                                                    | category | validation contract              |
|--------------------------------------------------------------------------------|----------|----------------------------------|
| `mcq`                                                                           | mcq      | options a–d + answer              |
| `ar` (assertion-reason)                                                         | mcq (fine: ar) | AR statement pair + options |
| `fill_blank`, `true_false`, `one_word`, `error_correction`, `rewrite`, `punctuation` | vsa | text + answer_explanation |
| `matching`                                                                      | vsa (subtype `matching`) | 2-column table of ≥4 pairs + options a–d (complete pairings) + answer + answer_explanation |
| `vsa`                                                                           | vsa      | text + answer_explanation         |
| `sa`                                                                            | sa       | text + answer_explanation         |
| `la`                                                                            | la       | text + answer_explanation (+ or_alternative only when slot says internal) |
| `writing` (paragraph/story/letter…)                                             | la       | same as la                        |
| `cbq`, `extract`                                                                | cbq      | source/extract + sub_questions    |
| `map`                                                                           | map      | map_note                          |

The enum values are added as recognized substrings in
`_type_category`/`_fine_category` so slot types never classify to `"other"`.

### Derived legacy aggregates (back-compat layer)

`derive_aggregates_from_slots(section)` recomputes, from slots:

- `questions_count` = number of slots (printed questions).
- `marks` = sum of slot `marks` (attempted marks).
- `marks_per_question` = the uniform slot marks value, else omitted.
- `question_types` = list of typed dicts `{type, count, marks_each, range}`
  built from contiguous runs of same (type, marks) — the exact dict form the
  CBSE compound dialect already uses and that `_blueprint_counts` /
  `qpos_block` already consume (core/section_generator.py:3192, 780).

This means even components that never learn about slots (paper_audit,
frontend read-only pages, `ExamPattern.save()` totals) see consistent
aggregates.

## Validator (`core/pattern_structure.py`)

`validate_pattern_structure(sections, declared_total=None)` returns a list of
error strings (empty = valid):

1. Slot shape: `qnum` int, `type` in enum, `marks` number > 0.
2. qnums unique and contiguous 1..N across the whole paper, in section order.
3. Parts: labels present; marks sum rule per `choice` (above);
   `attempt` requires `choice=="open"` and `2 <= attempt <= len(parts)` is
   `attempt < len(parts)` — attempt==len(parts) means no choice.
4. `choice=="internal"` with `parts` is rejected (internal choice applies to
   the whole question; use `alternatives`).
5. Section `marks` == sum of slot marks (when section declares marks).
6. `declared_total` (teacher's stated total / pattern `total_marks`) ==
   sum of section marks.

Flow in `generate_pattern_task`:

1. Parse LLM JSON → normalize slots (coerce ints/floats, default `choice`).
2. Validate. On errors → ONE repair call: original teacher text + previous
   JSON + error list, asking for corrected JSON.
3. Re-validate. Residual errors are stored as `section["_structure_warnings"]`
   (underscore key, serializer passes through; teacher-visible later) and the
   pattern still saves — generation falls back gracefully.
4. `derive_aggregates_from_slots` for slot sections;
   `_fill_section_counts` continues to handle slot-less sections.

Teacher-source arithmetic conflicts (PT-1 Section C: 9×1 marks vs declared 7)
therefore surface at **pattern time** as warnings instead of silently
reshaping the printed paper.

## Consumption

### build_work_orders (core/section_generator.py)

When a section has `question_slots`:

- `SectionWorkOrder.slots` carries the normalized slots.
- `questions_count` = len(slots); `marks` = slot sum; `marks_per_question`
  uniform-or-0; `mixed_marks` = varied slot marks; typed dicts from slot runs
  (replacing subsection synthesis); attempt/provided from open-choice slots
  or section fields.
- The heuristic inference chain (mpq-list patching, subsection synthesis,
  typical-marks fallbacks) is bypassed for slot sections.

### Generation prompt (build_section_prompt)

Slot sections get a per-question spec block instead of the derived
`qpos_block`:

```
PER-QUESTION SPEC (follow EXACTLY, one entry per question, in this order):
Q12: type=MCQ, topic="Homophones", marks=1
Q13: type=Fill in the blanks, topic="Conjunctions and their types", marks=1
…
Q22: type=Short Answer, 6 parts (A–F) of 2 marks each, students attempt any 5
Q23: type=Long Answer, marks=4, INTERNAL CHOICE — also provide "or_alternative"
     (option 1: critical question from prose/poem; option 2: direct question
     from supplementary reader)
```

- `or_rule` is gated: slot sections require `or_alternative` only on
  `choice=="internal"` slots (LA-blanket rule stays for slot-less sections).
- Topic strings finally reach the generation LLM.

### Validation of generated output

`validate_section_output` for slot sections checks per-slot (position-aware)
type/marks using slot order — `_blueprint_type_at` machinery generalizes.
Count-based checks remain for slot-less sections.

### Rendering (core/generator.py)

For slot-driven sections (blueprint dict carries `question_slots`):

- `_regroup_section` reordering is SKIPPED — authored order is preserved.
- `_section_type_marks` re-stamping is SKIPPED — each question keeps its own
  validated marks.
- Printed qnum stamping remains sequential, which now matches slot qnums
  because the validator enforced global continuity.

This retires the two recurring bug families (category marks stamping,
printed-vs-storage qnum divergence) for slot papers.

## Pressure test: PT-1 English example

- Section A → 10 slots: Q1–Q4 `mcq`, Q5–Q6 `fill_blank`, Q7 `true_false`,
  Q8–Q10 `sa` (1 mark each), section `passage_instruction` for the 500-word
  unseen passage, `source: "unseen"`.
- Section B → 1 slot: Q11 `writing`, marks 5, `choice: "internal"`,
  `alternatives: ["descriptive paragraph", "story writing"]`.
- Section C → 9 slots Q12–Q20 with `topic` per slot (Homophones, Conjunctions,
  Contracted words, Present progressive, Punctuation, Past tense, Past
  progressive, Past perfect) and honest types (`mcq`, `fill_blank`,
  `punctuation`, `rewrite`, `error_correction`). Validator flags
  `sum(9×1)=9 ≠ section marks 7` → repair/warning at pattern time.
- Section D → Q21 `extract` marks 5 with parts A–E (2 `mcq` + 3 `sa`, 1 mark
  each, `source: "textbook"`); Q22 `sa` marks 10, parts A–F at 2 marks,
  `choice: "open"`, `attempt: 5`; Q23 `la` marks 4, `choice: "internal"`,
  alternatives per source text.

## Blast radius / files touched

| File | Change |
|------|--------|
| `api/ai_service.py` | new prompt emitting `question_slots`; repair-call helper |
| `core/pattern_structure.py` | NEW: enum, normalize, validate, derive aggregates |
| `core/tasks.py` | validate + repair round in `generate_pattern_task` |
| `core/models.py` | totals prefer slots |
| `core/section_generator.py` | slot work orders, slot prompt block, enum in `_type_category`, gated or_rule, slot-aware validation |
| `core/generator.py` | pass slots through blueprint dict; slot-aware render (no regroup/re-stamp) |
| `core/tests.py` | validator/derivation/work-order/prompt tests |

## Since v1 (also done)

- `core/pattern_ai_generator.py` (legacy management-command path) migrated:
  shares the prompt rules via `pattern_structure.SLOT_SCHEMA_PROMPT_RULES` and
  runs normalize/validate/derive in `validate_and_enhance_pattern`.
- `core/paper_audit.py`: slot sections use slot sums/counts as truth and get a
  per-question audit (position i must carry slot i's marks and printed qnum).
- Frontend: pattern view page renders a per-question table + structure-warning
  banners; pattern edit page has a slot editor (type/topic/format/marks/choice)
  and `ExamPatternViewSet.perform_update` re-validates + re-derives aggregates
  server-side on every sections PUT.
- `source: "general"` (teacher: "give in general, NOT from the text book"):
  extraction prompt documents the value with trigger phrases; `normalize_slots`
  canonicalizes spellings ("GK", "general knowledge", …); the slot prompt line
  forbids textbook content for that question; sections whose slots are ALL
  general skip pgvector retrieval entirely (`_slots_all_general` in
  `get_section_context_map` + context blanked on the work order), and STRICT
  RULE 5 flips to "compose from your own knowledge".
- **English grammar and creative writing are always own-knowledge only** — no
  grammar question and no composition task on an English paper may use ANY of the
  retrieved reference material. Two live leaks, one mechanism:
  - NCERT English readers carry no grammar LESSONS, so `identify_grammar_chapters`
    found nothing to route a grammar section to and it retrieved prose instead:
    "gap filling" and "editing" questions came back built out of story sentences,
    tagged to literature chapters.
  - A Creative Writing section opened BOTH options of its internal choice with
    *"After reading 'The Laburnum Top', you are inspired by the theme of nature's
    vitality. Write an article …"* — a composition brief hung off a retrieved poem.
    An article, letter, notice or advertisement must stand on its own real-world
    brief; the student has to be able to answer it without having read any textbook.

  `english_own_scope` decides per section and returns `(kinds, own_only,
  slot_kinds)`, where `kinds ⊆ ("grammar", "writing")` and `slot_kinds` is
  `{index: kind}`. A slot counts as **grammar** when its `type` is
  `error_correction`/`punctuation`/`rewrite` or its `topic`/`format`/`condition`
  names a grammar skill; as **writing** when its `type` is `writing` or its wording
  names a composition form. Every slot of a grammar- or writing-NAMED section
  counts — `_english_own_section_kind` matches "Creative Writing Skills", "Writing
  Skills", "Composition", "Writing and Grammar", …

  Literature wording (`chapter`, `poem`, `extract`, …) exempts a slot **unless it
  also names a composition form** — "story writing" is a writing task, not a story
  question, because an explicit form is the stronger signal. `cbq`/`extract` slots
  never count, so a hybrid "Literature and Grammar" section keeps the material its
  literature questions need. Grammar vs writing only decides which prompt rule is
  stated (both get identical treatment), so that boundary is low-stakes; the one
  that matters is own-knowledge vs literature.

  Enforcement is three layers deep:
  1. own-knowledge slots are forced to `source: "general"`, so the machinery above
     applies verbatim (slot prompt line, chapter-assignment exemption,
     chapter-name validator — now word-bounded, and it reads `or_alternative` too,
     which is what catches a leak hiding in the second option of a choice);
  2. an ALL-own-knowledge section is denied retrieval outright
     (`get_section_context_map` skips it, `context_text`/`context_by_type` blanked
     on the work order, no chapter assignment and no chapter list in the prompt)
     and its prompt carries an explicit `ENGLISH GRAMMAR — ABSOLUTE RULE` and/or
     `CREATIVE WRITING — ABSOLUTE RULE` block. The writing rule bans "After
     reading …" / "Based on your reading of …" openers by name and requires BOTH
     options of an internal choice to be independent briefs;
  3. `_lifted_span` rejects a question that still copies an 8-word run of the
     material — the only case layer 2 cannot cover, since a MIXED section keeps its
     context for the literature slots. Instruction boilerplate shared with a
     textbook exercise page is excluded by a content-word floor.

  Non-English papers are untouched: Tamil/Hindi/Sanskrit grammar keeps its
  existing grammar-LESSON routing (`identify_grammar_chapters`) and its context.
  The single-prompt fallback in `generator.py` states both rules.
- Internal-choice extract/CBQ slots: `or_alternative` must be a full OBJECT
  (own `source_text`, `text`, `sub_questions` matching the first option's
  count/marks) — demanded in the prompt (slot line + or_rule) and enforced in
  `_validate_by_subtype`'s CBQ branch. The renderer (`process_question`)
  prints a dict alternative completely: passage, stem, lettered sub-questions,
  options. Previously the second option printed as a bare "OR" header.
- Slot `parts` are enforced at generation: `len(sub_questions)` must equal
  `len(slot.parts)` and per-part marks are checked positionally (the open-choice
  marks-sum exemption no longer lets an undercount through).
- Verbatim extracts: `type: "extract"` / `source: "textbook"` CBQ passages must
  share wording with the retrieved reference material (`_text_overlaps_context`,
  8-word-shingle overlap ≥ 30%) — a composed "the text explores…" meta-summary
  is rejected and retried. Prompt wording demands a word-for-word quotation.
- Renderer: Assertion-Reason questions merged into the "Multiple Choice
  Questions" display group (`_regroup_section` folds the `ar` bucket into `mcq`
  after marks stamping — AR keeps distinct marks; no separate "II. Assertion–
  Reason Questions" subheader). `sub_questions` now render in the
  `"question"`-key branch too, and sub-question dicts keyed `q`/`question`
  are no longer dropped.
- Extraction prompt: letter ranges ("Q21 A TO E … MCQ 2 and 3 short") MUST be
  captured as `parts`; with `choice: "internal"` the same parts describe each
  OR alternative (two passages, each with its own sub-questions).
- `matching` slots are answered like an MCQ, not written out. The question is a
  stem ("Match the following and choose the correct option:") + a two-column
  Markdown table of **at least `_MATCH_MIN_PAIRS` (4)** pairs — Column I
  labelled `(A)…(D)`, Column II labelled `(1)…(4)` and scrambled — plus four
  a/b/c/d options, each a COMPLETE pairing (`"A-3, B-1, C-4, D-2"`), an `answer`
  letter, and the correct pairing in `answer_explanation`. Four pairs is the
  floor because three pairs cannot carry four distinct pairing choices.
  Demanded in the prompt (matching slot line + a matching JSON example in
  `_output_schema`), repaired deterministically by `_repair_matching_options`
  (the key in `answer_explanation` makes the whole option set derivable, so a
  bare table costs no retry; a mis-pointed `answer` letter is also corrected),
  and enforced by `_validate_matching`. Column II is scrambled, so table row
  order is display order only — never the pairing.

## Out of scope (later)

- Slot authoring in the manual create-pattern builder (new patterns get slots
  via the AI flow; manual patterns stay aggregate-based).
- Normalizer pass converting CBSE-seeded / manual dialects to slots.
- Per-slot topic RAG retrieval (topic reaches the prompt; retrieval stays
  chapter-based).
- Adding/removing/renumbering slots in the editor (regenerate from the prompt
  to restructure — qnum continuity spans sections).
