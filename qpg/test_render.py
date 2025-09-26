#!/usr/bin/env python3
"""
Test script to directly process temp_clean.json and see what questions are generated
"""

import json
import sys
import os

# Add the current directory to Python path
sys.path.append('.')

# Import the render function
from core.generator import render_section_questions

def test_render():
    print("=" * 60)
    print("TESTING DIRECT JSON RENDERING")
    print("=" * 60)
    
    # Load the JSON file
    try:
        with open("temp_clean.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"✅ Successfully loaded temp_clean.json")
        print(f"📊 Data keys: {list(data.keys())}")
        
        # Check Section A structure
        if "A" in data:
            section_a = data["A"]
            print(f"📋 Section A keys: {list(section_a.keys())}")
            if "subsections" in section_a:
                subsections = section_a["subsections"]
                print(f"📋 Section A subsections: {list(subsections.keys())}")
                if "reading" in subsections:
                    reading_questions = subsections["reading"]
                    print(f"📋 Reading questions count: {len(reading_questions)}")
                    for i, q in enumerate(reading_questions):
                        print(f"  Question {i+1}: type={q.get('type')}, qnum={q.get('qnum')}")
                        if q.get('type') == 'unseen_passage_or_case_based':
                            options = q.get('options', [])
                            print(f"    Options count: {len(options)}")
                            for j, opt in enumerate(options):
                                questions = opt.get('questions', [])
                                print(f"      Option {j+1} ({opt.get('kind')}): {len(questions)} questions")
        
        # Create a simple blueprint
        blueprint = {
            "A": {"title": "Reading Skills", "marks": 26},
            "B": {"title": "Grammar and Creative Writing", "marks": 23},
            "C": {"title": "Literature", "marks": 31}
        }
        
        print("\n" + "=" * 60)
        print("CALLING render_section_questions")
        print("=" * 60)
        
        # Call the render function
        all_questions = render_section_questions([], data, blueprint)
        
        print(f"\n📊 Total questions generated: {len(all_questions)}")
        print("\n📋 First 20 questions:")
        for i, (typ, text) in enumerate(all_questions[:20]):
            print(f"  {i+1:2d}. [{typ:8s}] {text[:80]}{'...' if len(text) > 80 else ''}")
        
        if len(all_questions) > 20:
            print(f"  ... and {len(all_questions) - 20} more questions")
            
        # Count by type
        type_counts = {}
        for typ, text in all_questions:
            type_counts[typ] = type_counts.get(typ, 0) + 1
        
        print(f"\n📊 Question types:")
        for typ, count in type_counts.items():
            print(f"  {typ}: {count}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_render()
