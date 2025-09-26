#!/usr/bin/env python3
"""
Simple test to check temp_clean.json structure
"""

import json

def test_json_structure():
    print("=" * 60)
    print("TESTING temp_clean.json STRUCTURE")
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
                                # Show first few questions
                                for k, subq in enumerate(questions[:3]):
                                    print(f"        SubQ {k+1}: {subq.get('text', 'No text')[:60]}...")
        
        # Check Section B structure
        if "B" in data:
            section_b = data["B"]
            print(f"\n📋 Section B keys: {list(section_b.keys())}")
            if "subsections" in section_b:
                subsections = section_b["subsections"]
                print(f"📋 Section B subsections: {list(subsections.keys())}")
                for sub_name, sub_questions in subsections.items():
                    print(f"  {sub_name}: {len(sub_questions)} questions")
        
        # Check Section C structure
        if "C" in data:
            section_c = data["C"]
            print(f"\n📋 Section C keys: {list(section_c.keys())}")
            if "subsections" in section_c:
                subsections = section_c["subsections"]
                print(f"📋 Section C subsections: {list(subsections.keys())}")
                for sub_name, sub_questions in subsections.items():
                    print(f"  {sub_name}: {len(sub_questions)} questions")
                    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_json_structure()
