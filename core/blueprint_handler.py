"""
Blueprint Handler - A centralized class for managing blueprint structures
This ensures consistent blueprint handling throughout the application
"""
import json
from typing import Dict, List, Any, Optional

class Blueprint:
    """
    A class to handle blueprint data consistently across the application
    """

    def __init__(self, blueprint_data: Any):
        """
        Initialize blueprint from any format (dict with sections, dict without, or list)
        """
        self._sections = {}
        self._parse_blueprint(blueprint_data)

    def _parse_blueprint(self, blueprint_data: Any):
        """Parse blueprint data from any format into standard dict"""
        if isinstance(blueprint_data, dict):
            if "sections" in blueprint_data:
                if isinstance(blueprint_data["sections"], list):
                    # Array format: {"sections": [{"name": "A", ...}]}
                    for section in blueprint_data["sections"]:
                        if isinstance(section, dict) and "name" in section:
                            self._add_section(section)
                elif isinstance(blueprint_data["sections"], dict):
                    # Dict format: {"sections": {"A": {...}}}
                    self._sections = blueprint_data["sections"]
            else:
                # Direct dict format: {"A": {...}, "B": {...}}
                self._sections = blueprint_data
        elif isinstance(blueprint_data, list):
            # Direct list format: [{"name": "A", ...}]
            for section in blueprint_data:
                if isinstance(section, dict) and "name" in section:
                    self._add_section(section)

    def _add_section(self, section: Dict[str, Any]):
        """Add a section to the blueprint"""
        section_name = section.get("name", "")
        self._sections[section_name] = {
            "title": section.get("title", ""),
            "marks": section.get("marks", 0),
            "question_types": section.get("question_types", []),
            "subsections": section.get("subsections", {})
        }

    @property
    def sections(self) -> Dict[str, Dict[str, Any]]:
        """Get sections as dictionary"""
        return self._sections

    @property
    def section_names(self) -> List[str]:
        """Get list of section names"""
        return list(self._sections.keys())

    @property
    def section_count(self) -> int:
        """Get number of sections"""
        return len(self._sections)

    def get_section(self, section_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific section by name"""
        return self._sections.get(section_name)

    def iterate_sections(self):
        """Iterate over sections"""
        for section_name, section_data in self._sections.items():
            yield section_name, section_data

    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Export blueprint as standard dictionary"""
        return self._sections

    def to_json(self) -> str:
        """Export blueprint as JSON string"""
        return json.dumps(self._sections, indent=2)

    def to_database_format(self) -> Dict[str, Any]:
        """Export blueprint in database format (with sections key)"""
        sections_list = []
        for name, data in self._sections.items():
            section = {"name": name}
            section.update(data)
            sections_list.append(section)
        return {"sections": sections_list}

    def is_complex(self) -> bool:
        """Check if blueprint has subsections (complex structure)"""
        for section_data in self._sections.values():
            if isinstance(section_data, dict) and "subsections" in section_data:
                if section_data["subsections"]:
                    return True
        return False

    def get_all_question_types(self) -> List[str]:
        """Extract all unique question types from blueprint"""
        question_types = []
        for section_data in self._sections.values():
            if isinstance(section_data, dict):
                section_types = section_data.get("question_types", [])
                question_types.extend(section_types)
        return list(dict.fromkeys(question_types))  # Remove duplicates

    def __str__(self) -> str:
        """String representation"""
        return f"Blueprint({self.section_count} sections: {', '.join(self.section_names)})"

    def __repr__(self) -> str:
        """Detailed representation"""
        return f"Blueprint(sections={self._sections})"


# Usage example and tests
if __name__ == "__main__":
    # Test with different formats
    test_cases = [
        # Database format
        {
            "sections": [
                {"name": "A", "title": "Multiple Choice", "marks": 10, "question_types": ["MCQ"]},
                {"name": "B", "title": "Short Answer", "marks": 20, "question_types": ["Short answer"]}
            ]
        },
        # Direct dictionary format
        {
            "A": {"title": "Multiple Choice", "marks": 10, "question_types": ["MCQ"]},
            "B": {"title": "Short Answer", "marks": 20, "question_types": ["Short answer"]}
        },
        # List format
        [
            {"name": "A", "title": "Multiple Choice", "marks": 10, "question_types": ["MCQ"]},
            {"name": "B", "title": "Short Answer", "marks": 20, "question_types": ["Short answer"]}
        ]
    ]

    for i, test_data in enumerate(test_cases, 1):
        print(f"\n=== Test Case {i} ===")
        blueprint = Blueprint(test_data)
        print(f"Blueprint: {blueprint}")
        print(f"Sections: {blueprint.section_names}")
        print(f"Question types: {blueprint.get_all_question_types()}")
        print(f"Is complex: {blueprint.is_complex()}")

        # Iterate through sections
        for section_name, section_data in blueprint.iterate_sections():
            print(f"  Section {section_name}: {section_data.get('title')} ({section_data.get('marks')} marks)")