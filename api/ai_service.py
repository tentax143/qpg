import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import mantle_client

MODEL_ID = mantle_client.GEN_MODEL


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

Analyze this pattern and create a comprehensive JSON structure.

KEY RULES:
1. Extract sections (main topics/sections in the exam)
2. For each section, extract:
   - name (section name)
   - marks (total marks for section)
   - questions_count (number of questions)
   - question_types (types of questions like MCQ, Short Answer, Essay, etc.)
   - instructions (any special instructions mentioned for this section)
   - constraints (any limitations like word limits)
   - passage_instruction (if reading comprehension/passage needed)
   - extract_instruction (if literature extract needed)

OUTPUT FORMAT (Valid JSON only):
{{
    "sections": [
        {{
            "id": "SEC_A",
            "name": "Section Name",
            "marks": 10,
            "questions_count": 5,
            "marks_per_question": 2,
            "question_types": ["Type"],
            "instructions": ["Instr 1"],
            "constraints": {{"limit": "value"}},
            "subsections": []
        }}
    ],
    "total_marks": 50,
    "total_questions": 20,
    "metadata": {{
        "exam_name": "{exam_name}",
        "subject": "{subject}",
        "class": "{class_name}"
    }}
}}

Return ONLY valid JSON.
"""

    try:
        ai_response, _, _ = mantle_client.converse(
            model_id=MODEL_ID,
            prompt=prompt,
            max_tokens=3000,
            temperature=0.1,
        )

        # Strip markdown code fences if present
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

    except Exception as e:
        print(f"Mantle API Error: {str(e)}")
        raise
