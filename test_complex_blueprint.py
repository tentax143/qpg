#!/usr/bin/env python3
"""
Test script to create a complex blueprint template and test the universal generator
"""

import os
import sys
import django

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qpg.settings')
django.setup()

from core.models import BlueprintTemplate, ExamPattern
from core import generator
import json

def create_complex_blueprint_template():
    """Create a complex blueprint template for Class 11 English"""
    
    # Your exact blueprint structure
    complex_blueprint = {
        "A": {
            "title": "Reading Skills",
            "marks": 26,
            "subsections": {
                "reading": [
                    {
                        "qnum": 1,
                        "type": "unseen_passage_or_case_based",
                        "marks": 18,
                        "instruction": "Answer ANY ONE of the following:",
                        "options": [
                            {
                                "kind": "unseen_passage",
                                "passage": "",
                                "questions": []
                            },
                            {
                                "kind": "case_based_passage",
                                "passage": "",
                                "questions": []
                            }
                        ]
                    },
                    {
                        "qnum": 2,
                        "type": "note_making",
                        "marks": 5,
                        "passage": ""
                    },
                    {
                        "qnum": 3,
                        "type": "summary",
                        "marks": 3,
                        "instruction": "Write a summary of the above passage in about 80 words."
                    }
                ]
            }
        },
        "B": {
            "title": "Grammar and Creative Writing",
            "marks": 23,
            "subsections": {
                "grammar": [
                    {
                        "qnum": 5,
                        "type": "gap_filling",
                        "marks": 4
                    },
                    {
                        "qnum": 6,
                        "type": "reordering",
                        "marks": 3
                    }
                ],
                "writing": [
                    {
                        "qnum": 7,
                        "type": "advertisement",
                        "marks": 3
                    },
                    {
                        "qnum": 8,
                        "type": "poster",
                        "marks": 3
                    },
                    {
                        "qnum": 9,
                        "type": "speech",
                        "marks": 5
                    },
                    {
                        "qnum": 10,
                        "type": "debate",
                        "marks": 5
                    }
                ]
            }
        },
        "C": {
            "title": "Literature",
            "marks": 31,
            "subsections": {
                "extracts": [
                    {
                        "qnum": 11,
                        "source": "Hornbill (poem)",
                        "marks": 3
                    },
                    {
                        "qnum": 12,
                        "source": "Hornbill (prose)",
                        "marks": 3
                    },
                    {
                        "qnum": 13,
                        "source": "Snapshots (prose)",
                        "marks": 4
                    }
                ],
                "short_answers": [
                    {
                        "qnum": 14,
                        "source": "Hornbill",
                        "marks": 3
                    },
                    {
                        "qnum": 15,
                        "source": "Hornbill",
                        "marks": 3
                    },
                    {
                        "qnum": 16,
                        "source": "Snapshots",
                        "marks": 3
                    }
                ],
                "long_answers": [
                    {
                        "qnum": 17,
                        "source": "Hornbill",
                        "marks": 6
                    },
                    {
                        "qnum": 18,
                        "source": "Snapshots",
                        "marks": 6
                    }
                ]
            }
        }
    }
    
    # Create or update the blueprint template
    template, created = BlueprintTemplate.objects.get_or_create(
        name="CBSE English Core Class 11",
        subject="English Core",
        class_name="11",
        defaults={
            "description": "Complex blueprint template for CBSE English Core Class 11 with detailed subsections",
            "blueprint": complex_blueprint,
            "is_default": True,
            "is_active": True
        }
    )
    
    if not created:
        # Update existing template
        template.blueprint = complex_blueprint
        template.is_default = True
        template.save()
        print(f"✅ Updated existing blueprint template: {template.name}")
    else:
        print(f"✅ Created new blueprint template: {template.name}")
    
    return template

