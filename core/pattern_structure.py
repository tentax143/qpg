"""Per-question structure ("question_slots") for ExamPattern sections.

A slot is one printed question: {qnum, type, marks, format?, topic?, choice?,
alternatives?, parts?, attempt?, source?, condition?}. Slots are the source of
truth for slot-authored patterns; the legacy section aggregates
(questions_count / marks / marks_per_question / question_types) are derived
from them so every existing consumer keeps working. See
docs/PER_QUESTION_STRUCTURE.md for the full contract.
"""

import re

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
- attempt: with choice "open" only — how many parts the student answers. The slot's "marks"
  is then attempt x per-part marks — the TOTAL the student can earn — NEVER the per-part
  value ("answer any 4, each 2 marks" -> 6 parts of 2 marks, attempt 4, marks 8, NOT 2).
- READING COMPREHENSION ("read the passage/poem and answer the questions", "unseen passage",
  "படித்து பொருளுணர்ந்து வினாக்களுக்கு விடையளி"): model EACH passage as ONE slot that carries
  its questions as "parts" — type "cbq" with source "unseen" when the passage is to be newly
  composed, or type "extract" with source "textbook" when it must be quoted from the book
  (e.g. a 4-mark passage with 4 MCQs -> one slot, marks 4, parts: 4 x 1m mcq). NEVER emit the
  comprehension questions as independent slots — the printed paper must show the passage
  followed by its questions, and independent slots print no passage. Two passages (say one
  prose piece and one poem) = two slots. Use the section-level "passage_instruction" ONLY
  when the whole section shares one single passage.
- source: "textbook" when the material must come from the textbook, "unseen" for unseen
  passages, "general" when the teacher says the questions must NOT come from the
  textbook / given content and should be set from general knowledge (trigger phrases:
  "not from the textbook", "give in general", "on your own", "general knowledge").
  Omit otherwise.
