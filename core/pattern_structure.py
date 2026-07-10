"""Per-question structure ("question_slots") for ExamPattern sections.

A slot is one printed question: {qnum, type, marks, format?, topic?, choice?,
alternatives?, parts?, attempt?, source?, condition?}. Slots are the source of
truth for slot-authored patterns; the legacy section aggregates
(questions_count / marks / marks_per_question / question_types) are derived
from them so every existing consumer keeps working. See
docs/PER_QUESTION_STRUCTURE.md for the full contract.
"""

# Canonical slot type -> pipeline category (the vocabulary of
# section_generator._type_category: mcq / vsa / sa / la / cbq / map).
SLOT_TYPE_CATEGORY = {
    "mcq": "mcq",
    "ar": "mcq",
    "fill_blank": "vsa",
    "true_false": "vsa",
    "matching": "vsa",
    "one_word": "vsa",
    "error_correction": "vsa",
    "rewrite": "vsa",
    "punctuation": "vsa",
    "vsa": "vsa",
    "sa": "sa",
    "la": "la",
    "writing": "la",
    "cbq": "cbq",
    "extract": "cbq",
    "map": "map",
}

SLOT_TYPES = frozenset(SLOT_TYPE_CATEGORY)

# Human/display label per slot type — used in generation prompts, derived
# question_types dicts, and the frontend (which renders the string raw).
SLOT_TYPE_LABEL = {
    "mcq": "MCQ",
    "ar": "Assertion-Reason",
    "fill_blank": "Fill in the blank",
    "true_false": "True/False",
    "matching": "Matching",
    "one_word": "One-word answer",
    "error_correction": "Error correction",
    "rewrite": "Rewrite the sentence",
    "punctuation": "Punctuation",
    "vsa": "Very Short Answer",
    "sa": "Short Answer",
    "la": "Long Answer",
    "writing": "Writing",
    "cbq": "Case-Based",
    "extract": "Extract-Based",
    "map": "Map-Based",
}

# Shared prompt text: the slot schema as stated to the pattern LLMs. Single
# source of truth — both api/ai_service.py (live) and core/pattern_ai_generator.py
# (management command) embed these, so the schema can't drift between them.
SLOT_SCHEMA_PROMPT_RULES = """QUESTION SLOT RULES — inside every section, list ONE ENTRY PER PRINTED QUESTION in "question_slots":
- qnum: the printed question number (integer). Use the teacher's own numbering when given
  ("Q 12 Homophones MCQs" -> qnum 12). Number continuously across the WHOLE paper starting
  at 1 — never restart numbering in a new section.
- Expand ranges: "Q1-4 MCQs" becomes four separate slots (qnum 1, 2, 3, 4).
- type: EXACTLY one of:
  mcq, ar (assertion-reason), fill_blank, true_false, matching, one_word,
  error_correction, rewrite, punctuation, vsa (very short answer), sa (short answer),
  la (long answer), writing (paragraph/story/letter/essay), cbq (case/source-based),
  extract (literature extract), map.
  Never invent other type strings — put presentation detail in "format" instead.
- format: short free text for HOW the question is presented, when the teacher specified it
  (e.g. "Homophones MCQ", "Rewrite with correct punctuation").
- topic: the topic / skill / grammar point being tested, when the teacher named one
  (e.g. "Homophones", "Past perfect tense", "Conjunctions and their types").
- marks: the marks a student can earn on this question number. Whole or half numbers
  ONLY (1, 1.5, 2, 3 ...) — never 2.25, 3.33 or other decimals. If a section total does
  not divide evenly among its questions, give the questions UNEQUAL whole/half marks
  that sum to the total (10 marks over 3 long answers -> 4+3+3) or change the question
  count — NEVER split a total into repeating decimals (3 x 3.33 = 9.99 is wrong).
- choice: "internal" when the question offers OR alternatives (attempt one of two full
  questions) — also give "alternatives": ["hint for option 1", "hint for option 2"].
  For an extract/passage question, "internal" means TWO separate passages, each printed
  with its own full set of sub-questions, joined by OR.
  "open" when ONE question number has several parts and students attempt only some
  ("A to F, attempt any 5") — also give "parts" and "attempt". Omit "choice" otherwise.
- parts: sub-parts printed under one question number, e.g. an extract with questions A-E:
  "parts": [{"label": "A", "type": "mcq", "marks": 1}, {"label": "B", "type": "sa", "marks": 1}].
  Part marks must sum to the slot's marks (for open choice: attempt x part-marks = slot marks).
  Whenever the teacher writes a letter range ("Q21 A TO E", "A to F") or a per-part
  breakdown ("5 questions each one mark, MCQ 2 and 3 short"), you MUST emit one part
  per letter with its type and marks — never collapse them into a bare marks total.
  With choice "internal", the SAME parts describe EACH of the two OR alternatives.
- attempt: with choice "open" only — how many parts the student answers.
- source: "textbook" when the material must come from the textbook, "unseen" for unseen
  passages, "general" when the teacher says the questions must NOT come from the
  textbook / given content and should be set from general knowledge (trigger phrases:
  "not from the textbook", "give in general", "on your own", "general knowledge").
  Omit otherwise.
- condition: any special instruction for this specific question, in the teacher's words
  (e.g. "critical/HOTS question", "questions must be based on the paragraph").

SECTION RULES:
- id ("SEC_A", "SEC_B", ...), name, marks (total for the section — MUST equal the sum of its
  slots' marks), instructions (list of strings), constraints (object, e.g. word limits),
  passage_instruction (for unseen reading passages: length, difficulty), extract_instruction
  (for literature extracts).
- Do NOT emit questions_count, marks_per_question or question_types — they are derived
  automatically from question_slots.

CONSISTENCY RULES:
- Slot marks sum to the section's marks; section marks sum to total_marks.
- If the teacher's own numbers contradict each other, trust the per-question detail and set
  the section/total marks to the sum of the slots."""

