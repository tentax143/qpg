"""
Blueprint Detail Builder - Logic for creating detailed blueprints
"""
import json
from typing import Dict, List, Any, Optional


class DetailedBlueprintBuilder:
    """
    Builder class for creating detailed blueprints with specific requirements
    """

    def __init__(self):
        self.blueprint = {
            "version": "2.0",
            "type": "detailed",
            "sections": []
        }
        self.current_section = None

    def add_section(self, name: str, title: str, marks: int) -> 'DetailedBlueprintBuilder':
        """Add a new section to the blueprint"""
        section = {
            "name": name,
            "title": title,
            "marks": marks,
            "passage_config": None,
            "question_distribution": [],
            "special_instructions": ""
        }
        self.blueprint["sections"].append(section)
        self.current_section = section
        return self

    def configure_passage(
        self,
        enabled: bool = True,
        word_min: int = 300,
        word_max: int = 400,
        passage_type: str = "narrative",
        topics: List[str] = None
    ) -> 'DetailedBlueprintBuilder':
        """Configure passage requirements for the current section"""
        if not self.current_section:
            raise ValueError("No section selected. Add a section first.")

        if enabled:
            self.current_section["passage_config"] = {
                "enabled": True,
                "word_min": word_min,
                "word_max": word_max,
                "type": passage_type,
                "topics": topics or []
            }
        else:
            self.current_section["passage_config"] = {"enabled": False}

        return self

    def add_question_type(
        self,
        question_type: str,
        count: int,
        marks_each: float,
        source: str = "general",
        specific_chapters: List[str] = None,
        difficulty: str = "medium",
        additional_specs: Dict = None
    ) -> 'DetailedBlueprintBuilder':
        """Add a question type to the current section"""
        if not self.current_section:
            raise ValueError("No section selected. Add a section first.")

        question_spec = {
            "type": question_type,
            "count": count,
            "marks_each": marks_each,
            "total_marks": count * marks_each,
            "source": source,
            "specific_chapters": specific_chapters or [],
            "difficulty": difficulty
        }

        # Add any additional specifications
        if additional_specs:
            question_spec.update(additional_specs)

        self.current_section["question_distribution"].append(question_spec)
        return self

    def set_special_instructions(self, instructions: str) -> 'DetailedBlueprintBuilder':
        """Set special instructions for the current section"""
        if not self.current_section:
            raise ValueError("No section selected. Add a section first.")

        self.current_section["special_instructions"] = instructions
        return self

    def validate(self) -> Dict[str, Any]:
        """Validate the blueprint structure"""
        errors = []
        warnings = []

        total_marks = 0
        total_questions = 0

        for section in self.blueprint["sections"]:
            section_marks_calculated = 0
            section_questions = 0

            # Check section basics
            if not section.get("name"):
                errors.append(f"Section missing name")
            if not section.get("title"):
                warnings.append(f"Section {section.get('name', '?')} missing title")

            # Validate question distribution
            for q_spec in section.get("question_distribution", []):
                count = q_spec.get("count", 0)
                marks_each = q_spec.get("marks_each", 0)
                section_marks_calculated += count * marks_each
                section_questions += count

                # Check for required fields
                if not q_spec.get("type"):
                    errors.append(f"Question in section {section.get('name', '?')} missing type")
                if count <= 0:
                    errors.append(f"Question in section {section.get('name', '?')} has invalid count")

            # Check if marks match
            section_marks_specified = section.get("marks", 0)
            if section_marks_calculated != section_marks_specified:
                errors.append(
                    f"Section {section.get('name', '?')}: "
                    f"calculated marks ({section_marks_calculated}) != "
                    f"specified marks ({section_marks_specified})"
                )

            total_marks += section_marks_specified
            total_questions += section_questions

            # Check passage config if present
            if section.get("passage_config", {}).get("enabled"):
                passage_config = section["passage_config"]
                if passage_config.get("word_min", 0) >= passage_config.get("word_max", 1):
                    errors.append(
                        f"Section {section.get('name', '?')}: "
                        f"Invalid word limit range"
                    )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "total_marks": total_marks,
            "total_questions": total_questions
        }

    def build(self) -> Dict[str, Any]:
        """Build and return the final blueprint"""
        validation = self.validate()
        if not validation["valid"]:
            raise ValueError(f"Blueprint validation failed: {validation['errors']}")

        # Add metadata
        self.blueprint["metadata"] = {
            "total_marks": validation["total_marks"],
            "total_questions": validation["total_questions"],
            "section_count": len(self.blueprint["sections"])
        }

        return self.blueprint

    def to_json(self) -> str:
        """Export blueprint as JSON string"""
        return json.dumps(self.build(), indent=2)

    @classmethod
    def from_dict(cls, blueprint_dict: Dict) -> 'DetailedBlueprintBuilder':
        """Create builder from existing blueprint dictionary"""
        builder = cls()
        builder.blueprint = blueprint_dict
        return builder

    @classmethod
    def from_simple_text(cls, text: str, class_name: str, subject: str) -> 'DetailedBlueprintBuilder':
        """
        Parse simple text format and create detailed blueprint
        Example input:
        Section A - MCQ - 10 marks
        - 2 assertion reason from NCERT
        - 4 MCQ from inside text
        - 4 MCQ from book back
        """
        builder = cls()
        lines = text.strip().split('\n')
        current_section = None
        section_counter = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it's a section header
            if line.startswith('Section') or any(line.startswith(f'{letter} -') for letter in 'ABCDE'):
                # Parse section line
                parts = line.split('-')
                if len(parts) >= 2:
                    section_name = parts[0].strip().replace('Section', '').strip()
                    if not section_name or section_name == '':
                        section_name = chr(65 + section_counter)  # A, B, C, etc.

                    # Extract title and marks
                    remaining = '-'.join(parts[1:]).strip()
                    marks = 0

                    # Try to extract marks
                    import re
                    marks_match = re.search(r'(\d+)\s*marks?', remaining, re.IGNORECASE)
                    if marks_match:
                        marks = int(marks_match.group(1))
                        title = remaining[:marks_match.start()].strip()
                        if not title:
                            title = remaining.replace(marks_match.group(0), '').strip()
                    else:
                        title = remaining

                    builder.add_section(section_name, title or f"Section {section_name}", marks)
                    section_counter += 1

            elif line.startswith('-') and builder.current_section:
                # Parse question distribution line
                line = line[1:].strip()

                # Extract count, type, and source
                import re
                # Pattern: "2 assertion reason from NCERT"
                pattern = r'(\d+)\s+(.+?)\s+from\s+(.+)'
                match = re.match(pattern, line, re.IGNORECASE)

                if match:
                    count = int(match.group(1))
                    qtype = match.group(2).strip().lower().replace(' ', '_')
                    source = match.group(3).strip().lower().replace(' ', '_')

                    # Map common terms
                    qtype_map = {
                        'assertion_reason': 'assertion_reason',
                        'mcq': 'mcq',
                        'multiple_choice': 'mcq',
                        'short_answer': 'short_answer',
                        'long_answer': 'long_answer',
                        'fill_blanks': 'fill_blanks',
                        'fill_in_the_blanks': 'fill_blanks'
                    }

                    source_map = {
                        'ncert': 'ncert',
                        'inside_text': 'inside_text',
                        'book_back': 'book_back',
                        'book_back_exercises': 'book_back',
                        'textbook': 'ncert',
                        'general': 'general'
                    }

                    qtype = qtype_map.get(qtype, qtype)
                    source = source_map.get(source, source)

                    # Calculate marks per question
                    if builder.current_section["question_distribution"]:
                        # Use same marks as previous questions in section
                        marks_each = builder.current_section["question_distribution"][-1]["marks_each"]
                    else:
                        # Guess based on question type
                        marks_each = 1 if qtype in ['mcq', 'assertion_reason', 'fill_blanks'] else 2

                    builder.add_question_type(qtype, count, marks_each, source)

        return builder


