"""
Parallel per-section question paper generation pipeline.

Architecture:
  1. get_section_context_map()   — section-specific RAG (4–5 queries × 4 chunks, max 2000 chars each)
  2. build_work_orders()          — one SectionWorkOrder per blueprint section
  3. generate_paper_parallel()    — ThreadPoolExecutor(max_workers=3)
     └── generate_section()       — focused ~60-line prompt, up to 2 retries on validation failure
  4. cross_section_validate()     — fix sequential question numbering across sections

Entry points used by generator.py:
    from .section_generator import generate_paper_parallel, get_section_context_map
"""
from __future__ import annotations

import json
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace as dc_replace
from typing import Optional

from . import embeddings, mantle_client, pattern_structure
from .data.cbse_patterns import UNIT_MARKS_WEIGHTS
from .data.science_split import classify_chapter   # Science chapter → Physics/Chemistry/Biology

GEN_MODEL = mantle_client.GEN_MODEL   # deepseek.v3.2
MAX_PARALLEL_SECTIONS = 3
MAX_SECTION_RETRIES = 2

# Standard Assertion-Reason options — identical for every AR question in CBSE papers
_AR_STANDARD_OPTIONS = {
    "a": "Both A and R are true and R is the correct explanation of A",
    "b": "Both A and R are true but R is NOT the correct explanation of A",
    "c": "A is true but R is false",
    "d": "A is false but R is true",
}
# Strip embedded LOWERCASE option label prefix from values (e.g. LLM writes "(a) text").
# Lowercase-only: uppercase (A)-(D) appear legitimately in AR options ("A is true but R is false")
# and must NOT be stripped.
_OPT_PREFIX_RE = re.compile(r'^\([a-d]\)\s*')


def _as_int(val, default=0):
    """Coerce an LLM-provided value to int. Handles ints, '1', 'Q1', '  3 '; falls back."""
    try:
        return int(val)
    except (TypeError, ValueError):
        m = re.findall(r"-?\d+", str(val))
        return int(m[0]) if m else default


def _as_float(val, default=0.0):
    """Coerce an LLM-provided value to float; falls back on non-numeric input."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _recent_question_stems(class_name, subject, limit=40):
    """Texts of questions already generated for this class+subject across past papers, so the
    prompt can tell the model not to repeat them — prevents two classes getting near-identical
    papers from the same pattern. Best-effort; returns [] on any error."""
    try:
        from .models import GeneratedQuestion
        rows = (GeneratedQuestion.objects
                .filter(class_name=str(class_name), subject__iexact=str(subject))
                .order_by('-created_at')
                .values_list('question_text', flat=True)[:limit])
        return [str(t).strip() for t in rows if str(t).strip()]
    except Exception:
        return []

# 4.3 — Per-question-type generation parameters (temperature + token budget)
TYPE_PARAMS = {
    "mcq":          {"temp": 0.6,  "budget_per_q": 300},
    "assertion":    {"temp": 0.6,  "budget_per_q": 320},
    "vsa":          {"temp": 0.7,  "budget_per_q": 250},
    "sa":           {"temp": 0.75, "budget_per_q": 400},
    "la":           {"temp": 0.8,  "budget_per_q": 700},
    "cbq":          {"temp": 0.72, "budget_per_q": 900},
    "source_based": {"temp": 0.78, "budget_per_q": 1100},
    "map_work":     {"temp": 0.5,  "budget_per_q": 300},
}


# ─────────────────────────────────────────────
# Work-order dataclass
# ─────────────────────────────────────────────

@dataclass
class SectionWorkOrder:
    section_name: str            # "Section A" — must match blueprint key
    section_id: str              # "A"
    title: str                   # "MCQ + Assertion-Reason"
    marks: int
    questions_count: int         # how many questions to generate (= provided_count when set)
    marks_per_question: float
    question_types: list
    instructions: list
    constraints: dict
    context_text: str            # RAG context, capped at 2000 chars
    difficulty: str
    subject: str
    class_name: str
    chapters: list
    section_subject: str = ""                    # C-01: sub-subject for compound papers (e.g. "Biology")
    provided_count: Optional[int] = None         # MO-01: total questions provided (≥ attempt_count)
    attempt_count: Optional[int] = None          # MO-01: students attempt N of M
    is_map_work: bool = False                    # M-04: map-work type section
    mixed_marks: bool = False                    # M-01: section has multiple marks values per question type
    passage_instruction: Optional[str] = None
    extract_instruction: Optional[str] = None
    subsections: list = field(default_factory=list)
    context_by_type: dict = field(default_factory=dict)  # 3.2: {type_key: context_str}
    chapter_plan: list = field(default_factory=list)     # one chapter name per question slot (weighted allocation)
    slots: list = field(default_factory=list)            # question_slots (per-question structure) — see docs/PER_QUESTION_STRUCTURE.md
    is_grammar: bool = False                             # grammar (இலக்கணம்/व्याकरण) section — chapters routed to grammar lessons only


# ─────────────────────────────────────────────
# Token budget
# ─────────────────────────────────────────────

def _per_q_tokens(marks) -> int:
    """Approx output tokens one question of this marks-value needs (incl. answer_explanation)."""
    marks = _as_float(marks, 1.0)   # tolerate non-numeric ("varies") values defensively
    if marks >= 5:
        return 600   # LA + or_alternative
    if marks >= 4:
        return 520   # CBQ stem + 3 sub-questions + explanations (source_text added separately)
    if marks >= 3:
        return 360   # SA
    if marks >= 2:
        return 300   # VSA
    return 280        # MCQ / Assertion-Reason: 4 options + explanation (AR options are long;
                      # 180 truncated 16-MCQ sections at ~12 questions — sized up to fit)


def estimate_token_budget(wo: SectionWorkOrder) -> int:
    base = 500

    # Mixed-marks sections (e.g. 7 MCQ + 2 AR + 3 VSA + 2 SA + CBQ + LA) MUST be sized by
    # summing per-TYPE costs. Using the section average (mpq) drastically undersizes the
    # budget — a 16-question section averaging 1.9m looks like 16×150 but actually contains
    # 5m LA / 4m CBQ questions, so the JSON gets truncated mid-output and fails to parse.
    raw = base
    counted = False
    if wo.slots:
        # Slot sections state every printed question — including sub-parts, per-question
        # extracts and internal-choice alternatives that the per-TYPE summary knows nothing
        # about. A Literature section (5-part extract × 2 options + 6-part SA + LA with OR)
        # summarised as "3 questions" budgets the 3000-token floor and truncates mid-extract.
        _m = re.search(r"(\d{2,4})\s*words", str(wo.extract_instruction or ""), re.IGNORECASE)
        _extract_words = int(_m.group(1)) if _m else 200
        for s in wo.slots:
            if not isinstance(s, dict):
                continue
            per = _per_q_tokens(s.get("marks"))
            parts = [p for p in (s.get("parts") or []) if isinstance(p, dict)]
            if parts:
                per = max(per, 150 + 130 * len(parts))
            if pattern_structure.slot_category(str(s.get("type") or "")) == "cbq":
                # each option carries its OWN source_text passage (~1.4 tokens/word)
                per += min(1100, max(400, int(_extract_words * 1.4)))
            n_opts = 1
            if s.get("choice") == "internal":
                hints = len([a for a in (s.get("alternatives") or []) if str(a).strip()])
                n_opts = hints if hints >= 3 else 2
            raw += per * n_opts
        counted = True
    for qt in (wo.question_types or []) if not counted else []:
        if isinstance(qt, dict) and "marks_each" in qt:
            cnt = _as_int(qt.get("count", 1), 1)
            m = _as_float(qt.get("marks_each", 1), 1.0)
            pq = _per_q_tokens(m)
            tstr = _type_str(qt)
            if "cbq" in tstr or "source" in tstr or "case" in tstr or qt.get("sub_questions"):
                pq += 400  # source_text passage (150-250 words) lives on the question
            raw += cnt * pq
            counted = True

    if not counted:
        # Uniform-marks section (or no per-type detail): scale by the section average.
        per_q = _per_q_tokens(wo.marks_per_question or 1)
        # Assertion-Reason questions carry the full A/R statements + the 4 long standard
        # options + an explanation — far heavier than a plain MCQ. A 16-question MCQ+AR
        # Section A at 280/q budgets only 4980 tokens and truncates at ~15 (JSON-Salvage then
        # recovers 15); size AR sections up so all 16 fit in a single call.
        if any("assertion" in _type_str(t) for t in (wo.question_types or [])):
            per_q = max(per_q, 400)
        raw += wo.questions_count * per_q

    if wo.passage_instruction:
        raw += 900
    if wo.extract_instruction and not wo.slots:
        raw += 700   # slot cbq/extract questions budget their own per-option passage above

    # Floor 3000 (small sections), ceiling 8192 (model output cap).
    return min(8192, max(3000, raw))


# ─────────────────────────────────────────────
# Difficulty directive
# ─────────────────────────────────────────────

def _difficulty_block(difficulty: str) -> str:
    d = difficulty.strip().lower()
    if d == "hard":
        return """
