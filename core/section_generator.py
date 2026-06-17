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
    questions_count: int
    marks_per_question: float
    question_types: list
    instructions: list
    constraints: dict
    context_text: str            # RAG context, capped at 2000 chars
    difficulty: str
    subject: str
    class_name: str
    chapters: list
    passage_instruction: Optional[str] = None
    extract_instruction: Optional[str] = None
    subsections: list = field(default_factory=list)


# ─────────────────────────────────────────────
# Token budget
# ─────────────────────────────────────────────

def estimate_token_budget(wo: SectionWorkOrder) -> int:
    base = 400
    per_q = 200           # avg per question including options and answer
    passage = 900 if wo.passage_instruction else 0
    extract = 700 if wo.extract_instruction else 0
    return min(8192, max(1024, base + wo.questions_count * per_q + passage + extract))


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


def _output_schema(wo: SectionWorkOrder) -> str:
    has_mcq = any(t.lower() in ("mcq", "multiple_choice", "assertion_reason", "assertion-reason", "case_based") for t in wo.question_types)
    has_passage = bool(wo.passage_instruction or wo.extract_instruction)
    needs_img = _needs_image(wo)
    mpq = wo.marks_per_question

    if has_passage:
        return (
            '{\n'
            f'  "section_id": "{wo.section_id}",\n'
            f'  "section_name": "{wo.section_name}",\n'
            '  "passage": "FULL PASSAGE TEXT HERE (400-600 words for reading; shorter for case/extract)",\n'
            '  "questions": [\n'
            f'    {{"qnum": 1, "type": "extract_based", "text": "...", "marks": {mpq}}}\n'
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
            f'      "marks": {mpq}\n'
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
            f'    {{"qnum": 1, "type": "SA", "text": "Question text"{img_field}, "marks": {mpq}}}\n'
            '  ]\n'
            '}'
        )