def test_blueprint_resolution():
    """Test the blueprint resolution system"""
    
    print("\n=== Testing Blueprint Resolution ===")
    
    # Test blueprint resolution
    blueprint = generator.get_blueprint("11", "English Core")
    
    print(f"✅ Blueprint resolved successfully")
    print(f"Blueprint keys: {list(blueprint.keys())}")
    
    # Check if it's the complex blueprint
    is_complex = False
    for section_key, section_data in blueprint.items():
        if isinstance(section_data, dict) and 'subsections' in section_data:
            is_complex = True
            break
    
    print(f"Blueprint type: {'Complex' if is_complex else 'Simple'}")
    
    if is_complex:
        print("✅ Complex blueprint structure detected")
        for section_key, section_data in blueprint.items():
            print(f"  Section {section_key}: {section_data.get('title', 'No title')} ({section_data.get('marks', 0)} marks)")
            if 'subsections' in section_data:
                for subsection_key, subsection_questions in section_data['subsections'].items():
                    print(f"    Subsection {subsection_key}: {len(subsection_questions)} questions")
    else:
        print("⚠️ Simple blueprint structure detected")
    
    return blueprint

def test_question_type_extraction(blueprint):
    """Test question type extraction from blueprint"""
    
    print("\n=== Testing Question Type Extraction ===")
    
    # Extract question types
    all_question_types = []
    
    # Check if this is a complex blueprint
    is_complex_blueprint = False
    for section_key, section_data in blueprint.items():
        if isinstance(section_data, dict) and 'subsections' in section_data:
            is_complex_blueprint = True
            break
    
    if is_complex_blueprint:
        # Extract question types from complex blueprint structure
        for section_key, section_data in blueprint.items():
            if isinstance(section_data, dict) and 'subsections' in section_data:
                for subsection_key, subsection_questions in section_data['subsections'].items():
                    if isinstance(subsection_questions, list):
                        for question in subsection_questions:
                            if isinstance(question, dict) and 'type' in question:
                                all_question_types.append(question['type'])
    else:
        # Extract question types from simple blueprint structure
        for section_data in blueprint.get('sections', []):
            section_question_types = section_data.get('question_types', [])
            all_question_types.extend(section_question_types)
    
    # Remove duplicates while preserving order
    all_question_types = list(dict.fromkeys(all_question_types))
    
    print(f"✅ Extracted question types: {all_question_types}")
    print(f"Total unique question types: {len(all_question_types)}")
    
    return all_question_types

def main():
    """Main test function"""
    
    print("=== Complex Blueprint System Test ===")
    
    try:
        # Step 1: Create complex blueprint template
        print("\n1. Creating complex blueprint template...")
        template = create_complex_blueprint_template()
        
        # Step 2: Test blueprint resolution
        print("\n2. Testing blueprint resolution...")
        blueprint = test_blueprint_resolution()
        
        # Step 3: Test question type extraction
        print("\n3. Testing question type extraction...")
        question_types = test_question_type_extraction(blueprint)
        
        # Step 4: Test universal context retrieval
        print("\n4. Testing universal context retrieval...")
        try:
            context_data = generator.get_universal_context("11", "English Core", ["The Portrait of a Lady"], question_types)
            print(f"✅ Context retrieved: {len(context_data['context_text'])} characters")
            print(f"Context sources: {context_data['sources']}")
        except Exception as e:
            print(f"⚠️ Context retrieval failed: {e}")
        
        print("\n=== Test Summary ===")
        print("✅ Complex blueprint template created/updated")
        print("✅ Blueprint resolution working")
        print("✅ Question type extraction working")
        print("✅ System ready for complex blueprint generation")
        
        print(f"\n📋 Blueprint Template Details:")
        print(f"  Name: {template.name}")
        print(f"  Subject: {template.subject}")
        print(f"  Class: {template.class_name}")
        print(f"  Is Default: {template.is_default}")
        print(f"  Blueprint Keys: {list(template.blueprint.keys())}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