DIFFICULTY — HARD (NON-NEGOTIABLE REQUIREMENTS):
- Every question MUST demand multi-step reasoning or higher-order thinking (Bloom's: analysis, synthesis, evaluation)
- BANNED question formats: "What is", "Define", "Name", "List" — pure recall is strictly forbidden
- MCQ: all four options must be factually plausible with subtle distinctions — no obviously wrong distractors
- Assertion-Reason: pick non-obvious relationships where naive reasoning leads to the WRONG answer
- Short Answer: require "Explain why", "Justify", "Derive", "Predict", "Compare" — never "State" or "Describe"
- Long Answer: must integrate concepts from 2+ topics, require critical evaluation or synthesis, not narration
- Numericals: multi-step with unit conversions, formula derivations, or conceptual twists — single-step sums are banned
- Case-based: scenario must require inference; answers must NOT be directly lifted from the passage
- Passages (English): dense academic prose; test inference and implicit meaning — NOT literal comprehension
- A student who read the chapter only once should answer fewer than 25% of questions correctly
- Prefer: exceptions to rules, edge cases, counter-intuitive results, cross-topic links, real-world applications
""".strip()
    elif d == "medium":
        return """
DIFFICULTY — MEDIUM:
- Mix of application (50%) and analytical questions (50%)
- MCQ: 2 clearly wrong options, 2 plausible distractors
- Short Answer: require understanding + some application, not just recall
- Target standard CBSE board-exam level
""".strip()
    else:  # easy / default
        return """
DIFFICULTY — EASY:
- Majority direct knowledge and basic application questions
- Clear, unambiguous wording; suitable for revision and below-average students
- MCQ: one obvious correct answer with straightforward distractors
""".strip()


# ─────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────

def _ar_hint() -> str:
    return (
        'ASSERTION-REASON FORMAT — MANDATORY for every Assertion-Reason question:\n'
        '  Use "type": "MCQ" and "subtype": "assertion_reason" for every AR question.\n'
        '  The "text" field MUST contain the full Assertion AND Reason statements, like this:\n'
        '  "text": "Assertion (A): [Write the full assertion statement here.]\\nReason (R): [Write the full reason statement here.]"\n'
        '  Do NOT leave "text" as just "Assertion" or a placeholder — write real A and R statements.\n'
        '  "options" MUST always be exactly:\n'
        '  "options": {\n'
        '    "a": "Both A and R are true and R is the correct explanation of A",\n'
        '    "b": "Both A and R are true but R is NOT the correct explanation of A",\n'
        '    "c": "A is true but R is false",\n'
        '    "d": "A is false but R is true"\n'
        '  }\n'
        'Example:\n'
        '  "type": "MCQ", "subtype": "assertion_reason",\n'
        '  "text": "Assertion (A): The Green Revolution increased wheat production in Punjab.\\nReason (R): HYV seeds and irrigation infrastructure were already well-developed in Punjab."\n'
        '  "options": { "a": "Both A and R are true and R is the correct explanation of A", ... }'
    )


def _needs_image(wo: SectionWorkOrder) -> bool:
    """Return True if any instruction mentions image-based questions."""
    keywords = ("image", "picture", "diagram", "figure", "visual")
    for instr in wo.instructions:
        if any(k in instr.lower() for k in keywords):
            return True
    return False


def _qt_marks(qt) -> float:
    """Extract marks_each from a question_type entry (dict or string)."""
    if isinstance(qt, dict):
        return _as_float(qt.get("marks_each", 1), 1.0)
    return 1.0


def _output_schema(wo: SectionWorkOrder, image_vision: dict | None = None) -> str:
    # Use substring matching — type strings like "MCQ / Objective" or "MCQ / Assertion-Reason"
    # would fail exact-equality checks. Substring is safer.
    has_mcq = any(
        "mcq" in _type_str(t) or "multiple_choice" in _type_str(t) or "objective" in _type_str(t)
        for t in wo.question_types
    )
    has_ar  = any("assertion" in _type_str(t) for t in wo.question_types)
    has_passage = bool(wo.passage_instruction or wo.extract_instruction)
    has_cbq = any("cbq" in _type_str(t) or "source" in _type_str(t) or "case" in _type_str(t) for t in wo.question_types)
    has_la  = any("long" in _type_str(t) or _type_str(t) in ("la", "long_answer") for t in wo.question_types)
    has_sa  = any(_type_str(t) == "sa" or "short answer" in _type_str(t) for t in wo.question_types)
    has_vsa = any(_type_str(t) == "vsa" or "very short" in _type_str(t) for t in wo.question_types)
    has_map_type = wo.is_map_work or any("map" in _type_str(t) for t in wo.question_types)
    is_map  = wo.is_map_work
    needs_img = _needs_image(wo)
    mpq = wo.marks_per_question

    # Helpers to get per-type marks from blueprint (falls back to section average)
    def _m(keyword: str, fallback: float = mpq) -> float:
        for qt in wo.question_types:
            if keyword in _type_str(qt):
                return _qt_marks(qt)
        return fallback

    # ── Pure map-work section ─────────────────────────────────────────────────────
    if is_map and not has_cbq and not has_mcq:
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1, "type": "SA", "subtype": "map_based",\n'
            '      "text": "On the given outline map of India, locate and label the following: (a) ... (b) ...",\n'
            f'      "marks": {mpq},\n'
            '      "map_note": "[Attach outline map of India — examiner to supply]",\n'
            '      "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "application"\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    # ── Dedicated image-based CBQ section ────────────────────────────────────────
    if (has_passage or has_cbq) and _is_dedicated_cbq_section(wo):
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1, "type": "CBQ", "subtype": "image_based", "image_based": true,\n'
            '      "text": "Observe the diagram carefully and answer the following questions:",\n'
            f'      "marks": {mpq}, "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "application",\n'
            '      "sub_questions": [\n'
            '        {"text": "What does this diagram represent? Identify it.", "marks": 1, "answer_explanation": "Key answer points"},\n'
            '        {"text": "What do you observe about the [key structure/process] shown?", "marks": 2, "answer_explanation": "Key answer points"},\n'
            '        {"text": "What process or function is depicted in this diagram?", "marks": 1, "answer_explanation": "Key answer points"}\n'
            '      ]\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    # ── Mixed / compound section — show an example for EVERY type present ────────
    # This is the most important branch: sections like A (MCQ+VSA+SA+LA+CBQ+Map) must
    # see concrete schema examples for all their types, or the LLM invents wrong types.
    is_mixed = sum([has_mcq or has_ar, has_cbq, has_la, has_sa, has_vsa, has_map_type]) > 1
    if is_mixed or has_cbq or has_passage:
        examples = []
        qnum = 1

        if has_mcq and not has_ar:
            mcq_m = _m("mcq", _m("objective", 1.0))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "MCQ", "subtype": "standard",\n'
                f'      "text": "MCQ question text",\n'
                f'      "options": {{"a": "Option A", "b": "Option B", "c": "Option C", "d": "Option D"}},\n'
                f'      "answer": "b",\n'
                f'      "answer_explanation": "Why option b is correct and others are not (1-2 sentences)",\n'
                f'      "marks": {mcq_m}, "chapter_tag": "Chapter name", "competency_type": "recall"\n'
                f'    }}'
            )
            qnum += 1

        if has_ar:
            ar_m = _m("assertion", _m("mcq", _m("objective", 1.0)))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "MCQ", "subtype": "assertion_reason",\n'
                f'      "text": "Assertion (A): [full assertion statement]\\nReason (R): [full reason statement]",\n'
                f'      "options": {{\n'
                f'        "a": "Both A and R are true and R is the correct explanation of A",\n'
                f'        "b": "Both A and R are true but R is NOT the correct explanation of A",\n'
                f'        "c": "A is true but R is false",\n'
                f'        "d": "A is false but R is true"\n'
                f'      }},\n'
                f'      "answer": "a",\n'
                f'      "answer_explanation": "Why option a is correct",\n'
                f'      "marks": {ar_m}, "chapter_tag": "Chapter name", "competency_type": "application"\n'
                f'    }}'
            )
            qnum += 1

        if has_vsa:
            vsa_m = _m("vsa", _m("very short", 2.0))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "VSA", "subtype": "standard",\n'
                f'      "text": "Very short answer question text (answer in max 40 words)",\n'
                f'      "answer_explanation": "Key answer in 1-2 sentences",\n'
                f'      "marks": {vsa_m}, "chapter_tag": "Chapter name", "competency_type": "recall"\n'
                f'    }}'
            )
            qnum += 1

        if has_sa:
            sa_m = _m("short answer", _m("sa", 3.0))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "SA", "subtype": "standard",\n'
                f'      "text": "Short answer question text (answer in max 60 words)",\n'
                f'      "answer_explanation": "Model answer key points (2-3 sentences covering all mark-worthy content)",\n'
                f'      "marks": {sa_m}, "chapter_tag": "Chapter name", "competency_type": "constructed"\n'
                f'    }}'
            )
            qnum += 1

        if has_la:
            la_m = _m("long answer", _m("la", 5.0))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "LA", "subtype": "standard",\n'
                f'      "text": "Long answer question text (answer in max 120 words)",\n'
                f'      "answer_explanation": "Model answer key points — 4-6 bullet points covering all mark-worthy content",\n'
                f'      "marks": {la_m}, "chapter_tag": "Chapter name", "competency_type": "constructed",\n'
                f'      "or_alternative": "Alternate LA question on a DIFFERENT concept from the same chapter ({la_m}m)"\n'
                f'    }}'
            )
            qnum += 1

        if has_cbq:
            cbq_m = _m("cbq", _m("source", _m("case", mpq)))
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "CBQ", "subtype": "source_based",\n'
                f'      "source_text": "The case/source passage for THIS question ONLY (150-250 words). '
                f'This passage belongs to this CBQ alone — the MCQ/SA/LA questions in this section must NOT reference it.",\n'
                f'      "text": "Read the source above and answer the following:",\n'
                f'      "marks": {cbq_m}, "chapter_tag": "Chapter name", "competency_type": "application",\n'
                f'      "sub_questions": [\n'
                f'        {{"text": "Sub-question (a)", "marks": 1, "answer_explanation": "Key answer points"}},\n'
                f'        {{"text": "Sub-question (b)", "marks": 1, "answer_explanation": "Key answer points"}},\n'
                f'        {{"text": "Sub-question (c)", "marks": {max(1, round(cbq_m - 2))}, "answer_explanation": "Key answer points"}}\n'
                f'      ]\n'
                f'    }}'
            )
            qnum += 1

        if has_map_type:
            map_m = _m("map", 2.0)
            examples.append(
                f'    {{\n'
                f'      "qnum": {qnum}, "type": "SA", "subtype": "map_based",\n'
                f'      "text": "On the given outline map of India, locate and label: (a) ... (b) ...",\n'
                f'      "marks": {map_m}, "chapter_tag": "Chapter name",\n'
                f'      "map_note": "[Attach outline map of India — examiner to supply]",\n'
                f'      "competency_type": "application"\n'
                f'    }}'
            )
            qnum += 1

        examples_str = ',\n'.join(examples)
        # A genuine section-wide reading passage (driven by passage_instruction) stays at
        # section level. A CBQ's source passage does NOT — it lives in the CBQ's
        # "source_text" field so only that question references it.
        passage_note = ('  "passage": "FULL SECTION READING PASSAGE (400-600 words) — all questions reference this",\n'
                        if has_passage else '')
        cbq_note = (
            "\n— The CBQ's passage goes in its OWN \"source_text\" field, NOT at section level. "
            "MCQ/VSA/SA/LA questions are STANDALONE and must not reference any passage."
            if has_cbq else ""
        )
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            f'{passage_note}'
            '  "questions": [\n'
            f'{examples_str}\n'
            '  ]\n'
            '}\n'
            '— NOTE: Above shows ONE example per type. Generate ALL '
            f'{wo.questions_count} questions following EXACTLY these per-type formats.'
            f'{cbq_note}'
        )

    # ── Pure MCQ section (no other types) ────────────────────────────────────────
    if has_mcq:
        img_field = '\n      "image_prompt": "detailed description of the image/diagram to generate for this question",' if needs_img else ''
        ar_example = ''
        if has_ar:
            ar_example = (
                ',\n'
                '    {\n'
                '      "qnum": 2, "type": "MCQ", "subtype": "assertion_reason",\n'
                '      "text": "Assertion (A): [full assertion statement]\\nReason (R): [full reason statement]",\n'
                '      "options": {\n'
                '        "a": "Both A and R are true and R is the correct explanation of A",\n'
                '        "b": "Both A and R are true but R is NOT the correct explanation of A",\n'
                '        "c": "A is true but R is false",\n'
                '        "d": "A is false but R is true"\n'
                '      },\n'
                '      "answer": "a",\n'
                '      "answer_explanation": "Why this option is correct",\n'
                f'      "marks": {mpq}, "chapter_tag": "Chapter name or number from NCERT",\n'
                '      "competency_type": "application"\n'
                '    }\n'
            )
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1, "type": "MCQ", "subtype": "standard",\n'
            '      "text": "Question text",'
            f'{img_field}\n'
            '      "options": {"a": "...", "b": "...", "c": "...", "d": "..."},\n'
            '      "answer": "a",\n'
            '      "answer_explanation": "Why the correct option is right and why others are wrong (1-2 sentences)",\n'
            f'      "marks": {mpq}, "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "recall or application"\n'
            '    }'
            f'{ar_example}'
            '  ]\n'
            '}'
        )

    # ── Pure LA section ──────────────────────────────────────────────────────────
    if has_la:
        img_field = ', "image_prompt": "detailed description of the image/diagram to generate"' if needs_img else ''
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1, "type": "LA", "subtype": "standard",\n'
            f'      "text": "Long answer question text"{img_field},\n'
            f'      "marks": {mpq},\n'
            '      "answer_explanation": "Model answer key points — 4-6 bullet points covering all mark-worthy content",\n'
            '      "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "constructed",\n'
            f'      "or_alternative": "Alternate long answer question on a DIFFERENT concept from the same chapter — equal marks ({mpq}m)"\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    # ── Pure SA/VSA section (fallback) ───────────────────────────────────────────
    img_field = ', "image_prompt": "detailed description of the image/diagram to generate"' if needs_img else ''
    return (
        '{\n'
        f'  "section_id": "{wo.section_id}",\n'
        f'  "section_name": "{wo.section_name}",\n'
        '  "questions": [\n'
        f'    {{"qnum": 1, "type": "SA", "subtype": "standard", "text": "Question text"{img_field}, "marks": {mpq}, '
        f'"answer_explanation": "Model answer key points (2-3 sentences)", '
        f'"chapter_tag": "Chapter name or number from NCERT", "competency_type": "constructed"}}\n'
        '  ]\n'
        '}'
    )


# Language-subject papers must be written IN that language/script, not in English. Matched by
# substring against the subject name (covers "Hindi Core", "Hindi Course B", "Tamil", etc.).
_LANGUAGE_SUBJECTS = {
    "hindi":    "Hindi (हिन्दी), in Devanagari script",
    "tamil":    "Tamil (தமிழ்), in Tamil script",
    "sanskrit": "Sanskrit (संस्कृतम्), in Devanagari script",
}


def _language_directive(subject: str) -> str:
    """If the subject is a language paper (Hindi/Tamil/Sanskrit), return a MANDATORY block
    instructing the model to write the entire paper in that language/script. Empty otherwise."""
    s = (subject or "").lower()
    for key, desc in _LANGUAGE_SUBJECTS.items():
        if key in s:
            return (
                "LANGUAGE — MANDATORY (read FIRST):\n"
                f"This is a {desc} paper. Write the ENTIRE output — every question, all four "
                f"options, every passage, sub-question and answer_explanation — in {desc}. "
                "Do NOT write any question or option in English. Only the JSON keys "
                '("text", "options", "marks", "type", …) stay in English; every human-readable '
                "VALUE must be in the target language and script.\n"
            )
    return ""


def build_section_prompt(wo: SectionWorkOrder, attempt: int = 1, prior_error: str = "", image_vision: dict | None = None) -> str:
    types_str = ", ".join(_type_str(t) for t in wo.question_types) if wo.question_types else "Mixed"
    instructions_str = "\n".join(f"- {i}" for i in wo.instructions) if wo.instructions else "- Follow CBSE guidelines"

    constraints_str = ""
    if wo.constraints:
        for k, v in wo.constraints.items():
            constraints_str += f"- {k}: {v}\n"

    passage_block = ""
    if _is_dedicated_cbq_section(wo):
        # Question-first image CBQ: write observation questions from chapter knowledge.
        # image_finder will generate/find the image AFTER these questions are validated.
        # Do NOT reference image_vision here — no image exists yet at prompt-build time.
        effective_subject_local = wo.section_subject or wo.subject
        passage_block = (
            f"\nIMAGE-BASED CBQ INSTRUCTION:\n"
            f"This section places a scientific diagram in the question paper. "
            f"Students observe the image and answer the sub-questions.\n"
            f"Write observation sub-questions based on what is typically visible in a "
            f"CBSE Class {wo.class_name} {effective_subject_local} diagram of this chapter topic.\n"
            f"- Output 'image_based': true on the question — this triggers image generation\n"
            f"- Do NOT write a passage — no 'passage' key in JSON output\n"
            f"- Do NOT reference specific label letters (A, B, C) — an image will be generated later\n"
            f"  and labels may or may not exist. Ask observation questions like:\n"
            f"    'What does this diagram represent?'\n"
            f"    'What do you observe about the [structure/process] shown?'\n"
            f"    'What process is depicted in this diagram?'\n"
            f"- Sub-questions must be answerable by a student looking at a CBSE-standard diagram\n"
        )
    elif wo.passage_instruction:
        passage_block = f"\nPASSAGE: {wo.passage_instruction}\nGenerate the passage in the 'passage' JSON key; all questions must reference it.\n"
    elif wo.extract_instruction and not wo.slots:
        # Slot sections carry extracts per-question in "source_text" — a section-level
        # 'passage' there prints planning junk above the whole section.
        passage_block = f"\nEXTRACT: {wo.extract_instruction}\nInclude the text/extract in the 'passage' JSON key; questions must reference it.\n"

    ar_block = ""
    if any("assertion" in _type_str(t) for t in wo.question_types):
        ar_block = f"\n{_ar_hint()}\n"

    image_block = ""
    # Skip image_block for dedicated CBQ sections — image_finder handles image generation
    # post-question-validation. Adding image_block would make the LLM generate an image_prompt
    # field that triggers the Together AI pipeline and conflicts with our image flow.
    if _needs_image(wo) and not _is_dedicated_cbq_section(wo):
        image_block = (
            "\nIMAGE-BASED QUESTION RULE:\n"
            "- For any question that is image/diagram/picture based, add an \"image_prompt\" field.\n"
            "- The \"image_prompt\" value must be a self-contained visual description (20-40 words) that an AI image model can render.\n"
            "- The question \"text\" must reference the image (e.g. 'Study the diagram above and answer:'). The image is rendered ABOVE the question.\n"
            "- Only add \"image_prompt\" to the specific questions that need an image — not all questions.\n"
        )

    error_block = ""
    if prior_error and attempt > 1:
        error_block = f"\n⚠️  PREVIOUS ATTEMPT FAILED — FIX THESE ISSUES:\n{prior_error}\n"

    # source='general' slot census — drives the chapter block, rule 5 and rule 7 below.
    _general_count = sum(
        1 for s in (wo.slots or [])
        if str(s.get("source") or "").strip().lower() == "general"
    )
    _all_general = bool(wo.slots) and _general_count == len(wo.slots)

    if wo.context_text:
        ctx = wo.context_text
        ctx_label = "REFERENCE MATERIAL (base questions strictly on these textbook excerpts)"
        rule5 = "5. Draw question content from the reference material above"
    else:
        ctx = f"No textbook content indexed. Use your CBSE {wo.subject} Class {wo.class_name} knowledge."
        ctx_label = "REFERENCE MATERIAL"
        rule5 = (f"5. Compose original questions from your own CBSE {wo.subject} "
                 f"Class {wo.class_name} knowledge — no reference material is provided")
    rule7 = ("7. Do NOT reference the textbook, its chapters, stories or characters "
             "anywhere in this section."
             if _all_general else
             "7. Questions MUST come from different chapters — no chapter monopoly.")
    diff_block = _difficulty_block(wo.difficulty)

    # C-01: use section-specific sub-subject when set (compound papers)
    effective_subject = wo.section_subject or wo.subject
    chapters_str = ", ".join(wo.chapters) if wo.chapters else "all topics"
    chapter_count = len(wo.chapters) if wo.chapters else 1
    per_chapter = max(1, round(wo.questions_count / chapter_count)) if wo.questions_count else 1

    # CHAPTER ASSIGNMENT — use the deterministic, CBSE-weighted plan when present (set by
    # plan_chapter_allocation): it names exactly how many questions come from each chapter so
    # coverage is predictable and weighted instead of left to the model. Falls back to the
    # legacy "spread evenly" instruction when there is no plan (e.g. chapter-less tests).
    # source='general' slots are the exception: a chapter assignment would order the model
    # straight back into the textbook the teacher just banned (a Grammar section shipped a
    # 'Wit and Humour' comprehension question this way), so all-general sections replace the
    # block outright and mixed sections exempt their general questions.
    if _all_general:
        chapter_block = (
            "CHAPTER ASSIGNMENT: NONE — every question in this section is GENERAL KNOWLEDGE.\n"
            "Do NOT draw questions from, reference, or name any textbook chapter, story or "
            "character. Write each question on its stated TOPIC at the class level and set "
            'its "chapter_tag" to "General".'
        )
    elif wo.chapter_plan:
        from collections import Counter
        _dist = Counter(wo.chapter_plan)
        _lines = "\n".join(f'  - "{ch}": {n} question(s)' for ch, n in _dist.items())
        chapter_block = (
            "CHAPTER ASSIGNMENT — MANDATORY (counts are weighted by CBSE importance):\n"
            f"Draw the {wo.questions_count} questions from these chapters in EXACTLY this distribution:\n"
            f"{_lines}\n"
            'Set each question\'s "chapter_tag" to the exact chapter it is drawn from. '
            "Do NOT use any chapter that is not listed above."
        )
    else:
        chapter_block = (
            f"CHAPTER DISTRIBUTION — MANDATORY:\n"
            f"Spread questions across ALL {chapter_count} chapter(s): {chapters_str}\n"
            f"Target ~{per_chapter} question(s) per chapter. Never draw all questions from one chapter."
        )
    if _general_count and not _all_general:
        chapter_block += (
            "\nEXCEPTION: questions marked GENERAL KNOWLEDGE in the per-question "
            "specification are exempt — they must NOT come from any chapter; set their "
            '"chapter_tag" to "General".'
        )
    # Grammar sections: the chapter list is already routed to the textbook's grammar
    # LESSONS (see identify_grammar_chapters), but the model must also be told to test
    # grammar CONCEPTS — otherwise it happily writes literature-comprehension questions
    # about whatever text appears in the retrieved excerpts.
    if wo.is_grammar and not _all_general:
        chapter_block += (
            "\nGRAMMAR SECTION — MANDATORY: this section tests GRAMMAR only. Every question "
            "must test a grammar concept (letters/sounds, spelling, joining/sandhi rules, "
            "word forms and classes, sentence structure) as taught in the grammar lessons "
            "listed above. Do NOT ask reading-comprehension or literature questions here — "
            "no story/poem content, characters, authors or poem lines."
        )

    # QUESTION TYPE — MANDATORY. The STRICT RULES below are MCQ-heavy, and uniform non-MCQ
    # sections otherwise drift into producing MCQs (a "Short Answer" section coming back full
    # of MCQs). Name the exact allowed type(s) up front and forbid everything else.
    _CAT_LABEL = {
        "mcq": "MCQ (4 options a/b/c/d + answer)",
        "ar":  "Assertion-Reason MCQ (the 4 standard A/R options + answer)",
        "vsa": "Very Short Answer (VSA) — a written-answer question, NO options",
        "sa":  "Short Answer (SA) — a written-answer question, NO options",
        "la":  "Long Answer (LA) — a written-answer question, NO options",
        "cbq": "Case-Based Question (CBQ) with sub_questions",
        "map": "Map-work question (type SA, subtype map_based)",
    }
    _CAT_JSON = {
        "mcq": '"type":"MCQ"', "ar": '"type":"MCQ","subtype":"assertion_reason"',
        "vsa": '"type":"VSA"', "sa": '"type":"SA"', "la": '"type":"LA"',
        "cbq": '"type":"CBQ"', "map": '"type":"SA","subtype":"map_based"',
    }
    _allowed_cats = []
    for _t in (wo.question_types or []):
        _c = _fine_category(_t if isinstance(_t, str) else _t.get("type", ""))
        if _c and _c != "other" and _c not in _allowed_cats:
            _allowed_cats.append(_c)
    if _allowed_cats:
        _labels = "; ".join(_CAT_LABEL.get(c, c.upper()) for c in _allowed_cats)
        _jsons = " OR ".join(_CAT_JSON[c] for c in _allowed_cats if c in _CAT_JSON)
        type_directive = (
            "QUESTION TYPE — MANDATORY (read this first):\n"
            f"EVERY question in this section MUST be: {_labels}.\n"
            f"Use exactly {_jsons} in each question's JSON \"type\" field. "
            "Do NOT generate any other question type."
        )
        if all(c in ("vsa", "sa", "la") for c in _allowed_cats):
            type_directive += (
                "\n⚠️  These are WRITTEN-ANSWER questions — do NOT include an \"options\" field, "
                "do NOT make them multiple-choice. Provide \"answer_explanation\" instead."
            )
    else:
        type_directive = ""

    math_notation_block = ""
    if any(kw in effective_subject.lower() for kw in ("math", "physics", "chemistry", "science")):
        math_notation_block = """
MATHEMATICAL NOTATION (strictly follow):
- Powers: use Unicode superscripts — x² not x^2, Aⁿ⁻¹ not A^(n-1), xⁿ not x^n
- Multiplication: use × not * (e.g. 3 × 4, |A| × |B|)
- Square root: √x not sqrt(x)
- Fractions: write as p/q or use "over" (e.g. (n+1)/2)
"""

    # MO-01: attempt-N-of-M instruction
    attempt_block = ""
    if wo.provided_count and wo.attempt_count and wo.provided_count > wo.attempt_count:
        attempt_block = (
            f"\nATTEMPT INSTRUCTION — MANDATORY:\n"
            f"Generate EXACTLY {wo.provided_count} questions. "
            f"Students will answer any {wo.attempt_count} of these {wo.provided_count} questions. "
            f"Include a note at the top of the section: "
            f"\"Attempt any {wo.attempt_count} of the following {wo.provided_count} questions.\"\n"
        )

    # M-04: map work instruction
    map_work_block = ""
    if wo.is_map_work:
        map_work_block = (
            "\nMAP WORK INSTRUCTION:\n"
            "- Generate a list of specific historically/geographically significant places to locate on an outline map.\n"
            "- Format: (a) Place associated with [event/significance] (b) Place associated with ... etc.\n"
            "- Include \"map_note\" field: \"[Attach outline map of India — examiner to supply]\"\n"
            "- Do NOT attempt to describe the map itself; only list what to locate.\n"
        )

    # M-02: OR alternative rule. Slot-authored sections decide internal choice PER
    # QUESTION (slot.choice == "internal", flagged in the per-question spec below) —
    # the LA-blanket rule only applies to slot-less legacy sections.
    or_rule = ""
    if wo.slots:
        if any(s.get("choice") == "internal" for s in wo.slots):
            or_rule = (
                "\n9. INTERNAL CHOICE (OR):\n"
                "   Only the questions marked INTERNAL CHOICE in the per-question specification "
                "MUST include an \"or_alternative\" field (an alternate full question, same marks, "
                "different focus). Do NOT add \"or_alternative\" to any other question.\n"
            )
            if any(s.get("choice") == "internal"
                   and (pattern_structure.slot_category(str(s.get("type") or "")) == "cbq"
                        or s.get("parts"))
                   for s in wo.slots):
                or_rule += (
                    "   For passage/extract questions the \"or_alternative\" MUST be a JSON OBJECT — "
                    "a complete second question with its OWN \"source_text\" (a DIFFERENT passage or "
                    "extract), its OWN \"text\" and its OWN \"sub_questions\" (same count and marks as "
                    "the first option). Never return a bare string for these.\n"
                )
            if any(s.get("choice") == "internal"
                   and len([a for a in (s.get("alternatives") or []) if str(a).strip()]) >= 3
                   for s in wo.slots):
                or_rule += (
                    "   When the per-question specification lists MORE than two options, "
                    "\"or_alternative\" is a JSON ARRAY with one complete alternative per extra "
                    "option — the paper prints every option separated by OR.\n"
                )
    elif any(_type_str(t) in ("la", "long_answer", "long answer") for t in wo.question_types):
        or_rule = (
            "\n9. INTERNAL CHOICE (OR) — MANDATORY FOR LA:\n"
            "   Every Long Answer question MUST include an \"or_alternative\" field with an alternate "
            "question on a DIFFERENT concept from the same chapter, worth the same marks. "
            "This is mandatory in CBSE board papers.\n"
        )

    generate_count = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count

    # ── Per-type marks breakdown (critical for mixed-marks sections) ──────────────
    # For sections with uniform marks, a single "marks per question" line is fine.
    # For mixed sections (MCQ=1m, SA=3m, LA=5m, CBQ=4m, …) we MUST list marks per
    # type explicitly — otherwise the LLM uses the section average (e.g. 2.2m) for
    # every question, causing blanket marks-mismatch failures on every attempt.
    if wo.mixed_marks and wo.question_types:
        lines = []
        for qt in wo.question_types:
            if isinstance(qt, dict):
                rng  = qt.get("range", "")
                typ  = qt.get("type", "")
                cnt  = qt.get("count", 1)
                mke  = qt.get("marks_each", wo.marks_per_question)
                lines.append(f"  {rng}: {typ} → {mke} mark{'s' if mke != 1 else ''} each")
        marks_spec = (
            "- Marks per question: VARIES BY TYPE — use EXACT marks below:\n"
            + "\n".join(lines)
        )
        marks_rule4 = (
            "4. MARKS PER QUESTION TYPE — MANDATORY (section has mixed marks):\n"
            + "\n".join(f"   {l.strip()}" for l in lines) + "\n"
            "   ⚠️  DO NOT use the section average for all questions — each question's\n"
            "   marks must match its type as shown above. Using 2.2 or 2.0 for all\n"
            "   questions is WRONG and will cause the entire section to be rejected."
        )
    else:
        marks_spec = f"- Marks per question: {wo.marks_per_question}"
        marks_rule4 = f"4. Each question marks = {wo.marks_per_question}"

    # ── Question-position blueprint (for mixed-type sections) ─────────────────────
    # When a section has multiple question types (e.g. MCQ for Q1-4, VSA for Q5,
    # SA for Q6, LA for Q7, CBQ for Q8, Map for Q9), list the expected type at each
    # position explicitly so the LLM doesn't assign types freely.
    # Maps blueprint category to the canonical "type" value the LLM must write in JSON
    _cat_to_json = {
        "mcq": '"type": "MCQ"',
        "vsa": '"type": "VSA"',
        "sa":  '"type": "SA"',
        "la":  '"type": "LA"',
        "cbq": '"type": "CBQ"',
        "map": '"type": "SA", "subtype": "map_based"',
    }

    qpos_block = ""
    if wo.mixed_marks and wo.question_types and not wo.slots:
        pos_lines = []
        has_ar_pos = False
        local_start = 1
        for qt in wo.question_types:
            if isinstance(qt, dict):
                cnt  = int(qt.get("count", 1))
                typ  = qt.get("type", "")
                rng  = qt.get("range", f"Q{local_start}" if cnt == 1 else f"Q{local_start}-{local_start+cnt-1}")
                mke  = qt.get("marks_each", wo.marks_per_question)
                typ_lower = str(typ).lower()
                # Assertion-Reason is an MCQ subtype — emit it explicitly so the model
                # doesn't downgrade it to a plain MCQ (which loses the A/R statements).
                if "assertion" in typ_lower:
                    json_type = '"type": "MCQ", "subtype": "assertion_reason"'
                    has_ar_pos = True
                else:
                    cat = _type_category(typ)
                    json_type = _cat_to_json.get(cat, f'"type": "{cat.upper()}"')
                pos_lines.append(f"  {rng} ({cnt} question{'s' if cnt>1 else ''}): {json_type}, marks={mke}")
                local_start += cnt
        if pos_lines:
            ar_note = (
                "\nFor assertion_reason positions: 'text' MUST be "
                '"Assertion (A): [full statement]\\nReason (R): [full statement]" '
                "(both statements written out in full, NOT the word \"Assertion\" alone), "
                "with the 4 standard AR options.\n"
                if has_ar_pos else ""
            )
            qpos_block = (
                "\nQUESTION-POSITION BLUEPRINT — MANDATORY:\n"
                "Generate questions in EXACTLY this order, type, and marks:\n"
                + "\n".join(pos_lines) + "\n"
                "Each question's 'type', 'subtype', and 'marks' MUST match this blueprint exactly.\n"
                "Do NOT assign the same type to all questions — the section has MULTIPLE question types.\n"
                "Do NOT add Assertion-Reason questions at positions not marked assertion_reason above.\n"
                + ar_note
            )

    # ── Per-question slot specification (question_slots patterns) ──────────────────
    # Slot-authored sections state every printed question explicitly — type, topic,
    # format, marks, source and choice conditions. This supersedes the position
    # blueprint above (qpos_block is skipped for slot sections) and finally routes
    # per-question topics ("Homophones", "Past perfect tense") into the prompt.
    slot_block = ""
    if wo.slots:
        s_lines = []
        for pos, s in enumerate(wo.slots, start=1):
            styp = str(s.get("type") or "")
            parts = [p for p in (s.get("parts") or []) if isinstance(p, dict)]
            if styp == "ar":
                json_type = '"type": "MCQ", "subtype": "assertion_reason"'
            elif pattern_structure.slot_category(styp) == "cbq":
                json_type = '"type": "CBQ", "subtype": "source_based"'
            elif parts:
                json_type = '"type": "CBQ"'
            else:
                json_type = _cat_to_json.get(_type_category(styp), '"type": "SA"')
            label = pattern_structure.SLOT_TYPE_LABEL.get(styp, styp or "question")
            line = f"  Question {pos}: {label} — {json_type}, marks={s.get('marks')}"
            if s.get("topic"):
                line += f" | TOPIC: {s['topic']}"
            if s.get("format"):
                line += f" | format: {s['format']}"
            if s.get("source") == "textbook":
                line += " | material MUST come from the textbook/reference material"
            elif s.get("source") == "unseen":
                line += " | write UNSEEN (new, original) material"
            elif s.get("source") == "general":
                line += (
                    " | GENERAL KNOWLEDGE — do NOT take this question from the textbook or the "
                    "reference material; write an ORIGINAL question from general knowledge of the "
                    "subject at this class level (no chapter names, characters, or lines from any "
                    "textbook content)"
                )
            if s.get("condition"):
                line += f" | condition: {s['condition']}"
            if s.get("choice") == "internal":
                alts = [str(a).strip() for a in (s.get("alternatives") or []) if str(a).strip()]
                if pattern_structure.slot_category(styp) == "cbq" or parts:
                    line += (
                        ' | INTERNAL CHOICE — "or_alternative" MUST be a JSON OBJECT: a COMPLETE '
                        'second question with its OWN "source_text" (a DIFFERENT passage/extract), '
                        'its OWN "text" and its OWN "sub_questions" (same count and marks as the '
                        "first option); students answer ONE of the two"
                    )
                    if len(alts) >= 3:
                        line += (
                            f' — this question has {len(alts)} options, so "or_alternative" is a '
                            f"JSON ARRAY of {len(alts) - 1} such objects; each option's "
                            'sub_questions must be answerable ONLY from that option\'s OWN '
                            '"source_text", never from the other option\'s passage'
                        )
                    else:
                        line += (
                            "; each option's sub_questions must be answerable ONLY from that "
                            'option\'s OWN "source_text", never from the other option\'s passage'
                        )
                elif len(alts) >= 3:
                    line += (
                        f' | INTERNAL CHOICE with {len(alts)} options — provide {len(alts) - 1} '
                        'complete alternative questions in "or_alternative" as a JSON ARRAY '
                        f"(each worth {s.get('marks')} marks; the paper prints all {len(alts)} "
                        'options separated by OR). The "text" field must BE the first full '
                        'option — do NOT write an "Attempt any one" umbrella line and do NOT '
                        "prefix options with A/B/C (the OR separators express the choice)"
                    )
                else:
                    line += ' | INTERNAL CHOICE — include "or_alternative" (same marks)'
                if alts:
                    line += f" [option hints: {'; '.join(alts)}]"
            if parts:
                part_bits = ", ".join(
                    f"({p.get('label') or chr(97 + j)}) "
                    f"{pattern_structure.SLOT_TYPE_LABEL.get(str(p.get('type') or ''), str(p.get('type') or 'part'))} "
                    f"{p.get('marks')}m"
                    for j, p in enumerate(parts)
                )
                line += f' | {len(parts)} sub-parts in "sub_questions": {part_bits}'
                if any(str(p.get("type") or "") == "mcq" for p in parts):
                    line += (
                        ' | MCQ sub-parts MUST carry their four options INLINE in their "text" '
                        '("… a) …, b) …, c) …, d) …")'
                    )
                if s.get("choice") == "open" and s.get("attempt"):
                    line += (
                        f" | OPEN CHOICE: provide all {len(parts)} sub-parts; students attempt any "
                        f"{s['attempt']} — begin the question text with "
                        f"\"Attempt any {s['attempt']} of the following {len(parts)}:\""
                    )
            if parts and pattern_structure.slot_category(styp) != "cbq":
                line += (
                    ' | NO PASSAGE: do NOT include "source_text" on this question — the '
                    "sub-parts are standalone questions"
                )
            if pattern_structure.slot_category(styp) == "cbq":
                if styp == "extract" or s.get("source") == "textbook":
                    line += (
                        ' | put the extract in "source_text" — a VERBATIM word-for-word quotation '
                        "copied from the reference material (actual prose/poem lines as printed), "
                        "NOT a summary, a description of the text, or a newly composed passage. "
                        "Quote a CONTINUOUS narrative/literary passage with a natural beginning "
                        "and end (complete sentences) — NEVER grammar or pronunciation "
                        "explanations, skill boxes, activity instructions, fill-in-the-blank "
                        "exercise text, the chapter's own exercise questions ('Let us discuss', "
                        "'Share with your classmates'), or page headers/numbers"
                    )
                    if wo.extract_instruction:
                        line += f" | extract length/format: {wo.extract_instruction}"
                    if "[CONTINUOUS PASSAGE" in (wo.context_text or ""):
                        line += (
                            ' | quote each extract from inside ONE "[CONTINUOUS PASSAGE]" block '
                            "of the reference material — each block is one unbroken excerpt as "
                            "printed, long enough to satisfy the stated extract length"
                        )
                elif s.get("source") == "unseen":
                    line += (
                        ' | COMPOSE a NEW, original passage (or poem, if the topic/format says '
                        "so) appropriate for this class, subject and language, and put it in "
                        '"source_text" — the paper PRINTS it before the sub-questions. Every '
                        "sub-question must be answerable ONLY from that passage, never from "
                        "textbook chapters"
                    )
                    if wo.extract_instruction:
                        line += f" | {wo.extract_instruction}"
                else:
                    line += ' | include the passage/extract in "source_text" on this question'
                    if wo.extract_instruction:
                        line += f" | {wo.extract_instruction}"
            s_lines.append(line)
        general_note = ""
        if wo.context_text and any(str(s.get("source") or "").lower() == "general" for s in wo.slots):
            general_note = (
                "The REFERENCE MATERIAL below applies ONLY to questions marked textbook/unseen — "
                "questions marked GENERAL KNOWLEDGE must NOT reuse its content, wording, characters "
                "or chapter names. "
            )
        no_passage_note = ""
        if not any(str(s.get("source") or "").lower() == "unseen" for s in wo.slots):
            no_passage_note = (
                'Do NOT output a section-level "passage" key — passages belong on individual '
                'questions in "source_text". '
            )
        slot_block = (
            "\nPER-QUESTION SPECIFICATION — MANDATORY:\n"
            "Generate EXACTLY the following questions, in this exact order (one JSON question "
            "object per line item):\n"
            + "\n".join(s_lines) + "\n"
            "Each question's type, subtype and marks MUST match its line above. Write the "
            "question ON the stated TOPIC where one is given. Sub-parts go in that question's "
            '"sub_questions" array (each entry with "text" and "marks"). ' + general_note +
            no_passage_note + "Do NOT merge, split, reorder or renumber questions.\n"
        )

    # Avoid repeating questions from earlier papers (so two classes don't get identical papers).
    _recent = _recent_question_stems(wo.class_name, wo.subject)
    avoid_block = ""
    if _recent:
        avoid_block = (
            "\nALREADY ASKED IN EARLIER PAPERS — do NOT repeat or lightly reword these; "
            "write fresh, distinct questions:\n"
            + "\n".join(f"- {t[:130]}" for t in _recent[:30]) + "\n"
        )

    language_directive = _language_directive(effective_subject)

    return f"""You are a CBSE Class {wo.class_name} {effective_subject} question paper author.
Generate ONLY the questions for {wo.section_name} of the exam.

{language_directive}
SECTION SPECIFICATION:
- Section: {wo.section_name} ({wo.title})
- Questions required: {generate_count}
{marks_spec}
- Total marks: {wo.marks}
- Chapters to cover: {chapters_str}
- Subject focus: {effective_subject}

{type_directive}
{qpos_block}{slot_block}
{chapter_block}
{avoid_block}{diff_block}
{math_notation_block}
{ctx_label}:
---
{ctx}
---

INSTRUCTIONS:
{instructions_str}
{constraints_str}{passage_block}{ar_block}{image_block}{attempt_block}{map_work_block}
OUTPUT — return ONLY this JSON (no markdown fences, no explanations):
{_output_schema(wo, image_vision)}

STRICT RULES:
1. Generate EXACTLY {generate_count} questions — no more, no less
2. MCQ / Assertion-Reason questions MUST have 4 options: a, b, c, d
3. Do NOT embed section headers or question numbers in the 'text' field
{marks_rule4}
{rule5}
6. MCQ ANSWER DISTRIBUTION — MANDATORY: Spread correct answers across a, b, c, d roughly equally. Never place the correct answer in the same option letter for more than 2 consecutive questions. A biased answer key (e.g. mostly 'a' or 'b') will be REJECTED.
{rule7}
8. COMPETENCY TAGGING — MANDATORY: Every question must include a "competency_type" field:
   - "recall"      → direct knowledge MCQ (define, name, state — no reasoning required)
   - "application" → MCQ requiring reasoning, ALL assertion-reason, ALL case-based, numerical multi-step
   - "constructed" → ALL short-answer and long-answer written responses
   Target across the paper: ~50% application marks, ~20% recall marks, ~30% constructed marks.
9. SUBTYPE — MANDATORY: Every question must include a "subtype" field:
   - "standard"        → regular MCQ, SA, LA, or VSA question
   - "assertion_reason"→ Assertion-Reason MCQ (use with "type": "MCQ")
   - "map_based"       → map location/labelling question (use with "type": "SA")
   - "image_based"     → diagram/picture observation question (use with "type": "CBQ")
   - "source_based"    → passage/case/extract question (use with "type": "CBQ"){or_rule}
{error_block}""".strip()


# ─────────────────────────────────────────────
# JSON extraction
# ─────────────────────────────────────────────

def _salvage_truncated_section_json(clean: str) -> dict | None:
    """
    Best-effort recovery when a section's JSON is truncated (model hit the output cap mid-array).
    Pulls the section header fields and every COMPLETE question object that parsed before the
    cut-off, so the section ships partial instead of failing hard. Returns None if unusable.
    """
    qstart = re.search(r'"questions"\s*:\s*\[', clean)
    if not qstart:
        return None

    questions = []
    depth = 0
    obj_start = None
    in_str = False
    esc = False
    i = qstart.end()
    while i < len(clean):
        ch = clean[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    questions.append(json.loads(clean[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
        elif ch == "]" and depth == 0:
            break
        i += 1

    if not questions:
        return None

    data: dict = {"questions": questions}
    sid = re.search(r'"section_id"\s*:\s*"([^"]*)"', clean)
    sname = re.search(r'"section_name"\s*:\s*"([^"]*)"', clean)
    passage = re.search(r'"passage"\s*:\s*"((?:[^"\\]|\\.)*)"', clean)
    if sid:
        data["section_id"] = sid.group(1)
    if sname:
        data["section_name"] = sname.group(1)
    if passage:
        data["passage"] = passage.group(1)
    return data


def extract_section_json(raw: str) -> dict:
    clean = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r"\n?```$", "", clean.strip())
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Last resort: salvage complete question objects from truncated output
    salvaged = _salvage_truncated_section_json(clean)
    if salvaged and salvaged.get("questions"):
        print(f"[JSON-Salvage] Recovered {len(salvaged['questions'])} complete "
              f"question(s) from truncated output ({len(raw)} chars)")
        return salvaged
    raise ValueError(f"Could not extract JSON from LLM output ({len(raw)} chars)")


# ─────────────────────────────────────────────
# Per-question type+subtype validation
# ─────────────────────────────────────────────

def _validate_mcq_options(q: dict, n: int, label: str) -> list:
    """Require EXACTLY 4 non-empty options (keyed a/b/c/d for the dict form) and a valid
    answer key (a/b/c/d). Catches the student-visible MCQ defects: 3 options, a stray 5th,
    an empty choice, wrong keys, or no correct answer marked."""
    errs = []
    raw = q.get("options")
    if isinstance(raw, dict):
        keys = [str(k).lower().strip() for k in raw.keys()]
        vals = [str(v).strip() for v in raw.values()]
        if len(vals) == 4 and set(keys) != {"a", "b", "c", "d"}:
            errs.append(f"Q{n} [{label}]: option keys must be exactly a, b, c, d (got {sorted(keys)}).")
    elif isinstance(raw, list):
        vals = [str(v).strip() for v in raw]
    else:
        vals = []
    nonempty = [v for v in vals if v]
    if len(vals) != 4 or len(nonempty) != 4:
        errs.append(
            f"Q{n} [{label}]: must have EXACTLY 4 non-empty options (a/b/c/d) — "
            f"found {len(nonempty)} non-empty of {len(vals)}."
        )
    ans = str(q.get("answer", "")).lower().strip()
    if not ans:
        errs.append(f"Q{n} [{label}]: missing 'answer' — give the correct option letter (a/b/c/d).")
    elif ans not in {"a", "b", "c", "d"}:
        errs.append(f"Q{n} [{label}]: 'answer' must be a/b/c/d (got {ans!r}).")
    return errs


def _norm_text(t: str) -> str:
    """Bare lowercase words — whitespace/punctuation-insensitive comparison form."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(t or "").lower())).strip()


def _stitched_extract_issue(src: str, ctx: str):
    """First sentence of `src` that does not exist verbatim in `ctx`, or None.

    A quoted extract must be ONE continuous span. Passages stitched together from
    different places read fine to the shingle-overlap check (every fragment is
    verbatim) but their splice sentences don't exist in the material as written —
    sentence-level containment catches exactly those.
    """
    c = _norm_text(ctx)
    if not c:
        return None
    for sent in re.split(r"(?<=[.!?])\s+", str(src or "").strip()):
        ns = _norm_text(sent)
        if len(ns.split()) >= 5 and ns not in c:
            return sent.strip()[:60]
    return None


def _ctx_has_long_block(ctx: str, words: int) -> bool:
    """True when the reference material contains a [CONTINUOUS PASSAGE] block of at
    least `words` words — i.e. an extract that long is provably quotable from it."""
    for m in re.finditer(r"\[CONTINUOUS PASSAGE[^\]]*\](.*?)\[END OF PASSAGE",
                         str(ctx or ""), re.S):
        if len(m.group(1).split()) >= words:
            return True
    return False


def _extract_length_issue(src: str, instruction: str, ctx: str):
    """Error text when an extract falls far short of the pattern's stated word target
    (extract_instruction, e.g. "approximately 500 words per passage"), or None.

    Loose by design: ≥60% of the target passes ("approximately"), and the error only
    fires when a continuous block that long actually exists in the context — otherwise
    the retry could never succeed and would burn every attempt."""
    m = re.search(r"(\d{2,4})\s*words", str(instruction or ""), re.IGNORECASE)
    if not m:
        return None
    target = int(m.group(1))
    have = len(str(src or "").split())
    if have >= int(target * 0.6) or not _ctx_has_long_block(ctx, target):
        return None
    return (f"is only {have} words but the pattern asks for approximately {target} — "
            'quote a longer continuous passage from inside ONE "[CONTINUOUS PASSAGE]" block')


def _foreign_quote(sq_texts, own_src, other_src):
    """A phrase quoted in sub-questions that appears ONLY in the sibling option's
    passage — proof the sub-question was written against the wrong extract."""
    own, other = _norm_text(own_src), _norm_text(other_src)
    if not other:
        return None
    for t in sq_texts:
        for m in re.findall(r"[‘'\"“]([^’'\"”]{4,60})[’'\"”]", str(t or "")):
            nm = _norm_text(m)
            if nm and nm not in own and nm in other:
                return m
    return None


def _text_overlaps_context(src: str, ctx: str) -> bool:
    """True when `src` looks like a verbatim excerpt of `ctx` (extract provenance).

    A word-for-word quotation shares nearly all of its 8-word shingles with the
    reference material; a composed/summarised passage shares almost none. 30% is
    generous enough to survive OCR noise and punctuation drift (both sides are
    normalised to bare lowercase words before comparison).
    """
    s, c = _norm_text(src), _norm_text(ctx)
    if not s or not c:
        return False
    words = s.split()
    if len(words) < 8:
        return s in c
    shingles = [" ".join(words[i:i + 8]) for i in range(len(words) - 7)]
    step = max(1, len(shingles) // 40)   # sample ≤ ~40 shingles, evenly spread
    sample = shingles[::step]
    hits = sum(1 for sh in sample if sh in c)
    return hits / len(sample) >= 0.3


def _extract_text_issue(src: str):
    """Reason a literature-extract passage is unusable, or None.

    Extracts must be coherent literary text quoted whole: worksheet/skill-box
    content (fill-in blanks, bullets, (i)/(ii) numbering), the chapter's own
    exercise-question pages (numbered questions, "Share with your classmates…",
    page headers like "Poorvi62") and fragments clipped mid-sentence all shipped
    on real papers, so they are rejected mechanically.
    """
    s = str(src or "").strip()
    if not s:
        return None
    for m in ("___", "•", "→", "▪", "◦"):
        if m in s:
            return f"contains worksheet/skill-box markup ({m})"
    if "(i)" in s and "(ii)" in s:
        return "contains worksheet numbering ((i), (ii), …)"
    for ln in (ln.strip() for ln in s.splitlines() if ln.strip()):
        if re.match(r"^[A-Za-z]*\s?\d+\s*$", ln):
            return f"contains a page-header artefact ({ln!r})"
        if re.match(r"^\d+\s*[.)]\s", ln) or re.match(r"^[IVXivx]{2,4}[.)]?\s+[A-Z]", ln):
            return f"contains exercise/question numbering ({ln[:40]!r})"
    low = s.lower()
    for phrase in ("your classmates", "your teacher", "let us discuss",
                   "answer the following", "match the following", "fill in the blank",
                   "choose the correct option", "complete the sentence",
                   "tick the correct"):
        if phrase in low:
            return f"contains classroom-exercise wording ({phrase!r})"
    first = s.lstrip("\"'“‘( ")[:1]
    if first and first.islower():
        return "starts mid-sentence (clipped fragment)"
    if s[-1] not in ".!?\"'”’…":
        return "does not end at a sentence boundary (clipped fragment)"
    return None


def _sq_has_inline_mcq_options(txt: str) -> bool:
    """True when a sub-question's text carries inline MCQ options (a) … d) style)."""
    letters = {m.lower() for m in re.findall(r"\(?([a-dA-D])[).]", str(txt or ""))}
    return len(letters) >= 3


def _validate_by_subtype(q: dict, n: int, wo: SectionWorkOrder) -> list:
    """
    Explicit structural validation for every type+subtype combination.

    Matrix:
      MCQ  / standard         text + 4 options
      MCQ  / assertion_reason text with 'Assertion (A):' AND 'Reason (R):' + 4 standard AR options
      SA   / standard         text + answer_explanation
      SA   / map_based        text listing locations + map_note field
      VSA  / standard         text + answer_explanation
      LA   / standard         text + answer_explanation + or_alternative (CBSE internal choice)
      CBQ  / source_based     text + sub_questions (marks sum == q.marks)
      CBQ  / image_based      text + sub_questions (marks sum == q.marks); auto-sets image_based=True
    """
    errors = []
    raw_type = str(q.get("type", "")).strip()
    qtype = raw_type.upper()
    type_lower = raw_type.lower()
    subtype = str(q.get("subtype", "standard")).strip().lower()
    text = str(q.get("text", "")).strip()
    opts = q.get("options")
    if not isinstance(opts, dict):
        opts = {}
    # Slot-authored sections generate in slot order, so position n maps to slot n-1.
    # The slot carries per-question choice conditions that override type conventions.
    slot = wo.slots[n - 1] if (wo.slots and 0 <= n - 1 < len(wo.slots)) else None

    if not type_lower:
        errors.append(f"Q{n}: missing 'type' field (must be MCQ / VSA / SA / LA / CBQ)")

    # General-knowledge slots must not reference textbook chapters: the teacher banned
    # textbook content outright, yet a chapter-assigned model happily writes "In the
    # story X from the chapter Y…". Deterministic name check across the visible text.
    if slot and str(slot.get("source") or "").strip().lower() == "general":
        blobs = [text]
        _oa = q.get("or_alternative")
        for _oa_entry in (_oa if isinstance(_oa, list) else [_oa]):
            if isinstance(_oa_entry, str):
                blobs.append(_oa_entry)
            elif isinstance(_oa_entry, dict):
                blobs.append(str(_oa_entry.get("text", "")))
        blobs.extend(str(sq.get("text", "")) for sq in (q.get("sub_questions") or [])
                     if isinstance(sq, dict))
        blob = " ".join(blobs).lower()
        for ch in (wo.chapters or []):
            chl = str(ch).strip().lower()
            if len(chl) >= 4 and chl in blob:
                errors.append(
                    f"Q{n}: this question is GENERAL KNOWLEDGE — it must not reference the "
                    f"textbook chapter '{ch}'; write an original question on the stated topic"
                )
                break

    # ── MCQ ──────────────────────────────────────────────────────────────────────
    is_mcq = ("mcq" in type_lower or "objective" in type_lower or "multiple" in type_lower)
    # Detect AR by declared type/subtype OR by the tell-tale option content. The model
    # sometimes emits subtype="standard" but fills the 4 standard AR choices and leaves
    # 'text' as just "Assertion" — without the option-content check this passes as a
    # plain MCQ and renders as a headless Assertion-Reason question.
    _opt_blob = " ".join(str(v).lower() for v in opts.values())
    looks_like_ar = (
        "both a and r" in _opt_blob
        or ("a is true" in _opt_blob and "r is false" in _opt_blob)
        or ("a is false" in _opt_blob and "r is true" in _opt_blob)
    )
    is_ar_type = "assertion" in type_lower or subtype == "assertion_reason" or looks_like_ar

    if is_mcq or is_ar_type:
        if is_ar_type:
            # Full Assertion + Reason text required
            has_a = ("Assertion (A):" in text or "Assertion:" in text or
                     (text.startswith("A:") or "\nA:" in text))
            has_r = ("Reason (R):" in text or "Reason:" in text or
                     (text.startswith("R:") or "\nR:" in text))
            if not (has_a and has_r and len(text) > 50):
                errors.append(
                    f"Q{n} [MCQ/assertion_reason]: 'text' must contain both "
                    f"'Assertion (A): ...' AND 'Reason (R): ...' as full statements "
                    f"(got: {text[:60]!r}). "
                    'Required: "Assertion (A): [full statement]\\nReason (R): [full statement]"'
                )
            errors.extend(_validate_mcq_options(q, n, "MCQ/assertion_reason"))
        else:
            # Standard MCQ
            errors.extend(_validate_mcq_options(q, n, "MCQ/standard"))

    # ── SA / VSA ─────────────────────────────────────────────────────────────────
    elif qtype in ("SA", "VSA") or "short" in type_lower or "very short" in type_lower:
        if subtype == "map_based" or "map" in type_lower:
            if len(text) < 20:
                errors.append(
                    f"Q{n} [SA/map_based]: 'text' must list map locations "
                    f"(e.g. '(a) A place associated with ... (b) ...') — got {text[:40]!r}"
                )
            if not str(q.get("map_note", "")).strip():
                errors.append(
                    f"Q{n} [SA/map_based]: missing 'map_note' field "
                    "(must be '[Attach outline map of India — examiner to supply]')"
                )
        else:
            if not str(q.get("answer_explanation", "")).strip():
                errors.append(
                    f"Q{n} [{qtype}/standard]: missing 'answer_explanation' — "
                    "provide key answer points (2-3 sentences)"
                )

    # ── LA ────────────────────────────────────────────────────────────────────────
    elif qtype == "LA" or "long" in type_lower:
        if not str(q.get("answer_explanation", "")).strip():
            errors.append(
                f"Q{n} [LA/standard]: missing 'answer_explanation' — "
                "provide 4-6 bullet points of model answer content"
            )
        or_alt = q.get("or_alternative")
        # Per-question structure: the slot decides whether THIS question has internal
        # choice — the LA-blanket rule only applies to slot-less (legacy) sections.
        or_required = (slot.get("choice") == "internal") if slot else True
        # 3+ teacher alternatives ("paragraph OR letter OR notice") need an ARRAY with
        # one entry per extra option; two options keep the classic single alternative.
        _hint_count = len([a for a in ((slot or {}).get("alternatives") or [])
                           if str(a).strip()])
        _need = _hint_count - 1 if _hint_count >= 3 else 1
        if not or_alt:
            if or_required:
                errors.append(
                    f"Q{n} [LA/standard]: missing 'or_alternative' — "
                    "this question requires internal choice (OR)"
                )
        elif isinstance(or_alt, list):
            if len(or_alt) < _need:
                errors.append(
                    f"Q{n} [LA/standard]: the pattern offers {_hint_count} options — "
                    f"'or_alternative' must be an ARRAY of {_need} alternative questions"
                )
            for ai, a in enumerate(or_alt, start=2):
                if isinstance(a, str) and not a.strip():
                    errors.append(f"Q{n} [LA/standard]: 'or_alternative' option {ai} is empty")
                elif isinstance(a, dict) and not str(a.get("text", "")).strip():
                    errors.append(f"Q{n} [LA/standard]: 'or_alternative' option {ai} has empty text")
        elif _need > 1:
            errors.append(
                f"Q{n} [LA/standard]: the pattern offers {_hint_count} options — provide "
                f"{_need} alternative questions in 'or_alternative' as a JSON ARRAY"
            )
        elif isinstance(or_alt, str) and not or_alt.strip():
            errors.append(f"Q{n} [LA/standard]: 'or_alternative' is empty string")
        elif isinstance(or_alt, dict) and not str(or_alt.get("text", "")).strip():
            errors.append(f"Q{n} [LA/standard]: 'or_alternative.text' is empty")
        # Umbrella stems and A/B/C labels wreck the printed OR layout ("11. Attempt any
        # ONE… OR 11. A. …"): each option must itself be a complete question.
        if slot and slot.get("choice") == "internal":
            _opt_texts = [text]
            for _a in (or_alt if isinstance(or_alt, list) else [or_alt]):
                if isinstance(_a, str):
                    _opt_texts.append(_a)
                elif isinstance(_a, dict):
                    _opt_texts.append(str(_a.get("text", "")))
            if re.match(r"^\s*attempt any\b", text, re.IGNORECASE):
                errors.append(
                    f"Q{n} [LA/standard]: 'text' must BE the first full option — do not write "
                    "an 'Attempt any one' umbrella line (the OR separators express the choice)"
                )
            _labels = [m.group(1).upper() for t in _opt_texts
                       for m in [re.match(r"^\s*\(?([A-Da-d])[.)]\s", t or "")] if m]
            if len(_labels) >= 2:
                errors.append(
                    f"Q{n} [LA/standard]: do not prefix options with 'A.'/'B.'/'C.' — write "
                    "each option as a complete standalone question"
                )

    # ── CBQ ───────────────────────────────────────────────────────────────────────
    elif (qtype == "CBQ"
          or "source" in type_lower
          or "case" in type_lower
          or type_lower == "image_based"
          or subtype in ("source_based", "image_based")):
        sqs = q.get("sub_questions", [])
        if not isinstance(sqs, list):
            sqs = []
            q["sub_questions"] = []
        if not sqs:
            errors.append(
                f"Q{n} [CBQ/{subtype}]: missing 'sub_questions' — "
                "CBQ must have sub-questions each with 'text' and 'marks'"
            )
        else:
            for si, sq in enumerate(sqs):
                if isinstance(sq, dict) and not str(sq.get("text", "")).strip():
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: sub-question {si + 1} has empty 'text'"
                    )
            sq_sum = sum(
                _as_float(sq.get("marks", 0), 0.0) if isinstance(sq, dict) else 0.0
                for sq in sqs
            )
            expected = _as_float(q.get("marks", wo.marks_per_question), wo.marks_per_question)
            # Open-choice slots ("A to F, attempt any 5") legitimately provide MORE
            # sub-question marks than the question is worth — accept the provided total.
            open_total = 0.0
            if slot and slot.get("choice") == "open":
                open_total = sum(
                    _as_float(p.get("marks"), 0.0)
                    for p in (slot.get("parts") or []) if isinstance(p, dict)
                )
            if abs(sq_sum - expected) > 0.1 and not (open_total and abs(sq_sum - open_total) <= 0.1):
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: sub_question marks sum={sq_sum} "
                    f"!= question marks={expected} — adjust individual sub-question marks"
                )
            # Slot-declared parts pin the exact sub-part count and per-part marks: an
            # "attempt any 5 of 6" question shipping 5 parts slips past the marks-sum
            # check via the open-choice exemption, so count is enforced separately.
            slot_parts = ([p for p in (slot.get("parts") or []) if isinstance(p, dict)]
                          if slot else [])
            if slot_parts and len(sqs) != len(slot_parts):
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: the pattern declares {len(slot_parts)} sub-parts "
                    f"but got {len(sqs)} sub_questions — provide ALL {len(slot_parts)}"
                )
            elif slot_parts:
                for si, (sq, p) in enumerate(zip(sqs, slot_parts), start=1):
                    pm = _as_float(p.get("marks"), 0.0)
                    if pm > 0 and isinstance(sq, dict) and \
                            abs(_as_float(sq.get("marks", 0), 0.0) - pm) > 0.01:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: sub-question {si} marks="
                            f"{sq.get('marks')} but the pattern says part "
                            f"({p.get('label') or si}) is worth {p.get('marks')}m"
                        )
                    if str(p.get("type") or "") == "mcq" and isinstance(sq, dict) \
                            and not _sq_has_inline_mcq_options(sq.get("text")):
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: sub-question {si} is declared MCQ in the "
                            f"pattern (part {p.get('label') or si}) — include its four options "
                            "inline in its text: '… a) …, b) …, c) …, d) …'"
                        )
        _slot_type = str(slot.get("type") or "") if slot else ""
        _slot_cat = pattern_structure.slot_category(_slot_type) if _slot_type else None
        # Ensure image generation flag is set for image_based questions
        if subtype == "image_based" or type_lower == "image_based":
            q["image_based"] = True
        # A parts group that is NOT an extract/case study (e.g. SA "attempt any 5 of 6")
        # must not grow a passage — the sub-parts are standalone questions.
        elif slot and slot.get("parts") and _slot_cat and _slot_cat != "cbq":
            if str(q.get("source_text", "") or q.get("passage", "") or "").strip():
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: do NOT attach a 'source_text' passage — the pattern "
                    "asks for standalone sub-questions here (use subtype 'standard', no extract)"
                )
        # Source-based CBQ must carry its own passage in 'source_text' (mixed-section flow).
        # An image_based CBQ gets its visual from the image pipeline instead, so it's exempt.
        elif subtype == "source_based" or "source" in type_lower or "case" in type_lower:
            # Accept legacy 'passage' key too, but prefer 'source_text'
            src = str(q.get("source_text", "") or q.get("passage", "") or "").strip()
            if len(src) < 80:
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: missing 'source_text' — provide the case/source "
                    "passage (150-250 words) in a 'source_text' field on THIS question"
                )
            # Textbook extracts must be QUOTED, not composed: a slot that says
            # extract/textbook whose passage shares no wording with the reference
            # material is a hallucinated summary, not an extract.
            if (src and len(wo.context_text or "") >= 400
                    and (_slot_type == "extract" or (slot or {}).get("source") == "textbook")
                    and not _text_overlaps_context(src, wo.context_text)):
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: 'source_text' is NOT a verbatim excerpt from the "
                    "REFERENCE MATERIAL — copy the extract word-for-word from the textbook "
                    "excerpts above; do not summarise, describe or invent the passage"
                )
            elif (src and _slot_type == "extract" and len(wo.context_text or "") >= 400):
                # Verbatim overall, but is it ONE continuous span? Stitched passages
                # ("…of all people, for your choice.") splice fragments together.
                _sp = _stitched_extract_issue(src, wo.context_text)
                if _sp:
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: 'source_text' is stitched/edited — the sentence "
                        f"\"{_sp}…\" is not in the reference material as written; quote ONE "
                        "continuous passage exactly as printed"
                    )
            # …and quoted WHOLE: worksheet/skill-box text and mid-sentence fragments
            # are not literature extracts even when they are verbatim.
            if src and _slot_type == "extract":
                _issue = _extract_text_issue(src)
                if _issue:
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: 'source_text' {_issue} — quote a complete "
                        "literary passage (story/poem/reader lines) with a natural beginning "
                        "and end, not grammar/skill-box or exercise text"
                    )
                _len = _extract_length_issue(src, wo.extract_instruction, wo.context_text)
                if _len:
                    errors.append(f"Q{n} [CBQ/{subtype}]: 'source_text' {_len}")

        # Internal-choice CBQ/extract (slot.choice == "internal"): every OR alternative
        # must be a COMPLETE question — its own passage and its own sub-parts — or the
        # printed paper shows a bare "OR" line with nothing under it. 3+ teacher options
        # arrive as an ARRAY with one entry per extra option.
        if slot and slot.get("choice") == "internal":
            _exp = _as_float(q.get("marks", wo.marks_per_question), wo.marks_per_question)
            _hint_count = len([a for a in (slot.get("alternatives") or []) if str(a).strip()])
            _need = _hint_count - 1 if _hint_count >= 3 else 1
            or_alt = q.get("or_alternative")
            alt_list = or_alt if isinstance(or_alt, list) else ([or_alt] if or_alt is not None else [])
            if not alt_list:
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: 'or_alternative' must be a JSON OBJECT with its own "
                    "'source_text', 'text' and 'sub_questions' (a complete second question) — "
                    "it is missing"
                )
            elif len(alt_list) < _need:
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: the pattern offers {_hint_count} options — "
                    f"'or_alternative' must be an ARRAY of {_need} complete alternatives"
                )
            for ai, _alt in enumerate(alt_list, start=2):
                _tag = f"option {ai}" if len(alt_list) > 1 else "'or_alternative'"
                if not isinstance(_alt, dict):
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: {_tag} must be a JSON OBJECT with its own "
                        "'source_text', 'text' and 'sub_questions' (a complete second question)"
                        + (" — got a bare string" if isinstance(_alt, str) and _alt.strip() else "")
                    )
                    continue
                if not str(_alt.get("text", "")).strip():
                    errors.append(f"Q{n} [CBQ/{subtype}]: {_tag} 'text' is empty")
                alt_src = str(_alt.get("source_text", "") or _alt.get("passage", "") or "").strip()
                if subtype != "image_based" and len(alt_src) < 80:
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: {_tag} needs its OWN 'source_text' — "
                        "a DIFFERENT passage/extract, not a reference to the first one"
                    )
                elif (alt_src and len(wo.context_text or "") >= 400
                        and (str(slot.get("type") or "") == "extract"
                             or slot.get("source") == "textbook")
                        and not _text_overlaps_context(alt_src, wo.context_text)):
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: {_tag} 'source_text' is NOT a verbatim "
                        "excerpt from the REFERENCE MATERIAL — copy it word-for-word"
                    )
                elif (alt_src and str(slot.get("type") or "") == "extract"
                        and len(wo.context_text or "") >= 400):
                    _sp = _stitched_extract_issue(alt_src, wo.context_text)
                    if _sp:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: {_tag} 'source_text' is stitched/edited — "
                            f"the sentence \"{_sp}…\" is not in the reference material as "
                            "written; quote ONE continuous passage exactly as printed"
                        )
                if alt_src and str(slot.get("type") or "") == "extract":
                    _issue = _extract_text_issue(alt_src)
                    if _issue:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: {_tag} 'source_text' {_issue} — quote a "
                            "complete literary passage (story/poem/reader lines) with a natural "
                            "beginning and end, not grammar/skill-box or exercise text"
                        )
                    _len = _extract_length_issue(alt_src, wo.extract_instruction, wo.context_text)
                    if _len:
                        errors.append(f"Q{n} [CBQ/{subtype}]: {_tag} 'source_text' {_len}")
                alt_sqs = _alt.get("sub_questions")
                alt_sqs = alt_sqs if isinstance(alt_sqs, list) else []
                _n_expected = len([p for p in (slot.get("parts") or []) if isinstance(p, dict)]) \
                    or len(sqs)
                if not alt_sqs:
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: {_tag} needs its OWN 'sub_questions' "
                        "(same count and marks as the first option)"
                    )
                else:
                    if _n_expected and len(alt_sqs) != _n_expected:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: {_tag} has {len(alt_sqs)} "
                            f"sub_questions but must have {_n_expected} — all options must match"
                        )
                    for si, (sq, p) in enumerate(
                            zip(alt_sqs, [p for p in (slot.get("parts") or [])
                                          if isinstance(p, dict)]), start=1):
                        if str(p.get("type") or "") == "mcq" and isinstance(sq, dict) \
                                and not _sq_has_inline_mcq_options(sq.get("text")):
                            errors.append(
                                f"Q{n} [CBQ/{subtype}]: {_tag} sub-question {si} is declared "
                                f"MCQ in the pattern (part {p.get('label') or si}) — include "
                                "its four options inline in its text"
                            )
                    _fq = _foreign_quote(
                        [sq.get("text") for sq in alt_sqs if isinstance(sq, dict)],
                        alt_src,
                        str(q.get("source_text", "") or q.get("passage", "") or ""))
                    if _fq:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: {_tag} sub-questions quote '{_fq}' which "
                            "appears only in the FIRST option's passage — each option's "
                            "sub-questions must be answerable from its OWN source_text"
                        )
                    alt_sum = sum(
                        _as_float(sq.get("marks", 0), 0.0) if isinstance(sq, dict) else 0.0
                        for sq in alt_sqs
                    )
                    if _exp and abs(alt_sum - _exp) > 0.1:
                        errors.append(
                            f"Q{n} [CBQ/{subtype}]: {_tag} sub_question marks "
                            f"sum={alt_sum} != question marks={_exp}"
                        )
            _first_alt = next((a for a in alt_list if isinstance(a, dict)), None)
            if _first_alt is not None:
                _fq = _foreign_quote(
                    [sq.get("text") for sq in sqs if isinstance(sq, dict)],
                    str(q.get("source_text", "") or q.get("passage", "") or ""),
                    str(_first_alt.get("source_text", "") or _first_alt.get("passage", "") or ""))
                if _fq:
                    errors.append(
                        f"Q{n} [CBQ/{subtype}]: the first option's sub-questions quote '{_fq}' "
                        "which appears only in the OTHER option's passage — each option's "
                        "sub-questions must be answerable from its OWN source_text"
                    )

    return errors


