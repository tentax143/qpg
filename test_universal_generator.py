#!/usr/bin/env python
"""
Test script for the Universal Question Paper Generator
This script tests the new universal generator system.
"""

import os
import sys
import django
from django.conf import settings

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qpg.settings')
django.setup()

from core.models import ExamPattern, BlueprintTemplate, ExamBlueprint
from core import generator

def test_blueprint_resolution():
    """Test the enhanced blueprint resolution system"""
    print("🧪 Testing Blueprint Resolution System")
    print("=" * 50)
    
    # Test cases
    test_cases = [
        ("11", "English", None),
        ("11", "Biology", None),
        ("12", "Physics", None),
        ("11", "Mathematics", None),
    ]
    
    for class_name, subject, section in test_cases:
        try:
            print(f"\n📋 Testing: {class_name} {subject} (section: {section})")
            blueprint = generator.get_blueprint(class_name, subject, section)
            print(f"✅ Blueprint resolved successfully")
            print(f"   Sections: {len(blueprint.get('sections', []))}")
            
            # Print section details
            for section_data in blueprint.get('sections', []):
                section_name = section_data.get('name', 'Unknown')
                section_title = section_data.get('title', 'No title')
                section_marks = section_data.get('marks', 0)
                question_types = section_data.get('question_types', [])
                print(f"   - Section {section_name}: {section_title} ({section_marks} marks) - {question_types}")
                
        except Exception as e:
            print(f"❌ Failed: {e}")

def test_universal_context():
    """Test the universal context retrieval system"""
    print("\n🧪 Testing Universal Context Retrieval")
    print("=" * 50)
    
    test_cases = [
        ("11", "English", ["The Portrait of a Lady", "We're Not Afraid to Die"], ["unseen_passage", "grammar"]),
        ("11", "Biology", ["The Living World", "Biological Classification"], ["mcq", "short_answer"]),
    ]
    
    for class_name, subject, chapters, question_types in test_cases:
        try:
            print(f"\n📚 Testing context for: {class_name} {subject}")
            print(f"   Chapters: {chapters}")
            print(f"   Question types: {question_types}")
            
            context_data = generator.get_universal_context(class_name, subject, chapters, question_types)
            
            print(f"✅ Context retrieved successfully")
            print(f"   Total contexts: {context_data['metadata']['total_contexts']}")
            print(f"   Context length: {context_data['metadata']['context_length']} characters")
            print(f"   Queries used: {len(context_data['metadata']['queries_used'])}")
            
        except Exception as e:
            print(f"❌ Failed: {e}")

def test_question_type_instructions():
    """Test the question type instructions system"""
    print("\n🧪 Testing Question Type Instructions")
    print("=" * 50)
    
    test_cases = [
        (["unseen_passage", "grammar"], "English"),
        (["mcq", "short_answer", "long_answer"], "Biology"),
        (["numerical", "proof"], "Mathematics"),
    ]
    
    for question_types, subject in test_cases:
        try:
            print(f"\n📝 Testing instructions for: {subject}")
            print(f"   Question types: {question_types}")
            
            instructions = generator.get_question_type_instructions(question_types, subject)
            
            print(f"✅ Instructions generated successfully")
            print(f"   Length: {len(instructions)} characters")
            print(f"   Preview: {instructions[:100]}...")
            
        except Exception as e:
            print(f"❌ Failed: {e}")

def create_test_blueprint_templates():
    """Create some test blueprint templates for testing"""
    print("\n🏗️ Creating Test Blueprint Templates")
    print("=" * 50)
    
    # Test template for English
    english_template, created = BlueprintTemplate.objects.get_or_create(
        name="Test English Template",
        subject="English",
        class_name="11",
        defaults={
            "description": "Test template for English",
            "blueprint": {
                "sections": [
                    {"name": "A", "title": "Reading", "marks": 20, "question_types": ["unseen_passage", "case_based"]},
                    {"name": "B", "title": "Writing", "marks": 30, "question_types": ["grammar", "writing_tasks"]},
                    {"name": "C", "title": "Literature", "marks": 30, "question_types": ["extract_based", "short_answer"]},
                    {"name": "D", "title": "Flamingo", "marks": 20, "question_types": ["long_answer"]}
                ]
            },
            "is_default": True,
            "is_active": True
        }
    )
    
    if created:
        print("✅ Created English test template")
    else:
        print("ℹ️ English test template already exists")
    
    # Test template for Biology
    biology_template, created = BlueprintTemplate.objects.get_or_create(
        name="Test Biology Template",
        subject="Biology",
        class_name="11",
        defaults={
            "description": "Test template for Biology",
            "blueprint": {
                "sections": [
                    {"name": "A", "title": "Multiple Choice", "marks": 20, "question_types": ["mcq"]},
                    {"name": "B", "title": "Assertion-Reason", "marks": 10, "question_types": ["assertion_reason"]},
                    {"name": "C", "title": "Very Short Answer", "marks": 20, "question_types": ["very_short_answer"]},
                    {"name": "D", "title": "Short Answer", "marks": 30, "question_types": ["short_answer"]},
                    {"name": "E", "title": "Long Answer", "marks": 20, "question_types": ["long_answer"]}
                ]
            },
            "is_default": True,
            "is_active": True
        }
    )
    
    if created:
        print("✅ Created Biology test template")
    else:
        print("ℹ️ Biology test template already exists")

def main():
    """Run all tests"""
    print("🚀 Universal Question Paper Generator Test Suite")
    print("=" * 60)
    
    try:
        # Create test templates
        create_test_blueprint_templates()
        
        # Test blueprint resolution
        test_blueprint_resolution()
        
        # Test context retrieval
        test_universal_context()
        
        # Test question type instructions
        test_question_type_instructions()
        
        print("\n🎉 All tests completed!")
        print("\nNext steps:")
        print("1. Create blueprint templates for your subjects")
        print("2. Test the universal generator with real data")
        print("3. Create exam blueprints from templates")
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
