"""
AI-powered Blueprint Generator
Converts teacher's text input into proper JSON blueprint structure
"""
import json
from . import mantle_client

MODEL_ID = mantle_client.GEN_MODEL

def generate_blueprint_from_text(teacher_input, class_name, subject):
    """
    Convert teacher's text pattern into a proper JSON blueprint

    Args:
        teacher_input: Raw text from teacher (e.g., "Reading-5, Writing-10...")
        class_name: Class level (e.g., "8", "9", "10")
        subject: Subject name (e.g., "English", "Mathematics")

    Returns:
        dict: Properly formatted blueprint JSON
    """

    prompt = f"""You are an expert at converting teacher's exam pattern descriptions into structured JSON blueprints.

TEACHER'S INPUT:
{teacher_input}

CLASS: {class_name}
SUBJECT: {subject}

Convert this into a proper JSON blueprint structure. Follow these rules:

1. Identify sections (usually A, B, C, D, etc.)
2. Extract marks for each section
3. Identify question types (MCQ, Short Answer, Long Answer, etc.)
4. Calculate question counts based on marks

OUTPUT FORMAT:
{{
    "sections": [
        {{
            "name": "A",
            "title": "Section Title",
            "marks": total_marks,
            "question_types": ["type1", "type2"],
            "questions_count": number_of_questions,
            "marks_per_question": marks_per_question
        }}
    ]
}}

For the given input, analyze the pattern and create appropriate sections.
If the input mentions specific topics (like Reading, Writing, Grammar, Literature),
organize them into logical sections.

Common patterns:
- MCQ/Objective: Usually Section A (1 mark each)
- Short Answer: Usually Section B/C (2-3 marks each)
- Long Answer: Usually Section D/E (5 marks each)
- Extract-based: Can be in literature section

IMPORTANT:
- Return ONLY valid JSON, no explanations
- Ensure total marks match the pattern
- Make sections appropriate for the class level
- If marks distribution is unclear, make reasonable assumptions

Generate the blueprint JSON now:"""

    try:
        ai_response, _, _ = mantle_client.converse(
            model_id=MODEL_ID,
            prompt=prompt,
            max_tokens=2000,
            temperature=0.3,
        )

        # Clean the response
        ai_response = ai_response.strip()
        if ai_response.startswith("```json"):
            ai_response = ai_response[7:]
        if ai_response.startswith("```"):
            ai_response = ai_response[3:]
        if ai_response.endswith("```"):
            ai_response = ai_response[:-3]

        # Parse JSON
        blueprint = json.loads(ai_response.strip())

        # Validate and enhance the blueprint
        blueprint = validate_and_enhance_blueprint(blueprint, class_name, subject)

        return blueprint

    except json.JSONDecodeError as e:
        print(f"Error parsing AI response: {e}")
        return create_default_blueprint(class_name, subject)
    except Exception as e:
        print(f"Error generating blueprint: {e}")
        return create_default_blueprint(class_name, subject)


def validate_and_enhance_blueprint(blueprint, class_name, subject):
    """
    Validate and enhance the AI-generated blueprint
    """
    # Ensure required fields exist
    if "sections" not in blueprint:
        blueprint = {"sections": blueprint} if isinstance(blueprint, list) else {"sections": []}

    # Add missing fields to each section
    for section in blueprint.get("sections", []):
        if "question_types" not in section:
            # Infer question types based on marks
            marks = section.get("marks", 0)
            if marks <= 10:
                section["question_types"] = ["MCQ", "Fill in the blanks"]
            elif marks <= 20:
                section["question_types"] = ["Short answer"]
            else:
                section["question_types"] = ["Long answer"]

        # Ensure all required fields exist
        section.setdefault("name", "A")
        section.setdefault("title", "Section")
        section.setdefault("marks", 10)
        section.setdefault("question_types", ["Short answer"])

    return blueprint


def create_default_blueprint(class_name, subject):
    """
    Create a default blueprint if AI generation fails
    """
    return {
        "sections": [
            {
                "name": "A",
                "title": "Multiple Choice Questions",
                "marks": 10,
                "question_types": ["MCQ"],
                "questions_count": 10,
                "marks_per_question": 1
            },
            {
                "name": "B",
                "title": "Short Answer Questions",
                "marks": 20,
                "question_types": ["Short answer"],
                "questions_count": 10,
                "marks_per_question": 2
            },
            {
                "name": "C",
                "title": "Long Answer Questions",
                "marks": 20,
                "question_types": ["Long answer"],
                "questions_count": 4,
                "marks_per_question": 5
            }
        ]
    }


def parse_simple_pattern(text_input):
    """
    Parse simple pattern text and extract key information
    Helps the AI understand the structure better
    """
    lines = text_input.strip().split('\n')
    pattern_info = {
        "sections": [],
        "total_marks": 0
    }

    for line in lines:
        line = line.strip()
        if not line or line.startswith('Class') or line.startswith('Total'):
            continue

        # Look for patterns like "Reading-5" or "Grammar: 10"
        if '-' in line or ':' in line:
            parts = line.replace(':', '-').split('-')
            if len(parts) >= 2:
                section_name = parts[0].strip()
                try:
                    marks = int(parts[1].strip().split()[0])
                    pattern_info["sections"].append({
                        "name": section_name,
                        "marks": marks
                    })
                    pattern_info["total_marks"] += marks
                except:
                    pass

    return pattern_info


# Example usage
if __name__ == "__main__":
    # Test with the teacher's input
    teacher_input = """Class: 8
PT-2 Pattern

Reading Comprehension-5
Writing-5
Grammar-5
Literature - 25
i) Extract-based Questions ( SR or PR )- 5
ii) Extract-based Questions ( PM or SR )- 5
iii) Short Question Answer (PR, PM & SR)- 10
iv) Long Question Answer (PR, SR) -5

Total -40"""

    blueprint = generate_blueprint_from_text(teacher_input, "8", "English")
    print("Generated Blueprint:")
    print(json.dumps(blueprint, indent=2))