# ─────────────────────────────────────────────
# Blueprint position → expected type helper
# ─────────────────────────────────────────────

def _blueprint_type_at(n: int, wo: SectionWorkOrder) -> tuple[str, float] | None:
    """
    Return (expected_type_string, marks_each) for the nth question (1-based) in the section,
    derived from wo.question_types blueprint. Returns None if blueprint can't be resolved.
    """
    if not wo.question_types:
        return None
    pos = 1
    for qt in wo.question_types:
        if isinstance(qt, dict):
            count = _as_int(qt.get("count", 1), 1)
            marks = _as_float(qt.get("marks_each", wo.marks_per_question), wo.marks_per_question)
            t = qt.get("type", "")
        else:
            count = 1
            marks = _as_float(wo.marks_per_question, 1.0)
            t = str(qt)
        if pos <= n < pos + count:
            return (t, marks)
        pos += count
    return None


def _type_category(type_str: str) -> str:
    """Map any type string to a short category key for mismatch comparison."""
    t = type_str.strip().lower()
    if "mcq" in t or "objective" in t or "multiple" in t or "assertion" in t or t == "ar":
        return "mcq"
    if "vsa" in t or "very short" in t:
        return "vsa"
    if "short answer" in t or t == "sa":
        return "sa"
    if "long answer" in t or t == "la":
        return "la"
    if "cbq" in t or "source" in t or "case" in t or "case-based" in t:
        return "cbq"
    if "map" in t:
        return "map"
    # Canonical per-question slot types (core/pattern_structure.py) and their
    # common free-text spellings — previously these all fell to "other", which
    # disabled type directives, validation and strict top-up (the AI-pattern
    # free-form-types failure). Objective language formats behave as VSA
    # (written one-liner, no options); writing tasks behave as LA; extracts as CBQ.
    if ("fill" in t and "blank" in t) or t == "fill_blank":
        return "vsa"
    if ("true" in t and "false" in t) or t == "true_false":
        return "vsa"
    if "match" in t or "one word" in t or t == "one_word":
        return "vsa"
    if "error correction" in t or t == "error_correction" or "editing" in t or "omission" in t:
        return "vsa"
    if "rewrite" in t or "transformation" in t:
        return "vsa"
    if "punctuation" in t:
        return "vsa"
    if t == "writing" or "essay" in t or "letter" in t or "paragraph" in t or "story" in t:
        return "la"
    if "extract" in t:
        return "cbq"
    return "other"


def _fine_category(type_str, subtype="") -> str:
    """Like _type_category but distinguishes Assertion-Reason from plain MCQ (both render as
    type 'MCQ') and map questions. Used for COUNT-based section validation — we check the
    section has the right NUMBER of each type, not that each type sits at an exact position
    (the renderer regroups by type, so position doesn't matter)."""
    st = str(subtype or "").strip().lower()
    ts = str(type_str or "").lower()
    if st == "assertion_reason" or "assertion" in ts:
        return "ar"
    if st == "map_based":
        return "map"
    return _type_category(str(type_str or ""))


# ─────────────────────────────────────────────
# Per-section validation
# ─────────────────────────────────────────────

def validate_section_output(data: dict, wo: SectionWorkOrder) -> list:
    """
    V1 — Full structural validation. Checks ALL questions (not just first 3).
    Type-aware: MCQ needs options+answer, LA needs or_alternative, CBQ needs sub_questions.
    """
    errors = []
    if not isinstance(data, dict):
        return ["Response is not a JSON object"]
    questions = data.get("questions", [])
    if not questions:
        return ["No 'questions' array found in response"]

    # MO-01: expected count
    expected_count = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
    if len(questions) != expected_count:
        errors.append(f"Expected {expected_count} questions, got {len(questions)}")

    valid_competency = {"recall", "application", "constructed"}
    valid_answers = {"a", "b", "c", "d"}
    answer_dist: dict = {}
    section_marks_total = 0.0

    # COUNT-based blueprint check: how many of each type the section should contain, and the
    # marks for each type. We validate the right NUMBER of each type + per-type marks, NOT the
    # exact position (the renderer regroups questions by type, so order is handled there).
    expected_counts: dict = {}
    type_marks_map: dict = {}
    for qt in (wo.question_types or []):
        if isinstance(qt, dict) and "marks_each" in qt:
            cat = _fine_category(qt.get("type", ""))
            expected_counts[cat] = expected_counts.get(cat, 0) + _as_int(qt.get("count", 1), 1)
            type_marks_map[cat] = _as_float(qt.get("marks_each", wo.marks_per_question), wo.marks_per_question)
    has_blueprint_counts = bool(expected_counts)
    actual_counts: dict = {}

    # Uniform sections (plain-string question_types, no per-type marks dicts) build no
    # expected_counts above and so get NO type check — that let MCQs slip into a Short-Answer
    # section. Collect the ALLOWED categories from the declared types and enforce membership
    # after the loop (we can't enforce exact per-type counts here, only that no foreign type
    # appears — e.g. a "Short Answer I" section must be all SA, never MCQ/AR/CBQ).
    allowed_cats: set = set()
    if not has_blueprint_counts:
        for qt in (wo.question_types or []):
            c = _fine_category(qt if isinstance(qt, str) else qt.get("type", ""))
            if c and c != "other":
                allowed_cats.add(c)

    for i, q in enumerate(questions):
        n = i + 1
        # ── Text presence (ALL questions, not just first 3) ──────────────────────
        if not str(q.get("text", "")).strip():
            errors.append(f"Q{n}: missing or empty 'text' field")

        # ── Marks ───────────────────────────────────────────────────────────────
        q_marks = q.get("marks")
        if q_marks is not None:
            try:
                section_marks_total += float(q_marks)
                if not wo.mixed_marks and abs(float(q_marks) - wo.marks_per_question) > 0.1:
                    errors.append(f"Q{n}: marks={q_marks} expected {wo.marks_per_question}")
            except (ValueError, TypeError):
                errors.append(f"Q{n}: marks value '{q_marks}' is not a number")

        # ── Competency tag ───────────────────────────────────────────────────────
        ct = str(q.get("competency_type", "")).strip().lower()
        if ct and ct not in valid_competency:
            errors.append(f"Q{n}: invalid competency_type '{ct}' (must be recall/application/constructed)")

        type_lower = _type_str(q.get("type", ""))
        q_subtype = str(q.get("subtype", "")).strip().lower()

        # ── Count + per-type marks (NOT per-position) ─────────────────────────────
        # Tally this question's type, and verify its marks match what THAT type should be
        # (e.g. a VSA must be 2m). Position is intentionally not checked — the renderer groups
        # by type. The overall per-type counts are validated once after the loop.
        actual_cat = _fine_category(q.get("type", ""), q_subtype)
        actual_counts[actual_cat] = actual_counts.get(actual_cat, 0) + 1
        if wo.slots and 0 <= i < len(wo.slots):
            # Slot-authored sections check marks PER POSITION — the category-keyed
            # map below can't hold two same-category slots with different marks
            # (a 5m extract CBQ and a 10m open-choice CBQ would clobber each other).
            exp_m = _as_float(wo.slots[i].get("marks"), 0.0)
            if exp_m > 0 and abs(_as_float(q.get("marks", exp_m), exp_m) - exp_m) > 0.1:
                errors.append(
                    f"Q{n}: marks mismatch — the pattern requires {exp_m}m for this "
                    f"question but got '{q.get('marks', '?')}'"
                )
        elif wo.mixed_marks and has_blueprint_counts and actual_cat in type_marks_map:
            exp_m = type_marks_map[actual_cat]
            if abs(_as_float(q.get("marks", exp_m), exp_m) - exp_m) > 0.1:
                errors.append(
                    f"Q{n}: marks mismatch — a {actual_cat.upper()} question should be {exp_m}m "
                    f"but got '{q.get('marks', '?')}'"
                )

        # ── Per-type/subtype structural validation (delegates to _validate_by_subtype) ─
        errors.extend(_validate_by_subtype(q, n, wo))

        # ── MCQ answer key: validate + track distribution (all MCQ, not just AR) ─
        is_mcq_like = (
            "mcq" in type_lower or "objective" in type_lower or
            "assertion" in type_lower or q_subtype == "assertion_reason" or
            (not type_lower and any(
                "mcq" in _type_str(t) or "objective" in _type_str(t)
                for t in wo.question_types
            ))
        )
        if is_mcq_like:
            answer = str(q.get("answer", "")).lower().strip()
            if answer:
                if answer not in valid_answers:
                    errors.append(f"Q{n}: answer '{answer}' must be a/b/c/d")
                else:
                    answer_dist[answer] = answer_dist.get(answer, 0) + 1

    # ── Answer key distribution (MCQ only) ──────────────────────────────────────
    if answer_dist:
        total_mcq = sum(answer_dist.values())
        for letter, count in answer_dist.items():
            if total_mcq >= 4 and count / total_mcq > 0.65:
                errors.append(
                    f"Answer bias: '{letter}' used {count}/{total_mcq} times (>{65}%). "
                    "Distribute answers across a/b/c/d."
                )

    # ── Section type distribution (counts, not positions) ────────────────────────
    if has_blueprint_counts:
        issues = []
        for cat, exp in expected_counts.items():
            got = actual_counts.get(cat, 0)
            if got != exp:
                issues.append(f"{cat.upper()}: need {exp}, got {got}")
        for cat, got in actual_counts.items():
            if cat not in expected_counts and got:
                issues.append(f"{cat.upper()}: {got} not allowed in this section")
        if issues:
            want = ", ".join(f"{c.upper()}×{n}" for c, n in expected_counts.items())
            errors.append(
                f"Section type distribution wrong — produce EXACTLY: {want} "
                f"(order doesn't matter). Fix: {'; '.join(issues)}"
            )

    # ── Uniform-section type guard: no foreign types allowed ─────────────────────
    if allowed_cats:
        bad = {c: n for c, n in actual_counts.items() if c not in allowed_cats and n}
        if bad:
            want = "/".join(c.upper() for c in sorted(allowed_cats))
            got = ", ".join(f"{c.upper()}×{n}" for c, n in sorted(bad.items()))
            errors.append(
                f"Wrong question type(s) for this section — only {want} allowed, but got {got}. "
                f"Regenerate EVERY question as {want} (this is a {want} section, not MCQ)."
            )

    # ── Section marks total ──────────────────────────────────────────────────────
    # For attempt-N-of-M sections we GENERATE the larger 'provided' set, so the summed
    # marks legitimately exceed wo.marks (which budgets the ATTEMPTED subset). Scale the
    # expected total up to the provided set; otherwise the check fires every time and the
    # section ships partial. (e.g. provide 7×1m but section budgets 5m attempted.)
    expected_total = wo.marks
    if wo.provided_count and wo.attempt_count and wo.attempt_count > 0 and wo.provided_count > wo.attempt_count:
        expected_total = wo.marks * (wo.provided_count / wo.attempt_count)
    if section_marks_total > 0 and expected_total > 0:
        if abs(section_marks_total - expected_total) > 1.0:
            errors.append(
                f"Section marks total={section_marks_total:.1f} expected {expected_total:.1f}. "
                "Check individual question marks."
            )

    return errors


