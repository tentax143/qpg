"""
Blueprint Manager - Centralized blueprint handling system
This replaces the scattered blueprint conversion logic with a unified approach
"""
import json
from typing import Dict, List, Any, Optional, Union
from .models import ExamBlueprint, BlueprintTemplate


class BlueprintManager:
    """
    Centralized manager for all blueprint operations.
    Ensures consistent data structure throughout the application.
    """

    # Standard internal format: {"A": {...}, "B": {...}}
    # This is what all code expects to work with

    @staticmethod
    def normalize_blueprint(blueprint_data: Any) -> Dict[str, Dict[str, Any]]:
        """
        Convert any blueprint format to the standard dictionary format.
        This is the ONLY place where conversion happens.

        Standard format: {"A": {"title": "...", "marks": X, "question_types": [...]}}
        """
        if not blueprint_data:
            return {}

        # If it's already in the correct format
        if isinstance(blueprint_data, dict):
            # Check if it has section keys like A, B, C
            if any(key in ['A', 'B', 'C', 'D', 'E'] for key in blueprint_data.keys()):
                # Already in correct format
                return blueprint_data

            # Handle {"sections": [...]} format
            if "sections" in blueprint_data:
                if isinstance(blueprint_data["sections"], list):
                    # Array format: {"sections": [{"name": "A", ...}]}
                    result = {}
                    for section in blueprint_data["sections"]:
                        if isinstance(section, dict) and "name" in section:
                            section_name = section["name"]
                            result[section_name] = {
                                "title": section.get("title", ""),
                                "marks": section.get("marks", 0),
                                "question_types": section.get("question_types", []),
                                "subsections": section.get("subsections", {}),
                                "questions_count": section.get("questions_count", 0),
                                "marks_per_question": section.get("marks_per_question", 1),
                                "id": section.get("id", section_name),
                                "instructions": section.get("instructions", []),
                                "constraints": section.get("constraints", {}),
                                "passage_instruction": section.get("passage_instruction"),
                                "extract_instruction": section.get("extract_instruction"),
                            }
                    return result

                elif isinstance(blueprint_data["sections"], dict):
                    # Dict format: {"sections": {"A": {...}}}
                    return blueprint_data["sections"]

        elif isinstance(blueprint_data, list):
            # Direct list format: [{"name": "A", ...}]
            result = {}
            for section in blueprint_data:
                if isinstance(section, dict) and "name" in section:
                    section_name = section["name"]
                    result[section_name] = {
                        "title": section.get("title", ""),
                        "marks": section.get("marks", 0),
                        "question_types": section.get("question_types", []),
                        "subsections": section.get("subsections", {}),
                        "questions_count": section.get("questions_count", 0),
                        "marks_per_question": section.get("marks_per_question", 1),
                        "id": section.get("id", section_name),
                        "instructions": section.get("instructions", []),
                        "constraints": section.get("constraints", {}),
                        "passage_instruction": section.get("passage_instruction"),
                        "extract_instruction": section.get("extract_instruction"),
                    }
            return result

        # Unknown format
        print(f"[BlueprintManager] WARNING: Unknown blueprint format: {type(blueprint_data)}")
        return {}

    @staticmethod
    def to_database_format(blueprint_dict: Dict[str, Dict[str, Any]]) -> Dict[str, List]:
        """
        Convert standard format to database storage format.
        Database format: {"sections": [{"name": "A", ...}]}
        """
        sections_list = []
        for name, data in blueprint_dict.items():
            section = {"name": name}
            section.update(data)
            sections_list.append(section)
        return {"sections": sections_list}

    @staticmethod
    def get_blueprint(class_name: str, subject: str, section: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Get blueprint from database and return in standard format.
        This replaces the get_blueprint function in generator.py
        """
        print(f"[BlueprintManager] Resolving blueprint for {class_name} {subject} (section: {section})")

        # Normalize subject name
        normalized_subject = subject.strip().lower()
        subject_map = {
            "english": "English Core",
            "english core": "English Core",
            "biology": "Biology",
            "physics": "Physics",
            "chemistry": "Chemistry",
            "mathematics": "Mathematics",
            "math": "Mathematics"
        }
        subject_lookup = subject_map.get(normalized_subject, subject)

        # Priority 1: Look for specific exam blueprint
        qs = ExamBlueprint.objects.filter(
            class_name=class_name,
            subject__iexact=subject_lookup,
            is_active=True
        )
        if section:
            qs = qs.filter(section=section)

        exam_blueprint = qs.first()
        if exam_blueprint:
            print(f"[BlueprintManager] Found exam blueprint: {exam_blueprint}")
            return BlueprintManager.normalize_blueprint(exam_blueprint.blueprint)

        # Priority 2: Look for default template
        template = BlueprintTemplate.objects.filter(
            class_name=class_name,
            subject__iexact=subject_lookup,
            is_default=True,
            is_active=True
        ).first()

        if template:
            print(f"[BlueprintManager] Found default template: {template.name}")
            return BlueprintManager.normalize_blueprint(template.blueprint)

        # Priority 3: Look for any template
        template = BlueprintTemplate.objects.filter(
            class_name=class_name,
            subject__iexact=subject_lookup,
            is_active=True
        ).first()

        if template:
            print(f"[BlueprintManager] Found template: {template.name}")
            return BlueprintManager.normalize_blueprint(template.blueprint)

        # No blueprint found
        raise ValueError(f"No blueprint found for {class_name} {subject} (section: {section})")

    @staticmethod
    def validate_blueprint(blueprint_dict: Dict[str, Dict[str, Any]]) -> bool:
        """
        Validate that a blueprint has the correct structure.
        """
        if not isinstance(blueprint_dict, dict):
            return False

        for section_name, section_data in blueprint_dict.items():
            if not isinstance(section_data, dict):
                return False
            if "title" not in section_data or "marks" not in section_data:
                return False

        return True

    @staticmethod
    def get_question_types(blueprint_dict: Dict[str, Dict[str, Any]]) -> List[str]:
        """
        Extract all unique question types from a blueprint.
        """
        question_types = []
        for section_data in blueprint_dict.values():
            if isinstance(section_data, dict):
                section_types = section_data.get("question_types", [])
                question_types.extend(section_types)
        return list(dict.fromkeys(question_types))  # Remove duplicates

    @staticmethod
    def get_total_marks(blueprint_dict: Dict[str, Dict[str, Any]]) -> int:
        """
        Calculate total marks for the blueprint.
        """
        total = 0
        for section_data in blueprint_dict.values():
            if isinstance(section_data, dict):
                total += section_data.get("marks", 0)
        return total

    @staticmethod
    def update_all_blueprints_in_db():
        """
        One-time migration to standardize all blueprints in the database.
        """
        print("[BlueprintManager] Starting database blueprint standardization...")

        # Update BlueprintTemplates
        templates = BlueprintTemplate.objects.all()
        updated_templates = 0

        for template in templates:
            original = template.blueprint
            normalized = BlueprintManager.normalize_blueprint(original)
            new_format = BlueprintManager.to_database_format(normalized)

            if original != new_format:
                template.blueprint = new_format
                template.save()
                updated_templates += 1
                print(f"[BlueprintManager] Updated template: {template.name}")

        # Update ExamBlueprints
        blueprints = ExamBlueprint.objects.all()
        updated_blueprints = 0

        for blueprint in blueprints:
            original = blueprint.blueprint
            normalized = BlueprintManager.normalize_blueprint(original)
            new_format = BlueprintManager.to_database_format(normalized)

            if original != new_format:
                blueprint.blueprint = new_format
                blueprint.save()
                updated_blueprints += 1
                print(f"[BlueprintManager] Updated blueprint: {blueprint}")

        print(f"[BlueprintManager] Standardization complete!")
        print(f"[BlueprintManager] Updated {updated_templates} templates and {updated_blueprints} blueprints")
        return updated_templates, updated_blueprints