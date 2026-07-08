import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import mantle_client
from core.pattern_structure import SLOT_SCHEMA_PROMPT_RULES as _SLOT_SCHEMA_RULES
from core.pattern_structure import SLOT_OUTPUT_EXAMPLE as _OUTPUT_EXAMPLE

MODEL_ID = mantle_client.GEN_MODEL


def _parse_pattern_json(ai_response):
    """Strip markdown fences and parse the model's JSON reply."""
    ai_response = ai_response.strip()
    if ai_response.startswith("```json"):
        ai_response = ai_response[7:]
    elif ai_response.startswith("```"):
        ai_response = ai_response[3:]
    if ai_response.endswith("```"):
        ai_response = ai_response[:-3]

    pattern = json.loads(ai_response.strip())

    if "sections" not in pattern:
        pattern["sections"] = []

    return pattern


def generate_pattern_via_api(teacher_input, class_name, subject, exam_name=""):
    """
    API-layer implementation of pattern generation using Mantle bearer-token auth.
    """
    prompt = f"""You are an expert at converting teacher's exam pattern descriptions into structured JSON patterns.

TEACHER'S INPUT:
{teacher_input}

CLASS: {class_name}
SUBJECT: {subject}
EXAM NAME: {exam_name}

Convert this pattern into a JSON structure with one entry per printed question.

{_SLOT_SCHEMA_RULES}

OUTPUT FORMAT (valid JSON only — this example shows the shape, not your content):
{_OUTPUT_EXAMPLE}

Return ONLY valid JSON.
"""

    try:
        ai_response, _, _ = mantle_client.converse(
            model_id=MODEL_ID,
            prompt=prompt,
            max_tokens=8000,
            temperature=0.1,
        )
        return _parse_pattern_json(ai_response)

    except Exception as e:
        print(f"Mantle API Error: {str(e)}")
        raise


def repair_pattern_via_api(teacher_input, class_name, subject, exam_name,
                           previous_json, errors_text):
    """One repair round: resend the teacher's text, the failed JSON and the
    validator's numbered errors; the model returns a corrected full JSON."""
    prompt = f"""You previously converted a teacher's exam pattern into JSON, but it failed validation.

TEACHER'S INPUT:
{teacher_input}

CLASS: {class_name}
SUBJECT: {subject}
EXAM NAME: {exam_name}

YOUR PREVIOUS JSON:
{json.dumps(previous_json, ensure_ascii=False, indent=1)}

VALIDATION ERRORS:
{errors_text}

Fix ALL the errors and return the corrected, COMPLETE JSON in the same schema.

REPAIR RULES — CRITICAL:
- NEVER delete, merge or renumber a question slot. Every qnum in the previous JSON
  MUST appear in your output. A repair with fewer slots is WRONG and will be rejected.
- NEVER change a slot's marks to make a section total match. When the slot marks and
  the declared section/total marks disagree, the per-question detail is the truth:
  KEEP every slot exactly as it is and CHANGE the section "marks" (and "total_marks")
  to the sum of its slots.
- Change only what the errors above require; keep everything else identical.

{_SLOT_SCHEMA_RULES}

Return ONLY valid JSON.
"""
    ai_response, _, _ = mantle_client.converse(
        model_id=MODEL_ID,
        prompt=prompt,
        max_tokens=8000,
        temperature=0.1,
    )
    return _parse_pattern_json(ai_response)