- condition: any special instruction for this specific question, in the teacher's words
  (e.g. "critical/HOTS question", "picture based question", "questions must be based on the
  paragraph"). Mark ONLY the question the teacher singled out — "one question must be picture
  based" is a quota of one, not a licence for the whole section.

SECTION RULES:
- id ("SEC_A", "SEC_B", ...), name, marks (see below), instructions (list of strings),
  constraints (object, e.g. word limits), passage_instruction (for unseen reading passages:
  length, difficulty), extract_instruction (for literature extracts).
- attempt: with "Answer any SIX of the following" over 8 printed questions, emit ALL 8 slots and
  set the section's "attempt" to 6. Every printed question still gets its own slot — "attempt"
  only records how many of them a student answers.
- marks: what a STUDENT CAN EARN in the section. With no "attempt" that is the sum of its slots'
  marks; with "attempt" it is attempt x the per-question marks ("answer any SIX of eight 2-mark
  questions" -> 8 slots, attempt 6, marks 12, NOT 16). Sections using "attempt" must give every
  slot the SAME marks.
- Do NOT emit questions_count, marks_per_question or question_types — they are derived
  automatically from question_slots.

CONSISTENCY RULES:
- Slot marks sum to the section's marks (or, with "attempt", attempt x the per-question marks);
  section marks sum to total_marks.
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
            _reconcile_open_choice_marks(slot)
    return sections


def _reconcile_open_choice_marks(slot):
    """Open-choice slots ("A to F, attempt any 4"): the earnable total is
    attempt x per-part marks. Pattern LLMs put the per-part value (or the
    all-parts sum) in 'marks' instead — observed on a Tamil PT-1 where two
    'any 4 of 6 x 2m' / 'any 2 of 4 x 4m' slots shipped as 2m and 4m,
    shrinking the 40-mark paper to 30. Those two shapes are unambiguous, so
    fix them deterministically here; any other conflict (e.g. part marks
    that look wrong against a plausible total) is left for the validator,
    because rewriting marks there could destroy a correct teacher total."""
    if str(slot.get("choice")) != "open":
        return
    attempt = _as_int(slot.get("attempt"), 0)
    parts = [p for p in slot.get("parts") or [] if isinstance(p, dict)]
    if not attempt or len(parts) < 2 or attempt >= len(parts):
        return
    part_marks = {round(_as_float(p.get("marks"), 0.0), 2) for p in parts}
    if len(part_marks) != 1:
        return
    per_part = next(iter(part_marks))
    if per_part <= 0:
        return
    earnable = attempt * per_part
    marks = _as_float(slot.get("marks"), 0.0)
    if abs(marks - earnable) <= 0.01:
        return
    all_parts_sum = len(parts) * per_part
    if marks <= 0 or abs(marks - per_part) <= 0.01 or abs(marks - all_parts_sum) <= 0.01:
        slot["marks"] = _int_if_whole(earnable)


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
        # An attempt-N-of-M section prints more marks than it awards, by design.
        expected_marks = attemptable_marks(section)
        if sec_marks > 0 and abs(expected_marks - sec_marks) > 0.01:
            _n = section_attempt(section)
            detail = (f"{name}: the student answers any {_n} of {len(slots)} questions, worth "
                      f"{_int_if_whole(expected_marks)} marks, but the section declares "
                      f"{_int_if_whole(sec_marks)}") if _n else (
                      f"{name}: slot marks sum to {_int_if_whole(slot_marks_sum)} but the "
                      f"section declares {_int_if_whole(sec_marks)} marks")
            err(idx, detail)

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
            if slots_for_section(section):
                paper_sum += attemptable_marks(section)
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


def _open_choice_conflict_qnums(sections):
    """qnums of open-choice slots whose marks contradict attempt x uniform part
    marks. Such a marks value is invalid by construction (the spec requires the
    identity to hold), so it is never faithful teacher content — a repair must
    be allowed to change it, like the off-grid marks exemption."""
    out = set()
    for section in sections or []:
        for slot in slots_for_section(section):
            if str(slot.get("choice")) != "open":
                continue
            attempt = _as_int(slot.get("attempt"), 0)
            parts = [p for p in slot.get("parts") or [] if isinstance(p, dict)]
            part_marks = {round(_as_float(p.get("marks"), 0.0), 2) for p in parts}
            if not attempt or len(part_marks) != 1:
                continue
            per_part = next(iter(part_marks))
            if per_part > 0 and abs(attempt * per_part - _as_float(slot.get("marks"), 0.0)) > 0.01:
                qnum = slot.get("qnum")
                if isinstance(qnum, int) and qnum > 0:
                    out.add(qnum)
    return out


def repair_preserves_slots(original_sections, repaired_sections):
    """True if a repair kept every original question slot intact.

    A marks conflict between the teacher's per-question detail and their declared
    section totals must be resolved by adjusting the TOTALS — a repair that instead
    deletes slots or lowers slot marks (observed: Q19/Q20 dropped and a 4m LA cut
    to 3m to force the sums to match) silently destroys teacher content and must be
    rejected, whatever its error count. Repairs may still ADD slots, fill in a
    missing/zero marks value, and re-split marks that are OFF the half-mark grid
    (2.25, 3.33 — even-division artifacts the validator flags; fixing them requires
    changing exactly those marks, and they are never faithful teacher content).
    Open-choice slots whose marks contradict attempt x part marks get the same
    exemption — the correct repair (marks = the earnable total) is otherwise
    impossible, and rejecting it shipped a Tamil paper at 30/40 marks."""
    orig = _slot_signature(original_sections)
    rep = _slot_signature(repaired_sections)
    reconcilable = _open_choice_conflict_qnums(original_sections)
    for qnum, marks in orig.items():
        if qnum not in rep:
            return False
        off_grid = abs(marks * 2 - round(marks * 2)) > 0.01
        if marks > 0 and not off_grid and qnum not in reconcilable \
                and abs(rep[qnum] - marks) > 0.01:
            return False
    return True


# ─────────────────────────────────────────────
# Attempt-N-of-M sections
# ─────────────────────────────────────────────
#
# "Answer any SIX of the following" over eight 2-mark slots prints 8 questions but is worth 12
# marks, not 16. The slot schema had no way to say so, so the pattern LLM — told that a section's
# marks must equal the sum of its slots — declared 16, and an 80-mark paper printed as 90. The
# downstream machinery for this already exists (attempt_count / provided_count on the work order,
# the scaled section-marks check, the "Attempt any N of these M" prompt line); nothing populated
# it. The section's own instruction line is the fallback source when the pattern predates the
# explicit "attempt" key.

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

# "any" is required: "Answer ALL the questions" and "Answer the following" are not quotas.
_ATTEMPT_RE = re.compile(
    r"\b(?:answer|attempt|do|write|solve)\s+any\s+"
    r"(?P<n>\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")\b",
    re.IGNORECASE,
)

# CBSE papers repeat a general internal-choice note inside section instructions ("Internal choice
# is provided in some questions. A student is expected to attempt only one of these questions").
# That is a per-question OR, not a section quota — reading it as one would price a 20-mark MCQ
# section at 1 mark.
_NOT_A_SECTION_QUOTA = ("internal choice", "in some questions", "each question", "every question")


def section_attempt(section):
    """How many of the section's printed questions a student actually answers, or None.

    Explicit "attempt" wins; otherwise it is read off the section's own instruction line. Only
    returned for a section whose slots carry UNIFORM marks — with mixed marks "any 6 of 8" does
    not name a marks total (which six?), and every consumer of this needs one.
    """
    slots = slots_for_section(section)
    if len(slots) < 2:
        return None
    marks_values = {round(_as_float(s.get("marks"), 0.0), 2) for s in slots}
    if len(marks_values) != 1 or next(iter(marks_values)) <= 0:
        return None

    n = _as_int(section.get("attempt"), 0)
    if not n:
        for instr in section.get("instructions") or []:
            text = str(instr)
            low = text.lower()
            if any(bad in low for bad in _NOT_A_SECTION_QUOTA):
                continue
            m = _ATTEMPT_RE.search(text)
            if m:
                raw = m.group("n").lower()
                n = _WORD_NUMBERS.get(raw) or _as_int(raw, 0)
                break
    if not n or n >= len(slots):
        return None
    # A quota that discards most of the section is a misread instruction, not a quota — the
    # phrasings that produce one ("attempt any one of these questions") are about internal
    # choice. Answering at least a third of what is printed is the plausibility floor.
    if n * 3 < len(slots):
        return None
    return n


def attemptable_marks(section):
    """The marks a student can earn in this section — what the paper should print.

    The sum of its slots, unless the section is attempt-N-of-M, in which case only N of the
    printed questions count.
    """
    slots = slots_for_section(section)
    total = sum(_as_float(s.get("marks"), 0.0) for s in slots)
    n = section_attempt(section)
    if n:
        return n * _as_float(slots[0].get("marks"), 0.0)
    return total


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
        # The section's marks are what a STUDENT CAN EARN, which is the sum of the slots only
        # when every printed question is compulsory. questions_count stays the printed count —
        # all of them are generated and printed; the student picks.
        attempt = section_attempt(section)
        if attempt:
            section["attempt"] = attempt
        total = attemptable_marks(section)
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
