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
import time
import traceback
import zlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field, replace as dc_replace
from typing import Optional

from . import embeddings, mantle_client, pattern_structure
from .data.cbse_patterns import UNIT_MARKS_WEIGHTS, UNIT_MARKS_WEIGHT_CLASSES
from .data.science_split import classify_chapter   # Science chapter → Physics/Chemistry/Biology

GEN_MODEL = mantle_client.GEN_MODEL   # deepseek.v3.2
MAX_PARALLEL_SECTIONS = 3
MAX_SECTION_RETRIES = 2


def _k(n) -> str:
    n = int(n or 0)
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class _StepLog:
    """Sequential numbering and per-pass cost for one paper's assembly, so the Celery log reads
    as a progress trace instead of an undifferentiated wall of validator output.

    Each step also becomes the mantle_client stage, so every '[Mantle]' line emitted inside it
    says which pass it belongs to without any call site passing a label.
    """

    def __init__(self, total: int, tag: str = "Pipeline"):
        self.i = 0
        self.total = total
        self.tag = tag
        self.t0 = time.time()

    @contextmanager
    def __call__(self, label: str, detail: str = ""):
        self.i += 1
        n = f"{self.i}/{self.total}"
        before = mantle_client.run_stats()
        t = time.time()
        print(f"[{self.tag}] {n} {label} — START{(' ' + detail) if detail else ''}")
        try:
            with mantle_client.stage(label):
                yield
        except Exception as e:
            print(f"[{self.tag}] {n} {label} — RAISED {type(e).__name__} after "
                  f"{time.time() - t:.1f}s: {e}")
            raise
        else:
            a = mantle_client.run_stats()
            calls = a["calls"] - before["calls"]
            cost = (f" | {calls} llm call(s) in={_k(a['in'] - before['in'])} "
                    f"out={_k(a['out'] - before['out'])}") if calls else " | no llm"
            print(f"[{self.tag}] {n} {label} — done {time.time() - t:.1f}s{cost}"
                  f" | elapsed {time.time() - self.t0:.0f}s")

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
    is_english_grammar: bool = False                     # holds English grammar questions — composed from the model's OWN grammar knowledge, never from retrieved context
    is_english_writing: bool = False                     # holds English composition tasks (article/letter/notice/advertisement…) — the student's own writing, never built on textbook content
    english_own_only: bool = False                       # the ENTIRE section is own-knowledge (grammar and/or writing) — no RAG context, no chapter assignment
    sums_count: int = 0                                  # Accountancy: how many of this section's questions MUST be numerical problems ("sums") — see plan_sums_allocation
    sums_share: float = 0.0                              # paper-wide sums MARKS share this section was planned against (0.0 = not a sums subject)
    disable_images: bool = False                         # superadmin cut AI image generation for this school — skip image_finder entirely
    own_count: int = 0                                   # source-mix meter: how many of this section's questions must be the model's OWN composition rather than drawn from the book (slot sections also carry own_question=True on the chosen slots) — see plan_creative_allocation


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


# Slot fields that say HOW a question is presented. "topic" is deliberately excluded: a topic of
# "Diagram of the human eye" says what the question is about, not that a picture is printed.
_SLOT_FORM_FIELDS = ("condition", "format")
# Wider than the section-level keywords below, because a slot condition names the form outright
# ("graph based question") where a section instruction may just be telling students to draw one.
_SLOT_IMAGE_WORDS = ("image", "picture", "diagram", "figure", "visual", "illustration", "graph")


def _slot_wants_image(slot) -> bool:
    """True when a question_slot asks for a picture-based question.

    Teachers set this per question — "One question must be picture based" against Q21 — so it
    arrives on ONE slot's "condition" (or "format"), never as a section-wide setting.
    """
    if not isinstance(slot, dict):
        return False
    blob = " ".join(str(slot.get(k) or "") for k in _SLOT_FORM_FIELDS).lower()
    return any(w in blob for w in _SLOT_IMAGE_WORDS)


def _image_slot_positions(wo: SectionWorkOrder) -> list:
    """1-based positions of the slots that asked for a picture, in slot order."""
    return [i for i, s in enumerate(wo.slots or [], start=1) if _slot_wants_image(s)]


def _needs_image(wo: SectionWorkOrder) -> bool:
    """Return True if this section takes pictures at all — a slot asked for one, or an
    instruction / the section name / the title mentions image-based questions.

    This gates the "image_prompt" field in the JSON schema the model is shown, so a section
    whose only picture request lives on a slot condition used to be given no way to attach the
    picture the teacher asked for.
    """
    if _image_slot_positions(wo):
        return True
    keywords = ("image", "picture", "diagram", "figure", "visual")
    for instr in wo.instructions:
        if any(k in instr.lower() for k in keywords):
            return True
    if any(k in (wo.section_name or "").lower() for k in keywords):
        return True
    if any(k in (wo.title or "").lower() for k in keywords):
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
    # Match questions generate under the VSA type, so the plain VSA example above would tell
    # the model to omit 'options' — and a match question needs the 4 pairing choices it is
    # answered with. Detected from the slots (the authored type survives there; the derived
    # question_types entry is just "VSA") so a matching slot always gets its own example.
    has_matching = any(
        isinstance(s, dict) and str(s.get("type") or "").strip().lower() == "matching"
        for s in (wo.slots or [])
    ) or any("match" in _type_str(t) for t in wo.question_types)

    # Helpers to get per-type marks from blueprint (falls back to section average)
    def _m(keyword: str, fallback: float = mpq) -> float:
        for qt in wo.question_types:
            if keyword in _type_str(qt):
                return _qt_marks(qt)
        return fallback

    def _matching_example(qn: int) -> str:
        """JSON example for one match question — a 4-pair table plus the 4 pairing options.
        Column II is scrambled and the key sits on (c) so the example doesn't bias the
        answer letter."""
        return (
            f'    {{\n'
            f'      "qnum": {qn}, "type": "VSA", "subtype": "matching",\n'
            f'      "text": "Match the following and choose the correct option:\\n'
            f'| Column I | Column II |\\n| --- | --- |\\n'
            f'| (A) First Column-I entry | (1) match for entry C |\\n'
            f'| (B) Second Column-I entry | (2) match for entry D |\\n'
            f'| (C) Third Column-I entry | (3) match for entry A |\\n'
            f'| (D) Fourth Column-I entry | (4) match for entry B |",\n'
            f'      "options": {{"a": "A-1, B-2, C-3, D-4", "b": "A-3, B-1, C-4, D-2", '
            f'"c": "A-3, B-4, C-1, D-2", "d": "A-4, B-3, C-2, D-1"}},\n'
            f'      "answer": "c",\n'
            f'      "answer_explanation": "A-3, B-4, C-1, D-2",\n'
            f'      "marks": {_m("match", _m("vsa", 1.0))}, "chapter_tag": "Chapter name", '
            f'"competency_type": "recall"\n'
            f'    }}'
        )

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
    is_mixed = sum([has_mcq or has_ar, has_cbq, has_la, has_sa, has_vsa, has_map_type,
                    has_matching]) > 1
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

        if has_matching:
            examples.append(_matching_example(qnum))
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

    # ── Pure match-the-following section ─────────────────────────────────────────
    # Without this the SA/VSA fallback below would show an example with no 'options',
    # and the match questions would ship without the 4 pairing choices.
    if has_matching:
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            f'{_matching_example(1)}\n'
            '  ]\n'
            '}\n'
            f'— EVERY match question needs at least {_MATCH_MIN_PAIRS} pairs, a SCRAMBLED '
            'Column II, and 4 different complete pairings in "options".'
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


# Tamil board-exam conventions (Samacheer Kalvi). Appended to the language directive ONLY for
# Tamil papers — added after a Tamil teacher's review flagged that generated papers ignored the
# standard grammar question-type stems, the "answer any N" internal choice, and the Thirukkural
# சீர் (foot) fill-in-the-blank format. Scoped to Tamil so Hindi/Sanskrit papers are unaffected.
_TAMIL_CONVENTIONS = (
    "\nTAMIL EXAM CONVENTIONS — MANDATORY (Samacheer Kalvi format):\n"
    "இலக்கணம் (grammar) questions MUST use the standard Tamil question-type stems, and where the "
    "spec gives the section an internal choice, list one extra item and word the choice in Tamil:\n"
    '- "பின்வரும் கோடிட்ட இடங்களை நிரப்புக" (fill in the blanks)\n'
    '- "இலக்கணக் குறிப்பு தருக" (give the grammatical note — பெயரெச்சம், வினையெச்சம், '
    "பண்புத்தொகை, வினையாலணையும் பெயர், etc.)\n"
    '- "சான்று தருக" (give a supporting citation — a real குறள் / பாடல் அடி)\n'
    '- "கூறியவாறு செய்க" or "பிழை திருத்துக" (do as directed / correct the error)\n'
    'Word an internal choice as "(எவையேனும் மூன்றனுக்கு மட்டும் விடையளிக்க)" — answer any 3 of the '
    "listed items — unless the per-question spec says otherwise.\n"
    "திருக்குறள் questions: when the spec calls for a Kural blank, use the heading "
    '"பின்வரும் கோடிட்ட இடங்களைத் திருக்குறள் சீர்களால் நிரப்புக". Quote a REAL, complete Thirukkural '
    "with exactly ONE சீர் (foot) blanked and give four options (a–d) that are all plausible Tamil "
    "feet. NEVER invent a Kural or a foot — use only authentic Kurals.\n"
    "செய்யுள் (verse) / உரைநடை (prose) sections: where the section offers an internal choice, word "
    'verse choices as "(எவையேனும் இரண்டனுக்கு விடை தருக)" (answer any 2) and prose choices as '
    '"(எவையேனும் மூன்றனுக்கு விடையளிக்க)" (answer any 3), matching the marks in the spec.\n'
)


def _language_directive(subject: str) -> str:
    """If the subject is a language paper (Hindi/Tamil/Sanskrit), return a MANDATORY block
    instructing the model to write the entire paper in that language/script. Empty otherwise.
    Tamil papers also get the Samacheer-Kalvi question-type conventions in _TAMIL_CONVENTIONS."""
    s = (subject or "").lower()
    for key, desc in _LANGUAGE_SUBJECTS.items():
        if key in s:
            block = (
                "LANGUAGE — MANDATORY (read FIRST):\n"
                f"This is a {desc} paper. Write the ENTIRE output — every question, all four "
                f"options, every passage, sub-question and answer_explanation — in {desc}. "
                "Do NOT write any question or option in English. Only the JSON keys "
                '("text", "options", "marks", "type", …) stay in English; every human-readable '
                "VALUE must be in the target language and script.\n"
            )
            if key == "tamil":
                block += _TAMIL_CONVENTIONS
            return block
    return ""


# ─────────────────────────────────────────────
# Self-contained questions
# ─────────────────────────────────────────────
#
# The reference material is the AUTHOR's source, not the student's. Papers came back asking
# "In Activity 6.2, what is one of the properties mentioned to group objects?" and "Which body
# part did Deepa suggest using to measure the length of the table?" — questions about the
# textbook's page furniture and about the children in its activity boxes. A student in an exam
# hall has neither, so those test whether they remember the PAGE, not whether they know the
# concept. Stated to the model here and enforced deterministically by _book_reference_hit.