# ─────────────────────────────────────────────
# Single-section generator (with retry)
# ─────────────────────────────────────────────

def _type_str(t) -> str:
    """Return a lowercase string for a question_type that may be str or dict."""
    if isinstance(t, dict):
        return str(t.get("type", "")).lower()
    return str(t).lower()


_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "to",
    "by", "for", "with", "which", "what", "how", "why", "and", "or", "but",
    "not", "be", "as", "at", "from", "this", "that", "it", "its", "has",
    "have", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "can", "if", "then", "than", "so", "very", "more", "also",
}


def _map_locations_text(txt: str) -> str:
    """Comparable text for a map question: the part AFTER the boilerplate stem — i.e. the
    location list of 'On the given outline map of India, locate and label: (a) … (b) …'.
    The shared stem alone makes any two map questions score as near-duplicates."""
    _, sep, tail = str(txt or "").partition(":")
    tail = tail.strip()
    return tail if (sep and tail) else str(txt or "")


def _concept_overlap(t1: str, t2: str) -> float:
    """Token-overlap ratio between two question texts. Returns 0.0–1.0."""
    def tokens(s):
        return {w.lower() for w in re.split(r"\W+", s) if len(w) > 3 and w.lower() not in _STOP_WORDS}
    s1, s2 = tokens(t1), tokens(t2)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / min(len(s1), len(s2))


def _comparable_text(q: dict) -> str:
    """
    Build the text used for duplicate detection. For CBQ/source-based questions the 'text'
    field is just a boilerplate stem ("Read the source above and answer the following:"),
    so comparing it makes every CBQ look identical. Include the actual content —
    source_text/passage and the sub-question texts — so dedup reflects real overlap.
    """
    if not isinstance(q, dict):
        return str(q)
    parts = [str(q.get("text", ""))]
    src = q.get("source_text") or q.get("passage")
    if src:
        parts.append(str(src))
    sqs = q.get("sub_questions")
    if isinstance(sqs, list):
        for sq in sqs:
            if isinstance(sq, dict):
                parts.append(str(sq.get("text", "")))
            else:
                parts.append(str(sq))
    return " ".join(p for p in parts if p).strip()


def validate_uniqueness(questions: list) -> list:
    """
    V5 Layer 1 — detect duplicate or near-duplicate questions within a section.
    Returns list of warning strings (does not block, caller decides action).
    """
    warnings = []
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            t1 = _comparable_text(questions[i])
            t2 = _comparable_text(questions[j])
            score = _concept_overlap(t1, t2)
            if score > 0.50:
                warnings.append(
                    f"Q{i+1} and Q{j+1} overlap {score:.0%} — likely duplicate concept"
                )
    return warnings


def _regen_question_skeleton(orig_q: dict, qnum: int, marks) -> tuple:
    """Build a (type_instruction, JSON_skeleton) pair for regenerating ONE question to replace a
    confirmed duplicate. The skeleton MUST match the ORIGINAL question's type — a generic SA
    skeleton turns an MCQ replacement into an SA, which enforce_section_question_types then
    strips, shrinking the section below its required count (the '18/20 questions' cause)."""
    cat = _fine_category(orig_q.get("type", ""), str(orig_q.get("subtype", "")))
    m = _as_int(marks, 1)
    if cat == "ar":
        instr = ("Type: Assertion-Reason MCQ. 'text' must contain full 'Assertion (A): ...' and "
                 "'Reason (R): ...' statements; use the 4 standard AR options.")
        skel = ('{"qnum": %d, "type": "MCQ", "subtype": "assertion_reason", '
                '"text": "Assertion (A): ...\\nReason (R): ...", '
                '"options": {"a": "Both A and R are true and R is the correct explanation of A", '
                '"b": "Both A and R are true but R is NOT the correct explanation of A", '
                '"c": "A is true but R is false", "d": "A is false but R is true"}, '
                '"answer": "a", "answer_explanation": "...", "marks": %d, '
                '"chapter_tag": "...", "competency_type": "application"}' % (qnum, m))
    elif cat == "mcq":
        instr = "Type: MCQ with EXACTLY 4 options (a/b/c/d) and the correct answer letter."
        skel = ('{"qnum": %d, "type": "MCQ", "subtype": "standard", "text": "...", '
                '"options": {"a": "...", "b": "...", "c": "...", "d": "..."}, "answer": "a", '
                '"answer_explanation": "why the correct option is right", "marks": %d, '
                '"chapter_tag": "...", "competency_type": "application"}' % (qnum, m))
    elif cat == "la":
        instr = "Type: Long Answer (NO options). Include an 'or_alternative' on a DIFFERENT concept."
        skel = ('{"qnum": %d, "type": "LA", "subtype": "standard", "text": "...", '
                '"answer_explanation": "4-6 model-answer key points", '
                '"or_alternative": "alternate LA question on a different concept (%dm)", '
                '"marks": %d, "chapter_tag": "...", "competency_type": "constructed"}' % (qnum, m, m))
    else:   # vsa / sa / other written-answer
        qtype = (str(orig_q.get("type", "SA")).upper() or "SA")
        instr = f"Type: {qtype} (written answer, NO options)."
        skel = ('{"qnum": %d, "type": "%s", "subtype": "standard", "text": "...", '
                '"answer_explanation": "model answer key points", "marks": %d, '
                '"chapter_tag": "...", "competency_type": "constructed"}' % (qnum, qtype, m))
    return instr, skel


def verify_and_fix_semantic_duplicates(
    questions: list,
    l1_warnings: list,
    wo: SectionWorkOrder,
    quality_flags: list,
) -> tuple[list, list]:
    """
    V5 Layer 2 — LLM semantic duplicate confirmation + targeted replacement.
    Only called when Layer 1 flags at least one pair.

    For each flagged pair:
      1. Ask LLM: "Do these two questions test the same knowledge?"
      2. If confirmed: replace the lower-quality one (by quality_flags score, or the second one)
         with a fresh question on a DIFFERENT concept from the same section context.
    Returns (updated_questions, updated_warnings).
    """
    if not l1_warnings or not questions:
        return questions, l1_warnings

    # Parse (i, j) indices from L1 warning strings ("Q3 and Q7 overlap …")
    flagged_pairs = []
    for w in l1_warnings:
        m = re.search(r"Q(\d+) and Q(\d+)", w)
        if m:
            i, j = int(m.group(1)) - 1, int(m.group(2)) - 1
            if 0 <= i < len(questions) and 0 <= j < len(questions):
                flagged_pairs.append((i, j))

    if not flagged_pairs:
        return questions, l1_warnings

    # Build quality score lookup {q_idx: avg_score} from V2 flags (lower = worse)
    quality_score = {
        _as_int(f.get("qnum", 0), 0) - 1: _as_float(f.get("avg_score", 3.0), 3.0)
        for f in (quality_flags or []) if isinstance(f, dict)
    }

    remaining_warnings = list(l1_warnings)
    updated_questions = list(questions)

    for i, j in flagged_pairs:
        q_i = updated_questions[i]
        q_j = updated_questions[j]

        # LLM confirmation: are these actually the same concept?
        confirm_prompt = (
            f"Do these two CBSE {wo.subject} questions test the same knowledge or concept?\n\n"
            f"Q{i+1}: {str(q_i.get('text', ''))[:250]}\n\n"
            f"Q{j+1}: {str(q_j.get('text', ''))[:250]}\n\n"
            "Answer with JSON only:\n"
            '{"same_concept": true, "reason": "one sentence"}'
        )
        try:
            raw, _, _ = mantle_client.converse(
                model_id=mantle_client.VAL_MODEL,
                prompt=confirm_prompt,
                max_tokens=100,
                temperature=0.1,
            )
            raw = raw.strip()
            m2 = re.search(r"\{.*\}", raw, re.S)
            result = json.loads(m2.group()) if m2 else {}
            is_dup = result.get("same_concept", False)
        except Exception as e:
            print(f"[V5L2] LLM confirmation failed for Q{i+1}/Q{j+1}: {e} — skipping")
            continue

        if not is_dup:
            print(f"[V5L2] Q{i+1} and Q{j+1}: L1 false positive — not actually duplicates")
            remaining_warnings = [w for w in remaining_warnings
                                  if f"Q{i+1} and Q{j+1}" not in w]
            continue

        # Confirmed duplicate — replace the lower-quality question
        score_i = quality_score.get(i, 3.0)
        score_j = quality_score.get(j, 3.0)
        replace_idx = j if score_i >= score_j else i
        keep_idx = i if replace_idx == j else j
        keep_text = str(updated_questions[keep_idx].get("text", ""))[:150]

        print(f"[V5L2] Confirmed duplicate Q{i+1} ↔ Q{j+1} — regenerating Q{replace_idx+1}")

        orig_q = updated_questions[replace_idx]
        orig_cat = _fine_category(orig_q.get("type", ""), str(orig_q.get("subtype", "")))
        if orig_cat in ("cbq", "map"):
            # Structurally heavy (sub-questions / map locations) — a single-shot regen can't
            # reproduce them safely. Keep the original near-duplicate (valid + right type).
            print(f"[V5L2] Q{replace_idx+1} is {orig_cat.upper()} — skipping regen, keeping original")
            continue

        type_instr, skel = _regen_question_skeleton(
            orig_q, replace_idx + 1, orig_q.get("marks", wo.marks_per_question))
        regen_prompt = (
            f"Generate ONE CBSE Class {wo.class_name} {wo.subject} question.\n"
            f"{type_instr}\n"
            f"Marks: {orig_q.get('marks', wo.marks_per_question)}\n"
            f"Difficulty: {wo.difficulty}\n"
            f"Chapters: {', '.join(str(c) for c in wo.chapters)}\n\n"
            "IMPORTANT: The following concept is ALREADY covered — do NOT repeat it:\n"
            f"  ✗ {keep_text}\n\n"
            "Context:\n"
            f"{wo.context_text[:2500]}\n\n"
            "Output JSON only (single question object):\n"
            f"{skel}"
        )
        try:
            rraw, _, _ = mantle_client.converse(
                model_id=GEN_MODEL,
                prompt=regen_prompt,
                max_tokens=500,
                temperature=0.85,
            )
            new_q = extract_single_question_json(rraw, replace_idx, wo.marks_per_question)
            new_q.setdefault("subtype", orig_q.get("subtype", "standard"))
            # Preserve original qnum and marks
            new_q["qnum"] = orig_q.get("qnum", replace_idx + 1)
            new_q["marks"] = orig_q.get("marks", wo.marks_per_question)
            # Guard: the replacement MUST be the SAME coarse type as the original AND structurally
            # valid. A type-drifted replacement (e.g. an SA where the original was an MCQ) is later
            # stripped by enforce_section_question_types, silently shrinking the section below its
            # required count. When the regen drifts or is invalid, keep the original near-duplicate —
            # a flagged near-dup beats a missing question.
            new_cat = _fine_category(new_q.get("type", ""), str(new_q.get("subtype", "")))
            regen_errs = _validate_by_subtype(new_q, replace_idx + 1, wo)
            if new_cat != orig_cat or regen_errs:
                print(f"[V5L2] Q{replace_idx+1} regen drifted ({orig_cat}→{new_cat}) or invalid "
                      f"({regen_errs[:1]}) — keeping original near-duplicate")
            else:
                updated_questions[replace_idx] = new_q
                print(f"[V5L2] Q{replace_idx+1} replaced — chapter='{new_q.get('chapter_tag', '?')}'")
                # Remove the now-resolved warning
                remaining_warnings = [w for w in remaining_warnings
                                      if f"Q{i+1} and Q{j+1}" not in w and f"Q{j+1} and Q{i+1}" not in w]
        except Exception as e:
            print(f"[V5L2] Regen failed for Q{replace_idx+1}: {e}")

    return updated_questions, remaining_warnings