SLOT_OUTPUT_EXAMPLE = """{
    "sections": [
        {
            "id": "SEC_A",
            "name": "Reading",
            "marks": 4,
            "instructions": ["Read the unseen passage carefully and answer the questions."],
            "constraints": {},
            "passage_instruction": "Unseen passage of approximately 500 words.",
            "question_slots": [
                {"qnum": 1, "type": "mcq", "marks": 1, "source": "unseen"},
                {"qnum": 2, "type": "fill_blank", "marks": 1, "source": "unseen"},
                {"qnum": 3, "type": "sa", "marks": 2, "source": "unseen",
                 "condition": "must be based on the passage"}
            ]
        },
        {
            "id": "SEC_B",
            "name": "Grammar and Writing",
            "marks": 9,
            "instructions": [],
            "constraints": {"word_limit": "100-120 words"},
            "question_slots": [
                {"qnum": 4, "type": "mcq", "format": "Homophones MCQ", "topic": "Homophones", "marks": 1},
                {"qnum": 5, "type": "error_correction", "topic": "Past tense", "marks": 1,
                 "source": "general", "condition": "not from the textbook — set from general knowledge"},
                {"qnum": 6, "type": "writing", "marks": 5, "choice": "internal",
                 "alternatives": ["descriptive paragraph", "story writing"]},
                {"qnum": 7, "type": "extract", "marks": 2, "source": "textbook",
                 "parts": [{"label": "A", "type": "mcq", "marks": 1},
                            {"label": "B", "type": "sa", "marks": 1}]}
            ]
        }
    ],
    "total_marks": 13,
    "total_questions": 7,
    "metadata": {"exam_name": "...", "subject": "...", "class": "..."}
}"""

# Free-text spellings of the slot 'source' field -> canonical value.
_SOURCE_SYNONYMS = {
    "text book": "textbook",
    "text-book": "textbook",
    "book": "textbook",
    "general knowledge": "general",
    "gk": "general",
    "own": "general",
    "original": "general",
    "not from textbook": "general",
    "not from the textbook": "general",
}

