import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import mantle_client
from core.pattern_structure import SLOT_SCHEMA_PROMPT_RULES as _SLOT_SCHEMA_RULES
from core.pattern_structure import SLOT_OUTPUT_EXAMPLE as _OUTPUT_EXAMPLE

MODEL_ID = mantle_client.GEN_MODEL

# Pattern calls are BOUNDED, unlike paper-section calls. converse() otherwise derives its read
# window from max_tokens — 8000 tokens gives a 300s read, and with retries=3 a single wedged
# pattern call could occupy a worker for 15 minutes while the teacher watched a spinner. A
# pattern is one JSON document: 150s is far more than a healthy call needs (typical 30-90s)
# and still bounds the worst case to ~7.5 min including retries, under the task's soft limit.
PATTERN_CALL_TIMEOUT = (10, 150)   # (connect, read) seconds
PATTERN_CALL_RETRIES = 3
REPAIR_CALL_RETRIES = 2            # the repair is a bonus round — never let it outlast the first


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
            timeout=PATTERN_CALL_TIMEOUT,
            retries=PATTERN_CALL_RETRIES,
            stage="pattern-from-text",
        )
        return _parse_pattern_json(ai_response)

    except Exception as e:
        print(f"Mantle API Error: {str(e)}")
        raise


# Cap on the sample-paper text embedded in the extraction prompt. A 12-15 page
# board SQP is ~25-35k chars; anything past this is almost always answer keys or
# marking schemes appended to the same PDF, which the pattern doesn't need.
SQP_MAX_CHARS = 60000


def extract_pattern_from_sqp_via_api(sqp_text, class_name, subject, exam_name=""):
    """Extract a reusable exam pattern from the full text of an uploaded sample /
    board question paper. Unlike generate_pattern_via_api the input is a REAL paper,
    so the model must abstract the schema — never carry the paper's content into
    the pattern, or every paper generated from it would plagiarise the sample."""
    if len(sqp_text) > SQP_MAX_CHARS:
        sqp_text = sqp_text[:SQP_MAX_CHARS] + "\n[... remaining pages truncated ...]"

    prompt = f"""You are an expert exam-paper analyst. Below is the FULL TEXT of a sample question paper (extracted from an uploaded PDF). Convert it into a REUSABLE exam pattern JSON — the schema future papers will be generated from.

SAMPLE QUESTION PAPER TEXT:
{sqp_text}

CLASS: {class_name}
SUBJECT: {subject}
EXAM NAME: {exam_name}

EXTRACTION RULES — ABSTRACT THE STRUCTURE, NEVER COPY THE CONTENT:
1. NEVER copy the paper's passages, extracts, question wording, answer options or
   proper names into the pattern. Future papers must contain NEW questions in the
   SAME structure.
2. DO capture, for every printed question: its number, marks, question type, choice
   structure ("attempt any ten of twelve" -> choice "open" with parts + attempt;
   two full alternatives joined by OR -> choice "internal"), sub-parts with their
   per-part types and marks, and word limits.
3. DO describe HOW each question is asked in the "format" / "condition" fields, in a
   few generic words WITHOUT the content (e.g. "error-and-correction table",
   "reported speech conversion", "analogy completion from passage",
   "letter to the editor, about 120 words").
   For literature EXTRACT questions, look at the sample extract's SOURCE TEXT itself:
   if it is verse (short lines, stanzas) the slot's "format" MUST say "Poetry extract";
   if it is from a play (speaker labels, stage directions) say "Drama extract";
   otherwise say "Prose extract". This kind label is essential — it routes which
   chapters future papers quote from.
4. Copy the paper's General Instructions into the section "instructions" (rephrased
   generically where they reference this paper's specific content).
5. Use the paper's own section scheme (names, order, marks). If a section heading
   contradicts the paper's general instructions (e.g. a lettering typo), trust the
   general instructions.
6. Reading passages composed for the paper (not from the textbook) are source
   "unseen"; literature extracts/questions on named textbook chapters are source
   "textbook". Do NOT bind slots to the specific chapter titles this paper happens
   to use — chapter choice belongs to the teacher at generation time.
7. Word limits ("in about 50 words", "100-120 words") go in the slot "condition"
   or the section "constraints".
8. EITHER/OR PARTS — a paper may offer a choice between WHOLE parts and tell the
   candidate to attempt only one ("Part B has two options, attempt only ONE option";
   Accountancy XII: Analysis of Financial Statements OR Computerised Accounting).
   Emit ONLY THE FIRST such option as a section and DROP the other, then name the
   dropped alternative in that section's "instructions" (e.g. "CBSE offers an
   alternative Part B - Computerised Accounting - in place of this part; this pattern
   follows the first option"). Renumber nothing else. Keeping both options inflates
   every generated paper past the real question count and maximum marks (Accountancy
   XII becomes 42 questions / 100 marks instead of 34 / 80) — the pattern must describe
   the paper a single student actually sits.

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
            timeout=PATTERN_CALL_TIMEOUT,
            retries=PATTERN_CALL_RETRIES,
            stage="pattern-from-sqp",
        )
        return _parse_pattern_json(ai_response)

    except Exception as e:
        print(f"Mantle API Error (SQP import): {str(e)}")
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
- EXCEPTION — open-choice slots (choice "open"): the slot's "marks" MUST equal
  attempt x per-part marks (the total the student can earn). When an error flags that
  identity, FIX the slot's "marks" to attempt x per-part marks (e.g. attempt 4 of
  6 parts x 2m -> marks 8) — never "fix" it by shrinking the section or paper total
  the teacher declared.
- Change only what the errors above require; keep everything else identical.

{_SLOT_SCHEMA_RULES}

Return ONLY valid JSON.
"""
    ai_response, _, _ = mantle_client.converse(
        model_id=MODEL_ID,
        prompt=prompt,
        max_tokens=8000,
        temperature=0.1,
        timeout=PATTERN_CALL_TIMEOUT,
        retries=REPAIR_CALL_RETRIES,
        stage="pattern-repair",
    )
    return _parse_pattern_json(ai_response)
