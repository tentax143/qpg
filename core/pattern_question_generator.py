"""
Pattern-based Question Generator
Generates questions directly from the unified Pattern model without needing blueprints.
This is the core component that uses the new unified pattern system.
"""

import json
import random
from typing import Dict, List, Optional, Tuple
from .models import ExamPattern
from . import generator
from . import embeddings


class PatternQuestionGenerator:
    """
    Generates questions based on a unified Pattern.
    Handles sections, subsections, instructions, and constraints.
    """

    def __init__(self, pattern: ExamPattern):
        """
        Initialize generator with a pattern.

        Args:
            pattern: ExamPattern model instance
        """
        self.pattern = pattern
        self.pattern_data = pattern.sections
        self.metadata = {
            "class": pattern.class_name,
            "subject": pattern.subject,
            "exam_name": pattern.name
        }

    def generate_questions(
        self,
        chapters: List[str],
        difficulty: str = "Medium",
        max_retries: int = 3
    ) -> Dict:
        """
        Generate complete question paper based on the pattern.

        Args:
            chapters: List of chapters to draw from
            difficulty: Question difficulty level
            max_retries: Number of retries for generation

        Returns:
            Dict with question paper structure and content
        """
        questions_by_section = {}
        total_generated = 0
        errors = []

        for section in self.pattern_data:
            try:
                section_questions = self._generate_section_questions(
                    section=section,
                    chapters=chapters,
                    difficulty=difficulty,
                    retries=max_retries
                )
                questions_by_section[section.get("id", section.get("name"))] = section_questions
                total_generated += len(section_questions)
            except Exception as e:
                errors.append(f"Error in section {section.get('name')}: {str(e)}")

        return {
            "metadata": self.metadata,
            "pattern_info": {
                "name": self.pattern.name,
                "total_marks": self.pattern.total_marks,
                "total_questions": self.pattern.total_questions
            },
            "questions_by_section": questions_by_section,
            "total_generated": total_generated,
            "errors": errors,
            "status": "success" if not errors else "partial"
        }

    def _generate_section_questions(
        self,
        section: Dict,
        chapters: List[str],
        difficulty: str,
        retries: int = 3
    ) -> List[Dict]:
        """
        Generate questions for a single section.

        Args:
            section: Section configuration from pattern
            chapters: Available chapters
            difficulty: Difficulty level
            retries: Number of retries

        Returns:
            List of generated questions
        """
        questions = []

        # Handle subsections if they exist
        if section.get("subsections"):
            for subsection in section["subsections"]:
                sub_questions = self._generate_subsection_questions(
                    subsection=subsection,
                    parent_section=section,
                    chapters=chapters,
                    difficulty=difficulty,
                    retries=retries
                )
                questions.extend(sub_questions)
        else:
            # Generate questions directly for section
            questions = self._generate_subsection_questions(
                subsection=section,
                parent_section=None,
                chapters=chapters,
                difficulty=difficulty,
                retries=retries
            )

        return questions

    def _generate_subsection_questions(
        self,
        subsection: Dict,
        parent_section: Optional[Dict],
        chapters: List[str],
        difficulty: str,
        retries: int = 3
    ) -> List[Dict]:
        """
        Generate questions for a subsection with all constraints and instructions.

        Args:
            subsection: Subsection/section configuration
            parent_section: Parent section if this is a subsection
            chapters: Available chapters
            difficulty: Difficulty level
            retries: Number of retries

        Returns:
            List of generated questions
        """
        questions = []
        question_count = subsection.get("questions_count", 0)
        question_types = subsection.get("question_types", ["Short Answer"])
        instructions = subsection.get("instructions", [])
        constraints = subsection.get("constraints", {})

        # Build context from chapters
        context = self._get_section_context(chapters, limit=5000)

        for q_idx in range(question_count):
            try:
                question = self._generate_single_question(
                    subsection_config=subsection,
                    parent_section=parent_section,
                    question_types=question_types,
                    instructions=instructions,
                    constraints=constraints,
                    context=context,
                    difficulty=difficulty,
                    question_number=q_idx + 1,
                    retries=retries
                )

                if question:
                    questions.append(question)

            except Exception as e:
                print(f"Error generating question {q_idx + 1} for {subsection.get('name')}: {str(e)}")

        return questions

    def _generate_single_question(
        self,
        subsection_config: Dict,
        parent_section: Optional[Dict],
        question_types: List[str],
        instructions: List[str],
        constraints: Dict,
        context: str,
        difficulty: str,
        question_number: int,
        retries: int = 3
    ) -> Optional[Dict]:
        """
        Generate a single question with all pattern constraints.

        Args:
            subsection_config: Configuration for the subsection
            parent_section: Parent section if applicable
            question_types: Allowed question types
            instructions: Special instructions for this section
            constraints: Constraints (word limits, etc.)
            context: Content context for questions
            difficulty: Difficulty level
            question_number: Question number in sequence
            retries: Number of retries

        Returns:
            Generated question dict or None
        """
        # Randomly select a question type
        question_type = random.choice(question_types)

        # Build constraint description
        constraint_text = self._build_constraint_text(constraints)

        # Build instruction text
        instruction_text = "\n".join(instructions) if instructions else ""

        # Create prompt for question generation
        prompt = self._build_question_generation_prompt(
            subsection_name=subsection_config.get("name", "Question"),
            question_type=question_type,
            marks=subsection_config.get("marks_per_question", 1),
            difficulty=difficulty,
            instructions=instruction_text,
            constraints=constraint_text,
            context=context,
            question_number=question_number
        )

        # Call AI to generate question
        try:
            question_text, _, _ = generator.call_bedrock(
                prompt=prompt,
                model_ref=generator.GEN_MODEL_ID,
                max_tokens=1500,
                temperature=0.7,
                retries=retries
            )

            return {
                "id": f"{subsection_config.get('id', 'Q')}_{question_number}",
                "section": subsection_config.get("name", ""),
                "parent_section": parent_section.get("name", "") if parent_section else None,
                "marks": subsection_config.get("marks_per_question", 1),
                "question_type": question_type,
                "difficulty": difficulty,
                "content": question_text.strip(),
                "instructions_applied": instructions,
                "constraints_applied": constraint_text
            }

        except Exception as e:
            print(f"Error calling Bedrock for question generation: {str(e)}")
            return None

    def _build_constraint_text(self, constraints: Dict) -> str:
        """
        Convert constraints dict to human-readable text.

        Args:
            constraints: Constraints dictionary

        Returns:
            Formatted constraint text
        """
        if not constraints:
            return ""

        constraint_lines = []

        if "word_limit" in constraints:
            limit = constraints["word_limit"]
            if isinstance(limit, dict):
                min_words = limit.get("min", "")
                max_words = limit.get("max", "")
                if min_words and max_words:
                    constraint_lines.append(f"- Word limit: {min_words}-{max_words} words")
                elif max_words:
                    constraint_lines.append(f"- Maximum {max_words} words")
                elif min_words:
                    constraint_lines.append(f"- Minimum {min_words} words")

        if "character_limit" in constraints:
            constraint_lines.append(f"- Character limit: {constraints['character_limit']}")

        for key, value in constraints.items():
            if key not in ["word_limit", "character_limit"]:
                constraint_lines.append(f"- {key.replace('_', ' ').title()}: {value}")

        return "\n".join(constraint_lines)

    def _build_question_generation_prompt(
        self,
        subsection_name: str,
        question_type: str,
        marks: int,
        difficulty: str,
        instructions: str,
        constraints: str,
        context: str,
        question_number: int
    ) -> str:
        """
        Build the prompt for AI question generation.

        Args:
            subsection_name: Name of the subsection
            question_type: Type of question
            marks: Marks for this question
            difficulty: Difficulty level
            instructions: Special instructions
            constraints: Constraints text
            context: Content context
            question_number: Question number

        Returns:
            Formatted prompt
        """
        prompt = f"""Generate a high-quality {question_type} question for {subsection_name}.

QUESTION SPECIFICATIONS:
- Marks: {marks}
- Difficulty: {difficulty}
- Question Type: {question_type}
- Question Number: {question_number}

CONTENT CONTEXT:
{context}

SPECIAL INSTRUCTIONS:
{instructions if instructions else "No special instructions"}

CONSTRAINTS:
{constraints if constraints else "No specific constraints"}

REQUIREMENTS:
1. Create a well-structured {question_type}
2. Make it appropriate for the difficulty level
3. Ensure it's answerable from the provided context
4. Follow all constraints and instructions strictly
5. Make it engaging and clear

Generate only the question text. Do not include the answer or question number."""

        return prompt

    def _get_section_context(self, chapters: List[str], limit: int = 5000) -> str:
        """
        Retrieve context for questions from available chapters.

        Args:
            chapters: List of chapter identifiers
            limit: Maximum context length

        Returns:
            Formatted context text
        """
        context_parts = []

        for chapter in chapters[:3]:  # Use first 3 chapters
            try:
                # Try to get context using embedding search
                embeddings_result = embeddings.get_embeddings(
                    f"chapter {chapter} content",
                    k=5
                )

                if embeddings_result:
                    context_parts.append(embeddings_result)

            except Exception as e:
                print(f"Error retrieving context for chapter {chapter}: {str(e)}")

        full_context = "\n".join(context_parts)

        # Truncate if too long
        if len(full_context) > limit:
            full_context = full_context[:limit] + "..."

        return full_context if full_context else "General knowledge context"

    def get_pattern_summary(self) -> Dict:
        """
        Get a summary of the pattern structure.

        Returns:
            Pattern summary
        """
        summary = {
            "exam_name": self.pattern.name,
            "class": self.pattern.class_name,
            "subject": self.pattern.subject,
            "total_marks": self.pattern.total_marks,
            "total_questions": self.pattern.total_questions,
            "sections": []
        }

        for section in self.pattern_data:
            section_summary = {
                "name": section.get("name", ""),
                "marks": section.get("marks", 0),
                "questions_count": section.get("questions_count", 0),
                "question_types": section.get("question_types", []),
                "has_instructions": bool(section.get("instructions", [])),
                "has_constraints": bool(section.get("constraints", {})),
                "subsections_count": len(section.get("subsections", []))
            }
            summary["sections"].append(section_summary)

        return summary


def generate_question_paper_from_pattern(
    pattern_id: int,
    chapters: List[str],
    difficulty: str = "Medium"
) -> Dict:
    """
    Main function to generate a complete question paper from a pattern.

    Args:
        pattern_id: ID of the ExamPattern to use
        chapters: List of chapters to draw from
        difficulty: Difficulty level

    Returns:
        Generated question paper
    """
    try:
        pattern = ExamPattern.objects.get(id=pattern_id)
        generator = PatternQuestionGenerator(pattern)
        return generator.generate_questions(chapters, difficulty)

    except ExamPattern.DoesNotExist:
        return {
            "status": "error",
            "message": f"Pattern with ID {pattern_id} not found"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error generating question paper: {str(e)}"
        }