# Free-text spellings the pattern LLM (or a teacher) may emit -> canonical type.
_TYPE_SYNONYMS = {
    "multiple choice": "mcq",
    "multiple choice question": "mcq",
    "objective": "mcq",
    "assertion reason": "ar",
    "assertion-reason": "ar",
    "fill in the blank": "fill_blank",
    "fill in the blanks": "fill_blank",
    "fill blank": "fill_blank",
    "fib": "fill_blank",
    "true false": "true_false",
    "true/false": "true_false",
    "true or false": "true_false",
    "match the following": "matching",
    "match": "matching",
    "one word": "one_word",
    "one word answer": "one_word",
    "error correction": "error_correction",
    "editing": "error_correction",
    "omission": "error_correction",
    "rewrite": "rewrite",
    "rewrite sentences": "rewrite",
    "transformation": "rewrite",
    "very short answer": "vsa",
    "short answer": "sa",
    "long answer": "la",
    "essay": "writing",
    "letter": "writing",
    "paragraph": "writing",
    "story": "writing",
    "descriptive paragraph": "writing",
    "story writing": "writing",
    "case based": "cbq",
    "case study": "cbq",
    "source based": "cbq",
    "competency based": "cbq",
    "extract based": "extract",
    "extract": "extract",
    "map based": "map",
    "map work": "map",
}

_CHOICES = ("none", "internal", "open")


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _int_if_whole(value):
    return int(value) if float(value) == int(value) else round(float(value), 2)


def canonical_slot_type(raw):
    """Map a raw type string to a canonical slot type, or None if unknown."""
    if not raw:
        return None
    key = str(raw).strip().lower().replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    compact = key.replace(" ", "_")
    if compact in SLOT_TYPES:
        return compact
    return _TYPE_SYNONYMS.get(key)


def slot_category(slot_type):
    """Pipeline category (mcq/vsa/sa/la/cbq/map) for a canonical slot type."""
    return SLOT_TYPE_CATEGORY.get(slot_type, "other")


def slots_for_section(section):
    """The section's question_slots list, or [] when absent/malformed."""
    if not isinstance(section, dict):
        return []
    slots = section.get("question_slots")
    if not isinstance(slots, list):
        return []
    return [s for s in slots if isinstance(s, dict)]


def normalize_slots(sections):
    """Coerce slot fields in place (qnum/marks/attempt numerics, canonical
    type, defaulted choice). Unknown types are left as-is for the validator
    to report. Returns the same sections list."""
    for section in sections or []:
        for slot in slots_for_section(section):
            slot["qnum"] = _as_int(slot.get("qnum"), 0)
            canon = canonical_slot_type(slot.get("type"))
            if canon:
                slot["type"] = canon
            marks = _as_float(slot.get("marks"), 0.0)
            slot["marks"] = _int_if_whole(marks) if marks else 0
            # Invalid values are kept for the validator to report.
            slot["choice"] = str(slot.get("choice") or "none").strip().lower()
            # Canonicalize source ("textbook" / "unseen" / "general"); other spellings
            # are mapped when obvious, unknown values pass through, empty is dropped.
            src = str(slot.get("source") or "").strip().lower()
            src = _SOURCE_SYNONYMS.get(src, src)
            if src:
                slot["source"] = src
            else:
                slot.pop("source", None)
            if slot.get("attempt") is not None:
                slot["attempt"] = _as_int(slot.get("attempt"), 0)
            parts = slot.get("parts")
            if isinstance(parts, list):
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    pm = _as_float(part.get("marks"), 0.0)
                    part["marks"] = _int_if_whole(pm) if pm else 0
                    pcanon = canonical_slot_type(part.get("type"))
                    if pcanon:
                        part["type"] = pcanon
    return sections