def build_section_prompt(wo: SectionWorkOrder, attempt: int = 1, prior_error: str = "") -> str:
    types_str = ", ".join(wo.question_types) if wo.question_types else "Mixed"
    instructions_str = "\n".join(f"- {i}" for i in wo.instructions) if wo.instructions else "- Follow CBSE guidelines"

    constraints_str = ""
    if wo.constraints:
        for k, v in wo.constraints.items():
            constraints_str += f"- {k}: {v}\n"

    passage_block = ""
    if wo.passage_instruction:
        passage_block = f"\nPASSAGE: {wo.passage_instruction}\nGenerate the passage in the 'passage' JSON key; all questions must reference it.\n"
    elif wo.extract_instruction:
        passage_block = f"\nEXTRACT: {wo.extract_instruction}\nInclude the text/extract in the 'passage' JSON key; questions must reference it.\n"

    ar_block = ""
    if any(t.lower() in ("assertion_reason", "assertion-reason") for t in wo.question_types):
        ar_block = f"\n{_ar_hint()}\n"

    image_block = ""
    if _needs_image(wo):
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

    ctx = wo.context_text[:2000] if wo.context_text else f"Use your knowledge of CBSE {wo.subject} Class {wo.class_name}"
    diff_block = _difficulty_block(wo.difficulty)

    return f"""You are a CBSE {wo.class_name} {wo.subject} question paper author.
Generate ONLY the questions for {wo.section_name} of the exam.

SECTION SPECIFICATION:
- Section: {wo.section_name} ({wo.title})
- Questions required: {wo.questions_count}
- Marks per question: {wo.marks_per_question}
- Total marks: {wo.marks}
- Question types: {types_str}

{diff_block}

REFERENCE MATERIAL (base question content on this):
---
{ctx}
---

INSTRUCTIONS:
{instructions_str}
{constraints_str}{passage_block}{ar_block}{image_block}
OUTPUT — return ONLY this JSON (no markdown fences, no explanations):
{_output_schema(wo)}

STRICT RULES:
1. Generate EXACTLY {wo.questions_count} questions — no more, no less
2. MCQ / Assertion-Reason questions MUST have 4 options: a, b, c, d
3. Do NOT embed section headers or question numbers in the 'text' field
4. Each question marks = {wo.marks_per_question}
5. Draw question content from the reference material above
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
    if len(questions) != wo.questions_count:
        errors.append(f"Expected {wo.questions_count} questions, got {len(questions)}")
    need_options = any(t.lower() in ("mcq", "assertion_reason", "assertion-reason") for t in wo.question_types)
    for i, q in enumerate(questions[:3]):
        if not q.get("text"):
            errors.append(f"Q{i+1} missing 'text' field")
        if need_options and len(q.get("options", {})) < 4:
            errors.append(f"Q{i+1} must have 4 options (MCQ/AR)")
            break
    return errors


# ─────────────────────────────────────────────
# Single-section generator (with retry)
# ─────────────────────────────────────────────

def generate_section(wo: SectionWorkOrder):
    """
    Generate questions for one section. Retries up to MAX_SECTION_RETRIES times on validation
    failure, passing the error back to the LLM.
    Returns ({section_name: section_data}, total_input_tokens, total_output_tokens).
    """
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
            return {wo.section_name: section_data}, total_in_tok, total_out_tok

    raise RuntimeError(f"'{wo.section_name}': exhausted all retries")  # unreachable


# ─────────────────────────────────────────────
# RAG context per section
# ─────────────────────────────────────────────

def _query_hints_for_types(question_types: list, subject: str) -> list:
    hints = [f"{subject} important concepts definitions"]
    for qt in question_types:
        ql = qt.lower()
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


def get_section_context(class_name: str, subject: str, chapters: list, query_hints: list, max_chars: int = 2000) -> str:
    all_docs = []
    seen: set = set()

    for chapter in chapters:
        for query in query_hints[:4]:
            try:
                results = embeddings.query(
                    class_name=class_name,
                    subject=subject,
                    unit=chapter,
                    query_text=query,
                    n_results=4,
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


def get_section_context_map(class_name: str, subject: str, chapters: list, blueprint: dict, question_types_all: list) -> dict:
    """Return {section_name: context_text} for every section in blueprint."""
    context_map: dict = {}
    for sec_name, sec_data in blueprint.items():
        sec_types = sec_data.get("question_types", question_types_all)
        hints = _query_hints_for_types(sec_types, subject)
        ctx = get_section_context(class_name, subject, chapters, hints)
        context_map[sec_name] = ctx
        print(f"[Section-Context] '{sec_name}': {len(ctx)} chars")
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
        q_count = sec_data.get("questions_count", 0)
        marks = sec_data.get("marks", 0)
        mpq = round(marks / q_count, 1) if q_count else 1.0

        # Use the pattern section's explicit 'id' first, then blueprint's id, then derive from name
        section_id = (
            ps.get("id")
            or sec_data.get("id")
            or _section_id_from_name(sec_name, idx)
        )

        wo = SectionWorkOrder(
            section_name=sec_name,
            section_id=section_id,
            title=sec_data.get("title", ""),
            marks=marks,
            questions_count=q_count,
            marks_per_question=mpq,
            question_types=sec_data.get("question_types", []),
            instructions=ps.get("instructions", sec_data.get("instructions", [])),
            constraints=ps.get("constraints", sec_data.get("constraints", {})),
            context_text=context_map.get(sec_name, ""),
            difficulty=difficulty,
            subject=subject,
            class_name=class_name,
            chapters=list(chapters),
            passage_instruction=ps.get("passage_instruction"),
            extract_instruction=ps.get("extract_instruction"),
            subsections=sec_data.get("subsections", []),
        )
        work_orders.append(wo)
        print(f"[WorkOrder] '{sec_name}': {q_count}q × {mpq}m = {marks}m, types={wo.question_types}")

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
    return paper_data, total_input_tokens, total_output_tokens