SELF_CONTAINED_RULE = """
SELF-CONTAINED QUESTIONS — ABSOLUTE RULE (overrides every other instruction):
The student answers from this PAPER alone — no textbook, no notebook, no memory of a lesson.
The reference material is YOUR source for the concept; it is NOT in front of the student.
- NEVER point at the book's own furniture: "Activity 6.2", "Exercise 4.1", "Example 5.3",
  "Table 3.1", "Fig. 2.4", "in the chapter", "in the lesson", "your textbook", "as discussed in
  class". A question may refer to a passage or extract ONLY when it prints that passage itself
  in its own "source_text".
- NEVER ask what happened inside the book: what an Activity was for or what it listed, or what a
  child, teacher or character in one said, suggested, used, measured or found.
  WRONG: "In Activity 6.2, what is one of the properties mentioned to group objects?"
  WRONG: "Which body part did Deepa suggest using to measure the length of the table?"
  WRONG: "Activity 3.2 asks students to explore … What is the primary purpose of this activity?"
- Take the CONCEPT from the reference material and RESTATE it in the question.
  RIGHT: "Which of the following is a property used to group objects?"
  RIGHT: "Which of these is a non-standard unit of length?"
- Anything the question depends on — data, a situation, a passage, a diagram brief — must be
  written into the question itself.
"""


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
    # Picture-based questions are a QUOTA the teacher set per question, not a section-wide hint.
    # "One question must be picture based" used to reach the model only as the free-text tail
    # "| condition: picture based question": the JSON schema it was shown carried no
    # "image_prompt" field, nothing stated how many pictures the section takes, and nothing
    # checked the result. Papers came back with the picture on the wrong question, with none at
    # all, and with questions in sections that asked for none opening "He is shown a diagram
    # with labels…" — describing a picture that is never printed.
    _img_positions = _image_slot_positions(wo)
    # Dedicated CBQ sections are exempt: image_finder generates their image AFTER validation, so
    # an image_prompt here would fire a second, conflicting image pipeline.
    if _is_dedicated_cbq_section(wo):
        image_block = ""
    elif _img_positions:
        _pos_txt = ", ".join(f"Question {p}" for p in _img_positions)
        image_block = (
            f"\nPICTURE-BASED QUESTIONS — EXACTLY {len(_img_positions)} in this section:\n"
            f"- {_pos_txt} — and NO other question — must be picture-based.\n"
            "- Each of those MUST carry an \"image_prompt\": a self-contained visual description "
            "(20-40 words) an image model can render on its own, naming every object the "
            "question asks about. The image is printed directly ABOVE that question.\n"
            "- Its \"text\" must point at that picture ('Study the diagram above and answer:') "
            "and must be answerable FROM the picture.\n"
            "- EVERY OTHER question in this section must have NO \"image_prompt\" and must not "
            "mention a diagram, figure, picture, graph or photograph that it does not supply — "
            "nothing is printed above those questions, so the student would be answering about "
            "blank space. Asking the student to DRAW a diagram is fine.\n"
        )
    elif _needs_image(wo):
        image_block = (
            "\nIMAGE-BASED QUESTION RULE:\n"
            "- For any question that is image/diagram/picture based, add an \"image_prompt\" field.\n"
            "- The \"image_prompt\" value must be a self-contained visual description (20-40 words) that an AI image model can render.\n"
            "- The question \"text\" must reference the image (e.g. 'Study the diagram above and answer:'). The image is rendered ABOVE the question.\n"
            "- Only add \"image_prompt\" to the specific questions that need an image — not all questions.\n"
        )
    elif not wo.is_map_work:
        image_block = (
            "\nNO PICTURES IN THIS SECTION: no image is printed with any of these questions, so "
            "no question may point at a diagram, figure, picture, graph or photograph — no "
            "\"image_prompt\", no 'the diagram above', no 'he is shown a figure'. Describe the "
            "situation in words instead. Asking the student to DRAW or sketch is fine.\n"
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
    # An all-grammar / all-writing English section is in the same position as an all-general one:
    # nothing in it may come from the textbook, so it gets the same no-chapter-assignment
    # treatment. Kept separate from _all_general, which still governs the per-slot exemption
    # below (a slot-less section — legacy subsection blueprints — has no slots to mark general).
    _no_textbook = _all_general or wo.english_own_only

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
             if _no_textbook else
             "7. Questions MUST come from different chapters — no chapter monopoly.")
    diff_block = _difficulty_block(wo.difficulty)

    # C-01: use section-specific sub-subject when set (compound papers)
    effective_subject = wo.section_subject or wo.subject
    # A section that may draw on NO textbook content must not be handed the chapter list in its
    # spec either — naming the chapters re-invites exactly what its rules forbid.
    chapters_str = (
        "none — this section draws on no textbook chapter"
        if _no_textbook else
        (", ".join(wo.chapters) if wo.chapters else "all topics")
    )
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
    if _no_textbook:
        _own = [k for k, on in (("GRAMMAR", wo.is_english_grammar),
                                ("CREATIVE WRITING", wo.is_english_writing)) if on]
        _kind = (f"ENGLISH {' and '.join(_own)}, set from your own knowledge"
                 if (wo.english_own_only and _own) else "GENERAL KNOWLEDGE")
        _tag = ("Grammar" if _own == ["GRAMMAR"] else
                "Writing" if _own == ["CREATIVE WRITING"] else "General")
        chapter_block = (
            f"CHAPTER ASSIGNMENT: NONE — every question in this section is {_kind}.\n"
            "Do NOT draw questions from, reference, or name any textbook chapter, story or "
            "character. Write each question on its stated TOPIC at the class level and set "
            f'its "chapter_tag" to "{_tag}".'
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
    if wo.is_grammar and not _no_textbook:
        chapter_block += (
            "\nGRAMMAR SECTION — MANDATORY: this section tests GRAMMAR only. Every question "
            "must test a grammar concept (letters/sounds, spelling, joining/sandhi rules, "
            "word forms and classes, sentence structure) as taught in the grammar lessons "
            "listed above. Do NOT ask reading-comprehension or literature questions here — "
            "no story/poem content, characters, authors or poem lines."
        )
    # English grammar is composed from the model's OWN grammar knowledge — the reference
    # material is off-limits for it. Stated unconditionally, unlike the block above: an
    # all-grammar section arrives with _no_textbook already set, which is exactly the case that
    # needs this rule most. See the notes above english_own_slot_kinds for the why.
    if wo.is_english_grammar:
        _scope = ("Every question in this section is a grammar question."
                  if wo.english_own_only else
                  "This applies to every grammar question in this section — the ones marked "
                  "GENERAL KNOWLEDGE in the per-question specification.")
        chapter_block += (
            "\nENGLISH GRAMMAR — ABSOLUTE RULE (overrides every other instruction): "
            f"{_scope} A grammar question tests an ENGLISH GRAMMAR concept — tenses, voice, "
            "narration/reported speech, articles, prepositions, determiners, modals, "
            "subject-verb agreement, clauses and phrases, sentence transformation, gap "
            "filling, editing/omission, reordering, punctuation, parts of speech — and MUST be "
            "composed ENTIRELY from your own knowledge of English grammar.\n"
            "Take NOTHING from the REFERENCE MATERIAL for a grammar question: not a sentence, "
            "phrase, wording, name, character, place, event, chapter title or storyline. Write "
            "your OWN example sentences about everyday situations. Never ask a "
            "reading-comprehension or literature question here, and set every grammar "
            'question\'s "chapter_tag" to "Grammar".'
        )
    # Creative writing is the STUDENT's composition — the brief must stand on its own. A
    # generated section opened both options of its internal choice with "After reading 'The
    # Laburnum Top', you are inspired by…", hanging the article on a retrieved poem, which is
    # exactly what this forbids. Stated unconditionally, for the same reason as the block above.
    if wo.is_english_writing:
        _wscope = ("Every question in this section is a writing task."
                   if wo.english_own_only else
                   "This applies to every writing task in this section — the ones marked "
                   "GENERAL KNOWLEDGE in the per-question specification.")
        chapter_block += (
            "\nCREATIVE WRITING — ABSOLUTE RULE (overrides every other instruction): "
            f"{_wscope} Each one sets a SELF-CONTAINED, real-world brief in the stated format "
            "(article, formal or informal letter, letter to the editor, notice, classified or "
            "display advertisement, poster, speech, debate, report, story, diary entry, email, "
            "invitation, analytical or descriptive paragraph, précis, note-making) and MUST be "
            "composed ENTIRELY from your own knowledge.\n"
            "Take NOTHING from the REFERENCE MATERIAL: do NOT base the task on, quote, "
            "summarise or even MENTION a textbook chapter, story, poem, poet, author or "
            "character, and never open with \"After reading …\", \"Based on your reading of …\" "
            "or \"Inspired by the poem …\". The student must be able to write the answer "
            "without having read any textbook.\n"
            "Give the brief the everyday situation, role and details it needs — who the student "
            "is, what happened, the word limit — on topics from school life, the neighbourhood, "
            "the environment, health, technology, sport or current affairs. Where a question "
            "offers an internal choice, BOTH options must be independent briefs of this kind. "
            'Set every writing question\'s "chapter_tag" to "Writing".'
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

    # Accountancy composition: the paper is 80% sums by marks, and plan_sums_allocation has
    # already decided how many of THIS section's questions carry that. State the count, not the
    # paper-wide ratio — a section prompt cannot see the rest of the paper.
    sums_block = ""
    if wo.sums_share and wo.questions_count:
        _n, _k = wo.questions_count, max(0, min(wo.sums_count, wo.questions_count))
        if _k == _n:
            _split = f"ALL {_n} questions in this section MUST be SUMS."
        elif _k == 0:
            _split = (f"All {_n} questions in this section are QUIZ questions — no sums here.")
        else:
            _split = (f"EXACTLY {_k} of the {_n} questions in this section MUST be SUMS; "
                      f"the other {_n - _k} are QUIZ questions.")
        sums_block = (
            f"\n{effective_subject.upper()} COMPOSITION — MANDATORY:\n"
            f"This paper is {wo.sums_share:.0%} SUMS and {1 - wo.sums_share:.0%} QUIZ by marks. "
            f"{_split}\n"
            "A SUM supplies figures/transactions and asks the student to WORK SOMETHING OUT — "
            "journalise, pass entries, prepare (ledger / trial balance / Trading and Profit & "
            "Loss / Balance Sheet / Revaluation / Realisation / Partners' Capital or Current "
            "accounts / Cash Flow Statement), calculate, ascertain, distribute or apportion, "
            "value goodwill, or compute a ratio FROM GIVEN FIGURES. Every sum MUST print the "
            "actual amounts in ₹ (and the dates/names) the student needs — a sum with no "
            "figures is unanswerable.\n"
            "A QUIZ question tests a definition, concept, rule, principle, format name or "
            "reason, and needs no computation.\n"
            "Where a question is marked a SUM, do NOT substitute a theory question. This "
            "applies to MCQs too: a SUM in MCQ form gives the figures and makes all four "
            "options plausible computed amounts (e.g. \"₹4,000\", \"₹4,500\", \"₹5,000\", "
            "\"₹6,000\"), with the working stated in \"answer_explanation\"."
        )

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
        # Per-question source anchoring: slot i's chapter (from the weighted chapter plan) and
        # the ONE numbered excerpt of it this question must be written from. Empty for sections
        # that may use no textbook content at all — naming a chapter there re-invites exactly
        # what _no_textbook forbids.
        anchors = {} if _no_textbook else plan_slot_excerpts(wo)
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
            elif styp == "matching":
                json_type = '"type": "VSA", "subtype": "matching"'
            else:
                json_type = _cat_to_json.get(_type_category(styp), '"type": "SA"')
            label = pattern_structure.SLOT_TYPE_LABEL.get(styp, styp or "question")
            line = f"  Question {pos}: {label} — {json_type}, marks={s.get('marks')}"
            if styp == "matching":
                line += (
                    f' | MATCH THE FOLLOWING — EXACTLY {_MATCH_MIN_PAIRS} pairs, never fewer: '
                    '"text" is the stem "Match the following and choose the correct option:" '
                    'followed by the two columns as a Markdown table, NOT newline-stacked lists '
                    '— a header row "| Column I | Column II |", a separator "| --- | --- |", then '
                    'one pair per row like "| (A) item | (3) its match |", Column I labelled '
                    f'(A)…({chr(64 + _MATCH_MIN_PAIRS)}) and Column II labelled '
                    f'(1)…({_MATCH_MIN_PAIRS}) and SCRAMBLED so the pairing is not already in '
                    'order. This question is ANSWERED LIKE AN MCQ: "options" MUST be 4 DIFFERENT '
                    'complete pairings — {"a": "A-3, B-1, C-4, D-2", "b": "A-1, B-3, C-4, D-2", '
                    '"c": "A-3, B-4, C-1, D-2", "d": "A-2, B-4, C-1, D-3"} — with "answer" the '
                    'letter of the correct one and the same correct pairing in '
                    '"answer_explanation"'
                )
            # Set by apply_unit_map from the teacher's blueprint. The section-level chapter
            # block only states a DISTRIBUTION ("3 from Optics, 2 from Waves"), which is enough
            # for automatic allocation but cannot express "Q7 specifically must be Optics" —
            # this is what makes a blueprint's per-question assignment actually binding.
            if s.get("chapter"):
                line += f" | CHAPTER: draw this question from \"{s['chapter']}\" ONLY"
            elif pos - 1 in anchors:
                # Terse on purpose — the convention is spelled out once in anchor_note below
                # rather than re-explained on all 20 of a section's lines.
                _a_ch, _a_eid = anchors[pos - 1]
                line += f" | CHAPTER: \"{_a_ch}\" ONLY"
                if _a_eid:
                    line += f" | SOURCE EXCERPT: [E{_a_eid}]"
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
            if s.get("own_question"):
                line += (
                    " | OWN COMPOSITION — write this question YOURSELF: a fresh scenario, "
                    "context, data or example of your own. It must still test the chapter/topic "
                    "assigned above at this class level, but must NOT be copied, quoted or "
                    "reworded from the REFERENCE MATERIAL or from the textbook's own exercises"
                )
            if s.get("condition"):
                line += f" | condition: {s['condition']}"
            if _slot_wants_image(s):
                # The condition tail above is the teacher's own wording and reads as a hint;
                # this states what the JSON must actually contain.
                line += (
                    ' | PICTURE-BASED — this question MUST carry an "image_prompt" (a 20-40 '
                    "word description of the picture printed above it) and must be answerable "
                    "from that picture"
                )
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
        # Source-mix meter: the per-slot lines above already carry the rule, but the model
        # honours a stated COUNT far more reliably than N scattered flags — say the split once.
        own_note = ""
        _own_n = sum(1 for s in wo.slots if s.get("own_question"))
        if _own_n:
            own_note = (
                f"{_own_n} of these {len(wo.slots)} questions are marked OWN COMPOSITION — "
                "those must be original questions you write yourself on their assigned chapter, "
                "NOT taken from the reference material; every other question must stay grounded "
                "in it. "
            )
        # Per-question source anchoring: the slot lines carry the assignment, but the model
        # honours a stated CONVENTION far more reliably than a repeated inline flag — say once
        # what [E7] means and that reusing one excerpt for two questions is the failure being
        # prevented.
        anchor_note = ""
        if anchors:
            anchor_note = (
                'A line\'s CHAPTER is binding: that question comes from that chapter and no '
                'other, and its "chapter_tag" is that exact name. '
            )
        _anchor_ids = {eid for _ch, eid in anchors.values() if eid}
        if len(_anchor_ids) > 1:
            # State the FULL range the material carries, not just the ids this section was
            # given — a section that stops at [E9] must not read as if [E12] were spurious.
            _last = max([e for e, _c in _excerpt_index(wo.context_text or "")] or _anchor_ids)
            anchor_note += (
                f"The REFERENCE MATERIAL below is split into numbered excerpts [E1]…"
                f"[E{_last}]. A line's SOURCE EXCERPT is the material for THAT "
                "question: take the fact, term, example, figure or data it tests from that "
                "excerpt. Different questions are given different excerpts on purpose — do NOT "
                "write two questions off the same excerpt, and do not fall back on your own "
                "recollection of the chapter while its excerpt is in front of you. "
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
            '"sub_questions" array (each entry with "text" and "marks"). ' + anchor_note +
            general_note + own_note + no_passage_note +
            "Do NOT merge, split, reorder or renumber questions.\n"
        )

    # Slot-less sections (legacy subsection blueprints, One-Mark tests) have no per-question line
    # to hang the mix on, so it is stated against the section's count instead.
    if wo.own_count and not wo.slots:
        _book_n = max(0, generate_count - wo.own_count)
        chapter_block += (
            f"\nSOURCE MIX — MANDATORY: EXACTLY {wo.own_count} of these {generate_count} "
            "questions must be YOUR OWN composition — an original question you write yourself "
            "on its assigned chapter, built on a fresh scenario, context, data or example that "
            "does NOT appear in the reference material. The other "
            f"{_book_n} must be grounded in the reference material above. Never copy or lightly "
            "reword a question, example or exercise the reference material already contains."
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
{avoid_block}{diff_block}{sums_block}
{math_notation_block}
{ctx_label}:
---
{ctx}
---
{SELF_CONTAINED_RULE}
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


def _validate_matching(q: dict, n: int) -> list:
    """Match-the-following contract: a two-column table of at least _MATCH_MIN_PAIRS pairs,
    the 4 pairing options the question is answered with, a valid answer letter, and the
    correct pairing in 'answer_explanation'.

    Four pairs is the CBSE norm and the floor here — a 3-pair match cannot carry four
    distinct pairing choices, so it is not answerable as a 4-option question.
    """
    errs = []
    label = "VSA/matching"
    left, right = _match_table_labels(q.get("text", ""))
    if min(len(left), len(right)) < _MATCH_MIN_PAIRS:
        errs.append(
            f"Q{n} [{label}]: needs a two-column Markdown table of AT LEAST "
            f"{_MATCH_MIN_PAIRS} pairs — a header '| Column I | Column II |', a separator "
            "'| --- | --- |', then one pair per row like '| (A) item | (3) its match |' "
            f"(found {len(left)} labelled Column I / {len(right)} labelled Column II rows)."
        )
    elif len(left) != len(right):
        errs.append(
            f"Q{n} [{label}]: Column I has {len(left)} labelled entries but Column II has "
            f"{len(right)} — every table row must carry a label in BOTH columns."
        )

    raw = q.get("options")
    if isinstance(raw, dict):
        vals = {str(k).lower().strip(): str(v).strip() for k, v in raw.items()}
    elif isinstance(raw, list):
        vals = {"abcd"[i]: str(v).strip() for i, v in enumerate(raw) if i < 4}
    else:
        vals = {}
    filled = {k: v for k, v in vals.items() if v}
    if len(vals) != 4 or set(filled) != {"a", "b", "c", "d"}:
        errs.append(
            f"Q{n} [{label}]: must offer EXACTLY 4 options a/b/c/d, each a COMPLETE pairing "
            f'like "A-3, B-1, C-4, D-2" (found {len(filled)} non-empty of {len(vals)}).'
        )
    elif left:
        want = sorted(left)
        keys = {k: _parse_match_key(v) for k, v in sorted(filled.items())}
        bad = [k for k, m in keys.items() if sorted(m) != want]
        if bad:
            errs.append(
                f"Q{n} [{label}]: option(s) {', '.join(bad)} do not pair EVERY Column I "
                f"entry ({', '.join(want)}) — each option must read like "
                '"A-3, B-1, C-4, D-2".'
            )
        elif len({tuple(sorted(m.items())) for m in keys.values()}) != 4:
            errs.append(
                f"Q{n} [{label}]: the 4 options must be 4 DIFFERENT pairings — "
                "duplicated choices leave more than one correct answer."
            )

    ans = str(q.get("answer", "")).lower().strip()
    if ans not in {"a", "b", "c", "d"}:
        errs.append(
            f"Q{n} [{label}]: 'answer' must be the correct option letter a/b/c/d "
            f"(got {ans!r})."
        )
    if not str(q.get("answer_explanation", "")).strip():
        errs.append(
            f"Q{n} [{label}]: missing 'answer_explanation' — state the correct pairing "
            '("A-3, B-1, C-4, D-2").'
        )
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


# Boilerplate that a grammar question STEM and a textbook exercise page share word for word
# ("fill in the blanks with the correct form of the verb given in brackets"). A verbatim run
# made mostly of these words is a shared instruction, not copied material.
_STEM_WORDS = frozenset("""
a an the and or of to in on at for with from by as is are was were be been being do does did
have has had this that these those there their they them he she it his her its you your i we
our not no any all each one two three four five six following correct incorrect option options
answer answers question questions blank blanks fill choose complete rewrite change identify
underlined given brackets bracket sentence sentences word words form forms error errors below
above suitable appropriate most best use using make write put insert select match true false
verb verbs voice tense tenses passive active plural singular adjective adjectives adverb
adverbs noun nouns pronoun pronouns preposition prepositions article articles conjunction
clause clauses phrase phrases direct indirect reported speech correctly grammatically
sin cos tan cot sec cosec sinh cosh tanh log ln exp lim theta alpha beta pi degrees degree
radian radians interval solution solutions equation equations identity identities inequality
inequalities prove show solve find value values simplify evaluate hence graph graphically
where lies quadrant function functions period principal general
""".split())


def _lifted_span(src: str, ctx: str, span: int = 8, content_floor: int = 5):
    """First `span`-word run of `src` that appears verbatim in `ctx`, or None.

    Used to prove a question was NOT built out of the reference material. A run must carry at
    least `content_floor` words outside _STEM_WORDS to count, so a question stem that happens
    to match a textbook exercise heading ("fill in the blanks with the correct form of the
    verb") does not read as copied material — only real prose lifted from the chapter does.
    Both sides normalise to bare lowercase words first.
    """
    c = _norm_text(ctx)
    if not c:
        return None
    words = _norm_text(src).split()
    for i in range(len(words) - span + 1):
        run = words[i:i + span]
        if sum(1 for w in run if w not in _STEM_WORDS) < content_floor:
            continue
        joined = " ".join(run)
        if joined in c:
            return joined
    return None


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


def _student_visible_text(q: dict) -> str:
    """Everything the student reads on a question EXCEPT a printed passage: the stem, its options,
    its sub-questions and every internal-choice alternative. The passage is left out on purpose —
    a case-based question that prints its own source_text may legitimately point at it."""
    parts = [str(q.get("text", ""))]
    opts = q.get("options")
    if isinstance(opts, dict):
        parts.extend(str(v) for v in opts.values())
    alts = q.get("or_alternative")
    for alt in (alts if isinstance(alts, list) else [alts]):
        if isinstance(alt, str):
            parts.append(alt)
        elif isinstance(alt, dict):
            parts.append(str(alt.get("text", "")))
            parts.extend(str(sq.get("text", "")) for sq in (alt.get("sub_questions") or [])
                         if isinstance(sq, dict))
    parts.extend(str(sq.get("text", "")) for sq in (q.get("sub_questions") or [])
                 if isinstance(sq, dict))
    return " ".join(p for p in parts if p)


# Numbered references to the textbook's own furniture. Always wrong, because there is no book in
# the exam hall: "Activity 6.2" names something the student cannot see. The trailing unit guard
# keeps a measurement ("the figure 2.5 cm across") from reading as a figure number.
_BOOK_NUMBERED_RE = re.compile(
    r"\b(?:activity|activities|exercise|example|table|fig|figure|section|chapter|unit|lesson|"
    r"page|box)\s*\.?\s*(?:no\.?\s*)?\d+\s*\.\s*\d+"
    r"(?!\s*(?:cm|mm|km|kg|mg|ml|m|g|l|s|N|J|W|V|A|%)\b)"
    r"|\b(?:activity|exercise)\s+(?:no\.?\s*)?\d+\b",
    re.IGNORECASE,
)

# Pointers at the book itself. "the text" is deliberately absent — a case-based question that
# prints its own passage says "according to the text" quite legitimately. Naming a work is fine
# too ("in the chapter 'A Letter to God'"), so a quoted title straight after is exempt.
_BOOK_POINTER_RE = re.compile(
    r"\b(?:in|from)\s+(?:the|your|this)\s+(?:previous\s+|above\s+|given\s+)?"
    r"(?:chapter|lesson)\b"
    r"(?!\s*[\x27\x22\u201c\u2018]|\s+(?:titled|named|called)\b)"
    r"|\b(?:your|the)\s+(?:ncert\s+)?(?:textbook|text\s?book)\b|\byour\s+book\b"
    # "discussed in class", "the experiment we did in class" — the classroom is not on the
    # paper either. Guarded against "taught in Class 9", where "class" names a grade.
    r"|\b(?:discussed|taught|studied|demonstrated|performed|shown|done)\s+in\s+"
    r"(?:the\s+)?class(?:room)?\b(?!\s*(?:\d|[ivxIVX]+\b))"
    r"|\b(?:as|which\s+(?:is|was))\s+(?:mentioned|given|stated|discussed|described|"
    r"explained|shown|taught|studied)\s+(?:in|by)\s+(?:the|your)\s+"
    r"(?:chapter|lesson|textbook|text\s?book|book|class)\b"
    r"|\baccording\s+to\s+(?:the|your)\s+(?:chapter|lesson|textbook|text\s?book|book)\b"
    r"|\bas\s+(?:discussed|done|taught|studied)\s+in\s+(?:the\s+)?class(?:room)?\b",
    re.IGNORECASE,
)


def _book_reference_hit(text: str) -> str:
    """The offending phrase when a question points at the textbook instead of standing on its
    own, or "" when it is self-contained."""
    for rx in (_BOOK_NUMBERED_RE, _BOOK_POINTER_RE):
        m = rx.search(text or "")
        if m:
            return " ".join(m.group(0).split())
    return ""


# A question that points at a picture the paper never prints. The student sees blank space above
# it, so it is unanswerable — the same defect as pointing at the textbook, one page later. Only
# SUPPLIED visuals count: "Draw a labelled diagram of the human eye" asks the student to make
# one, which is legitimate and must never be flagged (see _DRAWN_BY_STUDENT_RE below).
_SUPPLIED_VISUAL_RE = re.compile(
    # Deictic verbs point at something the paper is expected to print, on their own.
    r"\b(?:study|observe|look\s+at|refer\s+to|examine|based\s+on|according\s+to)\s+"
    r"(?:the|this|that|these|those)\s+"
    r"(?:given\s+|above\s+|below\s+|following\s+|adjacent\s+|accompanying\s+|shown\s+)?"
    r"(?:diagram|figure|picture|image|illustration|graph|photograph|flow\s?chart)\b"
    # A bare "in/from the …" needs a positional word for the everyday nouns, which turn up in
    # ordinary scenarios ("In the picture she painted, the artist used only primary colours").
    r"|\b(?:in|from)\s+(?:the|this|that)\s+"
    r"(?:given|above|below|following|adjacent|accompanying|shown)\s+"
    r"(?:diagram|figure|picture|image|illustration|graph|photograph|flow\s?chart)\b"
    # …but the technical ones never appear in a narrative, so bare is enough.
    r"|\b(?:in|from)\s+(?:the|this|that)\s+(?:diagram|graph|flow\s?chart|illustration)\b"
    r"|\b(?:diagram|figure|picture|image|illustration|graph|photograph)\s+"
    r"(?:given\s+)?(?:above|below|alongside|shown|here)\b"
    r"|\bthe\s+(?:diagram|figure|picture|image|illustration|graph|photograph)\s+"
    r"(?:shows|depicts|represents|illustrates)\b"
    r"|\b(?:is|are|was|were)\s+shown\s+(?:a|an|the)\s+"
    r"(?:diagram|figure|picture|image|illustration|graph|photograph)\b",
    re.IGNORECASE,
)

# The student makes the drawing, so nothing has to be printed — always legitimate, and common
# enough ("Draw a neat labelled diagram of…", "With the help of a diagram, explain…") that one
# false positive here would cost real questions on every retry.
_DRAWN_BY_STUDENT_RE = re.compile(
    r"\b(?:draw|sketch|make|construct|plot|label)\b[^.]{0,60}"
    r"\b(?:diagram|figure|sketch|graph|circuit|structure)\b"
    r"|\bwith\s+(?:the\s+help\s+of\s+)?(?:a|an|the)?\s*"
    r"(?:neat|suitable|well[\s-]?labelled|well[\s-]?labeled|labelled|labeled|simple)?\s*"
    r"(?:diagram|figure|sketch|graph)\b",
    re.IGNORECASE,
)


def _supplied_visual_hit(text: str) -> str:
    """The phrase where a question points at a picture the paper will not print, or ""."""
    blob = text or ""
    if _DRAWN_BY_STUDENT_RE.search(blob):
        return ""
    m = _SUPPLIED_VISUAL_RE.search(blob)
    return " ".join(m.group(0).split()) if m else ""


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

    # The student sits the exam with this paper only, so a question that names an Activity,
    # an Exercise or "the chapter" is asking them to recall a page they do not have.
    _book_ref = _book_reference_hit(_student_visible_text(q))
    if _book_ref:
        errors.append(
            f"Q{n}: refers to the textbook itself (\"{_book_ref}\") — the student has no "
            "book in the exam. Ask about the CONCEPT and write everything the question "
            "needs into the question itself: no Activity/Exercise/Table/Figure numbers, no "
            "\"the chapter\", and never ask what a person in the book said, suggested or did"
        )

    # Picture-based questions are a quota the teacher set per question. The marked slot must
    # carry its picture; no other question may carry one or point at one, because nothing is
    # printed above it. Dedicated CBQ sections are skipped — their image arrives after validation.
    if not _is_dedicated_cbq_section(wo):
        _slot_wants_pic = bool(slot) and _slot_wants_image(slot)
        _has_pic = bool(str(q.get("image_prompt", "") or "").strip()) or bool(q.get("image_based"))
        if wo.slots:
            _pic_positions = _image_slot_positions(wo)
            if _slot_wants_pic and not _has_pic and not wo.disable_images:
                errors.append(
                    f"Q{n}: the pattern marks this question PICTURE-BASED — add an "
                    '"image_prompt" (a 20-40 word description of the picture to print above it) '
                    "and make the question answerable from that picture"
                )
            elif not _slot_wants_pic and _has_pic:
                _where = (
                    "only on " + ", ".join(f"Q{p}" for p in _pic_positions)
                    if _pic_positions else "on no question in this section"
                )
                errors.append(
                    f'Q{n}: remove "image_prompt" — the pattern asks for a picture {_where}, '
                    "not here"
                )
        # A question that gets no picture must not describe one. Map work is exempt (its map IS
        # printed), and so is a slot-less section the pattern calls image-based — there, any
        # question may be the illustrated one.
        _q_gets_picture = _slot_wants_pic or _has_pic or (not wo.slots and _needs_image(wo))
        _is_map_q = (wo.is_map_work or subtype == "map_based"
                     or (bool(slot) and "map" in str(slot.get("type") or "").lower()))
        if not _q_gets_picture and not _is_map_q:
            _vis = _supplied_visual_hit(_student_visible_text(q))
            if _vis:
                errors.append(
                    f'Q{n}: points at a picture that is not printed ("{_vis}") — no image is '
                    "rendered for this question, so the student would see blank space. Describe "
                    "the situation in words inside the question, or ask the student to DRAW it"
                )

    # General-knowledge slots must not reference textbook chapters: the teacher banned
    # textbook content outright, yet a chapter-assigned model happily writes "In the
    # story X from the chapter Y…". Deterministic name check across the visible text.
    # English grammar slots are forced to source='general' upstream, so they land here too.
    _is_general_slot = bool(slot) and str(slot.get("source") or "").strip().lower() == "general"
    if _is_general_slot or (wo.english_own_only and not wo.slots):
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
            # Word-boundary match: a short title ("Fire and Ice") must not be flagged out of an
            # unrelated grammar sentence, and a substring hit on a longer word is never a
            # chapter reference either.
            if len(chl) >= 4 and re.search(rf"\b{re.escape(chl)}\b", blob):
                errors.append(
                    f"Q{n}: this question is GENERAL KNOWLEDGE — it must not reference the "
                    f"textbook chapter '{ch}'; write an original question on the stated topic"
                )
                break

    # English grammar, third layer: an all-grammar section carries no context at all, but a
    # MIXED section keeps its context for the literature/comprehension slots — so a grammar
    # question there can still lift a line out of it. Reject any verbatim span. Scoped to the
    # general-marked slots (which is what every English grammar slot becomes upstream) — the
    # section's literature questions are SUPPOSED to quote the material.
    if (wo.is_english_grammar or wo.is_english_writing) and wo.context_text and _is_general_slot:
        _lifted = _lifted_span(text, wo.context_text)
        if _lifted:
            _what = "writing task" if wo.is_english_writing else "grammar question"
            errors.append(
                f"Q{n}: this {_what} copies the reference material (\"{_lifted}\") — English "
                f"{'writing briefs' if wo.is_english_writing else 'grammar questions'} must be "
                "composed from your own knowledge; write your own instead"
            )

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

    # ── Match the following ───────────────────────────────────────────────────────
    # Checked before the type branches: a match question generates under the VSA
    # category but is answered like an MCQ (4 pairing choices + an answer letter), so
    # neither the plain-VSA nor the MCQ contract describes it.
    is_matching = subtype == "matching" or (
        slot is not None and str(slot.get("type") or "").strip().lower() == "matching"
    )

    if is_matching:
        errors.extend(_validate_matching(q, n))

    elif is_mcq or is_ar_type:
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


# ── Canonical question-type keys ─────────────────────────────────────────────────────
# _type_str() deliberately returns the RAW lowercased label and MUST keep doing so.
# Two thirds of its ~30 call sites match SPACE-separated display text against it
# ("short answer", "very short", "long answer", "(sa)" — _output_schema, the NON_CBQ
# guard in _is_dedicated_cbq_section, _typical_marks_for_types), and two of them
# (build_section_prompt, _validate_context_quality) put its output straight into an LLM
# prompt as the section's type list. Normalising inside _type_str would rewrite those
# prompts and silently break those substring tests, so canonicalisation lives HERE and
# only the call sites that need a stable KEY — the retrieval query hints and the
# TYPE_CONTEXT_PROFILES routing — go through it.
#
# Matching is by whole TOKEN RUN, never bare substring, and rule order is load-bearing:
# the narrower type is tested first and every run it owns is erased from the label
# before the next rule looks at it. That is what keeps "Very Short Answer" from also
# answering to "sa" (the defect the old `type_key in _type_str(t)` gate had in reverse)
# while still letting a compound label like "MCQ / Assertion-Reason" report both halves.
_CANON_TYPE_RULES = (
    # (canonical key,  token runs it owns, longest first)
    ("assertion",      ("assertion reason", "assertion", "ar")),
    ("map_work",       ("map work", "map based", "map")),
    ("unseen_passage", ("unseen passage", "reading comprehension", "comprehension")),
    ("cbq",            ("case based", "case study", "cbq", "case")),
    ("source_based",   ("source based", "source")),
    ("vsa",            ("very short answer", "very short", "vsa")),
    ("la",             ("long answer", "long", "essay", "la")),
    ("sa",             ("short answer", "short", "sa")),
    ("mcq",            ("multiple choice", "objective", "mcq")),
    ("numerical",      ("numerical", "calculation")),
    ("match",          ("match the following", "matching", "match")),
    ("writing_tasks",  ("writing task", "writing")),
    ("true_false",     ("true or false", "true false")),
    ("fill_blanks",    ("fill in the blanks", "fill in the blank", "blanks")),
)


def _canon_type_keys(t) -> list:
    """Every canonical type key named by a question-type label, most specific first.

    'Very Short Answer', 'very_short_answer', 'VSA' and 'Very Short Answer (VSA)' all
    give ['vsa']; 'Case-Based' and 'case_based' both give ['cbq']; a compound
    'MCQ / Assertion-Reason' gives ['assertion', 'mcq']. Unrecognised labels give [].
    """
    s = " %s " % re.sub(r"[^a-z0-9]+", " ", _type_str(t)).strip()
    if not s.strip():
        return []
    keys = []
    for key, runs in _CANON_TYPE_RULES:
        matched = False
        for run in runs:
            pad = " %s " % run
            while pad in s:
                # Erase the run (keeping the delimiting spaces) so a later, broader rule
                # cannot re-read these words — "very short answer" must not also be "sa".
                s = s.replace(pad, "  ")
                matched = True
        if matched:
            keys.append(key)
    return keys


_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "to",
    "by", "for", "with", "which", "what", "how", "why", "and", "or", "but",
    "not", "be", "as", "at", "from", "this", "that", "it", "its", "has",
    "have", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "can", "if", "then", "than", "so", "very", "more", "also",
}


# ── Sums vs quiz classification (Accountancy) ────────────────────────────────────
# Deterministic, so it works on a paper the model never tagged and on one a teacher has since
# edited. A question counts as a SUM only when it BOTH asks for work to be done AND supplies
# the figures to do it with: "Prepare the format of a Balance Sheet" carries a preparation verb
# but no amounts, and is a format question, not a sum.

_SUMS_VERB_RE = re.compile(
    r"(?i)\b(?:journalis\w*|journaliz\w*|pass\s+the\s+(?:necessary\s+)?(?:journal\s+)?entr\w*|"
    r"prepar\w*|draw\s+up|calculat\w*|comput\w*|ascertain\w*|determine|find\s+(?:out\s+)?the|"
    r"work\s+out|distribut\w*|apportion\w*|allocat\w*|value\s+(?:the\s+)?goodwill|amortis\w*|"
    r"amortiz\w*|record\s+the|post\s+the|show\s+the|rectif\w*|close\s+the|transfer\s+the|"
    r"revalu\w*|realis\w*|realiz\w*|adjust\w*)\b"
)
# ₹1,20,000 / Rs. 50000 / 4,000 / 12.5% — evidence the question carries workable figures.
_AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)\s*[\d,]+|\b\d{1,3}(?:,\d{2,3})+\b|\b\d{3,}\b|\b\d+(?:\.\d+)?\s*%")


def _question_nature(q: dict) -> str:
    """'sums' when this question is a numerical/practical problem, else 'quiz'.

    Requires a computation verb AND workable figures, so a definition, a format question or a
    "state the formula" prompt all land in 'quiz'. Reads options, sub-questions and any passage
    too — an MCQ whose figures live in its options ("Calculate interest on capital: ₹4,000 …")
    is a sum in MCQ clothing and must count as one.
    """
    if not isinstance(q, dict):
        return "quiz"
    parts = [str(q.get("text", "")), str(q.get("source_text") or q.get("passage") or "")]
    opts = q.get("options")
    if isinstance(opts, dict):
        parts.extend(str(v) for v in opts.values())
    for sq in (q.get("sub_questions") or []):
        parts.append(str(sq.get("text", "")) if isinstance(sq, dict) else str(sq))
    oa = q.get("or_alternative")
    for entry in (oa if isinstance(oa, list) else [oa]):
        if isinstance(entry, dict):
            parts.append(str(entry.get("text", "")))
        elif isinstance(entry, str):
            parts.append(entry)
    blob = " ".join(p for p in parts if p)
    if _SUMS_VERB_RE.search(blob) and _AMOUNT_RE.search(blob):
        return "sums"
    return "quiz"


def _sums_marks_split(paper_data: dict) -> tuple:
    """(sums_marks, quiz_marks) across the whole paper, by _question_nature."""
    sums = quiz = 0.0
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        for q in sec_data.get("questions", []):
            m = _as_float(q.get("marks"), 0.0)
            if _question_nature(q) == "sums":
                sums += m
            else:
                quiz += m
    return sums, quiz


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
                stage="v5-semantic-dup",
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

        new_q, _, _ = _regen_replacement_question(
            updated_questions[replace_idx], replace_idx, wo, keep_text, tag="V5L2")
        if new_q:
            updated_questions[replace_idx] = new_q
            # Remove the now-resolved warning
            remaining_warnings = [w for w in remaining_warnings
                                  if f"Q{i+1} and Q{j+1}" not in w and f"Q{j+1} and Q{i+1}" not in w]

    return updated_questions, remaining_warnings


def _regen_replacement_question(orig_q: dict, idx: int, wo: SectionWorkOrder,
                                avoid_text: str = "", tag: str = "Regen",
                                extra_rule: str = "") -> tuple:
    """Regenerate ONE question to replace a bad one. Returns
    (new_question | None, in_tokens, out_tokens); None means keep the original.

    Shared by the within-section (V5L2) and cross-section duplicate fixers and the Accountancy
    sums enforcer, so all three carry the same guards: structurally heavy types are never
    regenerated, and a replacement that drifts type or fails validation is discarded. A flagged
    bad question beats a missing one — a type-drifted replacement is later stripped by
    enforce_section_question_types, silently shrinking the section below its required count.

    `avoid_text` names a concept the replacement must NOT repeat (duplicate fixers);
    `extra_rule` is an additional MANDATORY requirement on the replacement (sums enforcer).
    """
    orig_cat = _fine_category(orig_q.get("type", ""), str(orig_q.get("subtype", "")))
    if orig_cat in ("cbq", "map"):
        # Sub-questions / map locations — a single-shot regen can't reproduce them safely.
        print(f"[{tag}] Q{idx+1} is {orig_cat.upper()} — skipping regen, keeping original")
        return None, 0, 0

    marks = orig_q.get("marks", wo.marks_per_question)
    type_instr, skel = _regen_question_skeleton(orig_q, idx + 1, marks)
    ctx_block = (
        f"Context:\n{wo.context_text[:2500]}\n\n" if wo.context_text else
        "Compose the question from your own knowledge of the subject at this class level.\n\n"
    )
    avoid_block = (
        "IMPORTANT: The following concept is ALREADY covered — do NOT repeat it:\n"
        f"  ✗ {avoid_text}\n\n" if avoid_text else ""
    )
    regen_prompt = (
        f"Generate ONE CBSE Class {wo.class_name} {wo.subject} question.\n"
        f"{type_instr}\n"
        f"Marks: {marks}\n"
        f"Difficulty: {wo.difficulty}\n"
        f"Chapters: {', '.join(str(c) for c in wo.chapters)}\n\n"
        f"{avoid_block}"
        f"{(extra_rule + chr(10) + chr(10)) if extra_rule else ''}"
        f"{ctx_block}"
        "Output JSON only (single question object):\n"
        f"{skel}"
    )
    try:
        rraw, in_tok, out_tok = mantle_client.converse(
            model_id=GEN_MODEL, prompt=regen_prompt, max_tokens=500, temperature=0.85, stage="regen")
    except Exception as e:
        print(f"[{tag}] Regen call failed for Q{idx+1}: {e}")
        return None, 0, 0
    try:
        new_q = extract_single_question_json(rraw, idx, wo.marks_per_question)
        new_q.setdefault("subtype", orig_q.get("subtype", "standard"))
        new_q["qnum"] = orig_q.get("qnum", idx + 1)      # preserve numbering and marks
        new_q["marks"] = marks
        new_cat = _fine_category(new_q.get("type", ""), str(new_q.get("subtype", "")))
        regen_errs = _validate_by_subtype(new_q, idx + 1, wo)
        if new_cat != orig_cat or regen_errs:
            print(f"[{tag}] Q{idx+1} regen drifted ({orig_cat}→{new_cat}) or invalid "
                  f"({regen_errs[:1]}) — keeping original near-duplicate")
            return None, in_tok, out_tok
        print(f"[{tag}] Q{idx+1} replaced — chapter='{new_q.get('chapter_tag', '?')}'")
        return new_q, in_tok, out_tok
    except Exception as e:
        print(f"[{tag}] Regen parse failed for Q{idx+1}: {e}")
        return None, in_tok, out_tok


def run_content_quality_critic(questions: list, class_name: str, subject: str, difficulty: str) -> list:
    """
    V2 — Content Quality Critic.
    Sends all questions in a section to the validator LLM in one batch call.
    Returns list of {qnum, score, issues} for questions scoring below threshold.
    Scores: 1–5 (5 = excellent). Threshold: ≥3 required (warn below, don't block).

    Evaluates:
      - Self-contained: Can a student answer it with only this paper in front of them?
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
        "  - pedagogical_value (1=trivial recall, 5=tests deep understanding)\n"
        "  - self_contained (1=unanswerable without the textbook, 5=fully answerable from "
        "the paper alone)\n"
        "    A question scores 1-2 on self_contained if it names the book's own material "
        "(\"Activity 6.2\", \"Exercise 4.1\", \"Fig. 2.4\", \"the chapter\", \"the lesson\"), "
        "asks what happened inside an activity, or asks what a child/teacher/character in "
        "the book said, suggested, used, measured or found — e.g. \"Which body part did "
        "Deepa suggest using to measure the table?\". Naming a real scientist, author or "
        "historical figure is FINE; so is a question that describes its own scenario.\n\n"
        "Questions:\n" + "\n".join(q_lines) + "\n\n"
        "Output JSON array only:\n"
        '[{"q": 1, "clarity": 4, "ncert_alignment": 5, "difficulty_match": 3, '
        '"pedagogical_value": 4, "self_contained": 5, '
        '"issues": "optional note if any score < 3"}, ...]\n'
        "Include ALL questions in the output."
    )

    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.1,
            stage="v2-critic",
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
        # Scored on its own rather than folded into the average: a question that cannot be
        # answered without the textbook is unusable however clear and well-pitched it is,
        # and (5,5,5,5,1) averages to a comfortable 4.2.
        self_contained = _as_float(r.get("self_contained", 5), 5.0)
        if avg < 3.0 or self_contained <= 2:
            flagged.append({
                "qnum": _as_int(r.get("q"), 0),
                "avg_score": round(avg, 1),
                "scores": {
                    "clarity": r.get("clarity"),
                    "ncert_alignment": r.get("ncert_alignment"),
                    "difficulty_match": r.get("difficulty_match"),
                    "pedagogical_value": r.get("pedagogical_value"),
                    "self_contained": r.get("self_contained"),
                },
                "issues": r.get("issues", ""),
            })
            print(
                f"[V2-Critic] ⚠️  Q{r.get('q')}: avg={avg:.1f}"
                + (f" self-contained={self_contained:.0f}" if self_contained <= 2 else "")
                + f" — {r.get('issues', '')}"
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
                model_id=mantle_client.VAL_MODEL, prompt=prompt, max_tokens=300, temperature=0.1, stage="v4-mcq-verify")
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


# ─────────────────────────────────────────────
# MCQ answer-key balancing (deterministic, no LLM)
# ─────────────────────────────────────────────
# Teachers reported answer keys with a visible shape — "aaabbbccc", or every answer (a). The
# prompt has always asked for a spread (STRICT RULE 6) and validate_section_output rejects a
# letter used in >65% of a section's MCQs, but neither catches a RUN pattern: "aaabbbccc" puts
# each letter at 33%, so it sails through, and rule 6's "never more than 2 consecutive" was
# never enforced anywhere. A patterned key is a real exam-integrity defect — a student who
# spots it scores without reading the questions.
#
# Asking the model again does not fix this reliably, so the key is fixed deterministically
# AFTER generation instead: permute each MCQ's option VALUES so its correct answer lands on a
# letter drawn from a balanced, run-free, paper-specific target sequence. An MCQ's options are
# an unordered set, so this changes nothing a student is being tested on.
#
# No RNG — the shuffle is seeded from the paper's own text (same reasoning as
# _match_option_set: a regenerated paper must come out identical), while still differing from
# paper to paper so two classes don't share an answer pattern.

_LETTERS4 = ("a", "b", "c", "d")

# Option wording that makes the option SET order-dependent — permuting these breaks the
# question ("All of the above" must stay last; "Both (a) and (b)" names its own siblings).
_ORDER_BOUND_OPTION_MARKERS = (
    "of the above", "of these", "all the above", "none the above",
    "both a", "both (a", "both b", "both (b", "a and b", "(a) and", "(b) and",
    "(i) and", "and (ii", "only a", "only (a", "only b", "only (b",
    "either", "neither", "above statements", "both statements",
)

# Letter references inside an answer_explanation ("option (b)", "Option C", "answer: d").
_ANS_LETTER_REF_RE = re.compile(
    r"(?i)option\s*\(?([a-d])\)?|\(([a-d])\)|(?:answer|correct)\s*(?:is\s*|:\s*)\(?([a-d])\)?"
)

# An option value that IS a bare letter or article makes a "(a)" in the explanation ambiguous —
# it may be the ANSWER TEXT rather than an option reference — so the letter remap cannot be
# trusted. Chiefly an articles MCQ: options "a" / "an" / "the" / "no article".
_LETTERISH_OPTION_VALUES = frozenset(
    ("a", "an", "the", "b", "c", "d", "i", "ii", "iii", "iv", "no article", "none", "no change")
)

# A value that is essentially JUST a number, optionally with a unit or currency symbol
# ("2", "4.5", "6 cm", "₹250", "30%", "100 m/s"). Deliberately tight: an option like
# "Statement 3 of the passage" is prose, not a numeric choice.
_NUMERIC_OPTION_RE = re.compile(
    r"[₹$€]?\s*(-?\d+(?:\.\d+)?)\s*(?:%|°[CF]?|[²³]|[a-zA-Zµ°Ω]{1,6}(?:/[a-zA-Z]{1,4})?)?"
)


def _seeded_shuffle(items: list, seed: int) -> list:
    """Fisher-Yates driven by splitmix32 — deterministic for a given seed, and no `random`
    module (which would make a regenerated paper come out different).

    splitmix32 rather than a plain LCG: an LCG's low bits are barely random, and `state % n`
    reads exactly those bits — the first version of this produced "cdabcdab", i.e. it swapped
    one visible pattern for another. splitmix32 avalanches, so the low bits are usable.
    """
    out = list(items)
    state = (seed or 1) & 0xFFFFFFFF
    for i in range(len(out) - 1, 0, -1):
        state = (state + 0x9E3779B9) & 0xFFFFFFFF
        z = state
        z = ((z ^ (z >> 16)) * 0x21F0AAAD) & 0xFFFFFFFF
        z = ((z ^ (z >> 15)) * 0x735A2D97) & 0xFFFFFFFF
        z ^= z >> 15
        j = z % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def _repeats_a_block(seq: list) -> bool:
    """True when the sequence is just one block repeated ("abab", "dbacdbac", "aaaa")."""
    n = len(seq)
    for blk in range(1, n // 2 + 1):
        if n % blk == 0 and seq == seq[:blk] * (n // blk):
            return True
    return False


def _repair_runs(seq: list) -> list:
    """Break every run of 3+ identical letters by swapping the offender with a later letter
    that differs from both of its new neighbours. Bounded, and leaves the counts untouched."""
    for i in range(2, len(seq)):
        if seq[i] != seq[i - 1] or seq[i] != seq[i - 2]:
            continue
        for j in range(i + 1, len(seq)):
            if seq[j] == seq[i]:
                continue
            if seq[j] != seq[i - 1] and (j + 1 >= len(seq) or seq[j + 1] != seq[i]):
                seq[i], seq[j] = seq[j], seq[i]
                break
    return seq


def _balanced_answer_letters(n: int, seed: int) -> list:
    """`n` answer letters: equal counts of a/b/c/d (±1), shuffled, no run longer than 2, and
    not a repeated block.

    Equal counts alone are not enough — "aaabbbccc" is perfectly balanced and still an obvious
    pattern — so the multiset is shuffled and run-repaired. A rotation ("abcdabcd") is equally
    a pattern, and an honest shuffle still lands on one about 1% of the time at n=8, so a
    sequence that repeats a block is rejected and reseeded. Deterministic throughout: the same
    paper always produces the same sequence.
    """
    if n <= 0:
        return []
    pool = [_LETTERS4[i % 4] for i in range(n)]          # equal counts, ±1
    seq = _repair_runs(_seeded_shuffle(pool, seed))
    attempt = 0
    while _repeats_a_block(seq) and attempt < 8 and n > 2:
        attempt += 1
        seq = _repair_runs(_seeded_shuffle(pool, (seed + attempt * 0x9E3779B1) & 0xFFFFFFFF))
    return seq


def _mcq_is_permutable(q: dict) -> bool:
    """True when this MCQ's four options may be reordered safely.

    Excluded, because reordering would change or break the question:
      - Assertion-Reason — CBSE prints its four options in one canonical order;
      - matching — _match_option_set already rotates which letter holds the key;
      - order-bound wording ("All of the above", "Both (a) and (b)");
      - an already-sorted numeric set (2/4/6/8), where ascending order is the convention;
      - letter-ish option VALUES ("a", "an", "the") — an articles question, where a "(a)" in
        the explanation may be the ANSWER TEXT rather than an option reference, so the letter
        remap cannot be trusted.
    """
    opts = q.get("options")
    if not isinstance(opts, dict) or set(opts) != set(_LETTERS4):
        return False
    vals = [str(opts[k]).strip() for k in _LETTERS4]
    if not all(vals) or len(set(vals)) != 4:
        return False
    if str(q.get("answer", "")).lower().strip() not in _LETTERS4:
        return False
    subtype = str(q.get("subtype", "")).strip().lower()
    if subtype in ("assertion_reason", "matching"):
        return False
    if "assertion" in _type_str(q.get("type", "")):
        return False
    if any(v.strip("'\"() ").lower() in _LETTERISH_OPTION_VALUES for v in vals):
        return False
    low = " ".join(vals).lower()
    if any(m in low for m in _ORDER_BOUND_OPTION_MARKERS):
        return False
    nums = [float(m.group(1))
            for m in (_NUMERIC_OPTION_RE.fullmatch(v) for v in vals) if m]
    if len(nums) == 4 and (nums == sorted(nums) or nums == sorted(nums, reverse=True)):
        return False
    return True


def _remap_answer_letters(text: str, mapping: dict) -> str:
    """Rewrite option-letter references in an explanation through `mapping` (old→new).

    re.sub scans left to right and never re-examines what it wrote, so an a↔b swap cannot
    double-remap. Only the letter character is replaced; surrounding wording and case are
    left exactly as the model wrote them.
    """
    if not text:
        return text

    def _sub(m):
        s = m.group(0)
        old = next((g for g in m.groups() if g), "").lower()
        new = mapping.get(old, old)
        if not old or new == old:
            return s
        i = s.lower().rfind(old)
        return s[:i] + (new.upper() if s[i].isupper() else new) + s[i + 1:]

    return _ANS_LETTER_REF_RE.sub(_sub, str(text))


def balance_mcq_answer_keys(paper_data: dict) -> dict:
    """Spread MCQ correct answers over a/b/c/d with no run longer than 2, paper-wide.

    Permutes each eligible MCQ's option values so its answer sits on a target letter, updates
    "answer", and remaps letter references in "answer_explanation". Deterministic and
    LLM-free. Questions _mcq_is_permutable rejects are left exactly as generated, so their
    letters still count toward the sequence the eligible ones are fitted around.
    """
    eligible, fixed = [], []
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        for q in sec_data.get("questions", []):
            if not isinstance(q, dict) or not isinstance(q.get("options"), dict):
                continue
            (eligible if _mcq_is_permutable(q) else fixed).append(q)
    if len(eligible) < 3:
        return paper_data          # too few to carry a pattern worth rewriting

    # Seed from the paper's own question text: stable across regenerations of the same paper,
    # different for a different paper, so two classes never share an answer pattern.
    seed = zlib.crc32(" ".join(
        str(q.get("text", ""))[:120] for q in (eligible + fixed)
    ).encode("utf-8", "ignore"))

    before = "".join(str(q.get("answer", "?")).lower().strip()[:1] for q in eligible)
    targets = _balanced_answer_letters(len(eligible), seed)

    moved = 0
    for q, target in zip(eligible, targets):
        opts = q["options"]
        cur = str(q["answer"]).lower().strip()
        if cur == target:
            continue
        correct_val = opts[cur]
        others = [opts[k] for k in _LETTERS4 if k != cur]
        new_opts, mapping, it = {}, {}, iter(others)
        for letter in _LETTERS4:
            if letter == target:
                new_opts[letter] = correct_val
                mapping[cur] = letter
            else:
                new_opts[letter] = next(it)
        # mapping for the three distractors, derived from where each value ended up
        old_of = {v: k for k, v in opts.items()}
        for letter, val in new_opts.items():
            mapping.setdefault(old_of.get(val, letter), letter)
        q["options"] = new_opts
        q["answer"] = target
        if q.get("answer_explanation"):
            q["answer_explanation"] = _remap_answer_letters(q["answer_explanation"], mapping)
        moved += 1

    after = "".join(str(q.get("answer", "?")).lower().strip()[:1] for q in eligible)
    print(f"[MCQ-Balance] {moved}/{len(eligible)} key(s) moved "
          f"({len(fixed)} left as-is: AR/matching/order-bound): {before} → {after}")
    return paper_data


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
            stage="v3-grounding",
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
            stage="v6-cbq-passage",
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
    if wo.disable_images:
        print(f"[Section-Gen] Image generation disabled for this school — skipping images in '{wo.section_name}'")
        return

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
    # Source-mix meter: this path generates one question at a time, so the slot at this index
    # is the one that carries whether the teacher asked for an own composition here.
    _mix_slot = wo.slots[q_index] if (wo.slots and 0 <= q_index < len(wo.slots)) else None
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

    # English grammar and creative writing never draw on the reference material (see
    # english_own_slot_kinds) — withhold the material outright and invert the provenance rule.
    if wo.english_own_only:
        context = ""
        if wo.is_english_writing:
            source_rule = (
                "- Set a SELF-CONTAINED, real-world writing brief composed ENTIRELY from your "
                "own knowledge\n"
                "- Take NOTHING from any textbook chapter, story, poem or character, and never "
                'open with "After reading …" — set "chapter_tag" to "Writing"\n'
            )
        else:
            source_rule = (
                "- Compose this question ENTIRELY from your own knowledge of English grammar\n"
                "- Take NOTHING from any textbook chapter, story, poem or character — write "
                'your own example sentence, and set "chapter_tag" to "Grammar"\n'
            )
    elif (_mix_slot or {}).get("own_question"):
        source_rule = (
            "- Write this question YOURSELF — a fresh scenario, context, data or example of "
            "your own\n"
            "- It must test the same chapter/topic at this class level, but must NOT be "
            "copied, quoted or reworded from the reference material or from the textbook's "
            "own exercises\n"
        )
    else:
        source_rule = "- Draw content ONLY from the reference material above\n"

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
        f"{source_rule}"
        "- The student has no textbook: never name an Activity/Exercise/Table/Figure "
        "number, never write \"the chapter\" or \"the lesson\", and never ask what a person "
        "in the book said, suggested or did — ask about the concept and write everything "
        "the question needs into it\n"
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
                stage="gen-single",
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


# ── Match-the-following normalisation ────────────────────────────────────────
# The pattern slot type "matching" collapses to the VSA category, so a generated
# match question arrives as type=VSA / subtype=standard with its two columns stacked
# by newlines ("(A) …\n(B) …\n(1) …\n(2) …"). _is_matching_question detects such a
# question and _matching_to_markdown rewrites the body into a two-column Markdown
# table — render_docx already turns a pipe table into a real side-by-side Word table.
#
# A match question is ANSWERED by choosing a pairing, so it also carries the same four
# a/b/c/d options an MCQ does ("A-3, B-1, C-4, D-2"). That is why Column I is lettered
# (A)…(D) and Column II numbered (1)…(4): the option strings are written against those
# labels. _MATCH_MIN_PAIRS pairs are required — three pairs cannot carry four distinct
# pairing choices, so a 3-row match is not answerable as a 4-option question.
_MATCH_MIN_PAIRS = 4

_MATCH_ROMAN_RE = re.compile(r'^\(\s*([ivxl]+)\s*\)\s*(.+)$')    # (i) (ii) (iii) …
_MATCH_ALPHA_RE = re.compile(r'^\(\s*([A-Z])\s*\)\s*(.+)$')      # (A) (B) (C) …
_MATCH_NUM_RE = re.compile(r'^\(\s*(\d{1,2})\s*\)\s*(.+)$')      # (1) (2) (3) …

# A column label is a single letter, a roman numeral, or a 1-2 digit number — deliberately
# NOT "any 1-3 letters", which would read "Dr. Ambedkar" as label "DR" and "The capital of
# India" as label "THE".
_MATCH_LABEL = r'[A-Za-z]|[ivxIVX]{2,3}|\d{1,2}'

# One cell of a match table: "(A) Chacha" / "A. Chacha" / "3) Mother's sister".
_MATCH_CELL_RE = re.compile(rf'^\(?\s*({_MATCH_LABEL})\s*[).\]:]\s*(.+)$')
# Same, with the label separated by whitespace alone ("A  Frederic Sorrieu"). Upper-case and
# digits only — a lower-case bare label is not a format anyone writes, and allowing it would
# read an ordinary cell ("a small village in Bengal") as label "A".
_MATCH_CELL_BARE_RE = re.compile(r'^([A-D]|[1-9]|[IVX]{1,3})\s+(\S.*)$')

# One "left-right" pair inside a pairing string — "A-3", "(i)-B", "A → 3", "C: 1".
_MATCH_KEY_PAIR_RE = re.compile(
    rf'\(?\s*({_MATCH_LABEL})\s*\)?\s*(?:-{{1,2}}>?|–|—|→|:|=)\s*\(?\s*({_MATCH_LABEL})\s*\)?'
)


def _is_match_label_line(line: str) -> bool:
    """True when a stacked-match line opens with any recognised column label."""
    return any(rx.match(line) for rx in (_MATCH_ROMAN_RE, _MATCH_ALPHA_RE, _MATCH_NUM_RE))


def _split_match_columns(text: str):
    """Parse a stacked match body into (left, right) lists of (label, value) by label style.

    Two conventions are recognised: the current lettered/numbered form — Column I "(A)…(D)"
    ↔ Column II "(1)…(4)", which the pairing options are written against — and the older
    roman "(i)…" ↔ letter "(A)…" form still present in already-stored papers.
    """
    roman, alpha, num = [], [], []
    for raw in str(text or "").split("\n"):
        line = raw.strip()
        for rx, bucket in ((_MATCH_ROMAN_RE, roman), (_MATCH_ALPHA_RE, alpha),
                           (_MATCH_NUM_RE, num)):
            m = rx.match(line)
            if m:
                bucket.append((f"({m.group(1)})", m.group(2).strip()))
                break
    if num:
        return (alpha or roman), num          # (A)…(D) ↔ (1)…(4)
    return roman, alpha                       # legacy (i)… ↔ (A)…


def _match_cell_label(cell: str):
    """Label of one match-table cell ("(A) Chacha" → "A", "3. Mother's sister" → "3"), or
    None when the cell carries no label (header and "---" separator rows)."""
    s = str(cell or "").strip()
    for rx in (_MATCH_CELL_RE, _MATCH_CELL_BARE_RE):
        m = rx.match(s)
        if m:
            return m.group(1).upper()
    return None


def _match_table_labels(text: str):
    """(left_labels, right_labels) in ROW order from a 2-column Markdown match table.

    Row order is display order, not the answer — Column II is scrambled — so these are
    used for the label SETS (how many pairs, which labels an option must cover), never
    to derive the pairing itself.
    """
    left, right = [], []
    for raw in str(text or "").split("\n"):
        ln = raw.strip()
        if not (ln.startswith("|") and ln.endswith("|")):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        ll, rl = _match_cell_label(cells[0]), _match_cell_label(cells[1])
        if ll and rl:
            left.append(ll)
            right.append(rl)
    return left, right


def _parse_match_key(text: str) -> dict:
    """{left_label: right_label} parsed from a pairing string like "A-3, B-1, C-4, D-2"
    (also accepts "(i)-B", "A → 3", "C: 1"). Labels are upper-cased, brackets dropped."""
    out = {}
    for lft, rgt in _MATCH_KEY_PAIR_RE.findall(str(text or "")):
        lbl, val = lft.strip().upper(), rgt.strip().upper()
        if lbl and val and lbl not in out:
            out[lbl] = val
    return out


def _format_match_key(labels, values) -> str:
    """Render a pairing as the canonical option/key string "A-3, B-1, C-4, D-2"."""
    return ", ".join(f"{lbl}-{val}" for lbl, val in zip(labels, values))


def _match_option_set(labels, correct, seed: int = 0):
    """Build the 4 pairing choices for a match question: the correct key plus 3 scrambles.

    Deterministic (fixed transforms, no RNG) so a regenerated paper is reproducible, and
    `seed` rotates which letter holds the key so several match questions in one section
    don't all answer (a). Returns ({"a": …, …}, answer_letter), or (None, "") when the
    pairing is too short to yield 3 distinct distractors.
    """
    base = list(correct)
    n = len(base)
    if n < 3 or len(labels) != n:
        return None, ""

    def _swap(i, j):
        w = list(base)
        w[i], w[j] = w[j], w[i]
        return w

    scrambles = []
    for build in (lambda: _swap(0, 1),
                  lambda: _swap(n - 2, n - 1),
                  lambda: base[1:] + base[:1],
                  lambda: base[2:] + base[:2],
                  lambda: list(reversed(base))):
        if len(scrambles) == 3:
            break
        w = build()
        if w != base and w not in scrambles:
            scrambles.append(w)
    if len(scrambles) < 3:
        return None, ""

    idx = seed % 4
    scrambles.insert(idx, base)
    letters = ("a", "b", "c", "d")
    return ({letters[i]: _format_match_key(labels, p) for i, p in enumerate(scrambles[:4])},
            letters[idx])


def _has_pipe_table(text: str) -> bool:
    """True if any line is already a Markdown pipe-table row (starts and ends with '|')."""
    return any(
        ln.strip().startswith("|") and ln.strip().endswith("|")
        for ln in str(text or "").split("\n")
    )


def _is_matching_question(q: dict) -> bool:
    """True when q is a match-the-following item: declared as such (subtype/type), or a
    'match the …' stem whose body carries both a (i)/(ii) list and an (A)/(B) list."""
    if str(q.get("subtype", "")).strip().lower() == "matching":
        return True
    if "match" in _type_str(q.get("type", "")):
        return True
    if "match the" not in str(q.get("text", "")).lower():
        return False
    left, right = _split_match_columns(q.get("text", ""))
    if len(left) >= 2 and len(right) >= 2:
        return True
    # Already laid out as a pipe table (labels sit inside cells, not at line start), which is
    # what the prompt asks for — the model just forgot to set subtype="matching".
    tbl_left, tbl_right = _match_table_labels(q.get("text", ""))
    return len(tbl_left) >= 2 and len(tbl_right) >= 2


def _matching_to_markdown(text: str) -> str:
    """Rewrite 'stem + stacked (i)/(A) lists' into 'stem + 2-column Markdown table'.
    Returns text unchanged if it is already a pipe table or two columns can't be parsed."""
    text = str(text or "")
    if _has_pipe_table(text):
        return text
    left, right = _split_match_columns(text)
    if len(left) < 2 or len(right) < 2:
        return text
    stem_lines = []
    for raw in text.split("\n"):
        s = raw.strip()
        if _is_match_label_line(s):
            break
        stem_lines.append(raw)
    stem = "\n".join(stem_lines).strip()
    n = max(len(left), len(right))
    rows = ["| Column I | Column II |", "| --- | --- |"]
    for i in range(n):
        lft = f"{left[i][0]} {left[i][1]}" if i < len(left) else ""
        rgt = f"{right[i][0]} {right[i][1]}" if i < len(right) else ""
        rows.append(f"| {lft} | {rgt} |")
    table = "\n".join(rows)
    return f"{stem}\n{table}" if stem else table


def _repair_matching_options(q: dict) -> None:
    """Give a match-the-following question the 4 pairing choices it is answered with.

    A match question is answered by picking the correct pairing, so it needs the same four
    a/b/c/d options an MCQ does. The correct pairing is already stated in
    'answer_explanation', which makes the whole option set derivable — build it here rather
    than spending a retry asking the model for something already determined. Also corrects
    a mis-pointed 'answer' letter when the model wrote all four options itself.

    Leaves the question untouched when no trustworthy key can be read; validation then asks
    for the retry. Mutates q in place.
    """
    left, right = _match_table_labels(q.get("text", ""))
    if len(left) < 2 or len(left) != len(right):
        return

    opts = q.get("options") if isinstance(q.get("options"), dict) else {}
    opts = {str(k).lower().strip(): str(v).strip() for k, v in opts.items() if str(v).strip()}
    # An option "counts" only if it pairs EVERY Column I label — a partial pairing
    # ("A-3, B-1") is not an answerable choice.
    full = {k: m for k, m in ((k, _parse_match_key(v)) for k, v in opts.items())
            if sorted(m) == sorted(left)}

    key = _parse_match_key(q.get("answer_explanation", ""))
    correct = [key.get(lbl, "") for lbl in left]
    # The key is trustworthy only when it pairs every Column I label with a distinct
    # Column II label — i.e. it is a permutation of the printed right column.
    key_ok = sorted(v for v in correct if v) == sorted(right)

    if set(full) == {"a", "b", "c", "d"}:
        if key_ok:
            hit = [k for k, m in full.items() if [m.get(lbl) for lbl in left] == correct]
            if len(hit) == 1 and str(q.get("answer", "")).lower().strip() != hit[0]:
                q["answer"] = hit[0]
                print(f"[Repair] Q{q.get('qnum','?')}: matching answer key → '{hit[0]}' "
                      "(the option matching answer_explanation)")
        return

    if not key_ok:
        return
    built, letter = _match_option_set(left, correct, _as_int(q.get("qnum"), 1) - 1)
    if built:
        # answer_explanation is left as the model wrote it — it already states the pairing
        # (that is what was just parsed) and may add teacher-facing reasoning worth keeping.
        q["options"], q["answer"] = built, letter
        print(f"[Repair] Q{q.get('qnum','?')}: built the 4 matching options from the "
              f"pairing key (answer '{letter}')")


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

        # ── Match-the-following: retag + reformat to a side-by-side table ─────────
        # "matching" slots collapse to the VSA category, so the model returns
        # type=VSA / subtype=standard with the two columns stacked by newlines. Retag
        # them (so the type identifies a match question) and rewrite the body into a
        # 2-column Markdown table, which render_docx lays out side by side. Then fill in
        # the four a/b/c/d pairing choices the question is answered with.
        if str(q.get("subtype", "")).strip().lower() in ("", "standard", "matching") \
                and _is_matching_question(q):
            q["subtype"] = "matching"
            q["text"] = _matching_to_markdown(str(q.get("text", "")))
            _repair_matching_options(q)

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
                    stage="ar-repair",
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
    topup_plan = _allocate_chapters_to_slots(wo.chapters, missing, eff_subject, covered,
                                             wo.class_name)

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
            stage="top-up",
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

        # An attempt-N-of-M section budgets only the N a student answers ("Answer any SIX of
        # the following" = 6 x 2 = 12m), but all M PRINTED questions still carry the full
        # marks_per_question. wo.marks is the attemptable budget, so comparing it against
        # count x mpq declares the section inconsistent and spreads the budget thin —
        # eight 2-mark questions became 2,2,2,2,1,1,1,1 and the audit then flagged the four
        # it had just docked. Reconcile against what the PRINTED questions must sum to.
        # Same adjustment the marks-sum validator already makes (see validate_section_marks).
        printed_marks = wo.marks
        if (wo.provided_count and wo.attempt_count and wo.attempt_count > 0
                and wo.provided_count > wo.attempt_count):
            printed_marks = wo.marks * (wo.provided_count / wo.attempt_count)

        consistent = (not expected) or abs(expected * mpq - printed_marks) <= 0.5

        # DISTRIBUTE only for an inconsistent written-answer section with a sane marks budget.
        n = len(targets)
        base, rem = divmod(int(printed_marks), n) if printed_marks else (0, 0)
        if has_objective or consistent or not printed_marks or base < 1:
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
            print(f"[Marks-Reconcile] '{sec_name}': distributed {printed_marks:g}m across {n} question(s) "
                  f"as {plan} (pattern {expected}×{mpq} = {expected * mpq if expected else '?'} "
                  f"≠ {printed_marks:g})")
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
            stage="gen",
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

# Which canonical section types make a TYPE_CONTEXT_PROFILES slice worth building.
# build_single_question_prompt is the ONLY reader of context_by_type and looks the slice
# up by generate_la_cbq_individually's dominant type, which is "LA" or "source_based" —
# so those two slices are the only ones any prompt can ever see. A dedicated case-study
# section is routed as source_based, hence cbq maps onto that slice.
_CONTEXT_BY_TYPE_CONSUMERS = {
    "la":           frozenset({"la"}),
    "source_based": frozenset({"source_based", "cbq"}),
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
            stage="ctx-precheck",
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


# Retrieval probe per canonical question type. Wording is unchanged from the original
# per-type branches; vsa / source_based / map_work / match are new — they had no probe at
# all, so those sections used to retrieve on the generic one alone.
_TYPE_QUERY_HINTS = {
    "mcq":            "facts MCQ questions",
    "assertion":      "principles assertion reason",
    "cbq":            "case study applications",
    "source_based":   "source passages extracts",
    "unseen_passage": "reading comprehension passages",
    "vsa":            "definitions key terms brief answers",
    "sa":             "short answer explanations",
    "la":             "detailed explanations processes",
    "numerical":      "numerical problems solved examples",
    "writing_tasks":  "writing formats samples letters",
    "map_work":       "locations places regions",
    "match":          "terms and their descriptions",
}


def _query_hints_for_types(question_types: list, subject: str) -> list:
    """Retrieval probes for a section, TYPE-SPECIFIC ONES FIRST.

    Two defects fixed here, both measured on live pattern 415 (Class 6 Science):

    1. The old branches compared UNDERSCORE keys ("short_answer", "long_answer") against
       the pattern's SPACE-separated display labels ("Short Answer", "Very Short Answer",
       "Long Answer"), which _type_str only lowercases — so three of that paper's five
       sections (20 of 43 questions) fell through to the generic probe. Matching now goes
       through _canon_type_keys, which reads every label form alike.
    2. The generic probe used to come FIRST, and that alone made the fix invisible:
       get_section_context admits only the top-ranked chunk per chapter once a paper has
       4+ chapters, and that chunk is whichever the FIRST probe returned. Every section of
       a paper therefore got a byte-identical context however many type hints followed.
       It is now LAST — a fallback for an unrecognised type, not the probe that decides the
       excerpt. It is also definition-biased ("important concepts definitions"), which is
       what pinned retrieval to chapter openings.
    """
    hints = []
    for qt in question_types:
        for key in _canon_type_keys(qt):
            probe = _TYPE_QUERY_HINTS.get(key)
            if probe:
                hints.append(f"{subject} {probe}")
    hints.append(f"{subject} important concepts definitions")
    return list(dict.fromkeys(hints))


def _class_key(class_name) -> str:
    """The bare class number from any label form ('11', 'Class 11', 'XI ' → '11'). '' when the
    label carries no number, which means "don't class-scope" (legacy callers)."""
    m = re.search(r"\d{1,2}", str(class_name or ""))
    return m.group() if m else ""


def _chapter_weight(subject: str, chapter: str, class_name: str = "", default: int = 1) -> int:
    """CBSE unit marks weight for a chapter, used to scale retrieval budget and the
    per-question chapter allocation. Returns `default` when the chapter has no entry.

    Two fixes over the original substring lookup, both of which cost real papers questions:

    1. ANCHORED matching — the catalog key must be contained in the CHAPTER name, never the
       reverse. The old two-way test let a shorter chapter name inherit a longer key's weight,
       so Class 11 'Trigonometric Functions' matched Class 12's 'Inverse Trigonometric
       Functions'.
    2. LONGEST key wins — dict order used to decide. 'Applications of Integrals' matched the
       key 'Integrals' (8) before reaching its own entry (5).

    Also scoped by class (UNIT_MARKS_WEIGHT_CLASSES): each table is one class's syllabus, so a
    Class 11 paper is no longer scored against the Class 12 distribution. class_name '' keeps
    the legacy unscoped lookup.
    """
    weights = UNIT_MARKS_WEIGHTS.get(subject, {})
    if not weights or not chapter:
        return default
    cls = _class_key(class_name)
    if cls:
        allowed = UNIT_MARKS_WEIGHT_CLASSES.get(subject)
        if allowed and cls not in allowed:
            return default
    chapter_lower = chapter.strip().lower()
    best_key, best_weight = "", default
    for unit_key, weight in weights.items():
        uk = unit_key.strip().lower()
        if uk and uk in chapter_lower and len(uk) > len(best_key):
            best_key, best_weight = uk, weight
    return best_weight


def _chapter_weights(subject: str, chapters: list, class_name: str = "") -> dict:
    """Per-chapter weights for ONE paper, normalised so an unlisted chapter is not starved.

    `_chapter_weight` returns 1 for a chapter with no weightage entry. Where some of the
    paper's chapters ARE listed (CBSE unit weights run 3-18) and others are not, that 1 is not
    a modest weight — it is a penalty of up to 18× for the crime of not being in the catalog,
    and it is applied twice over: to the chapter's share of question slots AND to its share of
    the retrieval character budget. An unlisted chapter therefore inherits the MEAN of the
    listed ones, so weighting still follows CBSE where CBSE has an opinion about this class and
    falls back to uniform where it does not.
    """
    chs = list(chapters or [])
    # `default=0` marks "no weightage entry" distinctly from a genuine light weight.
    raw = {ch: float(_chapter_weight(subject, ch or "", class_name, 0)) for ch in chs}
    listed = [ch for ch in chs if raw[ch] > 0]
    if listed and len(listed) < len(chs):
        mean = sum(raw[ch] for ch in listed) / len(listed)
        for ch in chs:
            if raw[ch] <= 0:
                raw[ch] = mean
    return {ch: max(1.0, raw[ch]) for ch in chs}


def _spread_order(cands: list) -> list:
    """Reorder retrieval candidates so any PREFIX of the list is spread across the whole
    chapter instead of clustered in one part of it.

    Retrieval returns chunks in similarity order and the character budget then keeps only the
    first few. Neighbouring chunks of a textbook are near-identical in embedding space, so that
    top-k is typically a contiguous run — one region of one chapter. On a real Class 11 Maths
    paper every section received the identical 7618-char block, i.e. all 21 questions were
    written from ~8 adjacent excerpts. That is the "questions only come from one part of the
    textbook" complaint, and it is a ranking artefact, not a shortage of material.

    Farthest-point traversal over printed position: keep the single most relevant chunk first
    (relevance still decides what the paper is about), then repeatedly take the candidate
    furthest — in printed order — from everything already taken. Whatever prefix the budget can
    afford is therefore spread over the chapter, with no need to know that length up front, and
    it degrades gracefully: room for one excerpt still yields the most relevant one. Ties break
    toward the more relevant candidate, so the result stays deterministic.

    `cands` are (material_id, chunk_index, text) in similarity order.
    """
    if len(cands) <= 2:
        return list(cands)
    # Rank by printed position (material first, then index within it) so distances stay
    # comparable when several materials are attached to the same chapter.
    order = sorted(range(len(cands)), key=lambda i: (cands[i][0], cands[i][1], i))
    pos = {ci: rank for rank, ci in enumerate(order)}
    picked = [0]
    mind = {i: abs(pos[i] - pos[0]) for i in range(1, len(cands))}
    while mind:
        nxt = min(mind, key=lambda i: (-mind[i], i))
        picked.append(nxt)
        at = pos[nxt]
        del mind[nxt]
        for i in mind:
            d = abs(pos[i] - at)
            if d < mind[i]:
                mind[i] = d
    return [cands[i] for i in picked]


# ─────────────────────────────────────────────
# Per-question source anchoring
# ─────────────────────────────────────────────
#
# The measured complaint ("questions come from only one part of a unit") has two halves. The
# first is retrieval: only ONE excerpt per chapter survived the character budget. The second is
# BINDING — even when several excerpts were present, the prompt named none of them against any
# particular question, so the model wrote all of a section's questions off whichever excerpt it
# liked (on the reference paper only 5 of 55 questions shared a 5-word run with the material they
# were given). Numbering the excerpts [E1]…[En] and naming one on each question slot line closes
# the second half; splitting each chapter's slice into several excerpts (same total chars, so the
# same input-token bill) gives that binding something to distribute.
_EXCERPT_SPLIT = 3            # pieces a chapter's slice is cut into when it is too tight to
                              # hold several whole chunks (a roomy slice keeps taking whole ones)
_EXCERPT_MIN_CHARS = 300      # ~50 words; below this an excerpt cannot ground a question at all


def _trim_excerpt(doc: str, cap: int) -> str:
    """`doc` cut to at most `cap` chars, ending at a sentence break where one is available in
    the last 40% (a mid-word stub reads as corrupt source material to the model)."""
    doc = (doc or "").strip()
    if len(doc) <= cap:
        return doc
    head = doc[:cap]
    for stop in (". ", ".\n", "! ", "? ", "\n"):
        cut = head.rfind(stop)
        if cut >= int(cap * 0.6):
            return head[:cut + 1].strip()
    cut = head.rfind(" ")
    return (head[:cut] if cut >= int(cap * 0.6) else head).strip()


_CTX_CHAPTER_RE = re.compile(r"^=== CHAPTER: (.+?) ===\s*$", re.M)
_CTX_EXCERPT_RE = re.compile(r"^\[E(\d+)\] ", re.M)


def _excerpt_index(context: str) -> list:
    """[(excerpt_id, chapter_name)] for a context string built by get_section_context.

    Read back off the assembled string rather than threaded through the work order: the context
    a section finally receives may have been rebuilt by the quality-check broad retry or had
    CONTINUOUS PASSAGE spans prepended, and whatever arrives is what the model actually sees."""
    if not context:
        return []
    heads = [(m.start(), m.group(1).strip()) for m in _CTX_CHAPTER_RE.finditer(context)]
    out = []
    for m in _CTX_EXCERPT_RE.finditer(context):
        chapter = ""
        for pos, name in heads:
            if pos < m.start():
                chapter = name
            else:
                break
        out.append((int(m.group(1)), chapter))
    return out


def plan_slot_excerpts(wo) -> dict:
    """{slot index: (chapter, excerpt id or None)} — the chapter and the ONE labeled excerpt
    each printed question must be written from.

    `wo.chapter_plan` already holds one chapter per question (plan_chapter_allocation, CBSE-mark
    weighted and coordinated paper-wide), but it reached the prompt only as an aggregate
    `Counter` distribution — "3 from Optics, 2 from Waves" — which the model satisfies by writing
    all three Optics questions off the same paragraph. This pairs plan[i] with slot i and then
    hands each slot a different excerpt of that chapter, round-robin, so a chapter that owes two
    questions gives them two different pieces of itself.

    Slots the teacher has already pinned (`slot['chapter']`, from an ExamBlueprint unit map) are
    left alone — that assignment is rendered by build_section_prompt and outranks this one.
    Slots that must NOT come from the textbook (source general/unseen, own-composition) get no
    excerpt; a general/unseen slot gets no chapter either."""
    if not getattr(wo, "slots", None) or not getattr(wo, "chapter_plan", None):
        return {}
    by_chapter: dict = {}
    for eid, chapter in _excerpt_index(getattr(wo, "context_text", "") or ""):
        by_chapter.setdefault(chapter, []).append(eid)
    cursor: dict = {}
    out: dict = {}
    for i, s in enumerate(wo.slots):
        if i >= len(wo.chapter_plan) or not isinstance(s, dict) or s.get("chapter"):
            continue
        if str(s.get("source") or "").strip().lower() in ("general", "unseen"):
            continue
        chapter = str(wo.chapter_plan[i] or "").strip()
        if not chapter:
            continue
        eid = None
        ids = by_chapter.get(chapter) or []
        # An own-composition slot keeps its chapter but must invent its own scenario, so it is
        # deliberately not pointed at a passage to lean on (see plan_creative_allocation).
        if ids and not s.get("own_question"):
            k = cursor.get(chapter, 0)
            eid = ids[k % len(ids)]
            cursor[chapter] = k + 1
        out[i] = (chapter, eid)
    return out


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

    # Compute total weight for proportional allocation. Class-scoped, and an unlisted chapter
    # inherits the mean of the listed ones rather than 1 — otherwise a chapter missing from the
    # CBSE catalog is starved of retrieval budget as well as questions (_chapter_weights).
    chapter_weights = _chapter_weights(subject, query_units, class_name)
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
                    doc_lists = results["documents"]
                    meta_lists = results.get("metadatas") or []
                    for li, doc_list in enumerate(doc_lists):
                        docs = doc_list if isinstance(doc_list, list) else [doc_list]
                        metas = meta_lists[li] if li < len(meta_lists) else []
                        if not isinstance(metas, list):
                            metas = []
                        for di, doc in enumerate(docs):
                            if not doc or doc in seen:
                                continue
                            seen.add(doc)
                            # Printed position, so _spread_order can walk ACROSS the chapter.
                            mt = metas[di] if di < len(metas) and isinstance(metas[di], dict) else {}
                            unit_docs.append((_as_int(mt.get("material_id"), 0),
                                              _as_int(mt.get("chunk_index"), 0), doc))
            except Exception as e:
                print(f"[Section-Context] query failed chapter='{chapter}' q='{query}': {e}")

    # Chapters that returned nothing are dropped and their budget share redistributed.
    live_units = [ch for ch in query_units if docs_by_unit.get(ch)]
    dropped = [ch for ch in query_units if ch and ch not in live_units]
    if dropped:
        print(f"[Section-Context] no source chunks for chapter(s) {dropped} — dropped from "
              f"context (likely un-ingested/un-enriched, or a label variant retrieval could "
              f"not match); these chapters will get no grounded questions")
    if not live_units:
        return ""
    live_weight = sum(chapter_weights[ch] for ch in live_units) or 1

    blocks = []
    excerpt_no = 0
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
        picked_at = []
        # Ceiling on ONE excerpt, so a tight slice yields several excerpts instead of one.
        # The old loop spent the ENTIRE remaining slice on the first (most-similar) chunk —
        # `room = max(400, budget - used)` — so from four chapters up every chapter
        # contributed exactly ONE excerpt and _spread_order's other picks were discarded
        # unused. One 880-char excerpt and two 440-char ones cost the SAME input tokens, but
        # only the second gives build_section_prompt distinct excerpts to hand to distinct
        # question slots. A roomy slice (one- or two-chapter papers) keeps taking whole
        # ~1000-char chunks exactly as before — the ceiling only binds once the slice falls
        # below chunk size, which is precisely the many-chapter case that was starving.
        room = max(400, budget - used)
        n_split = max(1, min(_EXCERPT_SPLIT, room // _EXCERPT_MIN_CHARS))
        per_excerpt = max(_EXCERPT_MIN_CHARS, room // n_split)
        # Spread across the chapter rather than taking the similarity-ordered top-k, which
        # clusters into one region (see _spread_order).
        for _mid, cidx, doc in _spread_order(docs_by_unit[chapter]):
            cap = min(per_excerpt, budget - used - 8)
            if cap < _EXCERPT_MIN_CHARS:
                if added:
                    break
                # Slice too small even for one floor-sized excerpt: represent the chapter
                # anyway with a trimmed one, exactly as the old `max(400, …)` did.
                cap = max(400, cap)
            piece = _trim_excerpt(doc, cap)
            if not piece:
                continue
            excerpt_no += 1
            # Numbered so a question slot can be pointed at ONE of them (_excerpt_index).
            parts.append(f"[E{excerpt_no}] {piece}")
            used += len(piece) + 8
            picked_at.append(cidx)
            added += 1
        if chapter and picked_at:
            # Printed positions of the excerpts actually sent. Adjacent numbers here mean the
            # paper is again being written from one part of the chapter.
            print(f"[Section-Context]   '{chapter}': {added} excerpt(s), {used} chars, "
                  f"chunk idx {','.join(str(i) for i in sorted(picked_at))}")
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
                stage="grammar-chapters",
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


# ─────────────────────────────────────────────
# English grammar — own knowledge only, never the retrieved context
# ─────────────────────────────────────────────
# An English paper's grammar questions must be composed from the model's OWN knowledge of
# English grammar. NOTHING may come from the reference material handed to the LLM.
#
# Why this needs its own rule: NCERT English readers (Honeydew, Beehive, First Flight,
# Footprints…) contain no grammar LESSONS, so identify_grammar_chapters finds nothing to route
# the grammar section to and _route_grammar_chapters falls back to the full chapter list. The
# section then retrieves prose/poetry and the model builds "gap filling", "editing" and
# "reordering" questions out of story sentences, tagged to literature chapters.
#
# Enforcement is layered, so a leak has to defeat all three:
#   1. grammar slots are forced to source='general' — this reuses the whole existing
#      general-knowledge machinery (per-slot prompt directive, chapter-assignment exemption,
#      chapter-name validator);
#   2. a section that is ENTIRELY grammar is denied retrieval outright — no context reaches
#      the prompt at all, plus an explicit ABSOLUTE RULE block in build_section_prompt;
#   3. _lifted_span rejects any grammar question that still copies a span of the material
#      (the case that survives 2 only in mixed sections, which keep context for their
#      literature/comprehension slots).

# Grammar skills named on a slot's type / topic / format. Deliberately grammar-only —
# vocabulary wording (synonym/antonym/word-meaning) is excluded because "find a word from the
# passage meaning X" is a comprehension question that legitimately needs the passage.
_ENGLISH_GRAMMAR_TOPIC_MARKERS = (
    "grammar", "tense", "article", "preposition", "conjunction", "determiner",
    "modal", "auxiliar", "voice", "passive", "active", "narration",
    "reported speech", "direct speech", "indirect speech", "subject-verb",
    "subject verb", "concord", "agreement", "gap fill", "gap-fill", "gap filling",
    "editing", "omission", "error correction", "reorder", "re-order", "rearrange",
    "jumbled", "transformation", "clause", "phrase", "degrees of comparison",
    "punctuation", "capitalisation", "capitalization", "parts of speech", "noun",
    "pronoun", "adjective", "adverb", "verb form", "infinitive", "gerund",
    "participle", "question tag", "homophone", "homonym", "singular", "plural",
    "syntax", "linker", "connector", "sentence type", "sentence structure",
)

# Literature wording exempts a slot — and, for a slot-less section, keeps the whole section's
# context — so a hybrid "Literature and Grammar" section does not lose the material its
# literature questions genuinely need.
_ENGLISH_LITERATURE_TOPIC_MARKERS = (
    "chapter", "story", "poem", "poetry", "prose", "extract", "passage",
    "character", "author", "poet", "lesson", "textbook", "novel", "drama", "play",
    "literature", "reading", "comprehension", "unseen", "supplementary",
)

# Slot types that ARE grammar questions whatever their topic says.
_ENGLISH_GRAMMAR_SLOT_TYPES = ("error_correction", "punctuation", "rewrite")

# ── Creative writing ─────────────────────────────────────────────────────────────
# Composition tasks belong to the student, not to the textbook. A generated Creative Writing
# section came back as: "After reading 'The Laburnum Top', you are inspired by the theme of
# nature's vitality. Write an article … on 'The Healing Power of Nature'" — the model reached
# into the retrieved poem and hung the writing task off it, in BOTH options of the internal
# choice. An article, letter, notice or advertisement must stand on its own real-world brief.

_ENGLISH_WRITING_SLOT_TYPES = ("writing",)

# Composition FORMS. Phrase-level wherever a bare word would collide with literature: "message
# writing" not "message" ("the message of the poem" is comprehension), "letter writing" /
# "formal letter" not "letter" ("A Letter to God" is a chapter).
_ENGLISH_WRITING_TOPIC_MARKERS = (
    "creative writing", "composition", "article writing", "write an article",
    "letter writing", "formal letter", "informal letter", "letter to the editor",
    "complaint letter", "enquiry letter", "order letter", "job application",
    "application writing", "notice writing", "notice", "advertisement", "classified",
    "poster", "speech", "debate", "essay", "report writing", "story writing",
    "diary entry", "email", "invitation", "bio-data", "biodata", "resume",
    "analytical paragraph", "descriptive paragraph", "paragraph writing", "precis",
    "précis", "dialogue writing", "summary writing", "message writing", "note making",
    "notemaking", "speech writing",
)

# Section names that make the WHOLE section own-knowledge composition work.
_ENGLISH_WRITING_SECTION_MARKERS = (
    "creative writing", "writing skill", "writing section", "composition",
    "writing", "letter and", "applied writing",
)


def _is_english_subject(subject: str) -> bool:
    """True for English papers ("English", "English Core", "English Lang. & Lit.", …)."""
    return "english" in str(subject or "").lower()


def _slot_wording(slot: dict) -> str:
    return " ".join(str(slot.get(k) or "") for k in ("topic", "format", "condition")).lower()


def _slot_names_grammar(slot: dict) -> bool:
    """True when a slot's own type/topic/format names an English grammar skill."""
    if str(slot.get("type") or "").strip().lower() in _ENGLISH_GRAMMAR_SLOT_TYPES:
        return True
    return any(m in _slot_wording(slot) for m in _ENGLISH_GRAMMAR_TOPIC_MARKERS)


def _slot_names_writing(slot: dict) -> bool:
    """True when a slot's own type/topic/format names a composition task."""
    if str(slot.get("type") or "").strip().lower() in _ENGLISH_WRITING_SLOT_TYPES:
        return True
    return any(m in _slot_wording(slot) for m in _ENGLISH_WRITING_TOPIC_MARKERS)


def _english_own_section_kind(sec_name, instructions) -> str:
    """'grammar' / 'writing' / '' — what a whole English section is, by name and instructions.

    Writing wins a tie: a "Writing and Grammar" section is composition-led, and either way the
    two get identical treatment (own knowledge, no context) — only the prompt wording differs.
    """
    hay = " ".join([str(sec_name or "")] + [str(i) for i in (instructions or [])]).lower()
    if any(m in hay for m in _ENGLISH_WRITING_SECTION_MARKERS):
        return "writing"
    if _is_grammar_section(sec_name, instructions):
        return "grammar"
    return ""


def english_own_slot_kinds(subject, section_subject, sec_name, sec_data, slots) -> dict:
    """{slot_index: 'grammar' | 'writing'} for the slots that must come from the model's OWN
    knowledge rather than the retrieved reference material.

    In a grammar- or writing-named section every slot counts; in any other section only the
    slots whose own type/topic/format names a grammar skill or a composition form do.

    A slot whose wording names literature is exempt UNLESS it also names a composition form —
    "story writing" is a writing task, not a story question — because an explicit form is a
    stronger signal than a bare content word. Passage-carrying slots (cbq/extract) never count:
    they print their own source_text and are comprehension questions by construction.

    Empty for non-English subjects, so no other paper's behaviour changes.
    """
    if not _is_english_subject(section_subject or subject):
        return {}
    sec_kind = _english_own_section_kind(sec_name, (sec_data or {}).get("instructions"))
    out = {}
    for i, s in enumerate(slots or []):
        if not isinstance(s, dict):
            continue
        if pattern_structure.slot_category(str(s.get("type") or "")) == "cbq":
            continue
        is_writing = _slot_names_writing(s)
        if not is_writing and any(m in _slot_wording(s)
                                  for m in _ENGLISH_LITERATURE_TOPIC_MARKERS):
            continue
        if is_writing:
            out[i] = "writing"
        elif _slot_names_grammar(s):
            out[i] = "grammar"
        elif sec_kind:
            out[i] = sec_kind
    return out


def english_own_scope(subject, section_subject, sec_name, sec_data, slots):
    """(kinds, own_only, slot_kinds) for one section of an English paper.

    kinds     — tuple of the own-knowledge kinds present ('grammar', 'writing'), so the prompt
                can state the right rule and the validator knows to police the section.
    own_only  — EVERY question in it is own-knowledge, so it gets no retrieved context and no
                chapter assignment at all.
    slot_kinds— {index: kind} for the slots to fence off individually (mixed sections).

    All empty/False for non-English subjects.
    """
    if not _is_english_subject(section_subject or subject):
        return (), False, {}
    real = [s for s in (slots or []) if isinstance(s, dict)]
    if real:
        kinds = english_own_slot_kinds(subject, section_subject, sec_name, sec_data, real)
        present = tuple(k for k in ("grammar", "writing") if k in kinds.values())
        return present, len(kinds) == len(real), kinds
    # Slot-less section (legacy subsection blueprints) — judged on its name and instructions
    # alone. One that ALSO names literature/reading keeps its context: only its grammar or
    # writing questions are fenced off, by the prompt rule and the lifted-span check.
    sec_kind = _english_own_section_kind(sec_name, (sec_data or {}).get("instructions"))
    if not sec_kind:
        return (), False, {}
    hay = " ".join([str(sec_name or "")]
                   + [str(i) for i in ((sec_data or {}).get("instructions") or [])]).lower()
    return (sec_kind,), not any(m in hay for m in _ENGLISH_LITERATURE_TOPIC_MARKERS), {}


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
        # English grammar and creative writing come from the model's own knowledge — such a
        # section gets NO reference material, so there is nothing for it to copy from (see the
        # notes above english_own_slot_kinds). Mixed sections keep their context for the
        # literature/comprehension slots; their own-knowledge slots are fenced off per-question.
        if english_own_scope(subject, section_subject, sec_name, sec_data,
                             sec_data.get("question_slots"))[1]:
            print(f"[English-Own] '{sec_name}': grammar/writing section — skipping retrieval "
                  "(questions come from the model's own knowledge)")
            context_map[sec_name] = ""
            context_by_type_map[sec_name] = {}
            continue
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
        sec_keys = {k for t in sec_types for k in _canon_type_keys(t)}
        for type_key, profile in TYPE_CONTEXT_PROFILES.items():
            # Only build per-type context if this section has that type. The old test was
            # `type_key in _type_str(t)` — a bare substring against the display label, so
            # "sa"/"la"/"vsa"/"cbq" never matched "Short Answer"/"Long Answer"/
            # "Very Short Answer"/"Case-Based" and only the mcq and assertion profiles
            # ever fired. Canonical keys read every label form.
            # Scoped to the slices something actually READS: build_single_question_prompt
            # is the only consumer and looks them up by the individual-generation path's
            # dominant type ("la" / "source_based"). Building the rest is retrieval work
            # nothing reads — with the gate fixed that would be 3-5 extra passes per
            # section on every paper.
            if not (sec_keys & _CONTEXT_BY_TYPE_CONSUMERS.get(type_key, frozenset())):
                continue
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


def _allocate_chapters_to_slots(candidate_chapters: list, n_slots: int, subject: str,
                                covered: dict, class_name: str = "") -> list:
    """Assign `n_slots` question slots to specific chapters.

    Score per chapter = weight / (1 + times already covered). Because an uncovered chapter
    scores its full weight, the allocator spreads across distinct chapters first (broad
    coverage), and only repeats a chapter once the higher-weight ones are each covered —
    so heavier (higher CBSE-marks) chapters get the repeats. `covered` is shared across the
    whole paper and mutated in place, so later sections fill the gaps earlier ones left.
    Deterministic: chapters are sorted and ties resolve to the alphabetically-first.

    The spreading is only as good as the weights: a spurious 8-vs-1 split put 19 of 21
    questions in one chapter of a two-chapter paper, which reads to the teacher as "it ignored
    the chapters I picked". Weights now come from `_chapter_weights`, which is class-scoped and
    gives an unlisted chapter the mean of the listed ones instead of 1."""
    chs = sorted({c for c in (candidate_chapters or []) if c})
    if not chs or n_slots <= 0:
        return []
    weights = _chapter_weights(subject, chs, class_name)
    plan = []
    for _ in range(int(n_slots)):
        best = max(chs, key=lambda c: (weights[c] / (1 + covered.get((subject, c), 0)), weights[c]))
        plan.append(best)
        covered[(subject, best)] = covered.get((subject, best), 0) + 1
    return plan


# ─────────────────────────────────────────────
# Book ↔ own-composition mix (the generate page's source-mix meter)
# ─────────────────────────────────────────────
#
# The teacher sets ONE paper-wide percentage ("50% from the book / 50% my own questions"). It is
# spent here, once, over the whole paper rather than per section, because sections differ wildly
# in what they are allowed to do:
#
#   · questions that MUST quote the book (extracts, source="textbook", map work) can never move;
#   · questions that are ALREADY the model's own work (English grammar/writing, source="general",
#     unseen passages) count TOWARD the requested share instead of being converted a second time;
#   · everything else is free, and the share is split across sections in proportion to how much
#     free room each one has, so a 40% meter takes ~40% out of every section instead of turning
#     the first section entirely creative and leaving the last one untouched.
#
# A converted question KEEPS its chapter assignment: "own" here means "not lifted from the book",
# not "off-syllabus" — the teacher still expects the paper to cover the chapters they ticked.
# That is why this marks slots with own_question=True instead of reusing source="general", which
# additionally strips the chapter (right for a Grammar section, wrong for a Physics paper the
# teacher wants half original).

def _slot_mix_state(wo, slot) -> str:
    """'fixed' (must stay book-grounded), 'own' (already the model's own work) or 'free'."""
    if wo.is_map_work:
        return "fixed"          # map questions are located on the prescribed map, not invented
    if wo.english_own_only:
        return "own"
    if (slot or {}).get("own_question"):
        return "own"          # already converted by an earlier pass — never pick it twice
    src = str((slot or {}).get("source") or "").strip().lower()
    styp = str((slot or {}).get("type") or "").strip().lower()
    if src in ("general", "unseen"):
        return "own"            # already composed by the model, not taken from the textbook
    if src == "textbook" or styp == "extract":
        return "fixed"          # the pattern demands textbook material, verbatim
    return "free"


def plan_creative_allocation(work_orders: list, creative_ratio, log=print) -> list:
    """Mark `creative_ratio` percent of the paper's questions as the model's OWN compositions.

    Sets own_question=True on the chosen question_slots (copied, never mutated in place — those
    dicts belong to the pattern/blueprint rows) and `wo.own_count` on every section it touches.
    No-op at 0, the default, which reproduces the previous everything-from-the-book behaviour.
    """
    ratio = max(0, min(100, _as_int(creative_ratio, 0)))
    if ratio <= 0:
        return work_orders

    total = already = 0
    free: list = []                      # [(wo, [indices this section may convert])]
    for wo in work_orders:
        if wo.slots:
            states = [_slot_mix_state(wo, sl) for sl in wo.slots]
        else:
            states = [_slot_mix_state(wo, None)] * max(0, _as_int(wo.questions_count, 0))
        total += len(states)
        already += sum(1 for st in states if st == "own")
        idxs = [i for i, st in enumerate(states) if st == "free"]
        if idxs:
            free.append((wo, idxs))

    pool = sum(len(idxs) for _, idxs in free)
    target = int(round(total * ratio / 100.0))
    need = max(0, min(target - already, pool))
    if not need:
        log(f"[SourceMix] {ratio}% own requested — {already}/{total} question(s) already are and "
            f"{pool} could convert; nothing to reassign")
        return work_orders

    # Largest-remainder split of `need` across the sections that have room.
    shares = []
    for wo, idxs in free:
        exact = need * len(idxs) / pool
        shares.append([wo, idxs, int(exact), exact - int(exact)])
    _short = need - sum(sh[2] for sh in shares)
    for k in sorted(range(len(shares)), key=lambda i: (-shares[i][3], i))[:_short]:
        shares[k][2] += 1

    for wo, idxs, n, _ in shares:
        n = max(0, min(n, len(idxs)))
        if not n:
            continue
        # Evenly spaced picks (strictly increasing, since n <= len(idxs)) so book-based and own
        # questions alternate through the section instead of bunching at its front.
        chosen = {idxs[int(j * len(idxs) / n)] for j in range(n)}
        wo.own_count += len(chosen)
        if wo.slots:
            wo.slots = [
                (dict(sl, own_question=True) if i in chosen else sl)
                for i, sl in enumerate(wo.slots)
            ]

    _done = sum(wo.own_count for wo in work_orders)
    log(f"[SourceMix] {ratio}% own: {already + _done}/{total} question(s) composed by the model "
        f"({already} already own, {_done} reassigned), {total - already - _done} from the book: "
        + ", ".join(f"'{wo.section_name}' {wo.own_count}/{wo.questions_count}"
                    for wo in work_orders if wo.own_count))
    return work_orders


def plan_chapter_allocation(work_orders: list) -> list:
    """Give every section a per-question chapter plan (`wo.chapter_plan`), weighted by CBSE
    unit marks where known for that CLASS (uniform otherwise) and coordinated across the whole
    paper to maximise unique-chapter coverage before any chapter repeats. No-op for sections
    with no chapters (e.g. One-Mark tests) — they keep the legacy 'spread across all topics'
    prompt."""
    covered: dict = {}
    for wo in work_orders:
        eff_subject = wo.section_subject or wo.subject
        wo.chapter_plan = _allocate_chapters_to_slots(wo.chapters, wo.questions_count,
                                                      eff_subject, covered, wo.class_name)
    return work_orders


def apply_unit_map(work_orders: list, unit_map, log=print) -> list:
    """Overlay a teacher's ExamBlueprint unit map onto the automatic chapter allocation.

    `plan_chapter_allocation` above decides which chapter each question comes from using CBSE
    mark weights. A blueprint is the teacher overriding that decision — "Q1 from Electrostatics,
    Q2 from Current Electricity". This applies the override in two layers:

      1. SECTION level ("units"): restricts the section's candidate chapters to the named units
         and re-allocates the section's questions across just those. Used for whole-section
         statements ("Section C is all Optics") and for legacy patterns that have no
         question_slots to address individually.
      2. QUESTION level ("questions"): pins individual printed questions, on top of layer 1.

    Anything the map does not mention keeps its automatic allocation, so a partial blueprint is
    valid — constraining 3 questions must not require filling in all 38.

    Matched on PRINTED QUESTION NUMBER, never on position: a section can be told to generate more
    questions than it prints (attempt-N-of-M, `provided_count` > printed slots), so indexing
    chapter_plan by a slot's ordinal would assign the wrong unit to the wrong question.

    `unit_map` is whatever was stored on the blueprint — possibly hand-edited, half-saved or from
    an older schema. It must never raise into paper generation, so every lookup is defensive and
    an unusable map simply leaves the automatic allocation alone.
    """
    if not unit_map:
        return work_orders

    # Accept either the model instance or a plain dict, so callers (task, tests) can pass either.
    if hasattr(unit_map, "question_units"):
        per_question_by_sec = unit_map.question_units()
        section_units_by_sec = unit_map.section_units()
    else:
        from .models import ExamBlueprint
        proxy = ExamBlueprint(unit_map=unit_map if isinstance(unit_map, dict) else {})
        per_question_by_sec = proxy.question_units()
        section_units_by_sec = proxy.section_units()

    if not per_question_by_sec and not section_units_by_sec:
        return work_orders

    def _for(wo, table):
        """A section's entry, matched by id first then by name — the builder writes the id the
        work order derives, but a hand-written map keyed by 'Section A' should still work."""
        for key in (wo.section_id, wo.section_name):
            if key and str(key) in table:
                return table[str(key)]
        return None

    covered: dict = {}
    for wo in work_orders:
        eff_subject = wo.section_subject or wo.subject

        # ── layer 1: section-wide units ───────────────────────────────────────────
        units = _for(wo, section_units_by_sec)
        if units:
            wo.chapters = list(units)
            wo.chapter_plan = _allocate_chapters_to_slots(
                units, wo.questions_count, eff_subject, covered, wo.class_name)
            log(f"[UnitMap] '{wo.section_name}': section restricted to {', '.join(units)}")

        # ── layer 2: individual printed questions ─────────────────────────────────
        per_q = _for(wo, per_question_by_sec)
        if not per_q:
            continue

        # chapter_plan may be empty when the paper had no chapters at all (one-mark tests) — the
        # blueprint is then the only source of chapters, so build a plan to overwrite.
        if not wo.chapter_plan:
            wo.chapter_plan = [""] * max(0, int(wo.questions_count or 0))

        # Chapter-shaped strings this section already knows about — used to decide whether a
        # slot's inherited `topic` is a rival chapter name or a skill within one.
        chapterish = {str(c).strip().lower() for c in (wo.chapters or []) if c}
        chapterish |= {str(u).strip().lower() for u in per_q.values()}

        pinned = []
        for pos, slot in enumerate(wo.slots or []):
            try:
                qnum = int(slot.get("qnum"))
            except (TypeError, ValueError):
                continue
            unit = per_q.get(qnum)
            if not unit or pos >= len(wo.chapter_plan):
                continue
            wo.chapter_plan[pos] = unit
            slot["chapter"] = unit      # read by the per-question prompt block

            # Patterns imported from a CBSE sample paper carry a per-slot `topic` lifted from
            # that paper ("Electrostatics"). If the teacher pins a DIFFERENT chapter, the prompt
            # would state both — 'draw from Optics' AND 'TOPIC: Electrostatics' — and the model
            # has to guess which to obey. The teacher's pin is the deliberate instruction, so a
            # topic that is itself a rival CHAPTER name is dropped. A topic naming a skill inside
            # a chapter ("Homophones", "Past perfect tense") is complementary and kept.
            topic = str(slot.get("topic") or "").strip()
            if topic and topic.lower() != unit.strip().lower() and topic.lower() in chapterish:
                slot.pop("topic", None)
                log(f"[UnitMap] '{wo.section_name}': Q{qnum} topic '{topic}' dropped — teacher "
                    f"pinned chapter '{unit}' instead")

            pinned.append(f"Q{qnum}->{unit}")

        # Any unit the teacher pinned must be a candidate for retrieval too, or the section gets
        # no context for it.
        for unit in dict.fromkeys(per_q.values()):
            if unit not in (wo.chapters or []):
                wo.chapters = list(wo.chapters or []) + [unit]

        if pinned:
            log(f"[UnitMap] '{wo.section_name}': {len(pinned)} question(s) pinned — "
                f"{', '.join(pinned)}")
        # A map naming questions this section does not print is a stale blueprint (the pattern
        # was edited under it). Say so rather than silently ignoring the teacher's intent.
        printed = {int(s.get("qnum")) for s in (wo.slots or [])
                   if str(s.get("qnum") or "").lstrip("-").isdigit()}
        unknown = sorted(q for q in per_q if q not in printed)
        if unknown:
            log(f"[UnitMap] '{wo.section_name}': blueprint maps Q{unknown} which this section "
                f"does not print — pattern changed since the blueprint was made; ignored")

    return work_orders


# ─────────────────────────────────────────────
# Sums / quiz composition (Accountancy)
# ─────────────────────────────────────────────
# An Accountancy paper must be 80% SUMS (numerical / practical problems — journal entries,
# ledger, final accounts, revaluation, goodwill valuation, ratios from given figures) and 20%
# QUIZ (definitions, concepts, rules, formats) BY MARKS. Left to itself the model writes
# theory-heavy Accountancy papers: an SA slot comes back as "Explain the features of a
# partnership" where the teacher needs "Pass the journal entries for the following
# transactions".
#
# The blueprint fixes each section's marks and counts, so the ratio cannot be met by changing
# the structure — it is met by choosing WHICH questions are sums. plan_sums_allocation spends
# the 20% quiz budget on the cheapest objective questions first (1-mark MCQs are the natural
# quiz carriers) and declares everything else a sum, which is what makes the leftover objective
# marks come back as NUMERICAL MCQs ("Calculate the interest on capital: ₹4,000 / ₹5,000 / …").
# Each section then gets a concrete count in its prompt rather than a paper-wide aspiration.

# Subject → required share of paper MARKS that must be sums. Accountancy-scoped by request;
# every other subject's composition is governed by the CBSE competency split instead.
_SUMS_MARKS_SHARE = {
    "accountancy": 0.80,
    "accounts": 0.80,
    "book keeping": 0.80,
    "book-keeping": 0.80,
    "bookkeeping": 0.80,
}

# How far the finished paper may drift from the target before enforcement regenerates anything.
SUMS_SHARE_TOLERANCE = 0.05
# Cap on regenerations per paper, so a stubborn model can't run the token bill up.
SUMS_MAX_REGENS = 6


def _sums_share_for_subject(subject: str) -> float:
    """Required sums MARKS share for this subject, or 0.0 when the subject has no such rule."""
    s = str(subject or "").lower()
    for marker, share in _SUMS_MARKS_SHARE.items():
        if marker in s:
            return share
    return 0.0


def _question_marks_plan(wo: SectionWorkOrder) -> list:
    """Per-question (marks, is_objective) for one section, one entry per generated question.

    Reads the slots first (they state every printed question), then the per-type breakdown,
    and falls back to the section's uniform marks_per_question.
    """
    n = wo.questions_count or 0
    out = []
    if wo.slots:
        for s in wo.slots:
            if not isinstance(s, dict):
                continue
            cat = pattern_structure.slot_category(str(s.get("type") or ""))
            m = _as_float(s.get("marks"), wo.marks_per_question)
            out.append((m, cat == "mcq" or m <= 1))
    if not out:
        for t in (wo.question_types or []):
            if not isinstance(t, dict) or "marks_each" not in t:
                continue
            cat = _fine_category(t.get("type", ""))
            m = _as_float(t.get("marks_each"), wo.marks_per_question)
            for _ in range(_as_int(t.get("count"), 0) or 0):
                out.append((m, cat in ("mcq", "ar") or m <= 1))
    if not out:
        cats = [_fine_category(t if isinstance(t, str) else t.get("type", ""))
                for t in (wo.question_types or [])]
        m = _as_float(wo.marks_per_question, 1.0)
        objective = bool(cats) and all(c in ("mcq", "ar") for c in cats) or m <= 1
        out = [(m, objective)] * n
    return out[:n] if n else out


def plan_sums_allocation(work_orders: list) -> list:
    """Set `wo.sums_count` / `wo.sums_share` so the paper hits its sums MARKS target.

    Spends the quiz budget ((1 - share) of total marks) on the cheapest OBJECTIVE questions
    first, then on the cheapest written ones if the objective marks alone cannot cover it.
    Every remaining question is a sum. No-op for subjects with no sums rule, so no other
    subject's work orders change.
    """
    if not work_orders:
        return work_orders
    share = _sums_share_for_subject(work_orders[0].section_subject or work_orders[0].subject)
    if not share:
        return work_orders

    slots = []            # (sec_idx, q_idx, marks, is_objective)
    for si, wo in enumerate(work_orders):
        for qi, (marks, objective) in enumerate(_question_marks_plan(wo)):
            slots.append((si, qi, marks, objective))
    total = sum(s[2] for s in slots)
    if total <= 0:
        return work_orders

    quiz_budget = (1.0 - share) * total
    # Objective first, then ascending marks — a 1-mark MCQ is the cheapest way to spend the quiz
    # budget, which leaves the expensive written questions (and any leftover objective marks) as
    # sums. Question index BEFORE section index, so the budget is spent round-robin across the
    # objective sections: every one of them then carries a share of the numerical MCQs, instead
    # of one section going pure-theory and another pure-numerical.
    order = sorted(slots, key=lambda s: (not s[3], s[2], s[1], s[0]))
    quiz = set()
    spent = 0.0
    for si, qi, marks, _obj in order:
        if spent + marks > quiz_budget + 1e-9:
            continue                      # would overshoot the budget — leave it as a sum
        quiz.add((si, qi))
        spent += marks

    for si, wo in enumerate(work_orders):
        n = len(_question_marks_plan(wo))
        wo.sums_count = sum(1 for qi in range(n) if (si, qi) not in quiz)
        wo.sums_share = share
    sums_marks = total - spent
    print(f"[Sums-Plan] target {share:.0%} sums by marks → {sums_marks:g}/{total:g} "
          f"({sums_marks / total:.0%}) sums, {spent:g}m quiz | per section: "
          + ", ".join(f"{wo.section_name}={wo.sums_count}/{len(_question_marks_plan(wo))}"
                      for wo in work_orders))
    return work_orders


def build_work_orders(blueprint: dict, pattern, context_map: dict, difficulty: str, class_name: str, subject: str, chapters: list, disable_images: bool = False,
                      unit_map=None, creative_ratio: int = 0) -> list:
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
            # The holder carries the attempt quota and the instructions it can be read from, or
            # derive_aggregates_from_slots would price an "answer any SIX of eight" section at
            # all eight questions and the section would print the wrong marks.
            holder = {
                "question_slots": slots,
                "attempt": sec_data.get("attempt") or ps.get("attempt"),
                "instructions": ps.get("instructions", sec_data.get("instructions", [])),
            }
            pattern_structure.normalize_slots([holder])
            pattern_structure.derive_aggregates_from_slots([holder])
            sec_data = dict(sec_data)
            sec_data["questions_count"] = holder.get("questions_count", len(slots))
            if holder.get("attempt"):
                sec_data["attempt"] = holder["attempt"]
                sec_data["attempt_count"] = holder["attempt"]
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
                # 2 decimals, not 1: a pattern stating 2.25m/question must not drift to
                # 2.2 here — reconcile_uniform_marks stamps THIS value onto every
                # question and the paper audit then flags each one against the slots.
                mpq = round(typed_marks / typed_count, 2)
                # The typed breakdown describes every question the section PRINTS. wo.marks
                # budgets what a student can EARN, which for "answer any SIX of these eight"
                # is 6 x 2 = 12, not 16 — validate_section_output scales it back up by
                # provided/attempt to check the eight generated questions.
                _sec_attempt = _as_int(sec_data.get("attempt"), 0)
                marks = (int(round(mpq * _sec_attempt))
                         if 0 < _sec_attempt < typed_count else int(round(typed_marks)))

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

        # English grammar / creative writing: force every own-knowledge slot to source='general'
        # so the existing general-knowledge machinery applies to it — the per-slot "do NOT take
        # this from the textbook or the reference material" prompt line, the chapter-assignment
        # exemption and the chapter-name validator. Copied, not mutated in place: these slot
        # dicts belong to the blueprint/pattern and are read again elsewhere.
        eng_own_kinds, eng_own_only, eng_own_slots = english_own_scope(
            subject, section_subject, sec_name, sec_data, slots)
        if eng_own_slots:
            slots = [
                (dict(s, source="general") if i in eng_own_slots else s)
                for i, s in enumerate(slots)
            ]
            print(f"[English-Own] '{sec_name}': {len(eng_own_slots)}/{len(slots)} slot(s) "
                  f"forced to source=general ({'/'.join(eng_own_kinds)} — own knowledge, "
                  "no textbook content)")
        elif eng_own_kinds:
            print(f"[English-Own] '{sec_name}': {'/'.join(eng_own_kinds)} section"
                  f"{' — no context, no chapter assignment' if eng_own_only else ''}")

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
            context_text="" if (_all_general or eng_own_only) else context_map.get(sec_name, ""),
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
            context_by_type={} if (_all_general or eng_own_only) else context_by_type_all.get(sec_name, {}),  # 3.2
            slots=slots,
            is_grammar=sec_is_grammar,
            is_english_grammar="grammar" in eng_own_kinds,
            is_english_writing="writing" in eng_own_kinds,
            english_own_only=eng_own_only,
            disable_images=disable_images,
        )
        work_orders.append(wo)
        subj_tag = f" [{section_subject}]" if section_subject else ""
        slot_tag = f", slots={len(slots)}" if slots else ""
        print(f"[WorkOrder] '{sec_name}'{subj_tag}: {generate_count}q × {mpq}m = {marks}m, types={types_list}{slot_tag}")

    # Deterministic, CBSE-weighted, paper-wide chapter allocation (sets wo.chapter_plan).
    plan_chapter_allocation(work_orders)
    # A teacher's blueprint overrides that allocation where it states one (no-op without one).
    apply_unit_map(work_orders, unit_map)
    # Book ↔ own-composition mix from the generate page's meter (no-op at the 0 default).
    plan_creative_allocation(work_orders, creative_ratio)
    # Accountancy sums/quiz composition (sets wo.sums_count) — no-op for other subjects.
    plan_sums_allocation(work_orders)
    for wo in work_orders:
        if wo.chapter_plan:
            from collections import Counter
            dist = ", ".join(f"{ch}×{n}" for ch, n in Counter(wo.chapter_plan).items())
            print(f"[ChapterPlan] '{wo.section_name}': {dist}")

    return work_orders


# ─────────────────────────────────────────────
# Cross-section validation (numbering)
# ─────────────────────────────────────────────

CROSS_SECTION_DUP_THRESHOLD = 0.55


def _cross_section_dup_pairs(paper_data: dict, threshold: float = CROSS_SECTION_DUP_THRESHOLD):
    """[(sec_i, idx_i, sec_j, idx_j, score)] for near-duplicate pairs in DIFFERENT sections.

    Same-section pairs are excluded — validate_uniqueness + verify_and_fix_semantic_duplicates
    already handle those during per-section generation.
    """
    items = []
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        for idx, q in enumerate(sec_data.get("questions", [])):
            text = _comparable_text(q)
            if text:
                items.append((sec_name, idx, text))
    pairs = []
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            sec_i, idx_i, text_i = items[a]
            sec_j, idx_j, text_j = items[b]
            if sec_i == sec_j:
                continue
            score = _concept_overlap(text_i, text_j)
            if score > threshold:
                pairs.append((sec_i, idx_i, sec_j, idx_j, score))
    return pairs


def fix_cross_section_duplicates(paper_data: dict, work_orders: list) -> tuple:
    """Replace questions duplicated ACROSS sections. Returns (paper_data, in_tok, out_tok).

    Cross-section duplicates were detected but never acted on: cross_section_validate logged
    them and handed them to the final LLM audit as a warning, so a paper that asked the same
    thing in Section A and Section D shipped with both. Sections are generated in parallel by
    independent prompts, so neither one can see the other's questions — this is the only place
    the overlap can be caught.

    Mirrors the within-section chain: heuristic pair detection → LLM confirmation (so a
    code-only 55% token overlap never removes a legitimate question on its own) → in-place
    replacement through _regen_replacement_question, which keeps type, marks and qnum. The
    question count never changes, so no section can be left short.
    """
    pairs = _cross_section_dup_pairs(paper_data)
    if not pairs:
        return paper_data, 0, 0

    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    in_tok = out_tok = 0
    replaced = set()                       # (sec, idx) already swapped — don't touch twice
    unresolved = []

    for sec_i, idx_i, sec_j, idx_j, score in pairs:
        if (sec_i, idx_i) in replaced or (sec_j, idx_j) in replaced:
            continue                       # one of the pair is already a fresh question
        try:
            q_i = paper_data[sec_i]["questions"][idx_i]
            q_j = paper_data[sec_j]["questions"][idx_j]
        except (KeyError, IndexError):
            continue
        label = (f"Q{q_i.get('qnum', idx_i + 1)} ({sec_i}) ↔ "
                 f"Q{q_j.get('qnum', idx_j + 1)} ({sec_j}) — {score:.0%} concept overlap")

        confirm_prompt = (
            "Do these two questions from the SAME exam paper test the same knowledge or "
            "concept? Answer true only if a student who can answer one can answer the other "
            "for the same reason.\n\n"
            f"A: {str(_comparable_text(q_i))[:250]}\n\n"
            f"B: {str(_comparable_text(q_j))[:250]}\n\n"
            "Answer with JSON only:\n"
            '{"same_concept": true, "reason": "one sentence"}'
        )
        try:
            raw, i_t, o_t = mantle_client.converse(
                model_id=mantle_client.VAL_MODEL, prompt=confirm_prompt,
                max_tokens=100, temperature=0.1, stage="dup-confirm")
            in_tok += i_t
            out_tok += o_t
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not (json.loads(m.group()) if m else {}).get("same_concept", False):
                print(f"[Cross-Dup] not a duplicate (L1 false positive): {label}")
                continue
        except Exception as e:
            print(f"[Cross-Dup] confirmation failed ({e}) — leaving both: {label}")
            unresolved.append(label)
            continue

        # Replace the LATER question: the earlier section usually owns the concept (Reading
        # before Literature), and its work order is the one whose spec the pair matched first.
        # Fall back to the other side when the later one is structurally heavy (CBQ/map).
        order = [(sec_j, idx_j, q_j, q_i), (sec_i, idx_i, q_i, q_j)]
        if _fine_category(q_j.get("type", ""), str(q_j.get("subtype", ""))) in ("cbq", "map"):
            order.reverse()

        for tgt_sec, tgt_idx, tgt_q, keep_q in order:
            wo = wo_by_name.get(tgt_sec)
            if not wo:
                continue
            print(f"[Cross-Dup] confirmed: {label} — regenerating in '{tgt_sec}'")
            new_q, i_t, o_t = _regen_replacement_question(
                tgt_q, tgt_idx, wo, str(keep_q.get("text", ""))[:150], tag="Cross-Dup")
            in_tok += i_t
            out_tok += o_t
            if new_q:
                paper_data[tgt_sec]["questions"][tgt_idx] = new_q
                replaced.add((tgt_sec, tgt_idx))
                break
        else:
            # Neither side could be safely regenerated (CBQ/map, no work order, or the model
            # drifted) — keep both and let the final audit report the overlap.
            unresolved.append(label)

    print(f"[Cross-Dup] {len(replaced)} replaced, {len(unresolved)} left flagged "
          f"(of {len(pairs)} candidate pair(s))")
    if unresolved:
        for sec_data in paper_data.values():
            if isinstance(sec_data, dict):
                sec_data.setdefault("_cross_section_duplicates", unresolved)
    return paper_data, in_tok, out_tok


def cross_section_validate(paper_data: dict, blueprint: dict) -> dict:
    """Renumber questions sequentially and run cross-section deduplication."""
    # Renumber
    q_num = 1
    for sec_name in blueprint.keys():
        for q in paper_data.get(sec_name, {}).get("questions", []):
            q["qnum"] = q_num
            q_num += 1

    # Cross-section dedup (3.1) — code-only, no LLM cost. This is the REPORT pass, run after
    # renumbering: fix_cross_section_duplicates has already replaced the confirmed ones, so
    # anything still here is either an LLM-cleared false positive or a pair it could not
    # safely regenerate.
    cross_dupes = []
    for sec_i, idx_i, sec_j, idx_j, score in _cross_section_dup_pairs(paper_data):
        qnum_i = paper_data[sec_i]["questions"][idx_i].get("qnum", idx_i + 1)
        qnum_j = paper_data[sec_j]["questions"][idx_j].get("qnum", idx_j + 1)
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

def validate_sums_distribution(paper_data: dict, subject: str) -> dict:
    """Measure the finished paper's sums/quiz MARKS split against the subject's target.

    Returns {} for subjects with no sums rule, so this is free for every other paper.
    """
    share = _sums_share_for_subject(subject)
    if not share:
        return {}
    sums, quiz = _sums_marks_split(paper_data)
    total = sums + quiz
    if total <= 0:
        return {"target_pct": round(share * 100, 1), "compliant": False,
                "violations": ["No questions found"]}
    got = sums / total
    violations = []
    if got < share - SUMS_SHARE_TOLERANCE:
        violations.append(
            f"Sums {got:.0%} of marks < {share:.0%} target "
            f"({sums:g}m sums vs {quiz:g}m quiz) — paper is theory-heavy")
    elif got > share + SUMS_SHARE_TOLERANCE:
        violations.append(
            f"Sums {got:.0%} of marks > {share:.0%} target "
            f"({sums:g}m sums vs {quiz:g}m quiz) — too few conceptual questions")
    result = {
        "target_pct": round(share * 100, 1),
        "sums_pct": round(got * 100, 1),
        "quiz_pct": round((1 - got) * 100, 1),
        "sums_marks": sums, "quiz_marks": quiz, "total_marks": total,
        "compliant": not violations,
        "violations": violations,
    }
    if violations:
        print(f"[SumsCheck] ⚠️  {violations}")
    else:
        print(f"[SumsCheck] ✅ sums {got:.0%} / quiz {1 - got:.0%} "
              f"(target {share:.0%}) — {sums:g}m / {quiz:g}m")
    return result


# The MANDATORY requirement handed to a regenerated question that must be a sum.
_SUMS_REGEN_RULE = (
    "MANDATORY: this question MUST be a NUMERICAL / PRACTICAL problem (a \"sum\"), not a theory "
    "question. Supply the actual figures in ₹ (with dates and names where relevant) and ask the "
    "student to work something out — journalise, pass entries, prepare an account or statement, "
    "calculate, ascertain, distribute, value goodwill, or compute a ratio from the figures "
    "given. Do NOT ask for a definition, an explanation, a format or a list. Put the full "
    "working in \"answer_explanation\"."
)


def enforce_sums_distribution(paper_data: dict, work_orders: list, subject: str) -> tuple:
    """Regenerate theory questions that were planned as sums. Returns (paper_data, in, out).

    Only runs for a sums subject that finished BELOW target. Targets the questions the plan
    allocated to sums but that came back as theory, highest marks first (one 6-mark long answer
    buys back more of the ratio than six 1-mark MCQs), capped at SUMS_MAX_REGENS. A replacement
    that still classifies as quiz is discarded, so this can never make the split worse.
    """
    share = _sums_share_for_subject(subject)
    if not share:
        return paper_data, 0, 0
    sums, quiz = _sums_marks_split(paper_data)
    total = sums + quiz
    if total <= 0 or sums / total >= share - SUMS_SHARE_TOLERANCE:
        return paper_data, 0, 0

    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    # A section planned for K sums but holding fewer is where the shortfall lives. Offer its
    # quiz-classified questions as candidates, richest first.
    candidates = []
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        wo = wo_by_name.get(sec_name)
        if not wo or not wo.sums_count:
            continue
        qs = sec_data.get("questions", [])
        natures = [_question_nature(q) for q in qs]
        deficit = wo.sums_count - natures.count("sums")
        if deficit <= 0:
            continue
        quiz_idxs = [i for i, nat in enumerate(natures) if nat == "quiz"]
        quiz_idxs.sort(key=lambda i: -_as_float(qs[i].get("marks"), 0.0))
        for i in quiz_idxs[:deficit]:
            candidates.append((_as_float(qs[i].get("marks"), 0.0), sec_name, i))
    candidates.sort(key=lambda c: -c[0])

    in_tok = out_tok = 0
    fixed = attempts = 0
    need = (share - SUMS_SHARE_TOLERANCE) * total - sums     # marks still to convert
    for marks, sec_name, idx in candidates:
        # Cap ATTEMPTS, not successes: a model that keeps returning theory would otherwise
        # retry every candidate in the paper and blow past the intended call budget.
        if attempts >= SUMS_MAX_REGENS or need <= 0:
            break
        attempts += 1
        wo = wo_by_name[sec_name]
        orig = paper_data[sec_name]["questions"][idx]
        new_q, i_t, o_t = _regen_replacement_question(
            orig, idx, wo, tag="Sums", extra_rule=_SUMS_REGEN_RULE)
        in_tok += i_t
        out_tok += o_t
        if not new_q:
            continue
        if _question_nature(new_q) != "sums":
            print(f"[Sums] '{sec_name}' Q{idx+1} regen came back theory again — keeping original")
            continue
        paper_data[sec_name]["questions"][idx] = new_q
        fixed += 1
        need -= marks

    sums2, quiz2 = _sums_marks_split(paper_data)
    print(f"[Sums] converted {fixed}/{attempts} attempted question(s) to sums — "
          f"{sums:g}m → {sums2:g}m of {sums2 + quiz2:g}m ({sums2 / max(1e-9, sums2 + quiz2):.0%})")
    return paper_data, in_tok, out_tok


# ─────────────────────────────────────────────
# V11 — Answer-leak audit (one question giving away another's answer)
# ─────────────────────────────────────────────
#
# The gap this closes: _cross_section_dup_pairs measures SYMMETRIC similarity between question
# stems. Answer leakage is a different shape and slips straight through it —
#   • it is ASYMMETRIC. The answer to Q7 sits in the STEM of Q3. "Assertion: the Dandi March was
#     a satyagraha against the salt tax" and "Why did Gandhi choose salt? (2m)" share almost no
#     tokens; the overlap score sees two different questions, because they ARE two different
#     questions.
#   • it DILUTES. A 2-mark answer is one sentence inside a 150-word case study. Token overlap
#     normalised over the whole passage lands near zero — so the longer the passage, the more
#     invisible the leak, which is exactly backwards.
# Neither existing paper-level audit can see it either: V8 is given only type/chapter summaries
# and V10 only the accumulated warning strings. Neither ever reads question text.

ANSWER_LEAK_MAX_REGENS = 4
_LEAK_STEM_CHARS = 320
_LEAK_ANS_CHARS = 320
_LEAK_PASSAGE_CHARS = 1200
_LEAK_MIN_SPAN_WORDS = 5
_LEAK_MAX_HINTS = 12


def _leak_flat(t, limit: int) -> str:
    """Single-line, length-capped text for prompt blocks. A helper rather than an inline
    re.sub because a backslash inside an f-string expression is a syntax error before 3.12."""
    return re.sub(r"\s+", " ", str(t or "")).strip()[:limit]


def _leak_norm(t) -> str:
    """Whitespace/case/punctuation-insensitive form, used ONLY to confirm a span the model
    quoted really does occur in the leaker's printed body.

    Collapses every non-word RUN — punctuation and whitespace together — to one space. Doing it
    in two passes (whitespace then punctuation) is wrong: 'press, and' becomes 'press  and' with
    a double space and no longer matches 'press and' in the source, so a real leak quoted with
    one comma out of place would be thrown away as a hallucination.

    Strips PUNCTUATION AND WHITESPACE, rather than keeping only [a-z0-9] or only \\w — both of
    those silently destroy this check on most of the catalogue:
      • [a-z0-9] normalised every Tamil/Hindi/Sanskrit span to the EMPTY string, so every finding
        on those papers was dropped as "span too short" and V11 was a silent no-op for them; and
        on Maths/Science it stripped Greek letters and superscripts, collapsing 'cot θ = cos θ /
        sin θ' to 'cot cos sin' — three tokens of pure notation unrelated formulas also match.
      • \\w excludes Indic combining marks (categories Mn/Mc), which fragments 'இலக்கணம்' into
        'இலக கணம' — consistent, so matching still works, but it inflates word counts and makes
        the span floor meaningless for those languages.
    Removing ASCII punctuation plus General Punctuation (U+2000–206F, i.e. — – " ' …) keeps every
    letter, digit, Greek symbol, superscript and combining mark exactly as written.
    """
    return re.sub(r"[\s!-/:-@\[-`{-~ -⁯]+", " ", str(t or "").lower()).strip()


def _disclosure_text(q: dict) -> str:
    """Everything about a question that a STUDENT ACTUALLY READS — stem, MCQ option texts, the
    OR alternative, its own case/source passage, and its sub-question stems.

    Deliberately EXCLUDES answer_explanation/answer. The marking key is never printed on the
    student's paper, so a key that happens to restate another question's answer cannot help
    anyone in the exam hall. Including it would flood the audit with unfixable non-findings.
    """
    if not isinstance(q, dict):
        return str(q or "")
    parts = [str(q.get("text", "") or ""), str(q.get("or_alternative", "") or "")]
    opts = q.get("options")
    if isinstance(opts, dict):
        parts.extend(str(v) for v in opts.values())
    elif isinstance(opts, list):
        parts.extend(str(v) for v in opts)
    src = q.get("source_text") or q.get("passage")
    if src:
        parts.append(str(src))
    for sq in (q.get("sub_questions") or []):
        parts.append(str(sq.get("text", "") or "") if isinstance(sq, dict) else str(sq))
    return "\n".join(p for p in parts if p).strip()


def _victim_answer_text(q: dict) -> str:
    """The answer this question is protecting. For an MCQ the stored letter says nothing on its
    own — the correct option's TEXT is what must stay secret. Sub-question keys count too, so a
    CBQ's own answers can be checked against other sections."""
    if not isinstance(q, dict):
        return ""
    parts = [str(q.get("answer_explanation", "") or "")]
    opts, ans = q.get("options"), str(q.get("answer", "") or "").strip().lower()
    if isinstance(opts, dict) and ans in opts:
        parts.insert(0, str(opts[ans]))
    for sq in (q.get("sub_questions") or []):
        if isinstance(sq, dict) and sq.get("answer_explanation"):
            parts.append(str(sq["answer_explanation"]))
    return " ".join(p for p in parts if p).strip()


def _leak_inventory(paper_data: dict) -> list:
    """One record per auditable SURFACE on the paper, in printed order.

    kind 'q' = a question (id S<i>Q<n>, n is its POSITION in the section, not its qnum, so the
    id stays stable across the renumbering in cross_section_validate).
    kind 'p' = a section-level reading passage (id S<i>P) that every question in its own
    section is meant to draw on.
    """
    inv = []
    si = 0
    for sec_name, sec_data in paper_data.items():
        if sec_name.startswith("__") or not isinstance(sec_data, dict):
            continue
        si += 1
        passage = str(sec_data.get("passage", "") or "")
        if len(passage) >= 50:
            inv.append({"id": f"S{si}P", "kind": "p", "sec": sec_name, "idx": None,
                        "qnum": None, "marks": 0.0, "cat": "passage",
                        "disclosure": passage, "answer": ""})
        for idx, q in enumerate(sec_data.get("questions", [])):
            if not isinstance(q, dict):
                continue
            inv.append({
                "id": f"S{si}Q{idx + 1}", "kind": "q", "sec": sec_name, "idx": idx,
                "qnum": q.get("qnum", idx + 1), "marks": _as_float(q.get("marks"), 0.0),
                "cat": _fine_category(q.get("type", ""), str(q.get("subtype", ""))),
                "disclosure": _disclosure_text(q), "answer": _victim_answer_text(q),
            })
    return inv


def _leak_pair_allowed(victim: dict, leaker: dict) -> bool:
    """Reject the pairs where shared content is the DESIGN, not a defect.

    A reading/case passage exists precisely so the questions printed beside it can draw on it —
    V6 actively REQUIRES every sub-question to be answerable from the passage alone. So a
    section passage never "leaks" to its own section, and nothing leaks to itself. The same
    overlap across sections is a genuine leak.
    """
    if victim["id"] == leaker["id"]:
        return False
    if victim["kind"] != "q" or not victim["answer"]:
        return False                       # a passage has no answer of its own to give away
    if leaker["kind"] == "p" and leaker["sec"] == victim["sec"]:
        return False
    return True


def _leak_prefilter(inv: list) -> list:
    """Cheap deterministic pass: a victim's answer copied VERBATIM into something a student
    reads. Returns [(victim_id, leaker_id, span)].

    Used as a HINT to the auditor, never as a gate. The Assertion-Reason case that prompted
    this check paraphrases rather than copies, so gating on a verbatim match would miss exactly
    the defect we are looking for.
    """
    hits = []
    for v in inv:
        if v["kind"] != "q" or not v["answer"]:
            continue
        for lk in inv:
            if not _leak_pair_allowed(v, lk):
                continue
            span = _lifted_span(v["answer"], lk["disclosure"], span=8, content_floor=4)
            # Hold hints to the SAME floor the audit applies to a reported span. Without this the
            # prefilter emits hints the verifier would itself reject — on the first live Maths
            # paper both hints were shared notation ('cot θ = cos θ / sin θ', 'sin x = -1/2 in
            # [0, 2π)'), one of them only 3 normalised tokens long. Pointing the auditor at noise
            # is worse than pointing it nowhere: it invites confirmation of a non-leak.
            if span and len(_leak_norm(span).split()) >= _LEAK_MIN_SPAN_WORDS:
                hits.append((v["id"], lk["id"], span))
                break                      # one hint per victim is enough to point the auditor
    return hits


def _audit_converse(prompt: str, max_tokens: int = 1200) -> tuple:
    """Paper-level audit call on AUDIT_MODEL, degrading to GEN_MODEL.

    AUDIT_MODEL is deliberately a stronger reasoner that is NOT confirmed against this endpoint
    the way GEN/VAL are, so an unknown-model error must cost us the model, not the audit.
    Returns (raw, in_tok, out_tok, model_used); model_used == "" means every candidate failed.
    """
    audit_model = str(getattr(mantle_client, "AUDIT_MODEL", "") or "").strip()
    for model_id in [m for m in dict.fromkeys([audit_model, GEN_MODEL]) if m]:
        try:
            raw, i_t, o_t = mantle_client.converse(
                model_id=model_id, prompt=prompt, max_tokens=max_tokens, temperature=0.1,
                stage="v11-answer-leak")
            return raw, i_t, o_t, model_id
        except Exception as e:
            print(f"[Leak] audit model '{model_id}' unavailable ({e})")
    return "", 0, 0, ""


def run_answer_leak_audit(paper_data: dict, class_name: str, subject: str) -> tuple:
    """
    V11 — cross-question answer-leak audit. ONE LLM call for the whole assembled paper.

    Returns (findings, in_tok, out_tok). Each finding is
      {"victim": id, "leaker": id, "leaked_span": str, "why": str}
    and every one has had its leaked_span CONFIRMED to occur verbatim in the leaker's printed
    body. That verification is the load-bearing part: without it an unverified audit invents
    leaks and the fixer below rewrites perfectly good questions. A finding the model cannot
    quote is dropped, which costs nothing.

    Pairwise prompting is not an option — a 35-question paper is ~600 pairs. The whole paper
    goes in one prompt (~5-6k input) and the model returns a list.
    """
    inv = _leak_inventory(paper_data)
    by_id = {it["id"]: it for it in inv}
    if len([it for it in inv if it["kind"] == "q"]) < 2:
        return [], 0, 0

    lines = []
    for it in inv:
        if it["kind"] == "p":
            lines.append(f"[{it['id']}] SECTION READING PASSAGE (printed once for its section)")
            lines.append(f"  PRINTED: {_leak_flat(it['disclosure'], _LEAK_PASSAGE_CHARS)}")
            continue
        lines.append(f"[{it['id']}] {it['marks']:g} marks, {it['cat'].upper()}")
        lines.append(f"  PRINTED: {_leak_flat(it['disclosure'], _LEAK_STEM_CHARS)}")
        if it["answer"]:
            lines.append(f"  ANSWER (kept secret — never printed): "
                         f"{_leak_flat(it['answer'], _LEAK_ANS_CHARS)}")

    hints = _leak_prefilter(inv)
    hint_block = ""
    if hints:
        hint_lines = "\n".join(
            f"  • {v} may be given away by {lk}: \"{_leak_flat(sp, 120)}\""
            for v, lk, sp in hints[:_LEAK_MAX_HINTS])
        hint_block = (
            "\nA verbatim-text scan already flagged these as WORTH CHECKING FIRST. They are "
            "unconfirmed — judge each one yourself, and look for leaks it missed (a paraphrased "
            "leak is still a leak and the scan cannot see those):\n" + hint_lines + "\n")

    prompt = (
        f"You are the answer-leak auditor for a CBSE Class {class_name} {subject} question paper.\n\n"
        "A LEAK is when the PRINTED body of one item — its stem, its options, its OR-alternative "
        "or its case/source passage — states or plainly gives away the secret ANSWER to a "
        "DIFFERENT question on the same paper. The test: could a student who had studied nothing "
        "answer the second question correctly just by reading the first?\n\n"
        "Leaks look like:\n"
        "  • an Assertion-Reason item whose assertion states the very fact another question asks for\n"
        "  • a case/source passage containing the answer to a standalone question elsewhere on the paper\n"
        "  • an MCQ option that spells out what another question asks about\n\n"
        "These are NOT leaks — do not report them:\n"
        "  • a passage and the questions printed with it that are meant to draw on it\n"
        "  • two questions on the same topic that require different answers\n"
        "  • anything revealed only by an ANSWER line — those are marking keys, never printed for students\n"
        "  • general subject vocabulary or a shared technical term appearing in both\n\n"
        f"PAPER ITEMS:\n" + "\n".join(lines) + "\n"
        f"{hint_block}\n"
        "For every leak you report, quote the EXACT words from the LEAKER's PRINTED body that "
        "give the answer away — copied character-for-character, at least 6 words, and it must "
        "appear in that item's PRINTED line above (never from an ANSWER line). If you cannot "
        "quote it verbatim, do not report it.\n\n"
        "Output JSON only:\n"
        '{"leaks": [{"victim": "S1Q7", "leaker": "S2P", '
        '"leaked_span": "exact words copied from the leaker", "why": "one sentence"}]}\n'
        'If nothing leaks, output exactly {"leaks": []}'
    )

    raw, in_tok, out_tok, model_used = _audit_converse(prompt)
    if not model_used:
        print("[Leak] audit unavailable — no model answered; paper unchanged")
        return [], in_tok, out_tok
    try:
        m = re.search(r"\{.*\}", raw or "", re.S)
        reported = (json.loads(m.group()) if m else {}).get("leaks", []) or []
    except Exception as e:
        print(f"[Leak] could not parse audit response ({e}) — paper unchanged")
        return [], in_tok, out_tok

    findings, seen = [], set()
    for item in reported:
        if not isinstance(item, dict):
            continue
        v_id = str(item.get("victim", "") or "").strip().upper()
        l_id = str(item.get("leaker", "") or "").strip().upper()
        span = str(item.get("leaked_span", "") or "").strip()
        v_rec, l_rec = by_id.get(v_id), by_id.get(l_id)
        if not v_rec or not l_rec:
            print(f"[Leak] dropped — unknown item id ({v_id!r} ← {l_id!r})")
            continue
        if not _leak_pair_allowed(v_rec, l_rec):
            print(f"[Leak] dropped — {v_id} ← {l_id} is by design, not a leak")
            continue
        if len(_leak_norm(span).split()) < _LEAK_MIN_SPAN_WORDS:
            print(f"[Leak] dropped — span too short to verify ({v_id} ← {l_id})")
            continue
        if _leak_norm(span) not in _leak_norm(l_rec["disclosure"]):
            print(f"[Leak] dropped — span is NOT in {l_id}'s printed body (hallucinated quote)")
            continue
        if (v_id, l_id) in seen:
            continue
        seen.add((v_id, l_id))
        findings.append({"victim": v_id, "leaker": l_id, "leaked_span": span,
                         "why": str(item.get("why", "") or "").strip()})

    print(f"[Leak] {model_used}: {len(findings)} confirmed of {len(reported)} reported "
          f"({len(hints)} verbatim hint(s), {len(inv)} item(s) audited)")
    for f in findings:
        print(f"[Leak]   {f['victim']} answered by {f['leaker']} — {f['why'][:90]}")
    return findings, in_tok, out_tok


_LEAK_VICTIM_RULE = (
    "MANDATORY: another question already PRINTED on this same paper contains the following "
    "words, which give away the answer to this question:\n"
    "  ✗ \"{span}\"\n"
    "Your replacement must test DIFFERENT knowledge — something whose answer is neither stated "
    "in nor directly inferable from that text. Keep the same type, marks and difficulty."
)
_LEAK_LEAKER_RULE = (
    "MANDATORY: your question must NOT state, quote or reveal the following, because it is the "
    "secret answer to a DIFFERENT question on this same paper:\n"
    "  ✗ \"{span}\"\n"
    "Cover the same topic if you wish, but the text you produce must not give that away. "
    "Keep the same type, marks and difficulty."
)


def fix_answer_leaks(paper_data: dict, work_orders: list, class_name: str, subject: str) -> tuple:
    """Audit the assembled paper for cross-question answer leaks and rewrite one side of each.
    Returns (paper_data, in_tok, out_tok).

    Which side gets rewritten is policy, not the model's choice:
      • A case/source passage is NEVER a candidate. It is section-level scaffolding that every
        question printed beside it depends on, and replacing it cascades through all of them —
        so a passage leak is always fixed by rewriting the VICTIM.
        (_regen_replacement_question independently refuses cbq/map, so this is belt-and-braces.)
      • Otherwise rewrite the cheaper side, lowest marks first: replacing a 1-mark
        Assertion-Reason costs less than rewriting a 3-mark question. Assertion-Reason sorts
        last among equal marks because its structure (a true/false assertion plus a valid
        reason relation) is the hardest to regenerate cleanly.
      • If the chosen side cannot be regenerated safely, fall through to the other one; if
        neither can, keep both and REPORT. A flagged paper a teacher fixes in 30 seconds beats
        a failed generation.

    Bounded: at most ANSWER_LEAK_MAX_REGENS rewrites, then a single re-audit to confirm. Never
    loops, and never raises — any failure leaves the paper exactly as it was.
    """
    findings, in_tok, out_tok = run_answer_leak_audit(paper_data, class_name, subject)
    if not findings:
        return paper_data, in_tok, out_tok

    inv = {it["id"]: it for it in _leak_inventory(paper_data)}
    wo_by_name = {wo.section_name: wo for wo in (work_orders or [])}
    replaced, unresolved = set(), []

    for f in findings:
        v_rec, l_rec = inv.get(f["victim"]), inv.get(f["leaker"])
        label = f"{f['victim']} answered by {f['leaker']}"
        if not v_rec or not l_rec:
            continue
        if len(replaced) >= ANSWER_LEAK_MAX_REGENS:
            print(f"[Leak] regen cap ({ANSWER_LEAK_MAX_REGENS}) reached — flagging: {label}")
            unresolved.append(f"{label}: {f['why']}")
            continue
        if (v_rec["sec"], v_rec["idx"]) in replaced or (
                l_rec["kind"] == "q" and (l_rec["sec"], l_rec["idx"]) in replaced):
            continue                        # one side is already a fresh question

        cands = [it for it in (v_rec, l_rec)
                 if it["kind"] == "q" and it["cat"] not in ("cbq", "map")
                 and wo_by_name.get(it["sec"])]
        cands.sort(key=lambda it: (it["marks"], it["cat"] == "ar"))

        for tgt in cands:
            is_victim = tgt["id"] == f["victim"]
            rule = (_LEAK_VICTIM_RULE if is_victim else _LEAK_LEAKER_RULE).format(
                span=_leak_flat(f["leaked_span"], 240))
            print(f"[Leak] rewriting {'victim' if is_victim else 'leaker'} {tgt['id']} "
                  f"({tgt['marks']:g}m {tgt['cat'].upper()}) in '{tgt['sec']}' — {label}")
            new_q, i_t, o_t = _regen_replacement_question(
                paper_data[tgt["sec"]]["questions"][tgt["idx"]], tgt["idx"],
                wo_by_name[tgt["sec"]], tag="Leak", extra_rule=rule)
            in_tok += i_t
            out_tok += o_t
            if new_q:
                paper_data[tgt["sec"]]["questions"][tgt["idx"]] = new_q
                replaced.add((tgt["sec"], tgt["idx"]))
                break
        else:
            print(f"[Leak] neither side safely regenerable — flagging: {label}")
            unresolved.append(f"{label}: {f['why']}")

    # One confirmation pass. Rewrites are in place (count, marks and qnum preserved), so item
    # ids are unchanged and any leak still reported here genuinely survived the fix.
    if replaced:
        survivors, i_t, o_t = run_answer_leak_audit(paper_data, class_name, subject)
        in_tok += i_t
        out_tok += o_t
        for s in survivors:
            unresolved.append(f"{s['victim']} still answered by {s['leaker']}: {s['why']}")

    print(f"[Leak] {len(replaced)} question(s) rewritten, {len(unresolved)} left flagged")
    if unresolved:
        unresolved = list(dict.fromkeys(unresolved))
        for sec_data in paper_data.values():
            if isinstance(sec_data, dict):
                sec_data.setdefault("_answer_leaks", unresolved)
    return paper_data, in_tok, out_tok


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
        for w in (sec_data.get("_sums_report") or {}).get("violations", []):
            all_warnings.append(f"[Sums/Quiz] {w}")
        for w in sec_data.get("_answer_leaks", []):
            all_warnings.append(f"[Answer-Leak] {w}")

    # Paper-level reports (_cross_section_duplicates, _sums_report) are stored on EVERY section,
    # so the loop above collects each of their warnings once per section. Dedupe, order kept, so
    # the 40-line cap isn't spent restating one finding.
    all_warnings = list(dict.fromkeys(all_warnings))

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
            stage="v10-final",
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
            stage="v8-coherence",
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
            stage="v7-competency-fix",
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


def _section_worker(wo: SectionWorkOrder):
    """generate_section() under a named stage. mantle_client.stage is thread-local, so wrapping
    here labels every LLM call the section makes — including the ones inside its validators —
    with the section name, and three parallel sections never mix their labels. Wrapping at the
    call site rather than inside generate_section keeps the whole ~200-line body un-reindented.
    """
    with mantle_client.stage(wo.section_name):
        return generate_section(wo)


def generate_paper_parallel(blueprint: dict, pattern, context_map: dict, difficulty: str, class_name: str, subject: str, chapters: list, disable_images: bool = False,
                            unit_map=None, creative_ratio: int = 0):
    """
    Generate all sections in parallel using ThreadPoolExecutor.

    Returns (paper_data, total_input_tokens, total_output_tokens).
    Raises RuntimeError if any section is still entirely missing after the serial retry
    (caller falls back to the whole-paper single-prompt path).
    """
    # 15 numbered slots: the 14 passes below plus slot 3, which is the serial-retry pass that
    # only runs when a section failed (skipped on the happy path so the numbering stays stable).
    step = _StepLog(total=15)
    print(f"[Pipeline] ===== Class {class_name} {subject} | {difficulty} | "
          f"{len(chapters or [])} chapter(s) | {mantle_client.models_summary()} =====")

    with step("Build work orders"):
        work_orders = build_work_orders(blueprint, pattern, context_map, difficulty, class_name, subject, chapters, disable_images=disable_images, unit_map=unit_map,
                                        creative_ratio=creative_ratio)
        if not work_orders:
            raise RuntimeError("Blueprint produced no work orders")
        for wo in work_orders:
            _flags = [n for n, on in (("grammar-own", wo.is_english_grammar),
                                      (f"own-mix:{wo.own_count}", wo.own_count),
                                      ("writing-own", wo.is_english_writing),
                                      ("no-context", wo.english_own_only),
                                      ("map", wo.is_map_work),
                                      ("no-images", wo.disable_images)) if on]
            print(f"[Pipeline]   · '{wo.section_name}': {wo.questions_count}q "
                  f"{wo.marks}m mpq={wo.marks_per_question:g} ctx={_k(len(wo.context_text))}ch "
                  f"slots={len(wo.slots)} sums={wo.sums_count} "
                  f"chapters={len(wo.chapters)}{' [' + ','.join(_flags) + ']' if _flags else ''}")

    paper_data: dict = {}
    failed: list = []
    total_input_tokens = 0
    total_output_tokens = 0

    with step("Generate sections", f"{len(work_orders)} section(s), "
                                  f"{MAX_PARALLEL_SECTIONS} at a time"):
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SECTIONS) as executor:
            futures = {executor.submit(_section_worker, wo): wo for wo in work_orders}
            done_n = 0
            for future in as_completed(futures):
                wo = futures[future]
                done_n += 1
                try:
                    sec_dict, in_tok, out_tok = future.result()
                    paper_data.update(sec_dict)
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
                    _qs = sum(len(v.get("questions", [])) for v in sec_dict.values()
                              if isinstance(v, dict))
                    print(f"[Parallel-Gen] {done_n}/{len(work_orders)} OK '{wo.section_name}' — "
                          f"{_qs} question(s), in={_k(in_tok)} out={_k(out_tok)}")
                except Exception as e:
                    print(f"[Parallel-Gen] {done_n}/{len(work_orders)} FAILED "
                          f"'{wo.section_name}': {e}")
                    print(traceback.format_exc())
                    failed.append(wo.section_name)

    # A section can fail in the parallel burst purely from endpoint contention — the biggest
    # section (e.g. a 30-question language section) starves while the other two stream and even
    # its TLS handshake times out, so its base call never returns and the whole section is
    # dropped (-30 marks, "Short Answer MISSING"). Give each failed section ONE more attempt
    # SERIALLY, where it has the endpoint to itself; even a truncated base result is enough for
    # the top-up path to fill it. Only runs on failure — the happy path is untouched.
    if failed:
        with step("Serial retry of failed sections", f"{len(failed)}: {', '.join(failed)}"):
            for wo in [w for w in work_orders if w.section_name in failed]:
                print(f"[Parallel-Gen] serial retry of failed section '{wo.section_name}'")
                try:
                    sec_dict, in_tok, out_tok = _section_worker(wo)
                    paper_data.update(sec_dict)
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
                    failed.remove(wo.section_name)
                    print(f"[Parallel-Gen] ✅ serial retry recovered '{wo.section_name}'")
                except Exception as e:
                    print(f"[Parallel-Gen] serial retry FAILED '{wo.section_name}': {e}")
    else:
        step.i += 1                       # keep the step numbering stable on the happy path

    # Any section still failed here is ENTIRELY ABSENT from paper_data (paper_data.update only
    # runs on success) — it never generated even a truncated base to top up. Shipping the paper
    # anyway renders the literal line "No questions found for section X" and knocks the total
    # (e.g. 40/80 marks), and every later question is renumbered off-by-N because the missing
    # section's slots leave no gap. So a missing section is NOT acceptable output: raise to
    # trigger the single-prompt fallback, which regenerates the WHOLE paper in one pass. Sections
    # that merely came back SHORT (present but under-count) are not in `failed` — they are handled
    # by [Refill] below and never reach this gate.
    if failed:
        raise RuntimeError(
            f"{len(failed)} section(s) missing after serial retry "
            f"({', '.join(failed)}) — triggering single-prompt fallback"
        )

    # Final guarantee: strip any wrong-type questions before numbering/render (covers the
    # partial-emit path where a section shipped foreign types after exhausting retries).
    with step("Enforce section question types"):
        paper_data = enforce_section_question_types(paper_data, work_orders)

    # Symmetric to the [Refill] below: drop questions a section generated ABOVE its blueprint,
    # so an over-full section can't push the paper's marks over (e.g. Biology 33/30). Runs
    # before Refill so the two together converge each section on its exact per-type counts.
    with step("Trim over-full sections"):
        paper_data = trim_overfull_sections(paper_data, work_orders)

    # Refill any section the type-enforcer (or post-validation dedup) left SHORT. These trims
    # run AFTER per-section validation passed, so the section never went 'partial' and was
    # never topped up — e.g. a 20-question Objective section that emitted 2 stray SA questions
    # ends up 18/20 silently. Top each short section back up to its work order's count.
    with step("Refill short sections"):
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
    with step("Reconcile uniform marks"):
        paper_data = reconcile_uniform_marks(paper_data, work_orders)

    # Cross-section duplicates: sections are generated by independent parallel prompts, so
    # neither can see the other's questions — this is the only place the same question turning
    # up in two sections can be caught. Replaces in place (count and marks preserved), so it is
    # safe to run after the refill/marks passes above.
    with step("Cross-section duplicates (V5x)"):
        paper_data, _cd_in, _cd_out = fix_cross_section_duplicates(paper_data, work_orders)
        total_input_tokens += _cd_in
        total_output_tokens += _cd_out

    # Accountancy 80/20 sums-vs-quiz composition. Runs after the duplicate fixer (whose
    # replacements also have to satisfy the ratio) and before the answer-key balance, so a
    # regenerated numerical MCQ still gets its key spread. No-op for every other subject.
    with step("Sums/quiz composition", f"subject={subject}"):
        paper_data, _sm_in, _sm_out = enforce_sums_distribution(paper_data, work_orders, subject)
        total_input_tokens += _sm_in
        total_output_tokens += _sm_out
        sums_report = validate_sums_distribution(paper_data, subject)
        if sums_report:
            for _sd in paper_data.values():
                if isinstance(_sd, dict):
                    _sd["_sums_report"] = sums_report

    # V11 — cross-question answer leaks (an Assertion-Reason stem or a case passage stating the
    # answer to a 2-mark question elsewhere). Needs the WHOLE assembled paper plus the answer
    # keys, so it cannot run per-section; runs after every pass that adds or replaces questions
    # so its findings are about the questions that will actually ship, and before the answer-key
    # balance below so a rewritten MCQ still gets its key spread.
    with step("Answer-leak audit (V11)", f"model={getattr(mantle_client, 'AUDIT_MODEL', '?')}"):
        paper_data, _lk_in, _lk_out = fix_answer_leaks(paper_data, work_orders, class_name, subject)
        total_input_tokens += _lk_in
        total_output_tokens += _lk_out

    # Spread the MCQ answer key over a/b/c/d with no run longer than 2. Deterministic and
    # LLM-free; runs LAST so every earlier pass that can change an answer (V4 verification,
    # duplicate replacement, refill) has already settled.
    with step("Balance MCQ answer keys"):
        paper_data = balance_mcq_answer_keys(paper_data)

    with step("Renumber + report leftover dupes"):
        paper_data = cross_section_validate(paper_data, blueprint)
        total_q = sum(len(v.get("questions", [])) for v in paper_data.values())
        print(f"[Parallel-Gen] ✅ {len(paper_data)} sections, {total_q} questions | in={total_input_tokens} out={total_output_tokens} tokens")

    with step("Competency distribution (V7)"):
        competency_report = validate_competency_distribution(paper_data)
        if not competency_report.get("compliant", True):
            # V7 — attempt to fix competency distribution via targeted LLM relabelling
            paper_data = enforce_competency_distribution(paper_data, class_name, subject)
            # Re-run check to capture final distribution
            competency_report = validate_competency_distribution(paper_data)
        for sec_data in paper_data.values():
            sec_data["_competency_report"] = competency_report

    # V8 — Cross-section coherence audit (one LLM call for the full paper)
    with step("Cross-section coherence (V8)", f"model={mantle_client.VAL_MODEL}"):
        coherence_report = run_cross_section_coherence_audit(
            paper_data, class_name, subject, chapters
        )
        for sec_data in paper_data.values():
            sec_data["_coherence_report"] = coherence_report

    # V10 — Final paper-level audit (master QC gate, deepseek.v3.2)
    with step("Final paper audit (V10)", f"model={GEN_MODEL}"):
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

    # Closing trace: per-section shape, then the whole run's LLM spend broken down by model, by
    # KEY and by slowest stage. This is the block to read first when a paper looks wrong or slow.
    print(f"[Pipeline] ===== assembled in {time.time() - step.t0:.0f}s =====")
    for _sn, _sd in paper_data.items():
        if _sn.startswith("__") or not isinstance(_sd, dict):
            continue
        _qs = _sd.get("questions", [])
        _flags = [f"{_t}={len(_sd.get(_key) or [])}" for _t, _key in (
            ("dupes", "_cross_section_duplicates"), ("leaks", "_answer_leaks"),
            ("quality", "_quality_flags"), ("answers", "_mcq_answer_warnings"),
            ("grounding", "_grounding_issues")) if _sd.get(_key)]
        print(f"[Pipeline]   · '{_sn}': {len(_qs)} q, "
              f"{sum(_as_float(q.get('marks'), 0.0) for q in _qs):g} marks"
              f"{' | ' + ' '.join(_flags) if _flags else ''}")
    print(f"[Pipeline] paper tokens: in={_k(total_input_tokens)} out={_k(total_output_tokens)}")
    for _line in mantle_client.run_stats_lines():
        print(f"[Pipeline] {_line}")

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
        # Per-thread filename: with one worker running several papers at once, a single
        # fixed temp_questions.json meant whichever paper finished last silently clobbered
        # the others' dump, so the file was useless exactly when concurrency made it
        # interesting. temp_* is gitignored, so the suffixed names are ignored too.
        fname = f"temp_questions_{threading.get_ident()}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(debug_payload, f, indent=2, ensure_ascii=False, default=str)
        print(f"[Debug] Question JSON written to {fname}")
    except Exception as e:
        print(f"[Debug] Could not write the question JSON dump: {e}")