def validate_pattern_structure(sections, declared_total=None):
    """Validate question_slots across sections.

    Returns a list of {"section": index-or-None, "msg": str} dicts; empty
    means valid. Sections without slots are skipped (legacy dialects stay
    untouched); cross-paper checks apply only to what slots exist.
    """
    errors = []

    def err(idx, msg):
        errors.append({"section": idx, "msg": msg})

    all_qnums = []
    every_section_has_slots = bool(sections)

    for idx, section in enumerate(sections or []):
        slots = slots_for_section(section)
        if not slots:
            every_section_has_slots = False
            continue
        name = section.get("name") or section.get("id") or f"section {idx + 1}"
        prev_qnum = None
        slot_marks_sum = 0.0

        for slot in slots:
            qnum = slot.get("qnum")
            label = f"Q{qnum}" if qnum else "a slot"

            if not isinstance(qnum, int) or qnum <= 0:
                err(idx, f"{name}: slot has invalid qnum {qnum!r} (positive integer required)")
            else:
                all_qnums.append(qnum)
                if prev_qnum is not None and qnum <= prev_qnum:
                    err(idx, f"{name}: qnums must be strictly ascending ({prev_qnum} then {qnum})")
                prev_qnum = qnum

            stype = slot.get("type")
            if stype not in SLOT_TYPES:
                err(idx, f"{name} {label}: unknown type {stype!r} — allowed: {', '.join(sorted(SLOT_TYPES))}")

            marks = _as_float(slot.get("marks"), 0.0)
            if marks <= 0:
                err(idx, f"{name} {label}: marks must be a positive number, got {slot.get('marks')!r}")
            elif abs(marks * 2 - round(marks * 2)) > 0.01:
                # Real papers award whole/half marks; 2.25 or 3.33 is an even-division
                # artifact (9/4, 10/3) that downstream rounding then mangles further.
                err(idx, f"{name} {label}: marks must be a whole or half number, got "
                         f"{slot.get('marks')!r} — split the section total into unequal "
                         "whole/half marks instead (e.g. 10 over 3 questions -> 4+3+3)")
            slot_marks_sum += marks

            choice = slot.get("choice", "none")
            if choice not in _CHOICES:
                err(idx, f"{name} {label}: choice must be one of {_CHOICES}, got {choice!r}")
            parts = [p for p in slot.get("parts") or [] if isinstance(p, dict)]
            for p in parts:
                pm = _as_float(p.get("marks"), 0.0)
                if pm > 0 and abs(pm * 2 - round(pm * 2)) > 0.01:
                    err(idx, f"{name} {label}: part {str(p.get('label') or '?')!r} marks must "
                             f"be a whole or half number, got {p.get('marks')!r}")
            attempt = slot.get("attempt")

            if choice == "internal":
                # parts + internal choice is legitimate: the parts describe EACH of the
                # two OR alternatives (e.g. an extract printed twice, A-E under both).
                alts = slot.get("alternatives")
                if alts is not None and (not isinstance(alts, list) or not all(isinstance(a, str) for a in alts)):
                    err(idx, f"{name} {label}: alternatives must be a list of strings")
            if choice == "open":
                if len(parts) < 2:
                    err(idx, f"{name} {label}: open choice requires at least 2 parts")
                elif not attempt:
                    err(idx, f"{name} {label}: open choice requires 'attempt' (answer N of {len(parts)} parts)")
                else:
                    if attempt >= len(parts):
                        err(idx, f"{name} {label}: attempt ({attempt}) must be less than the number of parts ({len(parts)})")
                    part_marks = {round(_as_float(p.get("marks"), 0.0), 2) for p in parts}
                    if len(part_marks) > 1:
                        err(idx, f"{name} {label}: open-choice parts must carry uniform marks, got {sorted(part_marks)}")
                    elif marks > 0 and abs(attempt * next(iter(part_marks)) - marks) > 0.01:
                        err(idx, f"{name} {label}: attempt ({attempt}) x part marks ({next(iter(part_marks))}) != slot marks ({_int_if_whole(marks)})")
            if attempt and choice != "open":
                err(idx, f"{name} {label}: 'attempt' is only valid with choice='open'")
            if parts and choice != "open":
                psum = sum(_as_float(p.get("marks"), 0.0) for p in parts)
                if marks > 0 and abs(psum - marks) > 0.01:
                    err(idx, f"{name} {label}: parts marks sum to {_int_if_whole(psum)} but slot marks is {_int_if_whole(marks)}")

        sec_marks = _as_float(section.get("marks"), 0.0)
        if sec_marks > 0 and abs(slot_marks_sum - sec_marks) > 0.01:
            err(idx, f"{name}: slot marks sum to {_int_if_whole(slot_marks_sum)} but the section declares {_int_if_whole(sec_marks)} marks")

    if all_qnums:
        seen = set()
        for q in all_qnums:
            if q in seen:
                err(None, f"duplicate question number Q{q} across the paper")
            seen.add(q)
        if every_section_has_slots and not errors:
            expected = list(range(1, len(all_qnums) + 1))
            if sorted(all_qnums) != expected:
                err(None, f"question numbers must run 1..{len(all_qnums)} with no gaps, got {sorted(set(all_qnums))}")

    if declared_total and all_qnums:
        paper_sum = 0.0
        for section in sections or []:
            slots = slots_for_section(section)
            if slots:
                paper_sum += sum(_as_float(s.get("marks"), 0.0) for s in slots)
            else:
                paper_sum += _as_float(section.get("marks"), 0.0)
        if paper_sum > 0 and abs(paper_sum - _as_float(declared_total, 0.0)) > 0.01:
            err(None, f"paper marks sum to {_int_if_whole(paper_sum)} but the declared total is {declared_total}")

    return errors


