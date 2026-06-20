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
        'Assertion-Reason format:\n'
        '  "text": "A: [Assertion]\\nR: [Reason]"\n'
        '  "options": {\n'
        '    "a": "Both A and R are true and R is the correct explanation of A",\n'
        '    "b": "Both A and R are true but R is NOT the correct explanation of A",\n'
        '    "c": "A is true but R is false",\n'
        '    "d": "A is false but R is true"\n'
        '  }'
    )


def _needs_image(wo: SectionWorkOrder) -> bool:
    """Return True if any instruction mentions image-based questions."""
    keywords = ("image", "picture", "diagram", "figure", "visual")
    for instr in wo.instructions:
        if any(k in instr.lower() for k in keywords):
            return True
    return False


def _output_schema(wo: SectionWorkOrder, image_vision: dict | None = None) -> str:
    has_mcq = any(_type_str(t) in ("mcq", "multiple_choice", "assertion_reason", "assertion-reason", "case_based") for t in wo.question_types)
    has_passage = bool(wo.passage_instruction or wo.extract_instruction)
    has_cbq = any("cbq" in _type_str(t) or "source" in _type_str(t) or "case" in _type_str(t) for t in wo.question_types)
    has_la = any(_type_str(t) in ("la", "long_answer", "long answer") for t in wo.question_types)
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
            '      "type": "map_work",\n'
            '      "text": "On the given outline map of India, locate and label the following: (a) ... (b) ...",\n'
            f'      "marks": {mpq},\n'
            '      "map_note": "[Attach outline map of India — examiner to supply]",\n'
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
            '      "type": "image_based",\n'
            '      "image_based": true,\n'
            '      "text": "Observe the diagram carefully and answer the following questions:",\n'
            f'      "marks": {mpq},\n'
            '      "competency_type": "application",\n'
            '      "sub_questions": [\n'
            '        {"text": "What does this diagram represent? Identify it.", "marks": 1},\n'
            '        {"text": "What do you observe about the [key structure/process] shown?", "marks": 2},\n'
            '        {"text": "What process or function is depicted in this diagram?", "marks": 1}\n'
            '      ]\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    if has_passage or has_cbq:
        # M-05: sub-question marks included in CBQ schema
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "passage": "FULL PASSAGE TEXT HERE (400-600 words for reading; 200-300 words for case/source-based)",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "source_based",\n'
            '      "text": "Read the passage above and answer the following:",\n'
            f'      "marks": {mpq},\n'
            '      "competency_type": "application",\n'
            '      "sub_questions": [\n'
            '        {"text": "Sub-question (a)", "marks": 1},\n'
            '        {"text": "Sub-question (b)", "marks": 1},\n'
            '        {"text": "Sub-question (c)", "marks": 2}\n'
            '      ]\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    elif has_mcq:
        img_field = '\n      "image_prompt": "detailed description of the image/diagram to generate for this question",' if needs_img else ''
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "questions": [\n'
            '    {\n'
            '      "qnum": 1,\n'
            '      "type": "MCQ",\n'
            '      "text": "Question text (write question as if referring to the image above)",'
            f'{img_field}\n'
            '      "options": {"a": "...", "b": "...", "c": "...", "d": "..."},\n'
            '      "answer": "a",\n'
            f'      "marks": {mpq},\n'
            '      "competency_type": "recall or application"\n'
            '    }\n'
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
            f'      "text": "Long answer question text"{img_field},\n'
            f'      "marks": {mpq},\n'
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
            f'    {{"qnum": 1, "type": "SA", "text": "Question text"{img_field}, "marks": {mpq}, "competency_type": "constructed"}}\n'
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
    if any(_type_str(t) in ("assertion_reason", "assertion-reason") for t in wo.question_types):
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
   Target across the paper: ~50% application marks, ~20% recall marks, ~30% constructed marks.{or_rule}
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
# Per-section validation
# ─────────────────────────────────────────────

def validate_section_output(data: dict, wo: SectionWorkOrder) -> list:
    errors = []
    if not isinstance(data, dict):
        return ["Response is not a JSON object"]
    questions = data.get("questions", [])
    if not questions:
        return ["No 'questions' array found in response"]

    # MO-01: expected count is provided_count when attempt-N-of-M is active
    expected_count = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) else wo.questions_count
    if len(questions) != expected_count:
        errors.append(f"Expected {expected_count} questions, got {len(questions)}")

    need_options = any(_type_str(t) in ("mcq", "assertion_reason", "assertion-reason") for t in wo.question_types)
    for i, q in enumerate(questions[:3]):
        if not q.get("text"):
            errors.append(f"Q{i+1} missing 'text' field")
        if need_options and len(q.get("options", {})) < 4:
            errors.append(f"Q{i+1} must have 4 options (MCQ/AR)")
            break

    # M-01: skip uniform marks check for mixed-marks sections (compound sections
    # have MCQ at 1m and SA at 3m in the same work order). Only check when
    # marks_per_question is the sole type in the section.
    if not wo.mixed_marks:
        wrong_marks = [
            i + 1 for i, q in enumerate(questions)
            if "marks" in q and abs(float(q["marks"]) - wo.marks_per_question) > 0.1
        ]
        if wrong_marks:
            errors.append(
                f"Q{wrong_marks} have wrong marks value (expected {wo.marks_per_question} each)"
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
        if not (q.get("image_based") or q.get("type") == "image_based"):
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

        errors = validate_section_output(section_data, wo)
        if not errors:
            section_data["title"] = wo.title
            section_data["marks"] = wo.marks
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
    """
    context_map: dict = {}
    for sec_name, sec_data in blueprint.items():
        sec_types = sec_data.get("question_types") or question_types_all
        # C-01: use sub-subject for compound papers; fall back to paper-level subject
        effective_subject = sec_data.get("section_subject") or subject
        hints = _query_hints_for_types(sec_types, effective_subject)
        ctx = get_section_context(class_name, effective_subject, chapters, hints, school_id=school_id)
        # If subsection store is empty (e.g. 10_history not ingested), retry with parent subject
        if not ctx and effective_subject != subject:
            print(f"[Section-Context] '{sec_name}' subsection store empty, retrying with parent subject '{subject}'")
            hints = _query_hints_for_types(sec_types, subject)
            ctx = get_section_context(class_name, subject, chapters, hints, school_id=school_id)
        context_map[sec_name] = ctx
        print(f"[Section-Context] '{sec_name}' (subject={effective_subject}): {len(ctx)} chars")
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
        )
        work_orders.append(wo)
        subj_tag = f" [{section_subject}]" if section_subject else ""
        print(f"[WorkOrder] '{sec_name}'{subj_tag}: {generate_count}q × {mpq}m = {marks}m, types={types_list}")

    return work_orders


# ─────────────────────────────────────────────
# Cross-section validation (numbering)
# ─────────────────────────────────────────────

def cross_section_validate(paper_data: dict, blueprint: dict) -> dict:
    """Renumber questions sequentially across sections in blueprint order."""
    q_num = 1
    for sec_name in blueprint.keys():
        for q in paper_data.get(sec_name, {}).get("questions", []):
            q["qnum"] = q_num
            q_num += 1
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
    for sec_data in paper_data.values():
        sec_data["_competency_report"] = competency_report

    return paper_data, total_input_tokens, total_output_tokens