def run_content_quality_critic(questions: list, class_name: str, subject: str, difficulty: str) -> list:
    """
    V2 — Content Quality Critic.
    Sends all questions in a section to the validator LLM in one batch call.
    Returns list of {qnum, score, issues} for questions scoring below threshold.
    Scores: 1–5 (5 = excellent). Threshold: ≥3 required (warn below, don't block).

    Evaluates:
      - Clarity: Is the question unambiguous and well-worded?
      - NCERT alignment: Is the content from NCERT Class {class_name} {subject}?
      - Difficulty: Does the question match the requested difficulty ({difficulty})?
      - Pedagogical value: Does it test understanding rather than trivial facts?
    """
    if not questions:
        return []

    q_lines = []
    for i, q in enumerate(questions):
        q_lines.append(
            f"Q{i + 1} [{q.get('type','?')}] ({q.get('marks',1)}m): "
            f"{str(q.get('text', ''))[:200]}"
        )

    prompt = (
        f"You are a CBSE question paper quality auditor for Class {class_name} {subject}.\n"
        f"Requested difficulty: {difficulty}\n\n"
        "Rate each question on a 1–5 scale across:\n"
        "  - clarity (1=ambiguous, 5=crystal clear)\n"
        "  - ncert_alignment (1=off-syllabus, 5=directly from NCERT)\n"
        "  - difficulty_match (1=wrong level, 5=perfect for requested difficulty)\n"
        "  - pedagogical_value (1=trivial recall, 5=tests deep understanding)\n\n"
        "Questions:\n" + "\n".join(q_lines) + "\n\n"
        "Output JSON array only:\n"
        '[{"q": 1, "clarity": 4, "ncert_alignment": 5, "difficulty_match": 3, '
        '"pedagogical_value": 4, "issues": "optional note if any score < 3"}, ...]\n'
        "Include ALL questions in the output."
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\[.*\]", raw, re.S)
        ratings = json.loads(m.group()) if m else []
    except Exception as e:
        print(f"[V2-Critic] LLM call failed: {e}")
        return []

    flagged = []
    for r in ratings:
        if not isinstance(r, dict):
            continue
        # LLM may return scores as strings ("4") — coerce so sum()/avg never crash
        scores = [
            _as_float(r.get("clarity", 5), 5.0),
            _as_float(r.get("ncert_alignment", 5), 5.0),
            _as_float(r.get("difficulty_match", 5), 5.0),
            _as_float(r.get("pedagogical_value", 5), 5.0),
        ]
        avg = sum(scores) / len(scores)
        if avg < 3.0:
            flagged.append({
                "qnum": _as_int(r.get("q"), 0),
                "avg_score": round(avg, 1),
                "scores": {
                    "clarity": r.get("clarity"),
                    "ncert_alignment": r.get("ncert_alignment"),
                    "difficulty_match": r.get("difficulty_match"),
                    "pedagogical_value": r.get("pedagogical_value"),
                },
                "issues": r.get("issues", ""),
            })
            print(
                f"[V2-Critic] ⚠️  Q{r.get('q')}: avg={avg:.1f} — {r.get('issues', '')}"
            )

    if not flagged:
        print(f"[V2-Critic] ✅ All {len(questions)} questions passed quality check")

    return flagged


def _blind_answer_mcqs(items: list, class_name: str, subject: str) -> dict:
    """Blind-answer a list of (orig_idx, question) MCQs with the validation model (no NCERT
    context — purely tests the answer key). Returns {orig_idx: {"answer","confidence"}}."""
    out = {}
    batch_size = 10
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        qs_block = ""
        for idx, (_, q) in enumerate(batch):
            opts = q.get("options", {}) or {}
            qs_block += (
                f"\nQ{idx + 1}. {q.get('text', '')}\n"
                f"(a) {opts.get('a', '')}  (b) {opts.get('b', '')}\n"
                f"(c) {opts.get('c', '')}  (d) {opts.get('d', '')}\n"
            )
        prompt = (
            f"Answer these CBSE Class {class_name} {subject} multiple choice questions.\n"
            "Choose the single best answer based on your NCERT knowledge. Do NOT explain.\n"
            f"{qs_block}\n"
            'Output JSON array only:\n[{"q": 1, "answer": "a", "confidence": "high"}, ...]\n'
            'confidence: "high" (certain), "medium" (likely), "low" (guessing)'
        )
        try:
            raw, _, _ = mantle_client.converse(
                model_id=mantle_client.VAL_MODEL, prompt=prompt, max_tokens=300, temperature=0.1)
            m = re.search(r"\[.*\]", raw.strip(), re.S)
            llm_answers = json.loads(m.group()) if m else []
        except Exception as e:
            print(f"[V4-MCQ-Verify] LLM call failed: {e}")
            llm_answers = []
        for idx, (orig_idx, _q) in enumerate(batch):
            entry = next((x for x in llm_answers
                          if isinstance(x, dict) and _as_int(x.get("q"), -1) == idx + 1), {})
            out[orig_idx] = {
                "answer": str(entry.get("answer", "")).lower().strip(),
                "confidence": str(entry.get("confidence", "unknown")).lower().strip(),
            }
    return out


def verify_mcq_answers(questions: list, class_name: str, subject: str) -> list:
    """
    V4 — Blind LLM answer-key verification with confident auto-correction.

    A wrong stored answer key is CORRECTED in place only when TWO independent blind passes
    both pick the same *different* option with high confidence — so a single model opinion can
    never flip a correct key to a wrong one. Lesser disagreements are flagged (suspect) but
    left unchanged. Returns {qnum, stored, llm_answer, confidence, suspect, corrected} dicts.
    """
    valid = {"a", "b", "c", "d"}
    mcq_qs = [
        (i, q) for i, q in enumerate(questions)
        if str(q.get("type", "")).upper() in ("MCQ", "ASSERTION-REASON", "ASSERTION_REASON")
        and q.get("options") and q.get("answer")
    ]
    if not mcq_qs:
        return []

    first = _blind_answer_mcqs(mcq_qs, class_name, subject)

    # Re-verify only the high-confidence disagreements before overwriting any key.
    candidates = [
        (i, q) for (i, q) in mcq_qs
        if first.get(i, {}).get("confidence") == "high"
        and first[i]["answer"] in valid
        and first[i]["answer"] != str(q.get("answer", "")).lower().strip()
    ]
    second = _blind_answer_mcqs(candidates, class_name, subject) if candidates else {}

    results = []
    for i, q in mcq_qs:
        stored = str(q.get("answer", "")).lower().strip()
        f = first.get(i, {})
        llm_ans, conf = f.get("answer", ""), f.get("confidence", "unknown")
        corrected = False
        if (i in second and second[i].get("confidence") == "high"
                and second[i].get("answer") == llm_ans and llm_ans in valid and llm_ans != stored):
            q["answer"] = llm_ans          # two high-confidence passes agree → fix the key
            corrected = True
            print(f"[V4-MCQ-Verify] ✅ Q{i + 1}: corrected answer key '{stored}' → '{llm_ans}' (confirmed twice)")
        suspect = bool(llm_ans and llm_ans != stored and conf in ("high", "medium") and not corrected)
        if suspect:
            print(f"[V4-MCQ-Verify] ⚠️  Q{i + 1}: stored='{stored}' but LLM says '{llm_ans}' "
                  f"(confidence={conf}) — flagged, not auto-corrected")
        results.append({
            "qnum": i + 1, "stored": stored, "llm_answer": llm_ans,
            "confidence": conf, "suspect": suspect, "corrected": corrected,
        })
    return results


def _is_dedicated_cbq_section(wo: SectionWorkOrder) -> bool:
    """
    Return True only if this section should use the image-based CBQ flow.

    Image-based CBQ applies to observation questions: student sees a diagram/photograph
    and answers "What is shown?", "Identify the parts", "What process is occurring?".
    This is appropriate for Science, Biology, Physics, Chemistry, History, Social Science.

    Excluded — these subjects use text-based case studies, not observation images:
      Mathematics, Applied Mathematics, Accountancy, Economics, Business Studies, etc.

    Also excluded — CBSE official patterns store many question types (MCQ, VSA, SA, CBQ, LA)
    as dicts inside one section. Those mixed sections must NOT get the image schema because
    it would break MCQ/SA/LA rendering for the other question types.
    """
    # ── Slot-authored sections are excluded ────────────────────────────────────
    # question_slots state their material explicitly (extracts/case passages are
    # requested via "source_text" in the per-question spec) — never route them to
    # the image-observation CBQ flow.
    if wo.slots:
        return False

    # ── Subject exclusion ──────────────────────────────────────────────────────
    MATH_LIKE = {
        "mathematics", "maths", "math", "applied mathematics",
        "accountancy", "economics", "business studies", "commerce",
        "computer science", "informatics practices",
    }
    subject_lower = str(wo.section_subject or wo.subject or "").lower()
    if any(m in subject_lower for m in MATH_LIKE):
        return False

    # ── Mixed-section exclusion (CBSE official dict-type patterns) ─────────────
    qtypes = wo.question_types
    if not qtypes:
        return False
    NON_CBQ = {"mcq", "assertion", "vsa", "very short", "short answer", "(sa)", "long answer", "(la)"}
    for t in qtypes:
        s = _type_str(t)
        if any(m in s for m in NON_CBQ):
            return False

    # ── Must actually be CBQ type ──────────────────────────────────────────────
    return any(
        "cbq" in _type_str(t) or "source" in _type_str(t) or "case" in _type_str(t)
        for t in qtypes
    )


def check_ncert_grounding(questions: list, context_text: str, class_name: str, subject: str) -> list:
    """
    V3 — NCERT Grounding Check (RAG + LLM).
    Verifies that SA/LA questions are grounded in the provided NCERT context chunks.
    Uses the section's already-retrieved context — no extra embedding calls.
    Returns list of {qnum, text_snippet, issue} for questions that appear off-syllabus.
    """
    # Only check SA and LA questions (MCQ/CBQ validated elsewhere)
    sa_la_qs = [
        (i, q) for i, q in enumerate(questions)
        if str(q.get("type", "")).upper() in ("SA", "LA", "SHORT_ANSWER", "LONG_ANSWER")
        and q.get("text")
    ]
    if not sa_la_qs or not context_text or len(context_text) < 100:
        return []

    q_lines = "\n".join(
        f"Q{i + 1} [{q.get('type')}]: {str(q.get('text', ''))[:200]}"
        for i, (_, q) in enumerate(sa_la_qs)
    )

    prompt = (
        f"You are checking if CBSE Class {class_name} {subject} questions are grounded in "
        "the provided NCERT reference text.\n\n"
        f"NCERT REFERENCE TEXT (excerpt):\n{context_text[:3000]}\n\n"
        f"QUESTIONS TO CHECK:\n{q_lines}\n\n"
        "For each question, determine if it is clearly grounded in the reference text above "
        "(the answer should be findable in the text, or the question tests concepts present in the text).\n\n"
        "Output JSON array only:\n"
        '[{"q": 1, "grounded": true, "issue": ""}, ...]\n'
        "Include ALL questions. Set grounded=false only if the question topic is absent from the reference text."
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=1024,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\[.*\]", raw, re.S)
        results = json.loads(m.group()) if m else []
    except Exception as e:
        print(f"[V3-Grounding] LLM call failed: {e}")
        return []

    ungrounded = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if not r.get("grounded", True):
            # 'q' may arrive as int, "1", or "Q1" — coerce defensively
            q_idx = _as_int(r.get("q", 1), 1) - 1
            if 0 <= q_idx < len(sa_la_qs):
                orig_idx, q = sa_la_qs[q_idx]
                ungrounded.append({
                    "qnum": orig_idx + 1,
                    "text_snippet": str(q.get("text", ""))[:80],
                    "issue": r.get("issue", "Topic not found in NCERT context"),
                })
                print(
                    f"[V3-Grounding] ⚠️  Q{orig_idx + 1}: not grounded in context — "
                    f"{r.get('issue', '')}"
                )

    if not ungrounded:
        print(f"[V3-Grounding] ✅ All SA/LA questions grounded in NCERT context")

    return ungrounded


def validate_cbq_passage(section_data: dict, wo: SectionWorkOrder) -> list:
    """
    V6 — CBQ/Source-based passage validation.
    Checks:
      1. Passage is factually accurate and NCERT-aligned (not fabricated).
      2. Every sub-question is answerable SOLELY from the passage text.
      3. No sub-question answer requires outside knowledge.
    Returns list of issues (strings). Empty list = pass.
    """
    passage = section_data.get("passage", "")
    if not passage or len(passage) < 50:
        return []  # No passage or image-based CBQ — skip

    sub_qs = []
    for q in section_data.get("questions", []):
        for sq in q.get("sub_questions", []):
            sub_qs.append(sq.get("text", ""))

    if not sub_qs:
        return []

    sq_block = "\n".join(f"{i + 1}. {sq}" for i, sq in enumerate(sub_qs))

    prompt = (
        f"You are validating a CBSE Class {wo.class_name} {wo.subject} source-based question.\n\n"
        f"PASSAGE:\n{passage[:1500]}\n\n"
        f"SUB-QUESTIONS:\n{sq_block}\n\n"
        "Check ALL of the following and report any problems:\n"
        "1. Is the passage factually accurate and consistent with NCERT Class "
        f"{wo.class_name} {wo.subject}?\n"
        "2. Is every sub-question answerable using ONLY information in the passage "
        "(not requiring outside knowledge)?\n"
        "3. Are there any sub-questions whose answers cannot be found in the passage?\n\n"
        "Output JSON only:\n"
        '{"passage_accurate": true, "all_answerable": true, "issues": []}\n'
        "If issues exist, list them in the issues array as short strings."
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=512,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        result = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"[V6-CBQ] LLM call failed: {e}")
        return []

    issues = result.get("issues", [])
    if not result.get("passage_accurate", True):
        issues.insert(0, "Passage may contain factual inaccuracies or is not NCERT-aligned")
    if not result.get("all_answerable", True):
        issues.insert(0, "One or more sub-questions require outside knowledge not in passage")

    if issues:
        print(f"[V6-CBQ] ⚠️  Passage issues in '{wo.section_name}': {issues}")
    else:
        print(f"[V6-CBQ] ✅ Passage validated for '{wo.section_name}'")

    return issues


def _post_process_cbq_images(section_data: dict, wo: SectionWorkOrder) -> None:
    """
    After questions are validated, find/generate an image for each image_based question
    and replace its sub_questions with Kimi-verified ones.
    Mutates section_data in place. Fails silently on any error.
    """
    from . import image_finder

    subject = wo.section_subject or wo.subject or "Science"
    chapter = wo.chapters[0] if wo.chapters else subject

    questions = section_data.get("questions", [])
    for i, q in enumerate(questions):
        if not (q.get("image_based") or q.get("type") == "image_based" or q.get("subtype") == "image_based"):
            continue
        try:
            print(f"[Section-Gen] Generating image for Q{i + 1} (image_based)...")
            result = image_finder.generate_image_for_question(
                question_text=q.get("text", ""),
                sub_questions=q.get("sub_questions", []),
                subject=subject,
                chapter=chapter,
            )
            if result:
                section_data["image_path"] = result["image_path"]
                questions[i]["sub_questions"] = result["verified_sub_questions"]
                print(f"[Section-Gen] Image ready (source={result['source']!r}): {result['image_path']}")
            else:
                print(f"[Section-Gen] Image generation returned None for Q{i + 1} — skipping image")
        except Exception as exc:
            print(f"[Section-Gen] Image generation failed for Q{i + 1}: {exc}")


def _get_type_params(qtype_str: str) -> dict:
    """Return TYPE_PARAMS entry for a question type string, with safe fallback."""
    ql = qtype_str.lower().strip()
    for key in TYPE_PARAMS:
        if key in ql:
            return TYPE_PARAMS[key]
    return {"temp": 0.75, "budget_per_q": 500}


def build_single_question_prompt(wo: SectionWorkOrder, qtype_str: str, q_index: int, avoid_chapters: list) -> str:
    """
    4.3 — Build a focused prompt to generate exactly ONE LA or CBQ question.
    avoid_chapters: chapters already used in prior questions of this section.
    """
    context = (
        wo.context_by_type.get(qtype_str.lower(), "")
        or wo.context_by_type.get("la", "")
        or wo.context_text
    )
    avoid_block = (
        f"\nAVOID chapters already used: {', '.join(str(c) for c in avoid_chapters)}. "
        "Draw this question from a DIFFERENT chapter or concept.\n"
        if avoid_chapters else ""
    )
    is_la = qtype_str.lower() in ("la", "long_answer", "long answer")
    is_cbq = qtype_str.lower() in ("cbq", "source_based", "case_based", "source based", "case based")
    mpq = wo.marks_per_question

    if is_la:
        schema = (
            '{\n'
            f'  "qnum": {q_index + 1},\n'
            '  "type": "LA",\n'
            '  "text": "Long answer question text",\n'
            f'  "marks": {mpq},\n'
            '  "answer_explanation": "Model answer key points — 4-6 bullet points",\n'
            '  "chapter_tag": "NCERT chapter name",\n'
            '  "competency_type": "constructed",\n'
            f'  "or_alternative": "Alternate LA question on a DIFFERENT concept — same marks ({mpq}m)"\n'
            '}'
        )
    elif is_cbq:
        sq_marks = max(1, mpq // 3)
        schema = (
            '{\n'
            f'  "qnum": {q_index + 1},\n'
            '  "type": "source_based",\n'
            '  "passage": "PASSAGE TEXT (200-300 words, NCERT-aligned)",\n'
            '  "text": "Read the passage above and answer the following:",\n'
            f'  "marks": {mpq},\n'
            '  "chapter_tag": "NCERT chapter name",\n'
            '  "competency_type": "application",\n'
            '  "sub_questions": [\n'
            f'    {{"text": "Sub-question (a)", "marks": {sq_marks}, "answer_explanation": "Key answer points"}},\n'
            f'    {{"text": "Sub-question (b)", "marks": {sq_marks}, "answer_explanation": "Key answer points"}},\n'
            f'    {{"text": "Sub-question (c)", "marks": {mpq - 2 * sq_marks}, "answer_explanation": "Key answer points"}}\n'
            '  ]\n'
            '}'
        )
    else:
        schema = (
            '{\n'
            f'  "qnum": {q_index + 1},\n'
            f'  "type": "{qtype_str}",\n'
            '  "text": "Question text",\n'
            f'  "marks": {mpq},\n'
            '  "answer_explanation": "Model answer",\n'
            '  "chapter_tag": "NCERT chapter name",\n'
            '  "competency_type": "constructed"\n'
            '}'
        )

    language_directive = _language_directive(wo.section_subject or wo.subject)

    return (
        f"Generate exactly ONE CBSE Class {wo.class_name} {wo.subject} {qtype_str} question.\n"
        f"{language_directive}"
        f"Chapters: {', '.join(str(c) for c in wo.chapters)}\n"
        f"Difficulty: {wo.difficulty}\n"
        f"Marks: {mpq}\n"
        f"{avoid_block}\n"
        "REFERENCE MATERIAL:\n"
        f"{context[:4000]}\n\n"
        "RULES:\n"
        "- Draw content ONLY from the reference material above\n"
        "- Do not repeat concepts from the avoid list\n"
        "- Write at CBSE board exam quality\n\n"
        "OUTPUT — return ONLY this JSON (no markdown fences):\n"
        f"{schema}"
    )


def extract_single_question_json(raw: str, q_index: int, mpq: float) -> dict:
    """Extract a single question object from LLM response for 4.3 per-question generation."""
    raw = raw.strip()
    # Try direct JSON parse
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group())
            # Ensure required fields
            obj.setdefault("qnum", q_index + 1)
            obj.setdefault("marks", mpq)
            return obj
        except json.JSONDecodeError:
            pass
    return {
        "qnum": q_index + 1,
        "type": "SA",
        "text": f"[Generation failed for question {q_index + 1}]",
        "marks": mpq,
        "competency_type": "constructed",
        "_generation_error": True,
    }


def generate_la_cbq_individually(wo: SectionWorkOrder) -> tuple[dict, int, int]:
    """
    4.3 — Generate LA and CBQ questions one at a time with chapter diversity tracking.
    Returns (section_data, total_in_tok, total_out_tok).

    Strategy:
      - Detect which question type applies (LA or CBQ/source_based)
      - Generate each question sequentially, tracking chapter_tag from previous
      - Pass used chapters as avoid_chapters to next call
    """
    # Determine the dominant question type for this section
    la_types = {"la", "long_answer", "long answer"}
    cbq_types = {"cbq", "source_based", "source based", "case_based", "case based"}

    dominant_type = "LA"  # default
    for qt in wo.question_types:
        ql = _type_str(qt).lower()
        if ql in cbq_types:
            dominant_type = "source_based"
            break
        elif ql in la_types:
            dominant_type = "LA"

    params = _get_type_params(dominant_type)
    questions = []
    total_in_tok = 0
    total_out_tok = 0
    used_chapters: set = set()

    print(f"[4.3-Individual] '{wo.section_name}': generating {wo.questions_count}× {dominant_type} individually")

    for q_index in range(wo.questions_count):
        prompt = build_single_question_prompt(
            wo, dominant_type, q_index, list(used_chapters)
        )
        try:
            raw, in_tok, out_tok = mantle_client.converse(
                model_id=GEN_MODEL,
                prompt=prompt,
                max_tokens=params["budget_per_q"],
                temperature=params["temp"],
            )
            total_in_tok += in_tok
            total_out_tok += out_tok
            q_obj = extract_single_question_json(raw, q_index, wo.marks_per_question)
            questions.append(q_obj)
            # Track chapter used so next question avoids it
            chapter_used = q_obj.get("chapter_tag", "")
            if chapter_used:
                used_chapters.add(chapter_used)
            print(f"[4.3-Individual] Q{q_index + 1}/{wo.questions_count} done — chapter='{chapter_used}'")
        except Exception as e:
            print(f"[4.3-Individual] Q{q_index + 1} failed: {e}")
            questions.append({
                "qnum": q_index + 1,
                "type": dominant_type,
                "text": f"[Individual generation failed: {e}]",
                "marks": wo.marks_per_question,
                "competency_type": "constructed",
                "_generation_error": True,
            })

    section_data = {
        "section_id": wo.section_id,
        "section_name": wo.section_name,
        "title": wo.title,
        "marks": wo.marks,
        "questions": questions,
        "_individual_generation": True,
    }
    return section_data, total_in_tok, total_out_tok


def _repair_section_data(section_data: dict) -> dict:
    """
    Deterministic structural repair applied after JSON parse, before validation.

    Fixes two recurring LLM mistakes so they don't consume retry budget:

    1. Embedded letter prefix in option values — LLM writes "(a) text" inside the value;
       render_docx then prepends "(a)" again → "(a) (a) text".  Strip the prefix here.

    2. Assertion-Reason question with valid A/R text but empty/missing options — the four
       standard AR options are always the same, so we inject them deterministically instead
       of wasting a retry asking the LLM to add something it already knows.
    """
    for q in section_data.get("questions", []):
        # ── Normalise options to dict ──────────────────────────────────────────
        opts = q.get("options")
        if isinstance(opts, list):
            lmap = {0: "a", 1: "b", 2: "c", 3: "d"}
            opts = {lmap[i]: str(v) for i, v in enumerate(opts) if i in lmap}
            q["options"] = opts
        elif not isinstance(opts, dict):
            opts = {}
            q["options"] = opts

        # ── Strip embedded "(x) " prefix from every option value ──────────────
        for k, v in list(opts.items()):
            if isinstance(v, str) and _OPT_PREFIX_RE.match(v):
                opts[k] = _OPT_PREFIX_RE.sub('', v).strip()

        # ── AR detection: by declared type/subtype OR by option content ──────────
        type_lower = _type_str(q.get("type", ""))
        subtype = str(q.get("subtype", "")).strip().lower()
        _opt_blob = " ".join(str(v).lower() for v in opts.values())
        _looks_like_ar = (
            "both a and r" in _opt_blob
            or ("a is true" in _opt_blob and "r is false" in _opt_blob)
            or ("a is false" in _opt_blob and "r is true" in _opt_blob)
        )
        is_ar = "assertion" in type_lower or subtype == "assertion_reason" or _looks_like_ar
        if is_ar:
            text = str(q.get("text", "")).strip()
            # The model often puts the statements in separate 'assertion'/'reason' fields
            # and leaves 'text' as the bare word "Assertion". Compose proper text from them.
            assertion_f = str(q.get("assertion", "") or q.get("assertion_statement", "")).strip()
            reason_f    = str(q.get("reason", "") or q.get("reason_statement", "")).strip()
            text_is_placeholder = (
                len(text) < 50
                or text.lower().rstrip(":.") in ("assertion", "assertion-reason", "assertion reason", "a and r")
            )
            if assertion_f and reason_f and text_is_placeholder:
                q["text"] = f"Assertion (A): {assertion_f}\nReason (R): {reason_f}"
                text = q["text"]
                print(f"[Repair] Q{q.get('qnum','?')}: composed AR text from assertion/reason fields")
            # Inject the standard 4 options when A/R text is present but options are missing
            has_assertion = ("Assertion" in text or "A:" in text)
            has_reason = ("Reason" in text or "R:" in text)
            is_substantive = len(text.strip()) > 50
            if has_assertion and has_reason and is_substantive and len(opts) < 4:
                q["options"] = dict(_AR_STANDARD_OPTIONS)
                print(f"[Repair] Q{q.get('qnum','?')}: injected standard AR options (had A/R text, options missing)")
            # Normalize subtype so downstream validation enforces the AR text format
            q["subtype"] = "assertion_reason"

        # ── Infer and inject subtype when LLM omitted it (or set it wrong) ───────
        # Map questions arrive as type="SA" (no "map" in type_lower), so detect them by
        # the map_note field or "outline map" phrasing — otherwise they'd default to
        # "standard" and fail the blueprint MAP-position check, wasting a retry.
        _txt_lower = str(q.get("text", "")).lower()
        _has_map_signal = bool(str(q.get("map_note", "")).strip()) or "outline map" in _txt_lower
        cur_subtype = str(q.get("subtype", "")).strip().lower()
        if _has_map_signal and cur_subtype in ("", "standard"):
            q["subtype"] = "map_based"
        elif not q.get("subtype"):
            if is_ar:
                q["subtype"] = "assertion_reason"
            elif "map" in type_lower:
                q["subtype"] = "map_based"
            elif "image" in type_lower:
                q["subtype"] = "image_based"
            elif "source" in type_lower or "cbq" in type_lower or "case" in type_lower:
                q["subtype"] = "source_based"
            else:
                q["subtype"] = "standard"

    return section_data


def _ar_text_is_complete(text: str) -> bool:
    """True if 'text' already contains full Assertion AND Reason statements."""
    t = str(text or "").strip()
    has_a = ("Assertion (A):" in t or "Assertion:" in t)
    has_r = ("Reason (R):" in t or "Reason:" in t)
    return has_a and has_r and len(t) > 50


def _post_process_assertion_reason(section_data: dict, wo: SectionWorkOrder) -> tuple:
    """
    Guarantee every Assertion-Reason question carries full Assertion + Reason statements.

    The base model reliably emits the 4 standard AR options but frequently leaves 'text' as a
    bare placeholder ("Assertion") and never writes the statements — so after retries the
    section ships a headless AR question. This deterministic post-process detects such
    questions and fills them: first by salvaging separate assertion/reason fields (free),
    then via a focused single-question LLM call. The question is then assembled structurally,
    so the result never depends on the base model getting the inline format right.

    Mutates section_data in place. Returns (in_tokens, out_tokens) consumed.
    """
    questions = section_data.get("questions", [])
    if not isinstance(questions, list):
        return 0, 0

    total_in = 0
    total_out = 0
    subject = wo.section_subject or wo.subject or "Social Science"
    chapters = wo.chapters or []

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        opts = q.get("options") if isinstance(q.get("options"), dict) else {}
        opt_blob = " ".join(str(v).lower() for v in opts.values())
        subtype = str(q.get("subtype", "")).strip().lower()
        looks_like_ar = (
            subtype == "assertion_reason"
            or "both a and r" in opt_blob
            or ("a is true" in opt_blob and "r is false" in opt_blob)
            or ("a is false" in opt_blob and "r is true" in opt_blob)
        )
        if not looks_like_ar or _ar_text_is_complete(q.get("text", "")):
            continue

        qnum = q.get("qnum", i + 1)

        # 1) Salvage from separate fields (no LLM cost) ──────────────────────────
        a_field = str(q.get("assertion", "") or q.get("assertion_statement", "")
                      or q.get("statement_1", "") or q.get("statement1", "")).strip()
        r_field = str(q.get("reason", "") or q.get("reason_statement", "")
                      or q.get("statement_2", "") or q.get("statement2", "")).strip()
        answer = str(q.get("answer", "")).strip().lower()

        # 2) Focused LLM call when statements are genuinely absent ────────────────
        if not (a_field and r_field):
            chapter = q.get("chapter_tag") or (chapters[0] if chapters else subject)
            ctx = str(wo.context_text or "")[:1500]
            ctx_block = ("Base it on this reference material:\n" + ctx + "\n\n") if ctx else ""
            prompt = (
                f"Create ONE Assertion-Reason question for CBSE Class {wo.class_name} "
                f"{subject}, topic: {chapter}.\n"
                + ctx_block +
                "Return ONLY this JSON (no markdown, no commentary):\n"
                '{"assertion": "<one complete factual sentence>", '
                '"reason": "<one complete sentence>", "answer": "<a|b|c|d>"}\n\n'
                "The 'answer' must correctly describe the A–R relationship:\n"
                "a = Both A and R are true and R is the correct explanation of A\n"
                "b = Both A and R are true but R is NOT the correct explanation of A\n"
                "c = A is true but R is false\n"
                "d = A is false but R is true\n"
                "Make A and R substantive (test real understanding); the relationship MUST match the answer."
            )
            try:
                raw, in_tok, out_tok = mantle_client.converse(
                    model_id=GEN_MODEL, prompt=prompt, max_tokens=400, temperature=0.7,
                )
                total_in += in_tok
                total_out += out_tok
                clean = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip(), flags=re.MULTILINE)
                clean = re.sub(r"\n?```$", "", clean.strip())
                m = re.search(r"\{.*\}", clean, re.S)
                obj = json.loads(m.group(0)) if m else {}
                a_field = str(obj.get("assertion", "")).strip()
                r_field = str(obj.get("reason", "")).strip()
                ans = str(obj.get("answer", "")).strip().lower()
                if ans in ("a", "b", "c", "d"):
                    answer = ans
                print(f"[AR-Repair] Q{qnum}: generated Assertion/Reason statements via focused call")
            except Exception as exc:
                print(f"[AR-Repair] Q{qnum} focused generation failed: {exc}")

        # 3) Assemble the question structurally ──────────────────────────────────
        if a_field and r_field:
            q["text"] = f"Assertion (A): {a_field}\nReason (R): {r_field}"
            q["options"] = dict(_AR_STANDARD_OPTIONS)
            q["type"] = "MCQ"
            q["subtype"] = "assertion_reason"
            if answer in ("a", "b", "c", "d"):
                q["answer"] = answer
            # Drop now-redundant scattered fields
            for k in ("assertion", "reason", "assertion_statement", "reason_statement",
                      "statement_1", "statement_2", "statement1", "statement2"):
                q.pop(k, None)
            print(f"[AR-Repair] Q{qnum}: assembled complete Assertion-Reason question")
        else:
            print(f"[AR-Repair] Q{qnum}: could not obtain statements — left as-is")

    return total_in, total_out


def _top_up_short_section(section_data: dict, wo: SectionWorkOrder) -> tuple:
    """Last-resort fix for a section that came back SHORT ON COUNT (right types, right
    marks, just too few questions — e.g. a 16-MCQ Section A where the model emitted 8).

    Makes ONE focused follow-up call for exactly the missing questions, on the chapters
    still under-covered, forbidding repeats of what already exists. Strictly ADDITIVE:
    only appends questions that are the correct type, correct marks and not duplicates,
    and never more than the shortfall — so it can never worsen the section. Returns
    (in_tokens, out_tokens); a no-op (0, 0) when it doesn't apply or can't help.

    Scoped to UNIFORM-MARKS sections (every question worth the same — e.g. a 16-mark
    Section A of MCQ + Assertion-Reason, or an all-VSA/SA/LA section) where the missing
    question's marks are unambiguous and any of the section's declared types is acceptable.
    Mixed-marks, CBQ and passage/extract sections are left to the normal retry path —
    topping them up blindly is unsafe. Map sections ARE topped up: a map question is
    structurally simple (text + map_note), the rebuilt prompt carries the map-work
    instruction block, and the by-category filter below keeps only correctly-typed
    questions — without this a short map section had no recovery path at all.
    """
    questions = [q for q in section_data.get("questions", []) if isinstance(q, dict)]
    expected = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
    missing = int(expected or 0) - len(questions)
    if missing <= 0:
        return 0, 0

    # Collect the section's allowed categories. Multiple are fine (MCQ + Assertion-Reason)
    # as long as the section is uniform-marks — the missing question is worth wo.marks_per_question
    # whichever allowed type it is. Bail on mixed-marks or structurally heavy sections.
    allowed = []
    for t in (wo.question_types or []):
        c = _fine_category(t if isinstance(t, str) else t.get("type", ""))
        if c and c != "other" and c not in allowed:
            allowed.append(c)

    # Never blind-fill structurally heavy or mixed-marks sections — their questions carry
    # passages, sub-questions, or per-type marks that a generic top-up can't reproduce.
    if wo.mixed_marks or _is_dedicated_cbq_section(wo) \
            or wo.passage_instruction or wo.extract_instruction or "cbq" in allowed:
        return 0, 0

    # ``loose`` mode: a plain uniform-marks written-answer section whose declared types are
    # all free-form / descriptive ("2 Mark Questions", "Essay", "Letter Writing" — common in
    # AI-generated patterns) so none classify to a canonical category. We can't filter the
    # top-up by an exact type, but every question is worth the same and the section has no
    # special structure, so accept any on-topic, non-duplicate question and force the section
    # marks. When at least one type DID classify, keep the strict by-category filter unchanged
    # (so sections that already work — MCQ/VSA/SA/LA/… — behave exactly as before).
    loose = not allowed
    if loose and not wo.marks_per_question:
        return 0, 0          # no unambiguous per-question marks → unsafe; leave to retry
    allowed_set = set(allowed)

    eff_subject = wo.section_subject or wo.subject
    # Seed coverage from what already exists so the top-up prefers the still-missing chapters.
    covered: dict = {}
    for q in questions:
        tag = str(q.get("chapter_tag") or q.get("chapter") or "").strip().lower()
        if not tag:
            continue
        for ch in (wo.chapters or []):
            cl = ch.strip().lower()
            if cl and (cl in tag or tag in cl):
                covered[(eff_subject, ch)] = covered.get((eff_subject, ch), 0) + 1
                break
    topup_plan = _allocate_chapters_to_slots(wo.chapters, missing, eff_subject, covered)

    # Reuse the normal section prompt, but for just the missing count, then forbid repeats.
    sub_wo = dc_replace(wo, questions_count=missing, provided_count=None,
                        attempt_count=None, chapter_plan=topup_plan, marks=0)
    prompt = build_section_prompt(sub_wo, attempt=1, prior_error="")
    existing = [str(q.get("text", "")).strip() for q in questions if str(q.get("text", "")).strip()]
    if existing:
        prompt += (
            "\n\nALREADY-WRITTEN QUESTIONS — generate COMPLETELY DIFFERENT ones (different "
            "concepts/chapters, no paraphrases of these):\n"
            + "\n".join(f"- {t[:160]}" for t in existing)
        )

    try:
        raw, in_tok, out_tok = mantle_client.converse(
            model_id=GEN_MODEL, prompt=prompt,
            max_tokens=estimate_token_budget(sub_wo), temperature=0.8,
        )
        new_data = _repair_section_data(extract_section_json(raw))
    except Exception as e:
        print(f"[Top-Up] '{wo.section_name}': follow-up call failed ({e}) — keeping partial")
        return 0, 0

    seen = {t.lower() for t in existing}
    kept_texts = list(existing)   # for concept-overlap dedup, grows as we accept
    added = []
    for q in new_data.get("questions", []):
        if len(added) >= missing:
            break
        if not isinstance(q, dict) or not str(q.get("text", "")).strip():
            continue
        # Strict sections filter by category; loose (free-form-type) sections accept any
        # written-answer question but still reject structural types they can't host.
        cat = _fine_category(q.get("type", ""), str(q.get("subtype", "")).strip().lower())
        if loose:
            if cat in ("cbq", "map"):
                continue
        elif cat not in allowed_set:
            continue
        txt = str(q.get("text", "")).strip()
        low = txt.lower()
        if low in seen:
            continue
        # Reject a near-duplicate of anything already in the section (the model can echo an
        # existing question despite the "different concepts" instruction) — the topped-up
        # questions don't otherwise pass through the V5 dedup chain. Map questions all share
        # the same boilerplate stem ("On the given outline map of India, locate and label:"),
        # which alone scores ~0.8 overlap — compare only the location list after the stem, or
        # every legitimate extra map question is rejected and the section can never be filled.
        if cat == "map":
            cand = _map_locations_text(txt)
            if any(_concept_overlap(cand, _map_locations_text(e)) > 0.6 for e in kept_texts):
                continue
        elif any(_concept_overlap(txt, e) > 0.6 for e in kept_texts):
            continue
        # Force the section's per-question marks (the model occasionally drifts on the top-up).
        q["marks"] = wo.marks_per_question
        added.append(q)
        seen.add(low)
        kept_texts.append(txt)

    if added:
        section_data["questions"] = questions + added
        section_data["_topped_up"] = len(added)
        _types = "/".join(c.upper() for c in allowed) if allowed else "free-form"
        print(f"[Top-Up] '{wo.section_name}': added {len(added)}/{missing} missing {_types} question(s)")
    return in_tok, out_tok


def _fill_short_section(section_data: dict, wo: SectionWorkOrder, max_rounds: int = 3) -> tuple:
    """Top up a short section REPEATEDLY until it reaches its expected count or a round adds
    nothing. ``_top_up_short_section`` makes ONE follow-up call and keeps only questions that
    are the right type, right marks and not duplicates — so a single call routinely recovers
    fewer than the shortfall (a 20-MCQ section comes back 18, the top-up adds 1, still 19/20).
    One call is not enough on its own; loop it, recomputing the shortfall each round, so a
    section that is merely short on count is reliably filled instead of shipping partial.

    Stops early when a round makes no progress (the model can't produce more usable,
    non-duplicate questions) so it never burns the full budget needlessly. Sets a cumulative
    ``_topped_up`` so the caller re-validates. Returns accumulated (in_tokens, out_tokens)."""
    def _count():
        return len([q for q in section_data.get("questions", []) if isinstance(q, dict)])

    expected = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
    initial = _count()
    total_in = total_out = 0
    for _round in range(max_rounds):
        if expected and _count() >= expected:
            break
        before = _count()
        in_tok, out_tok = _top_up_short_section(section_data, wo)
        total_in += in_tok
        total_out += out_tok
        if in_tok == 0 and out_tok == 0:
            break               # top-up doesn't apply to this section type — stop immediately
        if _count() <= before:
            break               # round added nothing usable — retrying won't help
    final = _count()
    if final > initial:
        section_data["_topped_up"] = final - initial   # cumulative across rounds
    return total_in, total_out


def reconcile_uniform_marks(paper_data: dict, work_orders: list) -> dict:
    """Make every uniform-marks section sum to the marks its pattern declares. Two behaviours:

    • CLAMP — objective sections (MCQ/Assertion-Reason), and any written-answer section whose
      arithmetic is already consistent (count × marks_per_question == section marks): set each
      question to ``marks_per_question``. Kills the 'one 2-mark VSA written as 1 mark' drift
      that surfaces as 'Section B: 9/10 marks (-1)'. Objective marks are FIXED here — a 1-mark
      MCQ is never inflated, so a count shortfall stays visible instead of being masked.

    • DISTRIBUTE — written-answer sections whose pattern is internally inconsistent, where
      count × marks_per_question can NEVER equal the declared marks (e.g. 3 SA questions × 3m
      but the section is declared 10m): spread the declared marks across the questions as evenly
      as possible (10 over 3 → 4,3,3) so the section — and the paper total — match the pattern
      exactly, instead of shipping a mark short forever.

    Skips mixed-marks sections (legitimately varied) and CBQ questions (marks = Σ sub-questions)."""
    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    for sec_name, sec_data in paper_data.items():
        if not isinstance(sec_data, dict):
            continue
        wo = wo_by_name.get(sec_name)
        if not wo or wo.mixed_marks or not wo.marks_per_question:
            continue

        mpq = wo.marks_per_question
        # CBQ marks come from sub-questions — never override those; only written-answer /
        # objective questions are reconciled.
        targets = [q for q in sec_data.get("questions", [])
                   if isinstance(q, dict) and not q.get("sub_questions")]
        if not targets:
            continue

        has_objective = any(
            _fine_category(t if isinstance(t, str) else t.get("type", "")) in ("mcq", "ar")
            for t in (wo.question_types or [])
        )
        expected = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
        consistent = (not expected) or abs(expected * mpq - wo.marks) <= 0.5

        # DISTRIBUTE only for an inconsistent written-answer section with a sane marks budget.
        n = len(targets)
        base, rem = divmod(int(wo.marks), n) if wo.marks else (0, 0)
        if has_objective or consistent or not wo.marks or base < 1:
            fixed = 0
            for q in targets:
                cur = _as_float(q.get("marks"), None) if q.get("marks") is not None else None
                if cur is None or abs(cur - mpq) > 0.01:
                    q["marks"] = mpq
                    fixed += 1
            if fixed:
                print(f"[Marks-Reconcile] '{sec_name}': set {fixed} question(s) to {mpq}m (uniform section)")
            continue

        plan = [base + 1 if k < rem else base for k in range(n)]
        changed = any(_as_float(q.get("marks"), None) != float(m) for q, m in zip(targets, plan))
        for q, m in zip(targets, plan):
            q["marks"] = m
        if changed:
            print(f"[Marks-Reconcile] '{sec_name}': distributed {wo.marks}m across {n} question(s) "
                  f"as {plan} (pattern {expected}×{mpq} = {expected * mpq if expected else '?'} ≠ {wo.marks})")
    return paper_data


def generate_section(wo: SectionWorkOrder):
    """
    Generate questions for one section. Retries up to MAX_SECTION_RETRIES times on validation
    failure, passing the error back to the LLM.

    For dedicated CBQ sections the flow is question-first:
      1. LLM generates observation questions from chapter knowledge
      2. After validation: image_finder generates/finds image + Kimi verifies sub-questions
      3. section_data gets image_path + Kimi-corrected sub_questions injected

    Returns ({section_name: section_data}, total_input_tokens, total_output_tokens).
    """
    is_cbq = _is_dedicated_cbq_section(wo)

    # 4.3 — For pure LA or source-based CBQ sections: generate questions individually
    _la_types = {"la", "long_answer", "long answer"}
    _cbq_types = {"cbq", "source_based", "source based", "case_based", "case based"}
    _is_la_only = (
        wo.question_types
        and not wo.slots  # slot sections carry their per-question spec in the batch prompt
        and all(_type_str(t).lower() in _la_types for t in wo.question_types)
        and wo.marks_per_question >= 4
        and not is_cbq  # dedicated CBQ uses image-first path
    )
    _is_source_cbq = (
        wo.question_types
        and not wo.slots  # slot sections carry their per-question spec in the batch prompt
        and all(_type_str(t).lower() in _cbq_types for t in wo.question_types)
        and not is_cbq  # dedicated image-based CBQ uses its own path
    )
    if _is_la_only or _is_source_cbq:
        try:
            section_data, in_tok, out_tok = generate_la_cbq_individually(wo)
            # Run the full validation chain on individually generated questions too
            errors = validate_section_output(section_data, wo)
            if errors:
                print(f"[4.3-Individual] '{wo.section_name}' validation errors (will proceed): {errors}")
            dup_warnings = validate_uniqueness(section_data.get("questions", []))
            grounding_issues = check_ncert_grounding(
                section_data.get("questions", []), wo.context_text, str(wo.class_name), wo.subject
            )
            if grounding_issues:
                section_data["_grounding_issues"] = grounding_issues
            if _is_source_cbq and section_data.get("passage"):
                cbq_issues = validate_cbq_passage(section_data, wo)
                if cbq_issues:
                    section_data["_cbq_passage_issues"] = cbq_issues
            quality_flags = run_content_quality_critic(
                section_data.get("questions", []), str(wo.class_name), wo.subject, wo.difficulty
            )
            if quality_flags:
                section_data["_quality_flags"] = quality_flags
            # V5 Layer 2 — only on flag (individual LA/CBQ path)
            if dup_warnings:
                fixed_qs, remaining_dups = verify_and_fix_semantic_duplicates(
                    section_data.get("questions", []), dup_warnings, wo, quality_flags
                )
                section_data["questions"] = fixed_qs
                if remaining_dups:
                    section_data["_uniqueness_warnings"] = remaining_dups
            print(f"[4.3-Individual] '{wo.section_name}' ✓ ({len(section_data.get('questions', []))} questions)")
            section_data["_chapter_plan"] = list(wo.chapter_plan or [])
            return {wo.section_name: section_data}, in_tok, out_tok
        except Exception as e:
            print(f"[4.3-Individual] Failed for '{wo.section_name}': {e} — falling back to batch generation")
            # Fall through to normal batch generation below

    prior_error = ""
    total_in_tok = 0
    total_out_tok = 0
    for attempt in range(1, MAX_SECTION_RETRIES + 2):
        print(f"[Section-Gen] '{wo.section_name}' attempt {attempt}")
        prompt = build_section_prompt(wo, attempt, prior_error)
        token_budget = estimate_token_budget(wo)

        raw, in_tok, out_tok = mantle_client.converse(
            model_id=GEN_MODEL,
            prompt=prompt,
            max_tokens=token_budget,
            temperature=0.8,
        )
        total_in_tok += in_tok
        total_out_tok += out_tok

        try:
            section_data = extract_section_json(raw)
        except ValueError as e:
            prior_error = f"Invalid JSON: {e}"
            if attempt > MAX_SECTION_RETRIES:
                raise RuntimeError(f"'{wo.section_name}': JSON parse failed after {attempt} attempts")
            continue

        # Deterministic repair before validation — fixes known structural LLM mistakes
        # so they don't waste retry budget (e.g. AR missing options, duplicate option prefixes)
        section_data = _repair_section_data(section_data)
        # Guarantee Assertion-Reason questions carry full statements (focused fill when the
        # base model leaves them headless). Idempotent — skips already-complete AR questions,
        # so on retries it costs nothing. Runs before validation to avoid wasted retries.
        _ar_in, _ar_out = _post_process_assertion_reason(section_data, wo)
        total_in_tok += _ar_in
        total_out_tok += _ar_out
        errors = validate_section_output(section_data, wo)
        if not errors:
            section_data["title"] = wo.title
            section_data["marks"] = wo.marks
            # V5 Layer 1 — uniqueness check (warn, don't block)
            dup_warnings = validate_uniqueness(section_data.get("questions", []))
            if dup_warnings:
                for w in dup_warnings:
                    print(f"[Section-Gen] ⚠️  Uniqueness L1: {w}")
            # V3 — NCERT grounding check (RAG+LLM, SA/LA only, warn + store)
            grounding_issues = check_ncert_grounding(
                section_data.get("questions", []),
                wo.context_text,
                str(wo.class_name),
                wo.subject,
            )
            if grounding_issues:
                section_data["_grounding_issues"] = grounding_issues
            # V6 — CBQ passage validation (LLM, only for passage/source-based sections)
            if is_cbq and section_data.get("passage"):
                cbq_issues = validate_cbq_passage(section_data, wo)
                if cbq_issues:
                    section_data["_cbq_passage_issues"] = cbq_issues
            # V2 — Content quality critic (LLM, batched per section, warn + store, don't block)
            quality_flags = run_content_quality_critic(
                section_data.get("questions", []),
                str(wo.class_name),
                wo.subject,
                wo.difficulty,
            )
            if quality_flags:
                section_data["_quality_flags"] = quality_flags
            # V5 Layer 2 — Semantic uniqueness (LLM, only if L1 flagged pairs)
            if dup_warnings:
                fixed_qs, remaining_dups = verify_and_fix_semantic_duplicates(
                    section_data.get("questions", []),
                    dup_warnings,
                    wo,
                    section_data.get("_quality_flags", []),
                )
                section_data["questions"] = fixed_qs
                if remaining_dups:
                    section_data["_uniqueness_warnings"] = remaining_dups
                    print(f"[V5L2] {len(remaining_dups)} warning(s) remain after fix in '{wo.section_name}'")
                else:
                    print(f"[V5L2] ✅ All duplicates resolved in '{wo.section_name}'")
            # V4 — MCQ answer verification (blind LLM test, warn + store, don't block)
            mcq_verify_results = verify_mcq_answers(
                section_data.get("questions", []),
                str(wo.class_name),
                wo.subject,
            )
            suspect_mcqs = [r for r in mcq_verify_results if r.get("suspect")]
            corrected_mcqs = [r for r in mcq_verify_results if r.get("corrected")]
            if suspect_mcqs:
                section_data["_mcq_answer_warnings"] = suspect_mcqs
                print(
                    f"[Section-Gen] ⚠️  V4 MCQ: {len(suspect_mcqs)} suspect answer(s) in '{wo.section_name}'"
                )
            if corrected_mcqs:
                # The keys were already fixed in place by verify_mcq_answers; record what changed.
                section_data["_mcq_answer_corrections"] = corrected_mcqs
                print(
                    f"[Section-Gen] ✅ V4 MCQ: auto-corrected {len(corrected_mcqs)} answer key(s) in '{wo.section_name}'"
                )
            print(f"[Section-Gen] '{wo.section_name}' ✓ ({len(section_data.get('questions', []))} questions)")
            section_data["_chapter_plan"] = list(wo.chapter_plan or [])
            # Post-process: generate image and Kimi-verify sub-questions
            if is_cbq:
                _post_process_cbq_images(section_data, wo)
            return {wo.section_name: section_data}, total_in_tok, total_out_tok

        prior_error = "; ".join(errors)
        print(f"[Section-Gen] '{wo.section_name}' validation failed (attempt {attempt}): {prior_error}")
        if attempt > MAX_SECTION_RETRIES:
            section_data.setdefault("questions", [])
            section_data["title"] = wo.title
            section_data["marks"] = wo.marks
            # Before giving up: if the section is merely SHORT on count (right types/marks,
            # too few questions), make focused top-up calls for the missing questions
            # instead of shipping a half-empty section. Strictly additive — see helper.
            tu_in, tu_out = _fill_short_section(section_data, wo)
            total_in_tok += tu_in
            total_out_tok += tu_out
            remaining = validate_section_output(section_data, wo) if section_data.get("_topped_up") else errors
            if remaining:
                section_data["_partial"] = True
                section_data["_errors"] = remaining
                print(f"[Section-Gen] '{wo.section_name}' emitting partial result "
                      f"({len(section_data.get('questions', []))} q)")
            else:
                print(f"[Section-Gen] '{wo.section_name}' ✓ recovered via top-up "
                      f"({len(section_data.get('questions', []))} q)")
            section_data["_chapter_plan"] = list(wo.chapter_plan or [])
            if is_cbq:
                _post_process_cbq_images(section_data, wo)
            return {wo.section_name: section_data}, total_in_tok, total_out_tok

    raise RuntimeError(f"'{wo.section_name}': exhausted all retries")  # unreachable


# ─────────────────────────────────────────────
# RAG context per section
# ─────────────────────────────────────────────

# 3.2 — Per-question-type context routing profiles
TYPE_CONTEXT_PROFILES = {
    "mcq":          {"extra_hints": ["facts definitions key terms", "important dates events"],       "max_chars": 4000},
    "assertion":    {"extra_hints": ["principles laws statements cause effect"],                     "max_chars": 3000},
    "vsa":          {"extra_hints": ["definitions key terms one-liners"],                            "max_chars": 3000},
    "sa":           {"extra_hints": ["explanations processes mechanisms how why"],                   "max_chars": 5000},
    "la":           {"extra_hints": ["detailed explanations significance importance analysis"],       "max_chars": 8000},
    "cbq":          {"extra_hints": ["diagrams experiments observations case studies"],              "max_chars": 6000},
    "source_based": {"extra_hints": ["passages narratives extracts primary sources"],                "max_chars": 10000},
    "map_work":     {"extra_hints": ["geographic locations places regions states rivers"],           "max_chars": 4000},
}


def _validate_context_quality(context: str, section_name: str, questions_count: int, subject: str, class_name: str, question_types: list) -> bool:
    """
    3.3 — Quick LLM check: is context sufficient to generate the required questions?
    Returns True if sufficient, False if retry with broader query is needed.
    """
    if len(context) < 500:
        print(f"[Context-QC] '{section_name}': context too short ({len(context)} chars) — will retry")
        return False

    types_str = ", ".join(_type_str(t) for t in question_types) if question_types else "Mixed"
    prompt = (
        f"Context quality check.\n"
        f"Subject: {subject} Class {class_name}\n"
        f"Need to generate: {questions_count} questions of types: {types_str}\n\n"
        f"Context available ({len(context)} chars):\n---\n{context[:3000]}\n---\n\n"
        "Is there enough specific, factual content here to write good CBSE-level questions?\n"
        "Output JSON only:\n"
        '{"sufficient": true, "reason": "one sentence"}'
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=100,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        result = json.loads(m.group()) if m else {}
        sufficient = result.get("sufficient", True)
        reason = result.get("reason", "")
        if not sufficient:
            print(f"[Context-QC] '{section_name}': INSUFFICIENT — {reason}")
        return sufficient
    except Exception as e:
        print(f"[Context-QC] LLM check failed for '{section_name}': {e} — assuming sufficient")
        return True


def _query_hints_for_types(question_types: list, subject: str) -> list:
    hints = [f"{subject} important concepts definitions"]
    for qt in question_types:
        ql = _type_str(qt)
        if ql in ("mcq", "multiple_choice"):
            hints.append(f"{subject} facts MCQ questions")
        elif ql in ("assertion_reason", "assertion-reason"):
            hints.append(f"{subject} principles assertion reason")
        elif ql in ("case_based", "case-based"):
            hints.append(f"{subject} case study applications")
        elif ql in ("unseen_passage", "reading_comprehension"):
            hints.append(f"{subject} reading comprehension passages")
        elif ql in ("short_answer", "sa"):
            hints.append(f"{subject} short answer explanations")
        elif ql in ("long_answer", "la", "essay"):
            hints.append(f"{subject} detailed explanations processes")
        elif ql in ("numerical", "calculation"):
            hints.append(f"{subject} numerical problems solved examples")
        elif ql in ("writing_tasks", "writing"):
            hints.append(f"{subject} writing formats samples letters")
    return list(dict.fromkeys(hints))


def _chapter_weight(subject: str, chapter: str) -> int:
    """
    Return the CBSE unit marks weight for a chapter, used to scale n_results.
    Matches chapter name against UNIT_MARKS_WEIGHTS by substring (case-insensitive).
    Falls back to 1 if no match found.
    """
    weights = UNIT_MARKS_WEIGHTS.get(subject, {})
    if not weights or not chapter:
        return 1
    chapter_lower = chapter.strip().lower()
    for unit_key, weight in weights.items():
        if unit_key.lower() in chapter_lower or chapter_lower in unit_key.lower():
            return weight
    return 1


def get_section_context(class_name: str, subject: str, chapters: list, query_hints: list, max_chars: int = 8000, school_id=None) -> str:
    """Assemble the section's source-material context with a PER-CHAPTER share of the
    character window, each chapter headed by its LLM chapter summary (enrichment) when
    one exists.

    The old implementation appended docs chapter-by-chapter and then truncated the TAIL
    (`context[:max_chars]`) — the first chapter alone usually overflowed the window, so
    every later chapter got ZERO representation and the prompt's demanded chapter
    distribution was unsatisfiable (the same-unit clustering defect,
    docs/CHAPTER_ENRICHMENT_PLAN.md). Budgets are enforced BEFORE concatenation, so every
    chapter that returned anything is guaranteed a proportional slice."""
    seen: set = set()

    # When no chapters specified (e.g. One Mark Test), query across all ingested content
    # by passing unit=None — embeddings.query omits the where filter when unit is falsy.
    query_units = chapters if chapters else [None]

    # Compute total weight for proportional allocation
    chapter_weights = {ch: _chapter_weight(subject, ch or "") for ch in query_units}
    total_weight = sum(chapter_weights.values()) or 1
    # Base pool: 48 chunks across all chapters; each chapter gets a share proportional to its CBSE marks weight
    base_pool = max(48, 12 * len(query_units))

    docs_by_unit: dict = {}
    for chapter in query_units:
        weight = chapter_weights[chapter]
        n_results = max(4, round(base_pool * weight / total_weight))
        unit_docs = docs_by_unit.setdefault(chapter, [])
        for query in query_hints[:5]:
            try:
                results = embeddings.query(
                    class_name=class_name,
                    subject=subject,
                    unit=chapter,
                    query_text=query,
                    n_results=n_results,
                    school_id=school_id,
                )
                if results and results.get("documents"):
                    for doc_list in results["documents"]:
                        docs = doc_list if isinstance(doc_list, list) else [doc_list]
                        for doc in docs:
                            if doc and doc not in seen:
                                seen.add(doc)
                                unit_docs.append(doc)
            except Exception as e:
                print(f"[Section-Context] query failed chapter='{chapter}' q='{query}': {e}")

    # Chapters that returned nothing are dropped and their budget share redistributed.
    live_units = [ch for ch in query_units if docs_by_unit.get(ch)]
    if not live_units:
        return ""
    live_weight = sum(chapter_weights[ch] for ch in live_units) or 1

    blocks = []
    for chapter in live_units:
        if len(live_units) == 1:
            budget = max_chars
        else:
            # Weight-proportional slice, floored so even the lightest chapter fits its
            # header plus a meaningful piece of one chunk.
            budget = max(min(900, max_chars // len(live_units) + 500),
                         int(max_chars * chapter_weights[chapter] / live_weight))
        parts = []
        if chapter:
            header = f"=== CHAPTER: {chapter} ==="
            summary = embeddings.get_chapter_summary(class_name, subject, chapter, school_id=school_id)
            if summary:
                header += f"\n[About this chapter: {summary[:400]}]"
            parts.append(header)
        used = sum(len(p) for p in parts)
        added = 0
        for doc in docs_by_unit[chapter]:
            if not added:
                # Always represent the chapter with at least one (possibly trimmed) chunk.
                room = max(400, budget - used)
                parts.append(doc[:room])
                used += min(len(doc), room)
            elif used + len(doc) + 2 > budget:
                break
            else:
                parts.append(doc)
                used += len(doc) + 2
            added += 1
        blocks.append("\n\n".join(parts))

    context = "\n\n".join(blocks)
    # Budgets already keep the total ≈ max_chars; the slack tolerates header/floor
    # overflow on many-chapter papers without re-introducing tail starvation.
    return context[:int(max_chars * 1.25)]


def _extract_span_chars(instruction: str) -> int:
    """Chars of continuous source text an extract slot needs: the pattern's stated word
    count (≈6.5 chars/word incl. spaces) plus headroom so the model can choose a natural
    beginning and end inside the span. Default suits the CBSE-typical 100-150 word extract."""
    m = re.search(r"(\d{2,4})\s*words", str(instruction or ""), re.IGNORECASE)
    if not m:
        return 1800
    return max(1200, min(5000, int(int(m.group(1)) * 6.5) + 600))


# Kind signals for extract routing — matched against slot format/condition/alternatives,
# the section name and the pattern's extract_instruction. Latin keywords use word
# boundaries so ordinary pattern prose can't misfire ('verse' must not match 'diverse',
# 'play' must not match 'plays with words'); \bpoem (no closing boundary) still catches
# 'poems'. Tamil/Devanagari keep substring matching — agglutinative suffixes make word
# boundaries useless there. Deliberately NO generic-noun signals (e.g. the NCERT reader
# "Moments" — the bare word is far too common to mean the book).
_EXTRACT_KIND_PATTERNS = {
    "poem": (r"\bpoem", r"\bpoetry\b", r"\bverse\b", r"\bstanza"),
    "prose": (r"\bprose\b",),
    "drama": (r"\bdrama", r"\bplay\b"),
    "supplementary": (r"\bsupplementary\b", r"\bfootprints\b", r"\bsanchayan\b"),
}
_EXTRACT_KIND_SUBSTRINGS = {
    "poem": ("கவிதை", "செய்யுள்", "कविता", "पद्य"),
    "prose": ("உரைநடை", "गद्य"),
    "drama": ("நாடக", "नाटक"),
    "supplementary": ("துணைப்பாட",),
}


def _kind_signals(blob: str) -> set:
    """Chapter kinds explicitly signaled in a piece of pattern text."""
    blob = (blob or "").lower()
    found = set()
    for kind, patterns in _EXTRACT_KIND_PATTERNS.items():
        if any(re.search(p, blob) for p in patterns) or \
                any(s in blob for s in _EXTRACT_KIND_SUBSTRINGS.get(kind, ())):
            found.add(kind)
    return found


def _extract_kinds_wanted(sec_slots: list, sec_data: dict, sec_name: str = "") -> set:
    """Which chapter kinds the section's extract slots explicitly ask for (e.g. the CBSE
    English paper's separate PROSE and POETRY extract questions). Empty set = pattern
    doesn't say — no routing."""
    text_bits = [str(sec_name or ""), str(sec_data.get("extract_instruction") or "")]
    for sl in sec_slots or []:
        if str(sl.get("type") or "") != "extract":
            continue
        text_bits += [str(sl.get("format") or ""), str(sl.get("condition") or ""),
                      " ".join(str(a) for a in (sl.get("alternatives") or []))]
    return _kind_signals(" ".join(text_bits))


def _slot_extract_kind(sl: dict) -> str:
    """The ONE kind this extract slot asks for ('' = unconstrained/ambiguous)."""
    sigs = _kind_signals(" ".join([str(sl.get("format") or ""), str(sl.get("condition") or ""),
                                   " ".join(str(a) for a in (sl.get("alternatives") or []))]))
    return next(iter(sigs)) if len(sigs) == 1 else ""


def _extract_kind_needs(sec_slots: list) -> list:
    """One entry per PRINTED extract passage the section needs: an internal-choice
    extract slot prints TWO alternatives, so it needs two passages of its kind.
    Returns e.g. ['', '', 'poem', 'poem'] for a prose-unsignaled Q6 + poetry Q7."""
    needs = []
    for sl in sec_slots or []:
        if str(sl.get("type") or "") != "extract":
            continue
        k = _slot_extract_kind(sl)
        needs += [k] * (2 if str(sl.get("choice") or "") == "internal" else 1)
    return needs


def _chapters_for_extract_needs(class_name: str, subject: str, chapters: list,
                                kind_needs: list) -> list:
    """Pick one chapter per needed printed extract, honoring each slot's kind signal
    where ChapterInfo data exists. Unsignaled needs take the earliest chapter that is
    NOT of a kind some other slot explicitly asked for (so tagging only Q7 as poetry
    cannot starve Q6's prose alternatives). Fail-open: no classification data → the
    original order is untouched. Leftover chapters are appended for headroom."""
    if not chapters:
        return []
    if not kind_needs or not any(kind_needs):
        return list(chapters)
    from .models import ChapterInfo
    from .embeddings import normalize_label
    cls, subj = normalize_label(class_name), normalize_label(subject)
    norm_of = {ch: normalize_label(ch) for ch in chapters}
    try:
        kind_of = dict(ChapterInfo.objects.filter(class_name=cls, subject=subj,
                                                  unit__in=list(norm_of.values()))
                       .exclude(kind='').values_list('unit', 'kind'))
    except Exception as e:
        print(f"[Extract-Route] ChapterInfo lookup failed: {e}")
        return list(chapters)
    if not kind_of:
        return list(chapters)

    remaining = list(chapters)
    picked = []
    for need in kind_needs:
        cand = None
        if need:
            cand = next((ch for ch in remaining if kind_of.get(norm_of[ch]) == need), None)
        if cand is None:
            reserved = {k for k in kind_needs if k and k != need}
            cand = next((ch for ch in remaining if kind_of.get(norm_of[ch]) not in reserved),
                        remaining[0] if remaining else None)
        if cand is not None:
            picked.append(cand)
            remaining.remove(cand)
    if picked:
        print(f"[Extract-Route] needs {kind_needs} → chapters {picked}")
    return picked + remaining


def _looks_like_verse(text: str) -> bool:
    """Shape test for poetry: mostly short lines. PDF prose extracts with hard line
    breaks run ~60-90 chars/line; poem lines run ~15-45."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) < 4:
        return False
    short = sum(1 for l in lines if len(l) <= 48)
    return short / len(lines) >= 0.7


def _verse_passages(class_name: str, subject: str, chapters: list, school_id,
                    want: int, existing: list) -> list:
    """Poem passages for poetry-extract slots when NO poem-classified chapter can supply
    them: NCERT language readers interleave poems INSIDE prose chapters (Class 10 First
    Flight has no separate poem chapters at all), so chapter-kind routing has nothing to
    route to. Hunt verse-SHAPED chunks by similarity across the section's chapters
    instead — a single ~1000-char chunk holds a complete short poem or stanza, which is
    exactly what a CBSE poetry extract quotes."""
    out = []
    for chapter in (chapters or [None]):
        if len(out) >= want:
            break
        try:
            res = embeddings.query(class_name=class_name, subject=subject, unit=chapter,
                                   query_text=f"{subject} poem stanza verse rhyme lines",
                                   n_results=3, school_id=school_id)
        except Exception as e:
            print(f"[Verse-Hunt] query failed chapter='{chapter}': {e}")
            continue
        for doc in (res.get("documents") or [[]])[0]:
            if len(out) >= want:
                break
            if doc and _looks_like_verse(doc) and \
                    not any(doc in e or e in doc
                            for e in existing + [o["text"] for o in out]):
                out.append({"chapter": chapter or "", "kind": "poem", "text": doc.strip()})
    if out:
        print(f"[Verse-Hunt] found {len(out)} verse passage(s) inside prose chapters")
    return out


def get_extract_spans(class_name: str, subject: str, chapters: list, school_id=None,
                      span_chars: int = 3500, max_spans: int = 3) -> list:
    """Continuous narrative passages for literature-extract slots, each labeled with its
    chapter and kind: [{'chapter', 'kind', 'text'}].

    Retrieval returns isolated ~1000-char chunks in similarity order, so the section
    context never contains an unbroken passage longer than ~170 words — an extract slot
    whose pattern demands "approximately 500 words" could not be quoted verbatim at all
    (the stitched-extract validator rightly rejects quotes spliced across fragments).
    Seed one narrative chunk per chapter and extend it with its physical neighbours
    (embeddings.fetch_contiguous_span) into one printed-order span each. The chapter/
    kind labels let the prompt bind a poetry-extract slot to a POEM passage."""
    spans = []
    hint = f"{subject} story prose poem narrative dialogue lines"

    kind_of, norm_of = {}, {}
    try:
        from .models import ChapterInfo
        from .embeddings import normalize_label
        norm_of = {ch: normalize_label(ch) for ch in (chapters or []) if ch}
        if norm_of:
            kind_of = dict(ChapterInfo.objects.filter(class_name=normalize_label(class_name),
                                                      subject=normalize_label(subject),
                                                      unit__in=list(norm_of.values()))
                           .exclude(kind='').values_list('unit', 'kind'))
    except Exception:
        pass   # labels are best-effort — spans work fine without them

    for chapter in (chapters or [None])[:max_spans]:
        try:
            res = embeddings.query(class_name=class_name, subject=subject, unit=chapter,
                                   query_text=hint, n_results=1 if chapter else max_spans,
                                   school_id=school_id)
        except Exception as e:
            print(f"[Extract-Spans] query failed chapter='{chapter}': {e}")
            continue
        for cid in (res.get("ids") or [[]])[0]:
            try:
                span = embeddings.fetch_contiguous_span(cid, before=1, after=4, max_chars=span_chars)
            except Exception as e:
                print(f"[Extract-Spans] span fetch failed id={cid}: {e}")
                continue
            if span and not any(span in s["text"] or s["text"] in span for s in spans):
                spans.append({"chapter": chapter or "",
                              "kind": kind_of.get(norm_of.get(chapter, ""), "") if chapter else "",
                              "text": span})
    return spans[:max_spans]


# Keyword fallback for classifying a chapter into a sub-subject when its name isn't an exact
# catalog match (custom/renamed chapters). Mirrors generator.py's single-prompt classifier.
_SUBJECT_CHAPTER_KEYWORDS = {
    "history":           ["nationalism", "global world", "globalworld", "industriali",
                          "print culture", "rise of", "making of", "age of", "work life",
                          "indo-china", "indo china"],
    "geography":         ["resource", "agriculture", "water", "forest", "wildlife",
                          "mineral", "manufacturing", "lifeline", "land", "soil", "energy",
                          "crops", "irrigation"],
    "political science": ["power sharing", "federali", "democracy", "gender", "religion",
                          "political part", "struggle", "outcome", "challenge", "caste"],
    "civics":            ["power sharing", "federali", "democracy", "gender", "religion",
                          "political part", "struggle", "outcome", "challenge", "caste"],
    "economics":         ["development", "sector", "money", "credit", "globalisa",
                          "globaliza", "consumer", "income", "poverty", "employment"],
}


# Compound papers whose sections are named after their component sub-subjects.
_COMPOUND_COMPONENTS = {
    "science":        {"physics", "chemistry", "biology"},
    "social science": {"history", "geography", "political science", "civics", "economics"},
}


def _resolve_section_subject(parent_subject: str, section_name: str, explicit: str = "") -> str:
    """Resolve a section's sub-subject for compound papers.

    Uses the pattern's explicit ``section_subject`` when present; otherwise infers it
    from the section NAME when the parent is a compound subject and the section is named
    after one of its components (e.g. the "Biology" section of a Science paper). Returns
    "" for ordinary single-subject papers, so they are never scoped.

    Without this, compound patterns that omit ``section_subject`` (most of them) fall
    through to the "no sub-subject → use every chapter" path, which is why a Biology
    section ended up full of Chemistry and Physics questions.
    """
    if explicit:
        return explicit
    comps = _COMPOUND_COMPONENTS.get(str(parent_subject or "").strip().lower(), set())
    if section_name and section_name.strip().lower() in comps:
        return section_name.strip()
    return ""


def _chapters_for_subject(section_subject: str, parent_subject: str, all_chapters: list) -> list:
    """
    For COMPOUND papers, return only the chapters that belong to a section's sub-subject
    (e.g. the History section of a Social Science paper keeps History chapters only).

    SAFETY — single-subject papers are never touched. The full list is returned unchanged when:
      • section_subject is empty, or
      • section_subject equals the parent subject (not a compound paper), or
      • nothing matches the sub-subject (don't starve the section).

    Mapping is hybrid: exact/substring match against the CBSE UNIT_MARKS_WEIGHTS catalog first,
    then a keyword fallback for custom/renamed chapters.
    """
    if not section_subject or not all_chapters:
        return list(all_chapters)
    subj_lower = section_subject.strip().lower()
    if subj_lower == str(parent_subject or "").strip().lower():
        return list(all_chapters)  # single-subject paper — leave every chapter in place

    # 0) Science sub-subjects (Physics/Chemistry/Biology). The UNIT_MARKS_WEIGHTS catalog only
    # lists senior-secondary chapters and there is no keyword set for them, so the generic
    # logic below can't route a class 9-10 Science paper. Use the dedicated chapter classifier
    # (shared with the split_science command) to keep only this sub-subject's chapters.
    if subj_lower in ("physics", "chemistry", "biology"):
        matched = [c for c in all_chapters if (classify_chapter(c)[0] or "").lower() == subj_lower]
        return matched or list(all_chapters)

    # 1) Catalog chapters for this sub-subject (keys may be "History", "Economics Class 10", …)
    catalog_names = []
    for cat_key, chap_map in UNIT_MARKS_WEIGHTS.items():
        ck = cat_key.lower()
        if ck == subj_lower or ck.startswith(subj_lower) or subj_lower in ck:
            catalog_names = [c.lower() for c in chap_map.keys()]
            break

    # 2) Keyword set for this sub-subject (resolve by substring so "economics class 10" → economics)
    kw_set = []
    for ksub, kws in _SUBJECT_CHAPTER_KEYWORDS.items():
        if ksub in subj_lower or subj_lower in ksub:
            kw_set = kws
            break

    def _belongs(chapter: str) -> bool:
        cl = chapter.lower().strip()
        for cn in catalog_names:
            if cl in cn or cn in cl:
                return True
        return any(kw in cl for kw in kw_set)

    matched = [c for c in all_chapters if _belongs(c)]
    return matched or list(all_chapters)


# ─────────────────────────────────────────────
# Grammar-section chapter routing
# ─────────────────────────────────────────────
# Language papers carry a dedicated grammar section (இலக்கணம் / व्याकरण / "Grammar") whose
# questions must come from the textbook's grammar LESSONS — not from grammar-adjacent lines
# inside prose/poem chapters — and conversely the literature sections must not spend their
# question slots on the grammar lessons. Chapter titles rarely carry a literal grammar
# marker (class 6 Tamil grammar lessons: "மொழிமுதல் எழுத்துகள்", "முதலெழுத்தும்
# சார்பெழுத்தும்"…), so identification is keyword-first with one cached LLM classification
# on top. Routing only activates when the paper actually HAS a grammar-named section, so
# every other subject/pattern is untouched.

_GRAMMAR_MARKERS = ("இலக்கணம்", "இலக்கண", "grammar", "व्याकरण", "vyakaran", "ilakkanam")


def _is_grammar_section(sec_name: str, instructions=None) -> bool:
    """True when a section is a grammar section, judged by its name + instructions."""
    hay = str(sec_name or "").lower()
    for ins in instructions or []:
        hay += " " + str(ins).lower()
    return any(m in hay for m in _GRAMMAR_MARKERS)


def _blueprint_has_grammar_section(blueprint: dict) -> bool:
    return any(
        _is_grammar_section(sn, sd.get("instructions"))
        for sn, sd in (blueprint or {}).items()
        if isinstance(sd, dict)
    )


_grammar_chapters_cache: dict = {}


def identify_grammar_chapters(class_name: str, subject: str, chapters: list) -> list:
    """Subset of `chapters` that are grammar LESSONS (vs prose/poetry/supplementary).

    Title-keyword pass first, then ONE LLM classification (VAL_MODEL, cached per
    class+subject+chapters) for the titles a keyword can't decide. Fails open to []
    — meaning "no routing" — on any LLM error, so generation never starves."""
    chs = [str(c) for c in (chapters or []) if c]
    if not chs:
        return []
    key = (str(class_name), str(subject), tuple(sorted(chs)))
    if key in _grammar_chapters_cache:
        gram = _grammar_chapters_cache[key]
        return [c for c in chs if c in gram]

    kw = {c for c in chs if any(m in c.lower() for m in _GRAMMAR_MARKERS)}
    unknown = [c for c in chs if c not in kw]
    llm: set = set()
    if unknown:
        titles = "\n".join(f"- {c}" for c in unknown)
        prompt = (
            f"These are chapter titles from a class {class_name} {subject} school textbook "
            "(titles may be in any language):\n"
            f"{titles}\n\n"
            "Which of these are GRAMMAR lessons — lessons that TEACH language structure "
            "(letters/sounds, spelling, joining/sandhi rules, word forms and classes, "
            "sentence structure; இலக்கணம் / व्याकरण) — as opposed to prose, poetry or "
            "supplementary-reader lessons?\n"
            "Reply with ONLY a JSON array of the exact titles that are grammar lessons, "
            'e.g. ["title1", "title2"]. Reply [] if none are.'
        )
        try:
            raw, _, _ = mantle_client.converse(
                model_id=mantle_client.VAL_MODEL, prompt=prompt,
                max_tokens=500, temperature=0.0,
            )
            m = re.search(r"\[.*\]", raw or "", re.DOTALL)
            if m:
                by_strip = {c.strip(): c for c in unknown}
                llm = {
                    by_strip[str(t).strip()]
                    for t in json.loads(m.group(0))
                    if isinstance(t, str) and str(t).strip() in by_strip
                }
        except Exception as e:
            print(f"[Grammar-Chapters] LLM classification failed: {e}")

    gram = kw | llm
    _grammar_chapters_cache[key] = gram
    print(f"[Grammar-Chapters] {class_name}/{subject}: "
          f"{sorted(gram) if gram else 'none identified'}")
    return [c for c in chs if c in gram]


def _route_grammar_chapters(is_grammar: bool, sec_chapters: list, grammar_chapters: list) -> list:
    """Grammar sections keep ONLY the grammar chapters; every other section drops them.
    Falls back to the incoming list whenever routing would leave the section empty
    (unidentified grammar lessons must not starve generation)."""
    gset = set(grammar_chapters or [])
    if not gset:
        return list(sec_chapters or [])
    if is_grammar:
        kept = [c for c in (sec_chapters or []) if c in gset]
    else:
        kept = [c for c in (sec_chapters or []) if c not in gset]
    return kept or list(sec_chapters or [])


def _slots_all_general(sec_data) -> bool:
    """True when EVERY question slot in a section says source='general' — the teacher
    demanded the questions NOT come from the textbook ("give in general, not from the
    text book"), so RAG retrieval and context injection are skipped for the section.
    Missing/empty source counts as NOT general, so legacy sections keep full RAG."""
    if not isinstance(sec_data, dict):
        return False
    slots = [s for s in (sec_data.get("question_slots") or []) if isinstance(s, dict)]
    return bool(slots) and all(
        str(s.get("source") or "").strip().lower() == "general" for s in slots
    )


def get_section_context_map(class_name: str, subject: str, chapters: list, blueprint: dict, question_types_all: list, school_id=None) -> dict:
    """Return {section_name: context_text} for every section in blueprint.

    C-01: reads per-section 'section_subject' from blueprint to route RAG queries
    to the correct sub-subject for compound papers (Science → Biology/Chemistry/Physics;
    Social Science → History/Geography/PolSci/Economics).

    3.2: Also builds per-type context slices stored in _context_by_type_{sec_name}.
    3.3: Runs context quality pre-check with retry on failure.
    """
    context_map: dict = {}
    context_by_type_map: dict = {}  # {sec_name: {type_key: ctx_str}}

    # Grammar routing (language papers): identify the grammar lessons once, only when the
    # paper actually has a grammar-named section — every other paper skips this entirely.
    grammar_chapters = (
        identify_grammar_chapters(class_name, subject, chapters)
        if _blueprint_has_grammar_section(blueprint) else []
    )

    for sec_name, sec_data in blueprint.items():
        # All-general sections (teacher: "not from the textbook") get NO context at all —
        # retrieval is skipped and the quality pre-check must not fight the empty result.
        if _slots_all_general(sec_data):
            print(f"[Section-Context] '{sec_name}': all slots source=general — skipping retrieval")
            context_map[sec_name] = ""
            context_by_type_map[sec_name] = {}
            continue
        sec_types = sec_data.get("question_types") or question_types_all
        section_subject = _resolve_section_subject(subject, sec_name, sec_data.get("section_subject", ""))
        effective_subject = section_subject or subject
        q_count = sec_data.get("questions_count") or sec_data.get("questions") or 0
        # Compound papers: retrieve context only for chapters belonging to this sub-subject.
        # Single-subject papers get the full list back unchanged (see _chapters_for_subject).
        sec_chapters = _chapters_for_subject(section_subject, subject, chapters)
        if sec_chapters != list(chapters or []):
            print(f"[Section-Chapters] '{sec_name}' ({effective_subject}): "
                  f"{len(sec_chapters)}/{len(chapters or [])} chapters → {sec_chapters}")
        # Grammar routing: grammar sections retrieve from grammar lessons only, the rest
        # exclude them (no-op when no grammar section / no grammar chapters identified).
        sec_is_grammar = _is_grammar_section(sec_name, sec_data.get("instructions"))
        routed = _route_grammar_chapters(sec_is_grammar, sec_chapters, grammar_chapters)
        if routed != sec_chapters:
            print(f"[Grammar-Route] '{sec_name}': "
                  f"{'grammar-only' if sec_is_grammar else 'grammar-excluded'} → {routed}")
            sec_chapters = routed
        hints = _query_hints_for_types(sec_types, effective_subject)
        if sec_is_grammar:
            # Steer similarity toward the rules/exercises pages of the grammar lessons.
            hints.insert(0, f"{effective_subject} grammar இலக்கணம் व्याकरण rules letters "
                            "word forms examples exercises")
        # Literature-extract sections need STORY/POEM text, not the chapter's grammar or
        # skill-box pages — steer retrieval toward narrative content first.
        _sec_slots = [sl for sl in (sec_data.get("question_slots") or []) if isinstance(sl, dict)]
        if any(str(sl.get("type") or "") == "extract" for sl in _sec_slots):
            hints.insert(0, f"{effective_subject} story prose poem narrative dialogue lines")
        ctx = get_section_context(class_name, effective_subject, sec_chapters, hints, school_id=school_id)

        # If subsection store is empty (e.g. 10_history not ingested), retry with parent subject
        if not ctx and effective_subject != subject:
            print(f"[Section-Context] '{sec_name}' subsection store empty, retrying with parent subject '{subject}'")
            hints = _query_hints_for_types(sec_types, subject)
            ctx = get_section_context(class_name, subject, sec_chapters, hints, school_id=school_id)

        # 3.3 — Context quality pre-check with fallback. Grammar sections keep their chapter
        # filter even on the broad retry — dropping it would reopen the literature leak the
        # routing above just closed.
        if not _validate_context_quality(ctx, sec_name, q_count, effective_subject, class_name, sec_types):
            print(f"[Context-QC] '{sec_name}': retrying with broader query"
                  f"{' (chapter filter kept: grammar section)' if sec_is_grammar else ' (no chapter filter)'}")
            broad_hints = [f"{effective_subject} {ch}" for ch in (sec_chapters or [])] + hints
            ctx_broad = get_section_context(class_name, effective_subject,
                                            sec_chapters if sec_is_grammar else [],
                                            broad_hints, school_id=school_id)
            if len(ctx_broad) > len(ctx):
                ctx = ctx_broad
                print(f"[Context-QC] '{sec_name}': broad retry improved to {len(ctx)} chars")

        # Extract-slot sections additionally get CONTINUOUS passage spans prepended: the
        # similarity-ordered chunks above hold no unbroken passage longer than ~170 words,
        # so a pattern's extract length (e.g. "approximately 500 words per passage") is
        # unquotable without them and the verbatim/continuity validators reject anything
        # longer that the model improvises.
        if any(str(sl.get("type") or "") == "extract" for sl in _sec_slots):
            _span_chars = _extract_span_chars(sec_data.get("extract_instruction"))
            # Kind-aware routing (ChapterInfo): one passage per PRINTED alternative (an
            # internal-choice extract slot prints two), each slot's kind honored — a
            # poetry-extract slot draws from poem chapters, prose from prose, and
            # unsignaled slots keep non-reserved chapters. Fail open throughout.
            _kind_needs = _extract_kind_needs(_sec_slots)
            _span_chapters = _chapters_for_extract_needs(
                class_name, effective_subject, sec_chapters, _kind_needs)
            spans = get_extract_spans(class_name, effective_subject, _span_chapters,
                                      school_id=school_id, span_chars=_span_chars,
                                      max_spans=max(3, min(6, len(_kind_needs) or 3)))
            # Poetry shortfall: when poem passages are demanded but no poem CHAPTER could
            # supply them (poems live inside prose chapters in most NCERT readers), hunt
            # verse-shaped chunks directly.
            _poem_short = (sum(1 for k in _kind_needs if k == "poem")
                           - sum(1 for sp in spans if sp.get("kind") == "poem"))
            if _poem_short > 0:
                spans += _verse_passages(class_name, effective_subject, sec_chapters,
                                         school_id, _poem_short,
                                         [sp["text"] for sp in spans])
            if spans:
                def _passage_label(i, sp):
                    kind_tag = f" — {sp['kind'].upper()}" if sp.get("kind") else ""
                    ch = sp.get("chapter") or ""
                    ch_tag = f" from chapter '{ch}'" if ch else ""
                    return (f"[CONTINUOUS PASSAGE {i}{kind_tag}{ch_tag} — one unbroken "
                            f"excerpt exactly as printed; quote each extract from inside "
                            f"a single block]\n{sp['text']}\n[END OF PASSAGE {i}]")
                block = "\n\n".join(_passage_label(i, sp) for i, sp in enumerate(spans, 1))
                rules = []
                if any(_kind_needs):
                    rules.append("EXTRACT KIND RULE — MANDATORY: a slot whose format/condition "
                                 "asks for a POETRY extract must quote ONLY from a passage "
                                 "marked POEM (both OR alternatives); a PROSE extract only from "
                                 "PROSE/SUPPLEMENTARY passages; a DRAMA extract only from DRAMA "
                                 "passages. Never quote the SAME passage in two different "
                                 "questions or alternatives.")
                if any(sp.get("kind") == "poem" for sp in spans):
                    rules.append("POEM FORMATTING — MANDATORY: when quoting a poem into "
                                 "source_text, copy its LINE BREAKS exactly as printed — one "
                                 "verse line per line (use \\n between lines). Never join "
                                 "verse lines into one running paragraph.")
                if rules:
                    block = "\n".join(rules) + "\n\n" + block
                ctx = f"{block}\n\n{ctx}"
                print(f"[Extract-Spans] '{sec_name}': +{len(spans)} contiguous spans "
                      f"(kinds {[sp.get('kind') or '?' for sp in spans]}, "
                      f"{len(block)} chars, target {_span_chars}/span)")

        context_map[sec_name] = ctx
        print(f"[Section-Context] '{sec_name}' (subject={effective_subject}): {len(ctx)} chars")

        # 3.2 — Build per-type context for this section
        type_ctx: dict = {}
        for type_key, profile in TYPE_CONTEXT_PROFILES.items():
            # Only build per-type context if this section has that type
            if any(type_key in _type_str(t) for t in sec_types):
                type_hints = [f"{effective_subject} {' '.join(profile['extra_hints'])}"] + hints[:2]
                tctx = get_section_context(
                    class_name, effective_subject, sec_chapters,
                    type_hints, max_chars=profile["max_chars"], school_id=school_id
                )
                if tctx:
                    type_ctx[type_key] = tctx
        context_by_type_map[sec_name] = type_ctx

    # Store per-type map on the returned dict using a sentinel key
    context_map["__context_by_type__"] = context_by_type_map
    return context_map


# ─────────────────────────────────────────────
# Work-order builder
# ─────────────────────────────────────────────

def _section_id_from_name(sec_name: str, idx: int = 0) -> str:
    """
    Derive a short section ID from its name.
    'Section A' → 'A', 'Part I' → 'I', otherwise fall back to 'A'/'B'/'C' by index.
    """
    parts = sec_name.split()
    # If last token is a single letter or Roman numeral, use it
    if len(parts) >= 2 and len(parts[-1]) <= 3 and parts[-1].isalpha():
        return parts[-1].upper()
    # Fall back to alphabetical by position
    return chr(65 + idx)   # A, B, C ...


def _qt_dicts_from_subsections(subsections: list, section_mpq: float) -> list:
    """Build per-type question dicts ({type, count, marks_each, range}) from a compound
    section's subsections.

    Compound CBSE sections (Science = Biology/Chemistry/Physics, each split into
    MCQ/AR/VSA/SA/CBQ/LA subsections) carry their REAL per-type marks only in
    ``subsections``. The section's own ``question_types`` is just a flat list of type
    names and its ``marks_per_question`` is the literal string "varies". Normalising the
    subsections into type dicts lets the rest of the pipeline (token budget, mixed-marks
    detection, the per-position prompt blueprint) treat it like any other mixed section
    instead of crashing on the "varies" string or undersizing the budget.

    AI-authored patterns also attach subsections that are pure TOPIC hints (a name and a
    question type — no count, no marks). Those carry nothing countable: synthesising a
    1-question entry per topic overrode the section's real questions_count (a 9-question
    Grammar section silently shrank to 8). When no subsection states a count or any marks
    figure, return [] so the section-level fields stay authoritative.
    """
    if not any(
        isinstance(ss, dict) and (
            _as_int(ss.get("questions_count") or ss.get("questions") or ss.get("count"), 0) > 0
            or _as_float(ss.get("marks"), 0.0) > 0
            or _as_float(ss.get("marks_per_question"), 0.0) > 0
        )
        for ss in (subsections or [])
    ):
        return []
    out, pos = [], 1
    for ss in subsections or []:
        if not isinstance(ss, dict):
            continue
        cnt = _as_int(ss.get("questions_count") or ss.get("questions") or ss.get("count"), 1) or 1
        ss_marks = _as_float(ss.get("marks"), 0.0)
        mke = _as_float(ss.get("marks_per_question"), 0.0) or (round(ss_marks / cnt, 2) if cnt else section_mpq)
        qts = ss.get("question_types")
        typ = (qts[0] if isinstance(qts, list) and qts else None) or ss.get("name") or "SA"
        rng = f"Q{pos}" if cnt == 1 else f"Q{pos}-{pos + cnt - 1}"
        out.append({"type": typ, "count": cnt, "marks_each": mke, "range": rng})
        pos += cnt
    return out


def _qt_dicts_from_slots(slots: list) -> list:
    """Typed {type, count, marks_each, range} dicts from a section's question_slots,
    grouping contiguous runs of the same (pipeline type, marks) in authored order.

    The dict `type` is the JSON type the GENERATOR will be asked to produce (not the
    authored slot type): slots with sub-parts generate as one CBQ with lettered
    sub_questions, extracts generate as source-based CBQ, and objective language
    formats (fill_blank / true_false / error_correction / ...) generate as VSA —
    so expected-count validation matches what the prompt demands."""
    _CAT_TYPE = {"mcq": "MCQ", "vsa": "VSA", "sa": "SA", "la": "LA", "cbq": "CBQ", "map": "Map work"}
    runs = []
    for s in slots or []:
        if not isinstance(s, dict):
            continue
        styp = str(s.get("type") or "")
        if styp == "ar":
            label = "Assertion-Reason MCQ"
        elif s.get("parts") or pattern_structure.slot_category(styp) == "cbq":
            label = "CBQ"
        else:
            label = _CAT_TYPE.get(pattern_structure.slot_category(styp), "SA")
        marks = _as_float(s.get("marks"), 0.0)
        qn = s.get("qnum")
        if runs and runs[-1]["type"] == label and abs(runs[-1]["marks_each"] - marks) <= 0.01:
            runs[-1]["count"] += 1
            runs[-1]["_end"] = qn
        else:
            runs.append({"type": label, "count": 1, "marks_each": marks, "_start": qn, "_end": qn})
    out = []
    for r in runs:
        rng = f"Q{r['_start']}" if r["_start"] == r["_end"] else f"Q{r['_start']}-{r['_end']}"
        out.append({"type": r["type"], "count": r["count"], "marks_each": r["marks_each"], "range": rng})
    return out


def _blueprint_counts(question_types) -> tuple:
    """Sum the explicit per-type (count, total_marks) of a *detailed* blueprint whose
    question_types are dicts like {"type": "MCQ", "count": 1, "marks_each": 5} — authored that
    way, or synthesised from subsections by _qt_dicts_from_subsections.

    When a section states its questions this way, the per-type counts/marks are the source of
    truth for how many questions it holds and what they are worth — far more reliable than the
    section-level 'questions_count'/'marks_per_question', which AI-authored patterns routinely
    fill in inconsistently (e.g. questions_count=10 for a section whose two typed entries
    describe just 2 questions). Returns (0, 0.0) when the types carry no explicit counts (e.g.
    plain-string types), so callers fall back to the section-level fields unchanged."""
    total_count = 0
    total_marks = 0.0
    for qt in (question_types or []):
        if isinstance(qt, dict) and ("count" in qt or "marks_each" in qt):
            c = _as_int(qt.get("count", 1), 1)
            total_count += c
            total_marks += c * _as_float(qt.get("marks_each", 0), 0.0)
    return total_count, total_marks


def _typical_marks_for_types(types_list) -> float:
    """Typical CBSE per-question marks for a section's question type(s) — used to derive a
    sensible question count when the pattern left marks_per_question / questions_count blank."""
    text = " ".join(_type_str(t) for t in (types_list or []))
    if "long answer" in text or text.strip() == "la":
        return 5.0
    if "very short" in text or "vsa" in text:
        return 2.0
    if "short answer" in text or text.strip() == "sa":
        return 3.0
    if "case" in text or "source" in text or "cbq" in text:
        return 4.0
    # MCQ / Assertion-Reason / objective / true-false / fill-in / 1-mark types
    return 1.0


def _allocate_chapters_to_slots(candidate_chapters: list, n_slots: int, subject: str, covered: dict) -> list:
    """Assign `n_slots` question slots to specific chapters.

    Score per chapter = weight / (1 + times already covered). Because an uncovered chapter
    scores its full weight, the allocator spreads across distinct chapters first (broad
    coverage), and only repeats a chapter once the higher-weight ones are each covered —
    so heavier (higher CBSE-marks) chapters get the repeats. `covered` is shared across the
    whole paper and mutated in place, so later sections fill the gaps earlier ones left.
    Deterministic: chapters are sorted and ties resolve to the alphabetically-first."""
    chs = sorted({c for c in (candidate_chapters or []) if c})
    if not chs or n_slots <= 0:
        return []
    weights = {c: max(1, _chapter_weight(subject, c)) for c in chs}
    plan = []
    for _ in range(int(n_slots)):
        best = max(chs, key=lambda c: (weights[c] / (1 + covered.get((subject, c), 0)), weights[c]))
        plan.append(best)
        covered[(subject, best)] = covered.get((subject, best), 0) + 1
    return plan


def plan_chapter_allocation(work_orders: list) -> list:
    """Give every section a per-question chapter plan (`wo.chapter_plan`), weighted by CBSE
    unit marks where known (uniform otherwise) and coordinated across the whole paper to
    maximise unique-chapter coverage before any chapter repeats. No-op for sections with no
    chapters (e.g. One-Mark tests) — they keep the legacy 'spread across all topics' prompt."""
    covered: dict = {}
    for wo in work_orders:
        eff_subject = wo.section_subject or wo.subject
        wo.chapter_plan = _allocate_chapters_to_slots(wo.chapters, wo.questions_count, eff_subject, covered)
    return work_orders


def build_work_orders(blueprint: dict, pattern, context_map: dict, difficulty: str, class_name: str, subject: str, chapters: list) -> list:
    pattern_section_map: dict = {}
    if pattern and hasattr(pattern, "sections") and pattern.sections:
        for ps in pattern.sections:
            if isinstance(ps, dict):
                pattern_section_map[ps.get("name", "")] = ps

    # 3.2: extract per-type context map stored under sentinel key
    context_by_type_all = context_map.get("__context_by_type__", {})

    # Grammar routing — same scoping the retrieval used (identify_grammar_chapters is
    # cached, so this repeat call costs nothing).
    grammar_chapters = (
        identify_grammar_chapters(class_name, subject, chapters)
        if _blueprint_has_grammar_section(blueprint) else []
    )

    work_orders = []
    for idx, (sec_name, sec_data) in enumerate(blueprint.items()):
        ps = pattern_section_map.get(sec_name, {})

        # Per-question structure (question_slots) — slots are the source of truth.
        # Derive the aggregates from them and feed the pipeline typed dicts built from
        # the slots, so the count/marks inference heuristics below never run against
        # inconsistent section-level fields. See docs/PER_QUESTION_STRUCTURE.md.
        slots = sec_data.get("question_slots") or ps.get("question_slots") or []
        slots = [s for s in slots if isinstance(s, dict)]
        if slots:
            holder = {"question_slots": slots}
            pattern_structure.normalize_slots([holder])
            pattern_structure.derive_aggregates_from_slots([holder])
            sec_data = dict(sec_data)
            sec_data["questions_count"] = holder.get("questions_count", len(slots))
            if holder.get("marks"):
                sec_data["marks"] = holder["marks"]
            sec_data.pop("marks_per_question", None)
            if holder.get("marks_per_question") is not None:
                sec_data["marks_per_question"] = holder["marks_per_question"]
            sec_data["question_types"] = _qt_dicts_from_slots(slots)
            sec_data.pop("subsections", None)   # slots supersede topic-hint subsections
        # Coerce ALL numeric section fields up front — pattern/blueprint data is authored by
        # the AI generator, the frontend, and CBSE seed scripts, so any of these may arrive as
        # strings ("30") or non-numeric sentinels ("varies"). Normalising here once guarantees
        # the entire downstream pipeline only ever sees numbers (the "varies" crash, and the
        # string-vs-int family of bugs, originate from skipping this).
        # Support both field names: blueprint uses 'questions_count', CBSE seed uses 'questions'
        q_count = _as_int(sec_data.get("questions_count") or sec_data.get("questions"), 0)
        marks = _as_int(sec_data.get("marks"), 0)
        mpq_raw = sec_data.get("marks_per_question")
        mpq = _as_float(mpq_raw, 0.0)
        if mpq <= 0 and isinstance(mpq_raw, (list, tuple)):
            # AI-authored patterns may write marks_per_question as a per-question LIST
            # ([1]×9). _as_float coerces that to 0 and the marks/count fallback below then
            # invents a fractional figure that gets printed on the paper (7 marks over 8
            # questions → "0.9 marks" per question). A uniform list IS the per-question
            # mark; a varied list is left for the subsection/typed breakdown to resolve.
            vals = [v for v in (_as_float(x, 0.0) for x in mpq_raw) if v > 0]
            if vals and all(abs(v - vals[0]) <= 0.01 for v in vals):
                mpq = vals[0]

        # Resolve the section's question type(s) FIRST — the per-type breakdown is what
        # reconciles the count/marks below, so it must exist before that step.
        # Compound sections express their real per-type marks in `subsections` (the
        # section's own question_types is a flat name list + marks_per_question="varies").
        # Normalise those subsections into {type,count,marks_each} dicts so the budget,
        # mixed-marks and prompt-blueprint paths all work instead of crashing/undersizing.
        types_list = sec_data.get("question_types") or []
        if not types_list:
            # Tolerate the singular 'question_type' field (saved by the generate-page form) —
            # without this the section carries no type, so the prompt/validator/enforcer impose
            # no type constraint and the model mixes types (e.g. MCQs in a Short-Answer section).
            single = sec_data.get("question_type") or ps.get("question_type")
            if single:
                types_list = [single] if isinstance(single, str) else list(single)
        subsecs = sec_data.get("subsections") or ps.get("subsections", [])
        if subsecs and not any(isinstance(t, dict) for t in types_list):
            synth = _qt_dicts_from_subsections(subsecs, mpq)
            if synth:
                types_list = synth
        is_map = any("map" in _type_str(t) for t in types_list)

        # A detailed blueprint expresses its questions as explicit per-type entries, e.g.
        #   [{"type":"MCQ","count":1,"marks_each":5}, {"type":"Letter","count":1,"marks_each":5}]
        # (authored that way, or synthesised from subsections just above). Those per-type
        # counts/marks are AUTHORITATIVE. The section-level questions_count / marks_per_question
        # that AI-authored patterns emit alongside them are frequently inconsistent — a
        # 2-question, 10-mark section arrived with questions_count=10 and marks_per_question=1,
        # so the generator requested 10×1m questions while the per-type validator demanded
        # EXACTLY MCQ×1+Letter×1 at 5m each. The section could never satisfy both, shipped
        # partial, and blew the paper's marks total (a 10-mark section rendered as 38m). Trust
        # the per-type breakdown for the count and marks whenever it is present.
        typed_count, typed_marks = _blueprint_counts(types_list)
        if typed_count > 0:
            q_count = typed_count
            if typed_marks > 0:
                marks = int(round(typed_marks))
                # 2 decimals, not 1: a pattern stating 2.25m/question must not drift to
                # 2.2 here — reconcile_uniform_marks stamps THIS value onto every
                # question and the paper audit then flags each one against the slots.
                mpq = round(typed_marks / typed_count, 2)

        # Derive any missing per-question marks / question count so a section NEVER asks for
        # 0 questions. AI-generated patterns sometimes leave questions_count/marks_per_question
        # null with only the section marks set (e.g. VSA 12m, SA 18m, LA 30m) — without this,
        # those sections generate nothing and come out empty.
        if mpq <= 0:
            mpq = round(marks / q_count, 2) if q_count else _typical_marks_for_types(types_list)
        if q_count <= 0:
            q_count = max(1, round(marks / mpq)) if (marks and mpq) else 1

        # Use the pattern section's explicit 'id' first, then blueprint's id, then derive from name
        section_id = (
            ps.get("id")
            or sec_data.get("id")
            or _section_id_from_name(sec_name, idx)
        )

        # C-01: sub-subject routing for compound papers (infer from section name when the
        # pattern didn't set section_subject — e.g. a "Biology" section of a Science paper).
        section_subject = _resolve_section_subject(subject, sec_name, sec_data.get("section_subject", ""))
        # Scope chapters to this section's sub-subject (compound papers only; single-subject
        # papers get the full list back unchanged — see _chapters_for_subject).
        section_chapters = _chapters_for_subject(section_subject, subject, chapters)
        # Grammar routing: grammar sections draw from the grammar lessons only, other
        # sections exclude them — this feeds chapter_plan and the prompt's chapter block.
        sec_is_grammar = _is_grammar_section(
            sec_name, sec_data.get("instructions") or ps.get("instructions"))
        section_chapters = _route_grammar_chapters(sec_is_grammar, section_chapters, grammar_chapters)

        # MO-01: attempt-N-of-M support — 'attempt' = students answer, 'count'/'provided' = questions generated
        # (coerced to int — these feed a division in the section marks-total check).
        attempt_count = _as_int(sec_data.get("attempt_count") or ps.get("attempt"), 0) or None
        # Base 'provided' on the reconciled q_count: the stale provided_count that the blueprint
        # converter mirrors from the (unreliable) section-level questions_count must not override
        # the per-type total resolved above.
        provided_count = q_count if typed_count > 0 else (_as_int(sec_data.get("provided_count"), 0) or q_count)
        if attempt_count and provided_count and attempt_count < provided_count:
            # Generate the larger 'provided' set; students pick from it
            generate_count = provided_count
        else:
            generate_count = q_count
            attempt_count = None
            provided_count = None

        # M-01: detect mixed-marks sections (compound sections have multiple marks values).
        # Read from the resolved types_list first — it is authoritative and carries per-type
        # marks synthesised from subsections. Only fall back to 'question_type_details' when
        # types_list has no per-type marks dicts, because standardize_pattern seeds an absent
        # question_types with a plain default (e.g. ["Short Answer"]); trusting that instead
        # would flag a genuinely mixed section as uniform, sending it down the path where every
        # question fails the "marks=X expected <avg>" check → partial section.
        qt_dicts = (
            types_list
            if any(isinstance(t, dict) and "marks_each" in t for t in types_list)
            else (sec_data.get("question_type_details") or types_list)
        )
        marks_values = {
            qt["marks_each"] for qt in qt_dicts
            if isinstance(qt, dict) and "marks_each" in qt
        }
        mixed_marks = len(marks_values) > 1

        # Belt-and-braces with get_section_context_map's retrieval skip: even a context
        # retrieved by an older map (or another caller) is withheld from an all-general
        # section, covering build_single_question_prompt's context_by_type fallback too.
        _all_general = bool(slots) and all(
            str(s.get("source") or "").strip().lower() == "general" for s in slots
        )

        wo = SectionWorkOrder(
            section_name=sec_name,
            section_id=section_id,
            title=sec_data.get("title", ""),
            marks=marks,
            questions_count=generate_count,
            marks_per_question=mpq,
            question_types=types_list,
            instructions=ps.get("instructions", sec_data.get("instructions", [])),
            constraints=ps.get("constraints", sec_data.get("constraints", {})),
            context_text="" if _all_general else context_map.get(sec_name, ""),
            difficulty=difficulty,
            subject=subject,
            class_name=class_name,
            chapters=section_chapters,
            section_subject=section_subject,
            provided_count=provided_count,
            attempt_count=attempt_count,
            is_map_work=is_map,
            mixed_marks=mixed_marks,
            passage_instruction=ps.get("passage_instruction"),
            extract_instruction=ps.get("extract_instruction"),
            subsections=[] if slots else subsecs,
            context_by_type={} if _all_general else context_by_type_all.get(sec_name, {}),  # 3.2
            slots=slots,
            is_grammar=sec_is_grammar,
        )
        work_orders.append(wo)
        subj_tag = f" [{section_subject}]" if section_subject else ""
        slot_tag = f", slots={len(slots)}" if slots else ""
        print(f"[WorkOrder] '{sec_name}'{subj_tag}: {generate_count}q × {mpq}m = {marks}m, types={types_list}{slot_tag}")

    # Deterministic, CBSE-weighted, paper-wide chapter allocation (sets wo.chapter_plan).
    plan_chapter_allocation(work_orders)
    for wo in work_orders:
        if wo.chapter_plan:
            from collections import Counter
            dist = ", ".join(f"{ch}×{n}" for ch, n in Counter(wo.chapter_plan).items())
            print(f"[ChapterPlan] '{wo.section_name}': {dist}")

    return work_orders


# ─────────────────────────────────────────────
# Cross-section validation (numbering)
# ─────────────────────────────────────────────

def cross_section_validate(paper_data: dict, blueprint: dict) -> dict:
    """Renumber questions sequentially and run cross-section deduplication."""
    # Renumber
    q_num = 1
    for sec_name in blueprint.keys():
        for q in paper_data.get(sec_name, {}).get("questions", []):
            q["qnum"] = q_num
            q_num += 1

    # Cross-section dedup (3.1) — code-only, no LLM cost
    # Collect (section, q_idx, text) tuples
    all_qs = []
    for sec_name, sec_data in paper_data.items():
        for q_idx, q in enumerate(sec_data.get("questions", [])):
            text = _comparable_text(q)
            if text:
                all_qs.append((sec_name, q_idx, q.get("qnum", 0), text))

    cross_dupes = []
    for i in range(len(all_qs)):
        for j in range(i + 1, len(all_qs)):
            sec_i, _, qnum_i, text_i = all_qs[i]
            sec_j, _, qnum_j, text_j = all_qs[j]
            if sec_i == sec_j:
                continue  # same section already handled by validate_uniqueness
            score = _concept_overlap(text_i, text_j)
            if score > 0.55:
                cross_dupes.append(
                    f"Q{qnum_i} ({sec_i}) ↔ Q{qnum_j} ({sec_j}) — {score:.0%} concept overlap"
                )

    if cross_dupes:
        print(f"[Cross-Section-Dedup] ⚠️  {len(cross_dupes)} cross-section duplicate(s):")
        for d in cross_dupes:
            print(f"  • {d}")
        # Store in each section for downstream use
        for sec_data in paper_data.values():
            sec_data.setdefault("_cross_section_duplicates", cross_dupes)
    else:
        print("[Cross-Section-Dedup] ✅ No cross-section concept overlaps detected")

    return paper_data


# ─────────────────────────────────────────────
# CBSE 50/20/30 competency distribution check
# ─────────────────────────────────────────────

def validate_competency_distribution(paper_data: dict) -> dict:
    """
    Check that generated paper meets CBSE CBQ Policy 2025-26:
    50% application, 20% recall, 30% constructed (±5% tolerance).
    Returns a summary dict with percentages and any policy violations.
    """
    totals = {"recall": 0.0, "application": 0.0, "constructed": 0.0, "untagged": 0.0}
    grand_total = 0.0

    for sec_data in paper_data.values():
        for q in sec_data.get("questions", []):
            marks = float(q.get("marks", 1))
            ctype = q.get("competency_type", "").strip().lower()
            grand_total += marks
            if ctype in totals:
                totals[ctype] += marks
            else:
                totals["untagged"] += marks

    if grand_total == 0:
        return {"error": "No questions found", "compliant": False}

    pcts = {k: round(v / grand_total * 100, 1) for k, v in totals.items()}
    violations = []
    if pcts["application"] < 45:
        violations.append(f"Competency (application) {pcts['application']}% < 45% CBSE minimum")
    if pcts["recall"] > 25:
        violations.append(f"Recall MCQ {pcts['recall']}% > 25% CBSE maximum")
    if pcts["constructed"] < 25:
        violations.append(f"Constructed response {pcts['constructed']}% < 25% CBSE minimum")
    if pcts["untagged"] > 10:
        violations.append(f"{pcts['untagged']}% of marks have no competency_type tag")

    result = {
        "total_marks": grand_total,
        "application_pct": pcts["application"],
        "recall_pct": pcts["recall"],
        "constructed_pct": pcts["constructed"],
        "untagged_pct": pcts["untagged"],
        "compliant": len(violations) == 0,
        "violations": violations,
    }
    if violations:
        print(f"[CompetencyCheck] ⚠️  CBSE 50/20/30 policy violations: {violations}")
    else:
        print(f"[CompetencyCheck] ✅ Compliant — app={pcts['application']}% recall={pcts['recall']}% constructed={pcts['constructed']}%")
    return result


def run_final_paper_audit(paper_data: dict, class_name: str, subject: str, difficulty: str) -> dict:
    """
    V10 — Final paper-level LLM audit (deepseek.v3.2, one call per paper).
    This is the master QC gate — aggregates all warning flags and makes a final
    holistic assessment of paper quality. Does NOT block generation but produces
    a comprehensive report stored on each section.

    Checks:
      - Overall paper quality score (1–10)
      - Worst offending questions (by _quality_flags, _mcq_answer_warnings, _grounding_issues)
      - Whether the paper is ready to issue to students as-is
      - Top 3 recommendations for improvement
    """
    # Aggregate all accumulated warnings into a single summary for the LLM
    all_warnings = []
    total_qs = 0
    for sec_name, sec_data in paper_data.items():
        qs = sec_data.get("questions", [])
        total_qs += len(qs)

        for w in sec_data.get("_uniqueness_warnings", []):
            all_warnings.append(f"[Uniqueness] {sec_name}: {w}")
        for w in sec_data.get("_mcq_answer_warnings", []):
            all_warnings.append(
                f"[MCQ-Answer] {sec_name} Q{w.get('qnum')}: stored='{w.get('stored')}' "
                f"but LLM says '{w.get('llm_answer')}' (conf={w.get('confidence')})"
            )
        for w in sec_data.get("_quality_flags", []):
            all_warnings.append(
                f"[Quality] {sec_name} Q{w.get('qnum')}: avg={w.get('avg_score')} — {w.get('issues','')}"
            )
        for w in sec_data.get("_grounding_issues", []):
            all_warnings.append(
                f"[Grounding] {sec_name} Q{w.get('qnum')}: {w.get('issue','')}"
            )
        for w in sec_data.get("_cbq_passage_issues", []):
            all_warnings.append(f"[CBQ-Passage] {sec_name}: {w}")
        for w in sec_data.get("_cross_section_duplicates", []):
            all_warnings.append(f"[CrossDup] {w}")

    warnings_block = (
        "\n".join(f"  • {w}" for w in all_warnings[:40])
        if all_warnings
        else "  None — all validation checks passed"
    )

    prompt = (
        f"You are the final reviewer for a CBSE Class {class_name} {subject} question paper.\n"
        f"Difficulty: {difficulty}. Total questions: {total_qs}.\n\n"
        f"VALIDATION WARNINGS ACCUMULATED DURING GENERATION:\n{warnings_block}\n\n"
        "Based on these warnings, provide a final paper quality assessment:\n"
        "1. Overall quality score (1–10, where 10 = exam-ready, no issues)\n"
        "2. Is this paper ready to issue to students as-is? (yes/no/needs-minor-fix)\n"
        "3. The 3 most important issues to fix before issuing (if any)\n"
        "4. A one-line verdict for the teacher\n\n"
        "Output JSON only:\n"
        '{"quality_score": 8, "ready_to_issue": "yes", '
        '"top_issues": ["issue 1", "issue 2", "issue 3"], '
        '"verdict": "Paper is ready with minor answer key concerns in Section B"}'
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL,
            prompt=prompt,
            max_tokens=512,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        result = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"[V10-FinalAudit] LLM call failed: {e}")
        return {"quality_score": None, "ready_to_issue": "unknown", "top_issues": [], "verdict": "Audit unavailable"}

    score = result.get("quality_score", "?")
    verdict = result.get("verdict", "")
    ready = result.get("ready_to_issue", "unknown")
    top_issues = result.get("top_issues", [])

    print(f"[V10-FinalAudit] Quality score: {score}/10 | ready={ready}")
    print(f"[V10-FinalAudit] Verdict: {verdict}")
    if top_issues:
        for issue in top_issues:
            print(f"[V10-FinalAudit]   • {issue}")

    return {
        "quality_score": score,
        "ready_to_issue": ready,
        "top_issues": top_issues,
        "verdict": verdict,
        "total_warnings": len(all_warnings),
    }


def run_cross_section_coherence_audit(paper_data: dict, class_name: str, subject: str, chapters: list) -> dict:
    """
    V8 — Cross-section coherence audit (one LLM call per paper).
    Checks:
      1. No chapter is over-represented (>50% of questions from single chapter).
      2. Difficulty arc is consistent (easy → hard progression across sections).
      3. Question type distribution matches CBSE blueprint expectations.
      4. No factual contradictions between sections.
    Returns {"coherent": bool, "issues": [...], "chapter_balance": {...}}.
    """
    # Build paper summary for LLM
    section_summaries = []
    for sec_name, sec_data in paper_data.items():
        qs = sec_data.get("questions", [])
        chapter_tags = [q.get("chapter_tag", "") for q in qs if q.get("chapter_tag")]
        types = [str(q.get("type", "?")) for q in qs]
        section_summaries.append(
            f"Section '{sec_name}' ({sec_data.get('marks', '?')}m): "
            f"{len(qs)} questions, types=[{', '.join(set(types))}], "
            f"chapters=[{', '.join(set(chapter_tags)) or 'not tagged'}]"
        )

    if not section_summaries:
        return {"coherent": True, "issues": [], "chapter_balance": {}}

    prompt = (
        f"You are auditing a CBSE Class {class_name} {subject} question paper.\n"
        f"Chapters covered: {', '.join(str(c) for c in chapters)}\n\n"
        "PAPER STRUCTURE:\n" + "\n".join(section_summaries) + "\n\n"
        "Check for:\n"
        "1. Chapter balance: Is any single chapter over-represented (>50% of questions)?\n"
        "2. Coverage: Are all requested chapters represented?\n"
        "3. Section progression: Do question types match what CBSE expects "
        "(MCQ in early sections, SA/LA in later sections)?\n"
        "4. Any obvious structural problems?\n\n"
        "Output JSON only:\n"
        '{"coherent": true, "issues": [], "chapter_balance": {"chapter_name": "15%"}, '
        '"missing_chapters": [], "recommendation": ""}'
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=512,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        result = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"[V8-Coherence] LLM call failed: {e}")
        return {"coherent": True, "issues": [], "chapter_balance": {}}

    issues = result.get("issues", [])
    if issues:
        print(f"[V8-Coherence] ⚠️  {len(issues)} coherence issue(s): {issues}")
        if result.get("recommendation"):
            print(f"[V8-Coherence] Recommendation: {result['recommendation']}")
    else:
        print("[V8-Coherence] ✅ Paper is coherent across sections")

    return {
        "coherent": result.get("coherent", True),
        "issues": issues,
        "chapter_balance": result.get("chapter_balance", {}),
        "missing_chapters": result.get("missing_chapters", []),
        "recommendation": result.get("recommendation", ""),
    }


def enforce_competency_distribution(paper_data: dict, class_name: str, subject: str) -> dict:
    """
    V7 — Bloom's Taxonomy Enforcement.
    If paper is non-compliant, asks the LLM to re-tag or replace questions to fix
    the competency balance. Strategy: relabel / replace individual questions in a
    single batched LLM call per offending section to avoid blowing the token budget.

    Rules enforced:
      - application ≥ 45 %  (relabel recall→application where semantically valid)
      - recall ≤ 25 %        (demote excess recall questions)
      - constructed ≥ 25 %   (SA/LA should always be constructed)
    """
    _VALID_TYPES = {"recall", "application", "constructed"}

    # 1. Audit
    def _audit(pd):
        totals = {"recall": 0.0, "application": 0.0, "constructed": 0.0}
        grand = 0.0
        for sec_data in pd.values():
            for q in sec_data.get("questions", []):
                marks = float(q.get("marks", 1))
                ct = q.get("competency_type", "").strip().lower()
                grand += marks
                totals[ct] = totals.get(ct, 0.0) + marks
        if grand == 0:
            return None, totals, 0.0
        pcts = {k: v / grand * 100 for k, v in totals.items()}
        return pcts, totals, grand

    pcts, totals, grand = _audit(paper_data)
    if pcts is None:
        return paper_data

    app_ok = pcts.get("application", 0) >= 45
    recall_ok = pcts.get("recall", 0) <= 25
    constr_ok = pcts.get("constructed", 0) >= 25

    if app_ok and recall_ok and constr_ok:
        print("[V7-Bloom] ✅ Competency already compliant — no action needed")
        return paper_data

    print(
        f"[V7-Bloom] Non-compliant — app={pcts.get('application',0):.1f}% "
        f"recall={pcts.get('recall',0):.1f}% constructed={pcts.get('constructed',0):.1f}%"
    )

    # 2. Collect all questions with their section key for relabelling
    candidates = []
    for sec_key, sec_data in paper_data.items():
        for q_idx, q in enumerate(sec_data.get("questions", [])):
            candidates.append((sec_key, q_idx, q))

    # Build a minimal list of (sec_key, q_idx, text, marks, current_type) for LLM
    q_lines = []
    for i, (sk, qi, q) in enumerate(candidates):
        q_lines.append(
            f"{i + 1}. [{q.get('competency_type','untagged')}] "
            f"({q.get('marks', 1)}m, type={q.get('type','?')}) "
            f"{str(q.get('text',''))[:120]}"
        )

    prompt = (
        f"You are auditing a CBSE Class {class_name} {subject} question paper.\n"
        "CBSE 2025-26 policy requires: application ≥ 45%, recall ≤ 25%, constructed ≥ 25% (by marks).\n\n"
        f"Current distribution: application={pcts.get('application',0):.1f}% "
        f"recall={pcts.get('recall',0):.1f}% constructed={pcts.get('constructed',0):.1f}%\n\n"
        "Questions (numbered, with current competency_type):\n"
        + "\n".join(q_lines)
        + "\n\nFor each question whose competency_type label is WRONG for that question style, "
        "output a correction. Only output questions that need changing. "
        "Rules: MCQ testing facts/definitions → recall. MCQ with case/data/scenario → application. "
        "SA/LA requiring explanation/analysis/evaluation → constructed. "
        "CBQ/Source-based → application. Map-based → application.\n\n"
        "Output JSON array only:\n"
        '[{"n": 1, "new_type": "application"}, ...]\n'
        "Do NOT change constructed→recall or constructed→application. "
        "Do NOT output questions that are already correct."
    )

    try:
        raw, in_tok, out_tok = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=1024,
            temperature=0.1,
        )
        raw = raw.strip()
        m = re.search(r"\[.*\]", raw, re.S)
        corrections = json.loads(m.group()) if m else []
    except Exception as e:
        print(f"[V7-Bloom] LLM call failed: {e} — skipping enforcement")
        return paper_data

    # 3. Apply corrections
    applied = 0
    for corr in corrections:
        n = corr.get("n")
        new_type = str(corr.get("new_type", "")).strip().lower()
        if not n or new_type not in _VALID_TYPES:
            continue
        idx = int(n) - 1
        if 0 <= idx < len(candidates):
            sk, qi, _ = candidates[idx]
            paper_data[sk]["questions"][qi]["competency_type"] = new_type
            applied += 1

    print(f"[V7-Bloom] Applied {applied} competency re-tag(s)")

    # 4. Re-audit and report
    pcts2, _, _ = _audit(paper_data)
    if pcts2:
        print(
            f"[V7-Bloom] After fix — app={pcts2.get('application',0):.1f}% "
            f"recall={pcts2.get('recall',0):.1f}% constructed={pcts2.get('constructed',0):.1f}%"
        )

    return paper_data


# ─────────────────────────────────────────────
# Main parallel generator
# ─────────────────────────────────────────────

def enforce_section_question_types(paper_data: dict, work_orders: list) -> dict:
    """Final safety net — guarantee no foreign question type renders in a section.

    The prompt directive + per-section validation already push hard for the right types, but a
    section that exhausts its retries still EMITS a partial result containing whatever it has
    (and the single-prompt fallback validates loosely). This pass removes any question whose
    COARSE type (MCQ / SA / VSA / LA / CBQ / MAP) isn't one the section declared — so an MCQ
    can never appear in a Short-Answer section, etc.

    Coarse categories are used deliberately so legitimate subtype variants are never dropped:
    assertion-reason (renders as MCQ), map-based (renders as SA), image/source CBQ. Questions
    whose type can't be classified ("other") are kept, not dropped. Drops are logged and
    recorded on `_dropped_wrong_type`; the marks/coverage audits then surface the shortfall."""
    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    for sec_name, sec_data in paper_data.items():
        wo = wo_by_name.get(sec_name)
        if not wo or not isinstance(sec_data, dict):
            continue
        allowed = set()
        for t in (wo.question_types or []):
            c = _type_category(t if isinstance(t, str) else str(t.get("type", "")))
            if c and c != "other":
                allowed.add(c)
        if not allowed:
            continue  # section type indeterminate — never drop blindly
        questions = sec_data.get("questions") or []
        kept, dropped = [], []
        for q in questions:
            if not isinstance(q, dict):
                continue
            q_subtype = str(q.get("subtype", "")).strip().lower()
            if q_subtype == "assertion_reason":
                cat = "mcq"   # AR renders as MCQ — treat it as such
            elif q_subtype == "map_based" or str(q.get("map_note", "")).strip():
                # Map questions are emitted as type "SA" per the schema — classifying them by
                # the coarse type stripped every valid map question from Map-Work sections
                # (allowed={la,map} / {map}), shipping them 1/2 and 0/3.
                cat = "map"
            else:
                cat = _type_category(str(q.get("type", "") or ""))
            if cat == "other" or cat in allowed:
                kept.append(q)
            else:
                dropped.append(q)
        if dropped:
            sec_data["questions"] = kept
            sec_data["_dropped_wrong_type"] = [{"qnum": q.get("qnum"), "type": q.get("type")} for q in dropped]
            want = "/".join(sorted(allowed)).upper()
            print(f"[Type-Enforce] '{sec_name}': removed {len(dropped)} foreign-type question(s) "
                  f"(section allows {want}): {[q.get('type') for q in dropped]}")
    return paper_data


def trim_overfull_sections(paper_data: dict, work_orders: list) -> dict:
    """Drop questions a section generated ABOVE its blueprint — the mirror of the [Refill]
    top-up. A section that returns MORE questions than its work order asked for (an extra SA in
    a mixed section, a 7th MCQ in a 6-MCQ block) inflates the paper's marks. The type enforcer
    only removes FOREIGN types, never excess of an ALLOWED one, and reconcile_uniform_marks only
    fixes per-question marks in uniform sections — so these extras survived and pushed section
    totals over (Biology 33/30, Physics 28/25). Trim per fine-category when the blueprint states
    explicit per-type counts, else trim the tail to the section's total count. Excess is dropped
    from the END, preserving the earlier (usually higher-quality, on-plan) questions.
    OR-alternatives live ON the question (not as separate list entries), so they are unaffected."""
    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        wo = wo_by_name.get(sec_name)
        if not wo:
            continue
        questions = [q for q in sec_data.get("questions", []) if isinstance(q, dict)]

        # Per-type caps from the blueprint (fine categories, matching validate_section_output).
        per_type_cap: dict = {}
        for qt in (wo.question_types or []):
            if isinstance(qt, dict) and ("count" in qt or "marks_each" in qt):
                cat = _fine_category(qt.get("type", ""))
                per_type_cap[cat] = per_type_cap.get(cat, 0) + _as_int(qt.get("count", 1), 1)

        # Attempt-N-of-M sections legitimately provide MORE than they budget marks for — cap at
        # the provided set, not the attempted count.
        total_cap = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count

        kept, dropped = [], []
        if per_type_cap:
            seen: dict = {}
            for q in questions:
                cat = _fine_category(q.get("type", ""), q.get("subtype", ""))
                cap = per_type_cap.get(cat)
                seen[cat] = seen.get(cat, 0) + 1
                if cap is not None and seen[cat] > cap:      # excess of a capped type only
                    dropped.append(q)
                else:
                    kept.append(q)
        elif total_cap and len(questions) > total_cap:
            kept, dropped = questions[:total_cap], questions[total_cap:]
        else:
            continue

        if dropped:
            sec_data["questions"] = kept
            sec_data.setdefault("_trimmed_overfull", []).extend(
                {"qnum": q.get("qnum"), "type": q.get("type")} for q in dropped)
            print(f"[Trim] '{sec_name}': removed {len(dropped)} over-count question(s) "
                  f"(kept {len(kept)}): {[q.get('type') for q in dropped]}")
    return paper_data


def generate_paper_parallel(blueprint: dict, pattern, context_map: dict, difficulty: str, class_name: str, subject: str, chapters: list):
    """
    Generate all sections in parallel using ThreadPoolExecutor.

    Returns (paper_data, total_input_tokens, total_output_tokens).
    Raises RuntimeError if ≥2 sections fail hard (caller falls back to single-prompt path).
    """
    work_orders = build_work_orders(blueprint, pattern, context_map, difficulty, class_name, subject, chapters)
    if not work_orders:
        raise RuntimeError("Blueprint produced no work orders")

    paper_data: dict = {}
    failed: list = []
    total_input_tokens = 0
    total_output_tokens = 0

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SECTIONS) as executor:
        futures = {executor.submit(generate_section, wo): wo for wo in work_orders}
        for future in as_completed(futures):
            wo = futures[future]
            try:
                sec_dict, in_tok, out_tok = future.result()
                paper_data.update(sec_dict)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
            except Exception as e:
                print(f"[Parallel-Gen] FAILED '{wo.section_name}': {e}")
                print(traceback.format_exc())
                failed.append(wo.section_name)

    # A section can fail in the parallel burst purely from endpoint contention — the biggest
    # section (e.g. a 30-question language section) starves while the other two stream and even
    # its TLS handshake times out, so its base call never returns and the whole section is
    # dropped (-30 marks, "Short Answer MISSING"). Give each failed section ONE more attempt
    # SERIALLY, where it has the endpoint to itself; even a truncated base result is enough for
    # the top-up path to fill it. Only runs on failure — the happy path is untouched.
    if failed:
        for wo in [w for w in work_orders if w.section_name in failed]:
            print(f"[Parallel-Gen] serial retry of failed section '{wo.section_name}'")
            try:
                sec_dict, in_tok, out_tok = generate_section(wo)
                paper_data.update(sec_dict)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                failed.remove(wo.section_name)
                print(f"[Parallel-Gen] ✅ serial retry recovered '{wo.section_name}'")
            except Exception as e:
                print(f"[Parallel-Gen] serial retry FAILED '{wo.section_name}': {e}")

    if len(failed) >= 2:
        raise RuntimeError(
            f"{len(failed)} sections failed ({', '.join(failed)}) — triggering single-prompt fallback"
        )
    if failed:
        print(f"[Parallel-Gen] ⚠️  {len(failed)} section(s) partial/failed: {failed}")

    # Final guarantee: strip any wrong-type questions before numbering/render (covers the
    # partial-emit path where a section shipped foreign types after exhausting retries).
    paper_data = enforce_section_question_types(paper_data, work_orders)

    # Symmetric to the [Refill] below: drop questions a section generated ABOVE its blueprint,
    # so an over-full section can't push the paper's marks over (e.g. Biology 33/30). Runs
    # before Refill so the two together converge each section on its exact per-type counts.
    paper_data = trim_overfull_sections(paper_data, work_orders)

    # Refill any section the type-enforcer (or post-validation dedup) left SHORT. These trims
    # run AFTER per-section validation passed, so the section never went 'partial' and was
    # never topped up — e.g. a 20-question Objective section that emitted 2 stray SA questions
    # ends up 18/20 silently. Top each short section back up to its work order's count.
    wo_by_name = {wo.section_name: wo for wo in work_orders}
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        wo = wo_by_name.get(sec_name)
        if not wo:
            continue
        expected = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
        if expected and len(sec_data.get("questions", [])) < expected:
            print(f"[Refill] '{sec_name}': {len(sec_data.get('questions', []))}/{expected} after enforce — topping up")
            tu_in, tu_out = _fill_short_section(sec_data, wo)
            total_input_tokens += tu_in
            total_output_tokens += tu_out

    # Deterministic marks fix: every question in a uniform-marks section must equal its
    # marks_per_question. Runs after top-up (so newly added questions are covered too) and
    # before the audit, killing the 'Section B: 9/10 marks (-1)' single-question drift.
    paper_data = reconcile_uniform_marks(paper_data, work_orders)

    paper_data = cross_section_validate(paper_data, blueprint)
    total_q = sum(len(v.get("questions", [])) for v in paper_data.values())
    print(f"[Parallel-Gen] ✅ {len(paper_data)} sections, {total_q} questions | in={total_input_tokens} out={total_output_tokens} tokens")

    competency_report = validate_competency_distribution(paper_data)
    if not competency_report.get("compliant", True):
        # V7 — attempt to fix competency distribution via targeted LLM relabelling
        paper_data = enforce_competency_distribution(paper_data, class_name, subject)
        # Re-run check to capture final distribution
        competency_report = validate_competency_distribution(paper_data)
    for sec_data in paper_data.values():
        sec_data["_competency_report"] = competency_report

    # V8 — Cross-section coherence audit (one LLM call for the full paper)
    coherence_report = run_cross_section_coherence_audit(
        paper_data, class_name, subject, chapters
    )
    for sec_data in paper_data.values():
        sec_data["_coherence_report"] = coherence_report

    # V10 — Final paper-level audit (master QC gate, deepseek.v3.2)
    final_audit = run_final_paper_audit(paper_data, class_name, subject, difficulty)
    for sec_data in paper_data.values():
        sec_data["_final_audit"] = final_audit

    # ── DEBUG: dump the fully-assembled question JSON for inspection ──────────────
    # Writes temp_questions.json (latest run) in the project root. Gitignored via temp_*.
    # Never let a dump error break generation.
    _dump_questions_debug(
        paper_data, class_name, subject, difficulty, chapters,
        total_input_tokens, total_output_tokens, final_audit, coherence_report,
    )

    return paper_data, total_input_tokens, total_output_tokens


def _dump_questions_debug(paper_data, class_name, subject, difficulty, chapters,
                          in_tok, out_tok, final_audit, coherence_report) -> None:
    """
    Write a human-readable JSON of every generated question + its validation flags to
    temp_questions.json (project root). Debug aid only — failures are swallowed.
    """
    try:
        debug_payload = {
            "meta": {
                "class": class_name,
                "subject": subject,
                "difficulty": difficulty,
                "chapters": list(chapters or []),
                "total_questions": sum(len(v.get("questions", [])) for v in paper_data.values()),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            },
            "sections": {
                sec: {
                    "title": data.get("title"),
                    "section_subject": data.get("section_subject", ""),
                    "marks": data.get("marks"),
                    "partial": data.get("_partial", False),
                    "errors": data.get("_errors", []),
                    "grounding_issues": data.get("_grounding_issues", []),
                    "quality_flags": data.get("_quality_flags", []),
                    "mcq_answer_warnings": data.get("_mcq_answer_warnings", []),
                    "mcq_answer_corrections": data.get("_mcq_answer_corrections", []),
                    "uniqueness_warnings": data.get("_uniqueness_warnings", []),
                    "questions": data.get("questions", []),
                }
                for sec, data in paper_data.items()
            },
            "coherence_report": coherence_report,
            "final_audit": final_audit,
        }
        with open("temp_questions.json", "w", encoding="utf-8") as f:
            json.dump(debug_payload, f, indent=2, ensure_ascii=False, default=str)
        print("[Debug] Question JSON written to temp_questions.json")
    except Exception as e:
        print(f"[Debug] Could not write temp_questions.json: {e}")
