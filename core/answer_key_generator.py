"""Generate source-aware teacher answer keys from stored question-paper JSON."""

import hashlib
import json
from decimal import Decimal

from . import embeddings, mantle_client


INPUT_COST_PER_1K = Decimal("0.49")
OUTPUT_COST_PER_1K = Decimal("1.47")


def paper_revision_hash(paper_data):
    canonical = json.dumps(paper_data or {}, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def iter_paper_sections(paper_data):
    sections = paper_data.get("sections", paper_data) if isinstance(paper_data, dict) else paper_data
    if isinstance(sections, dict):
        for section_name, section_data in sections.items():
            if isinstance(section_data, dict) and isinstance(section_data.get("questions"), list):
                yield section_name, section_data
    elif isinstance(sections, list):
        for index, section_data in enumerate(sections, start=1):
            if isinstance(section_data, dict) and isinstance(section_data.get("questions"), list):
                name = section_data.get("section_name") or section_data.get("name") or f"Section {index}"
                yield name, section_data


def _number(value, fallback=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _display_marks(value):
    number = _number(value)
    return int(number) if number.is_integer() else number


def _target(target_id, label, text, marks, answer_hint="", options=None):
    return {
        "id": target_id,
        "label": label,
        "text": str(text or "").strip(),
        "marks": _display_marks(marks),
        "answer_hint": str(answer_hint or "").strip(),
        "options": options if isinstance(options, dict) else {},
    }


def answer_targets(question):
    """Return the independently answerable parts of one generated question."""
    targets = []
    base_marks = question.get("marks", 0)
    sub_questions = question.get("sub_questions")
    if isinstance(sub_questions, list) and sub_questions:
        for index, sub_question in enumerate(sub_questions):
            if not isinstance(sub_question, dict):
                continue
            label = f"Part ({chr(97 + index)})"
            targets.append(_target(
                f"part_{index + 1}", label,
                sub_question.get("text") or sub_question.get("question") or sub_question.get("q"),
                sub_question.get("marks", base_marks),
                sub_question.get("answer_explanation") or sub_question.get("answer"),
                sub_question.get("options"),
            ))
    else:
        targets.append(_target(
            "main", "Answer", question.get("text") or question.get("question") or question.get("q"),
            base_marks, question.get("answer_explanation") or question.get("answer"), question.get("options"),
        ))

    alternatives = question.get("or_alternative")
    alternatives = alternatives if isinstance(alternatives, list) else [alternatives] if alternatives else []
    for alternative_index, alternative in enumerate(alternatives, start=1):
        if isinstance(alternative, dict):
            alternative_parts = alternative.get("sub_questions")
            if isinstance(alternative_parts, list) and alternative_parts:
                for part_index, sub_question in enumerate(alternative_parts):
                    if not isinstance(sub_question, dict):
                        continue
                    label = f"Alternative {alternative_index}, part ({chr(97 + part_index)})"
                    targets.append(_target(
                        f"alternative_{alternative_index}_part_{part_index + 1}", label,
                        sub_question.get("text") or sub_question.get("question") or sub_question.get("q"),
                        sub_question.get("marks", alternative.get("marks", base_marks)),
                        sub_question.get("answer_explanation") or sub_question.get("answer"),
                        sub_question.get("options"),
                    ))
            else:
                targets.append(_target(
                    f"alternative_{alternative_index}", f"Alternative {alternative_index}",
                    alternative.get("text") or alternative.get("question") or alternative.get("q"),
                    alternative.get("marks", base_marks),
                    alternative.get("answer_explanation") or alternative.get("answer"), alternative.get("options"),
                ))
        elif isinstance(alternative, str):
            targets.append(_target(
                f"alternative_{alternative_index}", f"Alternative {alternative_index}", alternative,
                base_marks, "", {},
            ))
    return [target for target in targets if target["text"]]


def _evidence_for_question(paper, question, school_id):
    chapter = str(question.get("chapter_tag") or "").strip()
    question_text = str(question.get("text") or question.get("question") or question.get("q") or "").strip()
    query_text = " ".join(piece for piece in (paper.subject, chapter, question_text) if piece)
    if not query_text:
        return []
    try:
        results = embeddings.query(
            class_name=str(paper.class_name or "").split("-", 1)[0],
            subject=paper.subject,
            unit=chapter,
            query_text=query_text,
            n_results=3,
            school_id=school_id,
        )
    except Exception:
        return []
    identifiers = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadata = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    evidence = []
    for index, chunk_id in enumerate(identifiers):
        document = documents[index] if index < len(documents) else ""
        meta = metadata[index] if index < len(metadata) and isinstance(metadata[index], dict) else {}
        distance = distances[index] if index < len(distances) else None
        evidence.append({
            "chunk_id": str(chunk_id),
            "material_id": meta.get("material_id"),
            "title": meta.get("title") or "",
            "unit": meta.get("unit") or chapter,
            "excerpt": str(document or "")[:700],
            "distance": round(_number(distance), 4) if distance is not None else None,
        })
    return evidence


def _extract_json_object(text):
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _prompt_for_question(paper, question, targets, evidence, correction=""):
    source_context = [
        {
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "unit": item["unit"],
            "excerpt": item["excerpt"],
        }
        for item in evidence
    ]
    question_payload = {
        "qnum": question.get("qnum"),
        "type": question.get("type"),
        "subtype": question.get("subtype"),
        "chapter_tag": question.get("chapter_tag"),
        "source_text": question.get("source_text"),
        "existing_answer": question.get("answer"),
        "existing_explanation": question.get("answer_explanation"),
        "targets": targets,
    }
    return (
        f"CLASS: {paper.class_name}\nSUBJECT: {paper.subject}\n\n"
        f"QUESTION DATA:\n{json.dumps(question_payload, ensure_ascii=False)}\n\n"
        f"RETRIEVED SOURCE EVIDENCE:\n{json.dumps(source_context, ensure_ascii=False)}\n\n"
        f"{correction}\n"
        "Return the answer-key JSON now:"
    )


ANSWER_KEY_SYSTEM_PROMPT = """You create a teacher-only CBSE answer key and concept insight for one exam question.
Return ONLY valid JSON with this exact shape:
{
  "answers": [
    {
      "target": "target id supplied in QUESTION DATA",
      "answer": "direct, complete model answer",
      "correct_option": "a|b|c|d or empty string",
      "marking_scheme": [{"point": "mark-worthy point", "marks": 1}],
      "concept": {"name": "primary concept", "chapter": "chapter name", "explanation": "why this concept solves the question"},
      "insight": {"explanation": "clear concept explanation", "common_misconception": "likely error", "revision_tip": "specific study tip"},
      "evidence_chunk_ids": ["only supplied chunk ids"],
      "confidence": "high|medium|low"
    }
  ]
}
Rules:
- Produce exactly one answer object for every supplied target id and no extra targets.
- The marking_scheme marks must add up exactly to that target's marks.
- For MCQs, correct_option must be the valid correct option and answer must name or explain it.
- Answer every internal-choice alternative and every sub-question separately.
- Use retrieved evidence when it supports the answer. Never invent a source id. If evidence is insufficient, still provide a curriculum-appropriate answer but set confidence to low and evidence_chunk_ids to an empty list.
- Treat any existing answer/explanation as a draft to verify, not as ground truth.
"""


def _clean_marking_scheme(value):
    scheme = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        point = str(item.get("point") or "").strip()
        marks = _number(item.get("marks"), 0)
        if point and marks > 0:
            scheme.append({"point": point, "marks": _display_marks(marks)})
    return scheme


def _normalise_response(payload, targets, evidence):
    responses = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(responses, list):
        raise ValueError("The model did not return an answers list.")
    by_target = {
        str(item.get("target") or "").strip(): item
        for item in responses if isinstance(item, dict)
    }
    evidence_by_id = {item["chunk_id"]: item for item in evidence}
    answers = []
    issues = []
    for target in targets:
        response = by_target.get(target["id"])
        if not response:
            raise ValueError(f"The model omitted {target['label']}.")
        answer_text = str(response.get("answer") or "").strip()
        if not answer_text:
            raise ValueError(f"The model returned an empty answer for {target['label']}.")
        marking_scheme = _clean_marking_scheme(response.get("marking_scheme"))
        awarded_marks = sum(_number(item["marks"]) for item in marking_scheme)
        if abs(awarded_marks - _number(target["marks"])) > 0.01:
            issues.append(
                f"{target['label']}: marking scheme totals {_display_marks(awarded_marks)} instead of {target['marks']}."
            )
        concept = response.get("concept") if isinstance(response.get("concept"), dict) else {}
        insight = response.get("insight") if isinstance(response.get("insight"), dict) else {}
        requested_evidence = response.get("evidence_chunk_ids") if isinstance(response.get("evidence_chunk_ids"), list) else []
        selected_evidence = [evidence_by_id[chunk_id] for chunk_id in requested_evidence if chunk_id in evidence_by_id]
        correct_option = str(response.get("correct_option") or "").strip().lower()
        valid_options = {str(key).lower() for key in target["options"].keys()}
        if valid_options and correct_option not in valid_options:
            issues.append(f"{target['label']}: returned invalid MCQ option {correct_option or 'empty'}.")
        answers.append({
            "target": target["id"],
            "label": target["label"],
            "question": target["text"],
            "marks": target["marks"],
            "answer": answer_text,
            "correct_option": correct_option if correct_option in valid_options else "",
            "marking_scheme": marking_scheme,
            "concept": {
                "name": str(concept.get("name") or "").strip(),
                "chapter": str(concept.get("chapter") or "").strip(),
                "explanation": str(concept.get("explanation") or "").strip(),
            },
            "insight": {
                "explanation": str(insight.get("explanation") or "").strip(),
                "common_misconception": str(insight.get("common_misconception") or "").strip(),
                "revision_tip": str(insight.get("revision_tip") or "").strip(),
            },
            "confidence": str(response.get("confidence") or "low").strip().lower(),
            "evidence": selected_evidence,
            "warnings": [],
        })
    if len(by_target) != len(targets):
        issues.append("The model returned unexpected answer targets.")
    return answers, issues


def generate_question_answer_key(paper, question, school_id=None):
    targets = answer_targets(question)
    if not targets:
        raise ValueError("Question has no answerable text.")
    evidence = _evidence_for_question(paper, question, school_id)
    total_input_tokens = 0
    total_output_tokens = 0
    correction = ""
    for attempt in range(2):
        prompt = _prompt_for_question(paper, question, targets, evidence, correction)
        raw, input_tokens, output_tokens = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL,
            prompt=prompt,
            system_prompt=ANSWER_KEY_SYSTEM_PROMPT,
            max_tokens=1800,
            temperature=0.2,
        )
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        payload = _extract_json_object(raw)
        try:
            answers, issues = _normalise_response(payload, targets, evidence)
        except ValueError as error:
            if attempt == 1:
                raise
            correction = f"Your previous response was invalid: {error} Correct every schema error."
            continue
        return answers, issues, total_input_tokens, total_output_tokens
    raise ValueError("The model did not return a usable answer key.")


def build_answer_key(paper, school_id=None):
    sections = []
    errors = []
    total_input_tokens = 0
    total_output_tokens = 0
    generated_questions = 0
    for section_name, section_data in iter_paper_sections(paper.paper_data):
        question_entries = []
        for question in section_data.get("questions", []):
            if not isinstance(question, dict):
                continue
            try:
                answers, warnings, input_tokens, output_tokens = generate_question_answer_key(
                    paper, question, school_id=school_id)
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                generated_questions += 1
                question_entries.append({
                    "qnum": question.get("qnum"),
                    "text": str(question.get("text") or question.get("question") or question.get("q") or "").strip(),
                    "type": question.get("type") or "",
                    "subtype": question.get("subtype") or "",
                    "marks": _display_marks(question.get("marks")),
                    "chapter_tag": question.get("chapter_tag") or "",
                    "options": question.get("options") if isinstance(question.get("options"), dict) else {},
                    "answers": answers,
                    "warnings": warnings,
                })
            except Exception as error:
                errors.append({
                    "section": section_name,
                    "qnum": question.get("qnum"),
                    "error": str(error)[:500],
                })
        if question_entries:
            sections.append({"name": section_name, "questions": question_entries})
    if not generated_questions:
        raise ValueError("No question answers could be generated.")
    return {
        "paper": {
            "id": paper.id,
            "class_name": paper.class_name,
            "subject": paper.subject,
            "revision_hash": paper_revision_hash(paper.paper_data),
        },
        "sections": sections,
        "errors": errors,
        "generated_questions": generated_questions,
    }, total_input_tokens, total_output_tokens


def calculate_cost(input_tokens, output_tokens):
    return ((Decimal(input_tokens or 0) / Decimal(1000)) * INPUT_COST_PER_1K
            + (Decimal(output_tokens or 0) / Decimal(1000)) * OUTPUT_COST_PER_1K)
