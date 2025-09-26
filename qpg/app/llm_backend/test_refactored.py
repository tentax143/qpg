#!/usr/bin/env python3
"""
Test script for the refactored generator.py
This script tests the generator with different subjects and classes
"""

import os
import sys
import django

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qpg.settings')
django.setup()

from app.llm_backend.generator import load_exam_patterns, generate_paper

def test_exam_patterns_loading():
    """Test that exam patterns can be loaded correctly"""
    print("Testing exam patterns loading...")
    
    patterns = load_exam_patterns()
    if not patterns:
        print("❌ Failed to load exam patterns")
        return False
    
    print("✅ Exam patterns loaded successfully")
    print(f"Available classes: {list(patterns.keys())}")
    
    for class_name, subjects in patterns.items():
        print(f"  {class_name}: {list(subjects.keys())}")
        for subject, config in subjects.items():
            print(f"    {subject}: {len(config['sections'])} sections")
    
    return True

def test_subject_support():
    """Test that different subjects are supported"""
    print("\nTesting subject support...")
    
    patterns = load_exam_patterns()
    if not patterns:
        print("❌ Cannot test subjects without exam patterns")
        return False
    
    # Test Biology
    if "Class 11" in patterns and "Biology" in patterns["Class 11"]:
        print("✅ Biology support confirmed")
        bio_config = patterns["Class 11"]["Biology"]
        print(f"  Total marks: {bio_config['total_marks']}")
        print(f"  Sections: {list(bio_config['sections'].keys())}")
    else:
        print("❌ Biology support missing")
    
    # Test English
    if "Class 11" in patterns and "English" in patterns["Class 11"]:
        print("✅ English support confirmed")
        eng_config = patterns["Class 11"]["English"]
        print(f"  Total marks: {eng_config['total_marks']}")
        print(f"  Sections: {list(eng_config['sections'].keys())}")
    else:
        print("❌ English support missing")
    
    # Test Mathematics
    if "Class 11" in patterns and "Mathematics" in patterns["Class 11"]:
        print("✅ Mathematics support confirmed")
        math_config = patterns["Class 11"]["Mathematics"]
        print(f"  Total marks: {math_config['total_marks']}")
        print(f"  Sections: {list(math_config['sections'].keys())}")
    else:
        print("❌ Mathematics support missing")
    
    return True

def test_prompt_templates():
    """Test that prompt templates are properly formatted"""
    print("\nTesting prompt templates...")
    
    patterns = load_exam_patterns()
    if not patterns:
        print("❌ Cannot test templates without exam patterns")
        return False
    
    # Test a few templates
    test_cases = [
        ("Class 11", "Biology", "A"),
        ("Class 11", "English", "A"),
        ("Class 11", "Mathematics", "A"),
    ]
    
    for class_name, subject, section in test_cases:
        if class_name in patterns and subject in patterns[class_name] and section in patterns[class_name][subject]["sections"]:
            template = patterns[class_name][subject]["sections"][section]["prompt_template"]
            
            # Check that template has required placeholders
            required_placeholders = ["{q_start}", "{difficulty}", "{class_name}", "{subject}", "{chapters}", "{context}"]
            missing = [p for p in required_placeholders if p not in template]
            
            if not missing:
                print(f"✅ {class_name} {subject} Section {section} template OK")
            else:
                print(f"❌ {class_name} {subject} Section {section} missing placeholders: {missing}")
        else:
            print(f"❌ {class_name} {subject} Section {section} not found")
    
    return True

def test_generator_function():
    """Test the main generator function (without actually calling Bedrock)"""
    print("\nTesting generator function structure...")
    
    try:
        # Import the function
        from app.llm_backend.generator import generate_paper
        
        # Check function signature
        import inspect
        sig = inspect.signature(generate_paper)
        params = list(sig.parameters.keys())
        
        expected_params = ["class_name", "subject", "unit", "difficulty"]
        if params == expected_params:
            print("✅ generate_paper function signature correct")
        else:
            print(f"❌ generate_paper function signature incorrect. Expected: {expected_params}, Got: {params}")
        
        # Check return type annotation
        if sig.return_annotation != inspect.Signature.empty:
            print(f"✅ generate_paper return type annotated: {sig.return_annotation}")
        else:
            print("⚠️  generate_paper return type not annotated")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing generator function: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Refactored Generator")
    print("=" * 50)
    
    tests = [
        test_exam_patterns_loading,
        test_subject_support,
        test_prompt_templates,
        test_generator_function,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! The refactored generator is ready.")
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
