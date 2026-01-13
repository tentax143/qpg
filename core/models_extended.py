"""
Extended models for detailed blueprint specifications
"""
from django.db import models
from django.contrib.auth.models import User
import json


class DetailedBlueprintTemplate(models.Model):
    """
    Enhanced blueprint template with detailed question specifications
    """
    name = models.CharField(max_length=255)
    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=100)

    # The detailed blueprint structure
    blueprint_structure = models.JSONField(default=dict)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    # Usage tracking
    usage_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['name', 'class_name', 'subject']

    def __str__(self):
        return f"{self.name} - Class {self.class_name} {self.subject}"

    def get_total_marks(self):
        """Calculate total marks from blueprint structure"""
        total = 0
        for section in self.blueprint_structure.get('sections', []):
            total += section.get('marks', 0)
        return total

    def get_total_questions(self):
        """Calculate total number of questions"""
        total = 0
        for section in self.blueprint_structure.get('sections', []):
            for question in section.get('question_distribution', []):
                total += question.get('count', 0)
        return total

    def validate_structure(self):
        """Validate the blueprint structure"""
        errors = []

        if 'sections' not in self.blueprint_structure:
            errors.append("Blueprint must have 'sections' key")
            return errors

        total_marks = 0
        for i, section in enumerate(self.blueprint_structure['sections']):
            section_marks = 0

            # Validate section structure
            if 'name' not in section:
                errors.append(f"Section {i+1} missing 'name'")
            if 'marks' not in section:
                errors.append(f"Section {i+1} missing 'marks'")

            # Validate question distribution
            if 'question_distribution' in section:
                for j, question in enumerate(section['question_distribution']):
                    if 'count' not in question:
                        errors.append(f"Section {section.get('name', i+1)}, Question {j+1} missing 'count'")
                    if 'marks_each' not in question:
                        errors.append(f"Section {section.get('name', i+1)}, Question {j+1} missing 'marks_each'")

                    # Calculate marks
                    count = question.get('count', 0)
                    marks_each = question.get('marks_each', 0)
                    section_marks += count * marks_each

                # Check if section marks match
                if section_marks != section.get('marks', 0):
                    errors.append(f"Section {section.get('name', i+1)}: calculated marks ({section_marks}) don't match specified marks ({section.get('marks', 0)})")

            total_marks += section.get('marks', 0)

        return errors


class QuestionSource(models.Model):
    """
    Define available question sources
    """
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # Source-specific configuration
    requires_chapter = models.BooleanField(default=False)
    requires_topic = models.BooleanField(default=False)

    def __str__(self):
        return self.display_name


class QuestionTypeConfig(models.Model):
    """
    Configuration for different question types
    """
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Constraints
    min_marks = models.FloatField(default=1)
    max_marks = models.FloatField(default=10)
    typical_marks = models.FloatField(default=2)

    # Requirements
    requires_passage = models.BooleanField(default=False)
    requires_image = models.BooleanField(default=False)
    requires_extract = models.BooleanField(default=False)

    # Word limits for answers
    answer_word_min = models.IntegerField(null=True, blank=True)
    answer_word_max = models.IntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.display_name


# Default question sources
DEFAULT_SOURCES = [
    {"name": "ncert", "display_name": "NCERT Textbook", "requires_chapter": True},
    {"name": "inside_text", "display_name": "Inside Text Questions", "requires_chapter": True},
    {"name": "book_back", "display_name": "Book Back Exercises", "requires_chapter": True},
    {"name": "previous_years", "display_name": "Previous Year Papers", "requires_chapter": False},
    {"name": "general", "display_name": "General Knowledge", "requires_chapter": False},
    {"name": "application_based", "display_name": "Application Based", "requires_topic": True},
]

# Default question types
DEFAULT_QUESTION_TYPES = [
    {"name": "mcq", "display_name": "Multiple Choice Question", "typical_marks": 1},
    {"name": "assertion_reason", "display_name": "Assertion-Reason", "typical_marks": 1},
    {"name": "fill_blanks", "display_name": "Fill in the Blanks", "typical_marks": 1},
    {"name": "true_false", "display_name": "True or False", "typical_marks": 1},
    {"name": "very_short_answer", "display_name": "Very Short Answer", "typical_marks": 1, "answer_word_max": 20},
    {"name": "short_answer", "display_name": "Short Answer", "typical_marks": 2, "answer_word_min": 30, "answer_word_max": 50},
    {"name": "long_answer", "display_name": "Long Answer", "typical_marks": 5, "answer_word_min": 100, "answer_word_max": 150},
    {"name": "essay", "display_name": "Essay Type", "typical_marks": 10, "answer_word_min": 200, "answer_word_max": 300},
    {"name": "comprehension", "display_name": "Comprehension Based", "typical_marks": 5, "requires_passage": True},
    {"name": "extract_based", "display_name": "Extract Based", "typical_marks": 3, "requires_extract": True},
    {"name": "diagram_based", "display_name": "Diagram Based", "typical_marks": 3, "requires_image": True},
    {"name": "case_study", "display_name": "Case Study", "typical_marks": 4, "requires_passage": True},
]


def initialize_defaults():
    """Initialize default question sources and types"""
    # Create default sources
    for source_data in DEFAULT_SOURCES:
        QuestionSource.objects.get_or_create(
            name=source_data["name"],
            defaults={
                "display_name": source_data["display_name"],
                "requires_chapter": source_data.get("requires_chapter", False),
                "requires_topic": source_data.get("requires_topic", False),
            }
        )

    # Create default question types
    for qtype_data in DEFAULT_QUESTION_TYPES:
        QuestionTypeConfig.objects.get_or_create(
            name=qtype_data["name"],
            defaults={
                "display_name": qtype_data["display_name"],
                "typical_marks": qtype_data.get("typical_marks", 1),
                "requires_passage": qtype_data.get("requires_passage", False),
                "requires_image": qtype_data.get("requires_image", False),
                "requires_extract": qtype_data.get("requires_extract", False),
                "answer_word_min": qtype_data.get("answer_word_min"),
                "answer_word_max": qtype_data.get("answer_word_max"),
            }
        )