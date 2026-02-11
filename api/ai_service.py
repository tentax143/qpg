import json
import boto3
from botocore.config import Config
import re

# Use standard Claude 3 Sonnet which is widely available
# The core module uses a specific inference profile that might be failing
# We use this local fallback to ensure functionality
MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

def get_bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        config=Config(
            read_timeout=300,
            connect_timeout=60,
            retries={'max_attempts': 3}
        )
    )

def generate_pattern_via_api(teacher_input, class_name, subject, exam_name=""):
    """
    API-layer implementation of pattern generation.
    Bypasses the core module to ensure reliable execution with correct Model IDs.
    """
    client = get_bedrock_client()
    
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
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "max_tokens": 3000,
            "temperature": 0.1,
        }

        response = client.invoke_model(
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
            modelId=MODEL_ID,
        )

        result = json.loads(response["body"].read())
        ai_response = result["content"][0]["text"]

        # Clean JSON markdown if present
        ai_response = ai_response.strip()
        if ai_response.startswith("```json"):
            ai_response = ai_response[7:]
        if ai_response.startswith("```"):
            ai_response = ai_response[3:]
        if ai_response.endswith("```"):
            ai_response = ai_response[:-3]

        pattern = json.loads(ai_response.strip())
        
        # Basic validation
        if "sections" not in pattern:
            pattern["sections"] = []
            
        return pattern

    except Exception as e:
        # Re-raise exception to be caught by the view, allowing frontend to see the error
        # instead of silently falling back to defaults
        print(f"Bedrock API Error: {str(e)}")
        raise e
    
