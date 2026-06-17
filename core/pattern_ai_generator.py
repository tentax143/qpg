"""
Enhanced AI-powered Pattern Generator
Converts teacher's text input into comprehensive exam patterns with instructions and constraints.
Replaces the old blueprint system with a unified pattern approach.
"""
import json
import re
from . import mantle_client

MODEL_ID = mantle_client.GEN_MODEL


def generate_pattern_from_text(teacher_input, class_name, subject, exam_name=""):
    """
    Convert teacher's text pattern into a comprehensive exam pattern JSON.

    Args:
        teacher_input: Raw text from teacher with pattern details
        class_name: Class level (e.g., "7", "8", "10")
        subject: Subject name (e.g., "English", "Mathematics")
        exam_name: Exam name (e.g., "PT-2", "Half-Yearly")

    Returns:
        dict: Properly formatted pattern JSON with sections, instructions, and constraints

    Example input:
        Class: 7
        PT-2 Pattern
        *Reading Comprehension-5 limit the passage to 300-400 words
        *Writing -5 do it like this
        *Grammar-5 do it like that
        *Literature - 25
        i) Extract-based Questions ( SR or PR )- 5
        ii) Extract-based Questions ( PM or SR )- 5
        iii) Short Question Answer (PR, PM & SR)- 10
        iv) Long Question Answer (PR, SR) -5
        Total -40
    """

    prompt = f"""You are an expert at converting teacher's exam pattern descriptions into structured JSON patterns.
Your task is to extract ALL information including custom instructions, constraints, AND passage/extract requirements.

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
   - marks_per_question (marks per question)
   - question_types (types of questions like MCQ, Short Answer, Essay, etc.)
   - instructions (any special instructions mentioned for this section)
   - constraints (any limitations like word limits, specific requirements)
   - passage (IMPORTANT: If section mentions passage/reading material, include this key with explicit instruction "Generate passage of X-Y words and create Y questions from it")
   - extract (IMPORTANT: If section mentions extract/literature passages, include this key with instruction "Generate extract text with Y questions based on extract")
3. Handle subsections (when a section has multiple parts like Literature examples)
4. Keep custom instructions exactly as mentioned by teacher

CONSTRAINT EXTRACTION:
- Look for phrases like "limit to", "maximum", "minimum", "should be", "must be"
- Extract word limits, format requirements, specific requirements
- Parse numerical constraints (e.g., "300-400 words")

INSTRUCTION EXTRACTION:
- Any special instructions for that section
- Question types specifications
- Content requirements
- Format requirements
- PASSAGE REQUIREMENTS: If teacher mentions passage/comprehension, extract passage requirements (word count, source, custom requirements)
- EXTRACT REQUIREMENTS: If teacher mentions extracts (SR, PM, PR notation), extract extract requirements

PASSAGE/EXTRACT HANDLING:
When teacher's input mentions:
- "passage" or "reading comprehension" → Add "passage_instruction" field with word count and requirements
- "extract" or "SR/PM/PR" → Add "extract_instruction" field with extract type and requirements
Examples:
- Teacher input: "Reading Comprehension - 5, limit the passage to 300-400 words"
  → Add: "passage_instruction": "Generate a 300-400 word passage on relevant topic and create 5 comprehension questions from it"
- Teacher input: "Extract (SR/PM) - 5"
  → Add: "extract_instruction": "Generate extract text (SR/PM format) and create 5 questions based on the extract"

OUTPUT FORMAT (MUST be valid JSON):
{{
    "sections": [
        {{
            "id": "unique_id",
            "name": "Section Name",
            "marks": total_marks,
            "questions_count": number_of_questions,
            "marks_per_question": marks_per_question,
            "question_types": ["type1", "type2"],
            "instructions": ["instruction1", "instruction2"],
            "constraints": {{
                "word_limit": {{"min": 300, "max": 400}},
                "other_constraint": "value"
            }},
            "passage_instruction": "If applicable: instruction for passage generation",
            "extract_instruction": "If applicable: instruction for extract generation",
            "subsections": [
                {{
                    "id": "subsection_id",
                    "name": "Subsection Name",
                    "marks": marks,
                    "questions_count": count,
                    "marks_per_question": marks_per_question,
                    "question_types": ["type"],
                    "instructions": [],
                    "extract_instruction": "If applicable for this subsection"
                }}
            ]
        }}
    ],
    "total_marks": total_marks,
    "total_questions": total_questions,
    "metadata": {{
        "exam_name": "{exam_name}",
        "subject": "{subject}",
        "class": "{class_name}"
    }}
}}

IMPORTANT:
- Return ONLY valid JSON, no explanations
- Ensure total marks match the pattern given
- Make sections appropriate for class {class_name}
- Keep instructions and constraints separate and clear
- Use meaningful IDs (e.g., "RC" for Reading Comprehension, "LIT" for Literature)
- If a section has subsections, include them in the "subsections" array
- Extract ALL custom instructions mentioned by the teacher
- CRITICAL: For ANY section that requires passages or extracts, include passage_instruction or extract_instruction field
- The passage_instruction/extract_instruction must explicitly tell the paper generator to create passages/extracts with questions

Generate the pattern JSON now:"""

    try:
        ai_response, _, _ = mantle_client.converse(
            model_id=MODEL_ID,
            prompt=prompt,
            max_tokens=3000,
            temperature=0.2,
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
        pattern = json.loads(ai_response.strip())

        # Validate and enhance the pattern
        pattern = validate_and_enhance_pattern(pattern, class_name, subject, exam_name)

        return pattern

    except json.JSONDecodeError as e:
        print(f"Error parsing AI response: {e}")
        return create_default_pattern(class_name, subject, exam_name)
    except Exception as e:
        print(f"Error generating pattern: {e}")
        return create_default_pattern(class_name, subject, exam_name)


def validate_and_enhance_pattern(pattern, class_name, subject, exam_name):
    """
    Validate and enhance the AI-generated pattern
    """
    # Ensure required top-level fields
    if "sections" not in pattern:
        pattern = {"sections": pattern} if isinstance(pattern, list) else {"sections": []}

    # Add missing top-level fields
    pattern.setdefault("total_marks", 0)
    pattern.setdefault("total_questions", 0)
    pattern.setdefault("metadata", {})

    pattern["metadata"].update({
        "exam_name": exam_name,
        "subject": subject,
        "class": class_name
    })

    # Validate and enhance each section
    total_marks = 0
    total_questions = 0

    for section in pattern.get("sections", []):
        # Add default ID if missing
        if "id" not in section:
            section["id"] = section.get("name", "Section").upper()[:3]

        # Set defaults
        section.setdefault("name", "Section")
        section.setdefault("marks", 0)
        section.setdefault("questions_count", 0)
        section.setdefault("marks_per_question", 1)
        section.setdefault("question_types", ["Short Answer"])
        section.setdefault("instructions", [])
        section.setdefault("constraints", {})
        section.setdefault("subsections", [])

        # Calculate marks and questions for section
        total_marks += section.get("marks", 0)
        total_questions += section.get("questions_count", 0)

        # Validate subsections
        for subsec in section.get("subsections", []):
            if "id" not in subsec:
                subsec["id"] = f"{section['id']}_SUB{section['subsections'].index(subsec)}"

            subsec.setdefault("name", "Subsection")
            subsec.setdefault("marks", 0)
            subsec.setdefault("questions_count", 0)
            subsec.setdefault("marks_per_question", 1)
            subsec.setdefault("question_types", ["Short Answer"])
            subsec.setdefault("instructions", [])

            total_marks += subsec.get("marks", 0)
            total_questions += subsec.get("questions_count", 0)

    pattern["total_marks"] = total_marks
    pattern["total_questions"] = total_questions

    return pattern


def create_default_pattern(class_name, subject, exam_name="Default"):
    """
    Create a default pattern if AI generation fails
    """
    return {
        "sections": [
            {
                "id": "SEC_A",
                "name": "Section A",
                "marks": 10,
                "questions_count": 10,
                "marks_per_question": 1,
                "question_types": ["MCQ"],
                "instructions": [],
                "constraints": {},
                "subsections": []
            },
            {
                "id": "SEC_B",
                "name": "Section B",
                "marks": 20,
                "questions_count": 10,
                "marks_per_question": 2,
                "question_types": ["Short Answer"],
                "instructions": [],
                "constraints": {},
                "subsections": []
            },
            {
                "id": "SEC_C",
                "name": "Section C",
                "marks": 20,
                "questions_count": 4,
                "marks_per_question": 5,
                "question_types": ["Long Answer"],
                "instructions": [],
                "constraints": {},
                "subsections": []
            }
        ],
        "total_marks": 50,
        "total_questions": 24,
        "metadata": {
            "exam_name": exam_name,
            "subject": subject,
            "class": class_name
        }
    }


def parse_manual_pattern(pattern_dict):
    """
    Parse manually structured pattern dictionary into standardized format.
    Useful for when patterns are created programmatically.

    Args:
        pattern_dict: Dictionary with pattern structure

    Returns:
        dict: Standardized pattern
    """
    pattern = {
        "sections": [],
        "total_marks": 0,
        "total_questions": 0,
        "metadata": pattern_dict.get("metadata", {})
    }

    for section_idx, section in enumerate(pattern_dict.get("sections", [])):
        standardized_section = {
            "id": section.get("id", f"SEC_{chr(65+section_idx)}"),
            "name": section.get("name", f"Section {chr(65+section_idx)}"),
            "marks": section.get("marks", 0),
            "questions_count": section.get("questions_count", 0),
            "marks_per_question": section.get("marks_per_question", 1),
            "question_types": section.get("question_types", ["Short Answer"]),
            "instructions": section.get("instructions", []),
            "constraints": section.get("constraints", {}),
            "subsections": section.get("subsections", [])
        }

        pattern["sections"].append(standardized_section)
        pattern["total_marks"] += standardized_section["marks"]
        pattern["total_questions"] += standardized_section["questions_count"]

    return pattern


# Example usage and testing
if __name__ == "__main__":
    # Test with the teacher's PT-2 example
    teacher_input = """Class: 7
PT-2 Pattern
*Reading Comprehension-5 limit the passage to 300-400 words
*Writing -5 do it like this
*Grammar-5 do it like that
*Literature - 25
i) Extract-based Questions ( SR or PR )- 5
ii) Extract-based Questions ( PM or SR )- 5
iii) Short Question Answer (PR, PM & SR)- 10
iv) Long Question Answer (PR, SR) -5
Total -40"""

    pattern = generate_pattern_from_text(teacher_input, "7", "English", "PT-2")
    print("Generated Pattern:")
    print(json.dumps(pattern, indent=2))
