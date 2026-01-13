#!/usr/bin/env python
"""
Test script for the complete Universal Question Paper Generator system.
This script tests the integration between blueprints and generation.
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

from core.models import ExamPattern, BlueprintTemplate, ExamBlueprint, Material
from core import generator

def test_complete_integration():
    """Test the complete integration of the universal generator"""
    print("🧪 Testing Complete Universal Generator Integration")
    print("=" * 60)
    
    # Test 1: Check if we have any blueprints
    print("\n📋 Test 1: Checking Blueprint Availability")
    templates = BlueprintTemplate.objects.filter(is_active=True)
    exam_blueprints = ExamBlueprint.objects.filter(is_active=True)
    
    print(f"   Active Templates: {templates.count()}")
    print(f"   Active Exam Blueprints: {exam_blueprints.count()}")
    
    if templates.count() == 0 and exam_blueprints.count() == 0:
        print("   ⚠️ No blueprints found. Creating test templates...")
        create_test_templates()
        templates = BlueprintTemplate.objects.filter(is_active=True)
        exam_blueprints = ExamBlueprint.objects.filter(is_active=True)
        print(f"   ✅ Created {templates.count()} templates and {exam_blueprints.count()} exam blueprints")
    
    # Test 2: Test blueprint resolution
    print("\n🔍 Test 2: Testing Blueprint Resolution")
    test_cases = [
        ("11", "English", None),
        ("11", "Biology", None),
    ]
    
    for class_name, subject, section in test_cases:
        try:
            print(f"   Testing: {class_name} {subject}")
            blueprint = generator.get_blueprint(class_name, subject, section)
            print(f"   ✅ Blueprint resolved: {len(blueprint.get('sections', []))} sections")
            
            # Check if blueprint has question types
            all_question_types = []
            for section_data in blueprint.get('sections', []):
                section_question_types = section_data.get('question_types', [])
                all_question_types.extend(section_question_types)
            
            print(f"   📝 Question types: {list(set(all_question_types))}")
            
        except Exception as e:
            print(f"   ❌ Failed: {e}")
    
    # Test 3: Test context retrieval
    print("\n📚 Test 3: Testing Context Retrieval")
    try:
        context_data = generator.get_universal_context(
            class_name="11",
            subject="English",
            chapters=["The Portrait of a Lady"],
            question_types=["unseen_passage", "grammar"]
        )
        
        print(f"   ✅ Context retrieved: {context_data['metadata']['total_contexts']} contexts")
        print(f"   📊 Context length: {context_data['metadata']['context_length']} characters")
        print(f"   🔍 Queries used: {len(context_data['metadata']['queries_used'])}")
        
    except Exception as e:
        print(f"   ❌ Context retrieval failed: {e}")
    
    # Test 4: Test question type instructions
    print("\n📝 Test 4: Testing Question Type Instructions")
    try:
        instructions = generator.get_question_type_instructions(
            ["unseen_passage", "grammar", "mcq", "short_answer"], 
            "English"
        )
        
        print(f"   ✅ Instructions generated: {len(instructions)} characters")
        print(f"   📖 Preview: {instructions[:100]}...")
        
    except Exception as e:
        print(f"   ❌ Instructions generation failed: {e}")
    
    # Test 5: Test pattern availability
    print("\n📋 Test 5: Checking Exam Patterns")
    patterns = ExamPattern.objects.all()
    print(f"   Available patterns: {patterns.count()}")
    
    if patterns.count() == 0:
        print("   ⚠️ No patterns found. Creating test pattern...")
        create_test_pattern()
        patterns = ExamPattern.objects.all()
        print(f"   ✅ Created {patterns.count()} patterns")
    
    # Test 6: Test material availability
    print("\n📚 Test 6: Checking Materials")
    materials = Material.objects.all()
    print(f"   Available materials: {materials.count()}")
    
    if materials.count() == 0:
        print("   ⚠️ No materials found. Please upload some materials first.")
    else:
        subjects = materials.values_list("subject", flat=True).distinct()
        print(f"   Available subjects: {list(subjects)}")
    
    print("\n🎉 Integration Test Complete!")
    print("\nNext steps:")
    print("1. Create blueprint templates for your subjects")
    print("2. Upload materials for the subjects")
    print("3. Test paper generation through the web interface")

def create_test_templates():
    """Create test blueprint templates"""
    
    # English template
    BlueprintTemplate.objects.get_or_create(
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
    
    # Biology template
    BlueprintTemplate.objects.get_or_create(
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

def create_test_pattern():
    """Create a test exam pattern"""
    ExamPattern.objects.get_or_create(
        name="Test Pattern",
        defaults={
            "description": "Test exam pattern",
            "sections": {
                "Sections": [
                    {"name": "A", "questions": 10, "marks": 1},
                    {"name": "B", "questions": 5, "marks": 2},
                    {"name": "C", "questions": 3, "marks": 5}
                ]
            }
        }
    )

if __name__ == "__main__":
    test_complete_integration()