def format_structure_errors(errors):
    """Render validator errors as numbered lines for an LLM repair prompt."""
    return "\n".join(f"{i + 1}. {e['msg']}" for i, e in enumerate(errors))


def _slot_signature(sections):
    """{qnum: marks} across all slots — the load-bearing identity of a pattern."""
    sig = {}
    for section in sections or []:
        for slot in slots_for_section(section):
            qnum = slot.get("qnum")
            if isinstance(qnum, int) and qnum > 0:
                sig[qnum] = round(_as_float(slot.get("marks"), 0.0), 2)
    return sig


def repair_preserves_slots(original_sections, repaired_sections):
    """True if a repair kept every original question slot intact.

    A marks conflict between the teacher's per-question detail and their declared
    section totals must be resolved by adjusting the TOTALS — a repair that instead
    deletes slots or lowers slot marks (observed: Q19/Q20 dropped and a 4m LA cut
    to 3m to force the sums to match) silently destroys teacher content and must be
    rejected, whatever its error count. Repairs may still ADD slots, fill in a
    missing/zero marks value, and re-split marks that are OFF the half-mark grid
    (2.25, 3.33 — even-division artifacts the validator flags; fixing them requires
    changing exactly those marks, and they are never faithful teacher content)."""
    orig = _slot_signature(original_sections)
    rep = _slot_signature(repaired_sections)
    for qnum, marks in orig.items():
        if qnum not in rep:
            return False
        off_grid = abs(marks * 2 - round(marks * 2)) > 0.01
        if marks > 0 and not off_grid and abs(rep[qnum] - marks) > 0.01:
            return False
    return True


def derive_aggregates_from_slots(sections):
    """Recompute the legacy aggregate keys of every slot-bearing section from
    its slots, in place: questions_count, marks, marks_per_question (uniform
    only), and question_types as typed dicts {type, count, marks_each, range}
    built from contiguous runs — the dict form the CBSE compound dialect
    already uses and build_work_orders already consumes. Returns sections."""
    for section in sections or []:
        slots = slots_for_section(section)
        if not slots:
            continue

        section["questions_count"] = len(slots)
        total = sum(_as_float(s.get("marks"), 0.0) for s in slots)
        if total > 0:
            section["marks"] = _int_if_whole(total)

        marks_values = {round(_as_float(s.get("marks"), 0.0), 2) for s in slots}
        if len(marks_values) == 1:
            section["marks_per_question"] = _int_if_whole(next(iter(marks_values)))
        else:
            # Never leave a stale scalar/list behind — the mpq-list -> 0.0
            # coercion path is a known marks-stamping bug source.
            section.pop("marks_per_question", None)

        runs = []
        for slot in slots:
            stype = slot.get("type")
            label = SLOT_TYPE_LABEL.get(stype, str(stype or "SA"))
            marks = _as_float(slot.get("marks"), 0.0)
            qnum = slot.get("qnum")
            if runs and runs[-1]["type"] == label and abs(runs[-1]["marks_each"] - marks) <= 0.01:
                runs[-1]["count"] += 1
                runs[-1]["_end"] = qnum
            else:
                runs.append({"type": label, "count": 1, "marks_each": marks, "_start": qnum, "_end": qnum})
        typed = []
        for run in runs:
            rng = f"Q{run['_start']}" if run["_start"] == run["_end"] else f"Q{run['_start']}-Q{run['_end']}"
            typed.append({
                "type": run["type"],
                "count": run["count"],
                "marks_each": _int_if_whole(run["marks_each"]) if run["marks_each"] else 0,
                "range": rng,
            })
        section["question_types"] = typed
    return sections
