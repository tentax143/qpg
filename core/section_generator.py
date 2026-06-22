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
from dataclasses import dataclass, field
from typing import Optional

from . import embeddings, mantle_client
from .data.cbse_patterns import UNIT_MARKS_WEIGHTS

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
# LLMs sometimes embed the letter prefix in option values: "(a) text" → strip before render
_OPT_PREFIX_RE = re.compile(r'^\([a-dA-D]\)\s*')

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


# ─────────────────────────────────────────────
# Token budget
# ─────────────────────────────────────────────

def estimate_token_budget(wo: SectionWorkOrder) -> int:
    base = 500
    mpq = wo.marks_per_question or 1
    # Token cost scales with question complexity (marks value)
    # LA (5m) with or_alternative needs ~450 tokens each; MCQ (1m) ~150 tokens
    if mpq >= 5:
        per_q = 450
    elif mpq >= 4:
        per_q = 350
    elif mpq >= 3:
        per_q = 280
    elif mpq >= 2:
        per_q = 200
    else:
        per_q = 150
    passage = 900 if wo.passage_instruction else 0
    extract = 700 if wo.extract_instruction else 0
    raw = base + wo.questions_count * per_q + passage + extract
    # Floor of 3000 ensures even small sections with complex question types don't get truncated
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
    has_la = any("long" in _type_str(t) or _type_str(t) in ("la", "long_answer") for t in wo.question_types)
    is_map = wo.is_map_work
    needs_img = _needs_image(wo)
    mpq = wo.marks_per_question

    if is_map:
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "SA",\n'
            '      "subtype": "map_based",\n'
            '      "text": "On the given outline map of India, locate and label the following: (a) ... (b) ...",\n'
            f'      "marks": {mpq},\n'
            '      "map_note": "[Attach outline map of India — examiner to supply]",\n'
            '      "chapter_tag": "Chapter name or number from NCERT this question is drawn from",\n'
            '      "competency_type": "application"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    if (has_passage or has_cbq) and _is_dedicated_cbq_section(wo):
        # Image-based CBQ (question-first): LLM writes observation questions from chapter knowledge.
        # An image will be generated to match these questions AFTER section generation.
        # The "image_based": true flag triggers post-processing in generate_section().
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "CBQ",\n'
            '      "subtype": "image_based",\n'
            '      "image_based": true,\n'
            '      "text": "Observe the diagram carefully and answer the following questions:",\n'
            f'      "marks": {mpq},\n'
            '      "chapter_tag": "Chapter name or number from NCERT",\n'
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
    if has_passage or has_cbq:
        # Show MCQ example first when section also has MCQs (prevents LLM generating MCQs without options)
        mcq_example = ''
        if has_mcq:
            mcq_example = (
                '    {\n'
                '      "qnum": 1,\n'
                '      "type": "MCQ",\n'
                '      "subtype": "standard",\n'
                '      "text": "MCQ question text",\n'
                '      "options": {"a": "...", "b": "...", "c": "...", "d": "..."},\n'
                '      "answer": "a",\n'
                '      "answer_explanation": "Why correct option is right",\n'
                f'      "marks": 1,\n'
                '      "chapter_tag": "Chapter name",\n'
                '      "competency_type": "recall"\n'
                '    },\n'
            )
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "passage": "FULL PASSAGE TEXT HERE (400-600 words for reading; 200-300 words for case/source-based)",\n'
            '  "questions": [\n'
            f'{mcq_example}'
            '    {\n'
            '      "qnum": 2,\n'
            '      "type": "CBQ",\n'
            '      "subtype": "source_based",\n'
            '      "text": "Read the passage above and answer the following:",\n'
            f'      "marks": {mpq},\n'
            '      "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "application",\n'
            '      "sub_questions": [\n'
            '        {"text": "Sub-question (a)", "marks": 1, "answer_explanation": "Key answer points"},\n'
            '        {"text": "Sub-question (b)", "marks": 1, "answer_explanation": "Key answer points"},\n'
            '        {"text": "Sub-question (c)", "marks": 2, "answer_explanation": "Key answer points"}\n'
            '      ]\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    elif has_mcq:
        img_field = '\n      "image_prompt": "detailed description of the image/diagram to generate for this question",' if needs_img else ''
        # Show AR example in the schema when section contains Assertion-Reason questions
        ar_example = ''
        if has_ar:
            ar_example = (
                '    {\n'
                '      "qnum": 2,\n'
                '      "type": "MCQ",\n'
                '      "subtype": "assertion_reason",\n'
                '      "text": "Assertion (A): [full assertion statement]\\nReason (R): [full reason statement]",\n'
                '      "options": {\n'
                '        "a": "Both A and R are true and R is the correct explanation of A",\n'
                '        "b": "Both A and R are true but R is NOT the correct explanation of A",\n'
                '        "c": "A is true but R is false",\n'
                '        "d": "A is false but R is true"\n'
                '      },\n'
                '      "answer": "a",\n'
                '      "answer_explanation": "Why this option is correct",\n'
                f'      "marks": {mpq},\n'
                '      "chapter_tag": "Chapter name or number from NCERT",\n'
                '      "competency_type": "application"\n'
                '    }\n'
            )
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "MCQ",\n'
            '      "subtype": "standard",\n'
            '      "text": "Question text",'
            f'{img_field}\n'
            '      "options": {"a": "...", "b": "...", "c": "...", "d": "..."},\n'
            '      "answer": "a",\n'
            '      "answer_explanation": "Why the correct option is right and why others are wrong (1-2 sentences)",\n'
            f'      "marks": {mpq},\n'
            '      "chapter_tag": "Chapter name or number from NCERT",\n'
            '      "competency_type": "recall or application"\n'
            '    }'
            + (',\n' + ar_example if ar_example else '\n') +
            '  ]\n'
            '}'
        )
    elif has_la:
        # M-02: or_alternative field for LA questions
        img_field = ', "image_prompt": "detailed description of the image/diagram to generate"' if needs_img else ''
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "LA",\n'
            '      "subtype": "standard",\n'
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
    else:
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
    elif wo.extract_instruction:
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
            "- The question \"text\" must reference the image (e.g. 'Study the diagram below and answer:').\n"
            "- Only add \"image_prompt\" to the specific questions that need an image — not all questions.\n"
        )

    error_block = ""
    if prior_error and attempt > 1:
        error_block = f"\n⚠️  PREVIOUS ATTEMPT FAILED — FIX THESE ISSUES:\n{prior_error}\n"

    if wo.context_text:
        ctx = wo.context_text
        ctx_label = "REFERENCE MATERIAL (base questions strictly on these textbook excerpts)"
    else:
        ctx = f"No textbook content indexed. Use your CBSE {wo.subject} Class {wo.class_name} knowledge."
        ctx_label = "REFERENCE MATERIAL"
    diff_block = _difficulty_block(wo.difficulty)

    # C-01: use section-specific sub-subject when set (compound papers)
    effective_subject = wo.section_subject or wo.subject
    chapters_str = ", ".join(wo.chapters) if wo.chapters else "all topics"
    chapter_count = len(wo.chapters) if wo.chapters else 1
    per_chapter = max(1, round(wo.questions_count / chapter_count)) if wo.questions_count else 1

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

    # M-02: OR alternative rule for LA sections
    or_rule = ""
    if any(_type_str(t) in ("la", "long_answer", "long answer") for t in wo.question_types):
        or_rule = (
            "\n9. INTERNAL CHOICE (OR) — MANDATORY FOR LA:\n"
            "   Every Long Answer question MUST include an \"or_alternative\" field with an alternate "
            "question on a DIFFERENT concept from the same chapter, worth the same marks. "
            "This is mandatory in CBSE board papers.\n"
        )

    generate_count = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count

    return f"""You are a CBSE Class {wo.class_name} {effective_subject} question paper author.
Generate ONLY the questions for {wo.section_name} of the exam.

SECTION SPECIFICATION:
- Section: {wo.section_name} ({wo.title})
- Questions required: {generate_count}
- Marks per question: {wo.marks_per_question}
- Total marks: {wo.marks}
- Question types: {types_str}
- Chapters to cover: {chapters_str}
- Subject focus: {effective_subject}

CHAPTER DISTRIBUTION — MANDATORY:
Spread questions across ALL {chapter_count} chapter(s): {chapters_str}
Target ~{per_chapter} question(s) per chapter. Never draw all questions from one chapter.
{diff_block}
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
4. Each question marks = {wo.marks_per_question}
5. Draw question content from the reference material above
6. MCQ ANSWER DISTRIBUTION — MANDATORY: Spread correct answers across a, b, c, d roughly equally. Never place the correct answer in the same option letter for more than 2 consecutive questions. A biased answer key (e.g. mostly 'a' or 'b') will be REJECTED.
7. Questions MUST come from different chapters — no chapter monopoly.
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
    raise ValueError(f"Could not extract JSON from LLM output ({len(raw)} chars)")


# ─────────────────────────────────────────────
# Per-question type+subtype validation
# ─────────────────────────────────────────────

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

    # ── MCQ ──────────────────────────────────────────────────────────────────────
    is_mcq = ("mcq" in type_lower or "objective" in type_lower or "multiple" in type_lower)
    is_ar_type = "assertion" in type_lower or subtype == "assertion_reason"

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
            if len(opts) < 4:
                errors.append(
                    f"Q{n} [MCQ/assertion_reason]: must have 4 standard AR options, "
                    f"found {len(opts)}. Options must be the standard "
                    '"Both A and R true/false..." choices.'
                )
        else:
            # Standard MCQ
            if len(opts) < 4:
                errors.append(
                    f"Q{n} [MCQ/standard]: must have 4 options (a/b/c/d), found {len(opts)}. "
                    'Add: "options": {"a": "...", "b": "...", "c": "...", "d": "..."}'
                )

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
        if not or_alt:
            errors.append(
                f"Q{n} [LA/standard]: missing 'or_alternative' — "
                "CBSE board papers require internal choice (OR) for every LA question"
            )
        elif isinstance(or_alt, str) and not or_alt.strip():
            errors.append(f"Q{n} [LA/standard]: 'or_alternative' is empty string")
        elif isinstance(or_alt, dict) and not str(or_alt.get("text", "")).strip():
            errors.append(f"Q{n} [LA/standard]: 'or_alternative.text' is empty")

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
                float(sq.get("marks", 0)) if isinstance(sq, dict) else 0.0
                for sq in sqs
            )
            expected = float(q.get("marks", wo.marks_per_question))
            if abs(sq_sum - expected) > 0.1:
                errors.append(
                    f"Q{n} [CBQ/{subtype}]: sub_question marks sum={sq_sum} "
                    f"!= question marks={expected} — adjust individual sub-question marks"
                )
        # Ensure image generation flag is set for image_based questions
        if subtype == "image_based" or type_lower == "image_based":
            q["image_based"] = True

    return errors


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

    # ── Section marks total ──────────────────────────────────────────────────────
    if section_marks_total > 0 and wo.marks > 0:
        if abs(section_marks_total - wo.marks) > 1.0:
            errors.append(
                f"Section marks total={section_marks_total:.1f} expected {wo.marks}. "
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


def _concept_overlap(t1: str, t2: str) -> float:
    """Token-overlap ratio between two question texts. Returns 0.0–1.0."""
    def tokens(s):
        return {w.lower() for w in re.split(r"\W+", s) if len(w) > 3 and w.lower() not in _STOP_WORDS}
    s1, s2 = tokens(t1), tokens(t2)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / min(len(s1), len(s2))


def validate_uniqueness(questions: list) -> list:
    """
    V5 Layer 1 — detect duplicate or near-duplicate questions within a section.
    Returns list of warning strings (does not block, caller decides action).
    """
    warnings = []
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            t1 = str(questions[i].get("text", ""))
            t2 = str(questions[j].get("text", ""))
            score = _concept_overlap(t1, t2)
            if score > 0.50:
                warnings.append(
                    f"Q{i+1} and Q{j+1} overlap {score:.0%} — likely duplicate concept"
                )
    return warnings


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
    quality_score = {f.get("qnum", 0) - 1: f.get("avg_score", 3.0) for f in (quality_flags or [])}

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

        regen_prompt = (
            f"Generate ONE CBSE Class {wo.class_name} {wo.subject} question.\n"
            f"Type: {updated_questions[replace_idx].get('type', 'SA')}\n"
            f"Marks: {updated_questions[replace_idx].get('marks', wo.marks_per_question)}\n"
            f"Difficulty: {wo.difficulty}\n"
            f"Chapters: {', '.join(str(c) for c in wo.chapters)}\n\n"
            "IMPORTANT: The following concept is ALREADY covered — do NOT repeat it:\n"
            f"  ✗ {keep_text}\n\n"
            "Context:\n"
            f"{wo.context_text[:2500]}\n\n"
            "Output JSON only (single question object):\n"
            '{"qnum": ' + str(replace_idx + 1) + ', "type": "SA", "text": "...", '
            '"marks": ' + str(int(updated_questions[replace_idx].get("marks", wo.marks_per_question))) + ', '
            '"answer_explanation": "...", "chapter_tag": "...", "competency_type": "constructed"}'
        )
        try:
            rraw, _, _ = mantle_client.converse(
                model_id=GEN_MODEL,
                prompt=regen_prompt,
                max_tokens=500,
                temperature=0.85,
            )
            new_q = extract_single_question_json(rraw, replace_idx, wo.marks_per_question)
            # Preserve original qnum and marks
            new_q["qnum"] = updated_questions[replace_idx].get("qnum", replace_idx + 1)
            new_q["marks"] = updated_questions[replace_idx].get("marks", wo.marks_per_question)
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
        scores = [
            r.get("clarity", 5),
            r.get("ncert_alignment", 5),
            r.get("difficulty_match", 5),
            r.get("pedagogical_value", 5),
        ]
        avg = sum(scores) / len(scores)
        if avg < 3.0:
            flagged.append({
                "qnum": r.get("q"),
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


def verify_mcq_answers(questions: list, class_name: str, subject: str) -> list:
    """
    V4 — Blind LLM answer verification for MCQ questions.
    Sends each MCQ to the model without context; flags mismatches.
    Returns list of {qnum, stored, llm_answer, confidence, suspect} dicts.
    """
    mcq_qs = [
        (i, q) for i, q in enumerate(questions)
        if str(q.get("type", "")).upper() in ("MCQ", "ASSERTION-REASON", "ASSERTION_REASON")
        and q.get("options") and q.get("answer")
    ]
    if not mcq_qs:
        return []

    results = []
    # Batch up to 10 per LLM call
    batch_size = 10
    for batch_start in range(0, len(mcq_qs), batch_size):
        batch = mcq_qs[batch_start:batch_start + batch_size]
        qs_block = ""
        for idx, (_, q) in enumerate(batch):
            opts = q.get("options", {})
            qs_block += (
                f"\nQ{idx + 1}. {q.get('text', '')}\n"
                f"(a) {opts.get('a', '')}  (b) {opts.get('b', '')}\n"
                f"(c) {opts.get('c', '')}  (d) {opts.get('d', '')}\n"
            )

        prompt = (
            f"Answer these CBSE Class {class_name} {subject} multiple choice questions.\n"
            "Choose the single best answer based on your NCERT knowledge. "
            "Do NOT explain — just pick the option letter.\n"
            f"{qs_block}\n"
            "Output JSON array only:\n"
            '[{"q": 1, "answer": "a", "confidence": "high"}, ...]\n'
            'confidence: "high" (certain), "medium" (likely), "low" (guessing)'
        )
        try:
            raw, _, _ = mantle_client.converse(
                model_id=mantle_client.VAL_MODEL,
                prompt=prompt,
                max_tokens=300,
                temperature=0.1,
            )
            raw = raw.strip()
            # extract JSON array
            m = re.search(r"\[.*\]", raw, re.S)
            llm_answers = json.loads(m.group()) if m else []
        except Exception as e:
            print(f"[V4-MCQ-Verify] LLM call failed: {e}")
            llm_answers = []

        for idx, (orig_idx, q) in enumerate(batch):
            stored = str(q.get("answer", "")).lower().strip()
            llm_entry = next((x for x in llm_answers if x.get("q") == idx + 1), {})
            llm_ans = str(llm_entry.get("answer", "")).lower().strip()
            confidence = llm_entry.get("confidence", "unknown")
            suspect = bool(llm_ans and llm_ans != stored and confidence in ("high", "medium"))
            results.append({
                "qnum": orig_idx + 1,
                "stored": stored,
                "llm_answer": llm_ans,
                "confidence": confidence,
                "suspect": suspect,
            })
            if suspect:
                print(
                    f"[V4-MCQ-Verify] ⚠️  Q{orig_idx + 1}: stored='{stored}' "
                    f"but LLM says '{llm_ans}' (confidence={confidence})"
                )
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
        if not r.get("grounded", True):
            q_idx = r.get("q", 1) - 1
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

    return (
        f"Generate exactly ONE CBSE Class {wo.class_name} {wo.subject} {qtype_str} question.\n"
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

        # ── AR: inject standard 4 options when A/R text present but options missing ─
        type_lower = _type_str(q.get("type", ""))
        subtype = str(q.get("subtype", "")).strip().lower()
        is_ar = "assertion" in type_lower or subtype == "assertion_reason"
        if is_ar:
            text = q.get("text", "")
            has_assertion = ("Assertion" in text or "A:" in text)
            has_reason = ("Reason" in text or "R:" in text)
            is_substantive = len(text.strip()) > 50
            if has_assertion and has_reason and is_substantive and len(opts) < 4:
                q["options"] = dict(_AR_STANDARD_OPTIONS)
                print(f"[Repair] Q{q.get('qnum','?')}: injected standard AR options (had A/R text, options missing)")

        # ── Infer and inject subtype when LLM omitted it ─────────────────────────
        if not q.get("subtype"):
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
        and all(_type_str(t).lower() in _la_types for t in wo.question_types)
        and wo.marks_per_question >= 4
        and not is_cbq  # dedicated CBQ uses image-first path
    )
    _is_source_cbq = (
        wo.question_types
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
            if suspect_mcqs:
                section_data["_mcq_answer_warnings"] = suspect_mcqs
                print(
                    f"[Section-Gen] ⚠️  V4 MCQ: {len(suspect_mcqs)} suspect answer(s) in '{wo.section_name}'"
                )
            print(f"[Section-Gen] '{wo.section_name}' ✓ ({len(section_data.get('questions', []))} questions)")
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
            section_data["_partial"] = True
            section_data["_errors"] = errors
            print(f"[Section-Gen] '{wo.section_name}' emitting partial result")
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
    all_docs = []
    seen: set = set()

    # When no chapters specified (e.g. One Mark Test), query across all ingested content
    # by passing unit=None — embeddings.query omits the where filter when unit is falsy.
    query_units = chapters if chapters else [None]

    # Compute total weight for proportional allocation
    chapter_weights = {ch: _chapter_weight(subject, ch or "") for ch in query_units}
    total_weight = sum(chapter_weights.values()) or 1
    # Base pool: 48 chunks across all chapters; each chapter gets a share proportional to its CBSE marks weight
    base_pool = max(48, 12 * len(query_units))

    for chapter in query_units:
        weight = chapter_weights[chapter]
        n_results = max(4, round(base_pool * weight / total_weight))
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
                                all_docs.append(doc)
            except Exception as e:
                print(f"[Section-Context] query failed chapter='{chapter}' q='{query}': {e}")

    context = "\n\n".join(all_docs)
    return context[:max_chars]


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

    for sec_name, sec_data in blueprint.items():
        sec_types = sec_data.get("question_types") or question_types_all
        effective_subject = sec_data.get("section_subject") or subject
        q_count = sec_data.get("questions_count") or sec_data.get("questions") or 0
        hints = _query_hints_for_types(sec_types, effective_subject)
        ctx = get_section_context(class_name, effective_subject, chapters, hints, school_id=school_id)

        # If subsection store is empty (e.g. 10_history not ingested), retry with parent subject
        if not ctx and effective_subject != subject:
            print(f"[Section-Context] '{sec_name}' subsection store empty, retrying with parent subject '{subject}'")
            hints = _query_hints_for_types(sec_types, subject)
            ctx = get_section_context(class_name, subject, chapters, hints, school_id=school_id)

        # 3.3 — Context quality pre-check with fallback
        if not _validate_context_quality(ctx, sec_name, q_count, effective_subject, class_name, sec_types):
            print(f"[Context-QC] '{sec_name}': retrying with broader query (no chapter filter)")
            broad_hints = [f"{effective_subject} {ch}" for ch in (chapters or [])] + hints
            ctx_broad = get_section_context(class_name, effective_subject, [], broad_hints, school_id=school_id)
            if len(ctx_broad) > len(ctx):
                ctx = ctx_broad
                print(f"[Context-QC] '{sec_name}': broad retry improved to {len(ctx)} chars")

        context_map[sec_name] = ctx
        print(f"[Section-Context] '{sec_name}' (subject={effective_subject}): {len(ctx)} chars")

        # 3.2 — Build per-type context for this section
        type_ctx: dict = {}
        for type_key, profile in TYPE_CONTEXT_PROFILES.items():
            # Only build per-type context if this section has that type
            if any(type_key in _type_str(t) for t in sec_types):
                type_hints = [f"{effective_subject} {' '.join(profile['extra_hints'])}"] + hints[:2]
                tctx = get_section_context(
                    class_name, effective_subject, chapters,
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


def build_work_orders(blueprint: dict, pattern, context_map: dict, difficulty: str, class_name: str, subject: str, chapters: list) -> list:
    pattern_section_map: dict = {}
    if pattern and hasattr(pattern, "sections") and pattern.sections:
        for ps in pattern.sections:
            if isinstance(ps, dict):
                pattern_section_map[ps.get("name", "")] = ps

    # 3.2: extract per-type context map stored under sentinel key
    context_by_type_all = context_map.get("__context_by_type__", {})

    work_orders = []
    for idx, (sec_name, sec_data) in enumerate(blueprint.items()):
        ps = pattern_section_map.get(sec_name, {})
        # Support both field names: blueprint uses 'questions_count', CBSE seed uses 'questions'
        q_count = sec_data.get("questions_count") or sec_data.get("questions") or 0
        marks = sec_data.get("marks", 0)
        mpq = sec_data.get("marks_per_question") or (round(marks / q_count, 1) if q_count else 1.0)

        # Use the pattern section's explicit 'id' first, then blueprint's id, then derive from name
        section_id = (
            ps.get("id")
            or sec_data.get("id")
            or _section_id_from_name(sec_name, idx)
        )

        # C-01: sub-subject routing for compound papers
        section_subject = sec_data.get("section_subject", "")

        # MO-01: attempt-N-of-M support — 'attempt' = students answer, 'count'/'provided' = questions generated
        attempt_count = sec_data.get("attempt_count") or ps.get("attempt")
        provided_count = sec_data.get("provided_count") or sec_data.get("questions_count") or sec_data.get("questions") or 0
        if attempt_count and provided_count and attempt_count < provided_count:
            # Generate the larger 'provided' set; students pick from it
            generate_count = provided_count
        else:
            generate_count = q_count
            attempt_count = None
            provided_count = None

        # M-04: detect map-work question type
        types_list = sec_data.get("question_types", [])
        is_map = any("map" in _type_str(t) for t in types_list)

        # M-01: detect mixed-marks sections (compound sections have multiple marks values)
        qt_dicts = sec_data.get("question_type_details", [])  # from CBSE pattern question_types list
        marks_values = set()
        if qt_dicts:
            for qt in qt_dicts:
                if isinstance(qt, dict) and "marks_each" in qt:
                    marks_values.add(qt["marks_each"])
        mixed_marks = len(marks_values) > 1

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
            context_text=context_map.get(sec_name, ""),
            difficulty=difficulty,
            subject=subject,
            class_name=class_name,
            chapters=list(chapters),
            section_subject=section_subject,
            provided_count=provided_count,
            attempt_count=attempt_count,
            is_map_work=is_map,
            mixed_marks=mixed_marks,
            passage_instruction=ps.get("passage_instruction"),
            extract_instruction=ps.get("extract_instruction"),
            subsections=sec_data.get("subsections", []),
            context_by_type=context_by_type_all.get(sec_name, {}),  # 3.2
        )
        work_orders.append(wo)
        subj_tag = f" [{section_subject}]" if section_subject else ""
        print(f"[WorkOrder] '{sec_name}'{subj_tag}: {generate_count}q × {mpq}m = {marks}m, types={types_list}")

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
            text = q.get("text", "")
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

    if len(failed) >= 2:
        raise RuntimeError(
            f"{len(failed)} sections failed ({', '.join(failed)}) — triggering single-prompt fallback"
        )
    if failed:
        print(f"[Parallel-Gen] ⚠️  {len(failed)} section(s) partial/failed: {failed}")

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

    return paper_data, total_input_tokens, total_output_tokens