# Example usage functions
def create_sample_blueprint():
    """Create a sample detailed blueprint"""
    builder = DetailedBlueprintBuilder()

    # Section A - Reading Comprehension
    builder.add_section("A", "Reading Comprehension", 10)
    builder.configure_passage(
        enabled=True,
        word_min=300,
        word_max=400,
        passage_type="narrative",
        topics=["environment", "technology"]
    )
    builder.add_question_type("mcq", 5, 1, "passage_based")
    builder.add_question_type("short_answer", 2, 2.5, "passage_based")
    builder.set_special_instructions("Focus on vocabulary and inference questions")

    # Section B - Grammar
    builder.add_section("B", "Grammar", 10)
    builder.add_question_type("fill_blanks", 5, 1, "general")
    builder.add_question_type("error_correction", 5, 1, "general")

    # Section C - Literature
    builder.add_section("C", "Literature", 20)
    builder.add_question_type("extract_based", 2, 5, "ncert", ["Chapter 1", "Chapter 2"])
    builder.add_question_type("short_answer", 5, 2, "inside_text")

    return builder.build()


def parse_teacher_requirements(text: str) -> Dict[str, Any]:
    """
    Parse teacher's natural language requirements into structured format

    Example input:
    "For reading section, I want a passage of 300-400 words.
    Include 2 assertion-reason questions from NCERT,
    4 MCQs from inside text, and 4 MCQs from book back exercises."
    """
    requirements = {
        "passage_requirements": {},
        "question_requirements": []
    }

    # Parse passage requirements
    import re
    word_limit_pattern = r'(\d+)-(\d+)\s*words?'
    match = re.search(word_limit_pattern, text)
    if match:
        requirements["passage_requirements"] = {
            "word_min": int(match.group(1)),
            "word_max": int(match.group(2))
        }

    # Parse question requirements
    question_pattern = r'(\d+)\s+([^,]+?)(?:\s+from\s+([^,]+?))?(?:,|$)'
    matches = re.findall(question_pattern, text, re.IGNORECASE)

    for match in matches:
        count = int(match[0])
        qtype = match[1].strip()
        source = match[2].strip() if match[2] else "general"

        requirements["question_requirements"].append({
            "count": count,
            "type": qtype,
            "source": source
        })

    return requirements