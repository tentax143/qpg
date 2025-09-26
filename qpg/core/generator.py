import os, re, json, random, time, traceback
import boto3
from botocore.config import Config
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from django.conf import settings
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from . import embeddings
from .models import ExamBlueprint, BlueprintTemplate


# ------------------------------
# Bedrock setup
# ------------------------------
client = boto3.client(
    "bedrock-runtime", 
    region_name="us-east-1",
    config=Config(
        read_timeout=300,  # 5 minutes
        connect_timeout=60,  # 1 minute
        retries={'max_attempts': 3}
    )
)
# GEN_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
# VAL_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
GEN_MODEL_ID = "arn:aws:bedrock:us-east-1:659260838757:inference-profile/us.anthropic.claude-opus-4-1-20250805-v1:0"
VAL_MODEL_ID = "arn:aws:bedrock:us-east-1:659260838757:inference-profile/us.anthropic.claude-opus-4-20250514-v1:0"

# ------------------------------
# Bedrock helper
# ------------------------------
def call_bedrock(prompt, model_ref, max_tokens=3000, temperature=0.7, retries=5):
    # Log the prompt being sent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = model_ref.split("/")[-1] if "/" in model_ref else model_ref
    # Clean model name for filename (remove colons and other invalid chars)
    model_name = re.sub(r'[<>:"/\\|?*]', '_', model_name)
    
    # Save prompt to file
    prompt_file = f"temp_prompt_{model_name}_{timestamp}.txt"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(f"=== PROMPT SENT TO MODEL ===\n")
        f.write(f"Model: {model_ref}\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write(f"Max Tokens: {max_tokens}\n")
        f.write(f"Temperature: {temperature}\n")
        f.write(f"{'='*50}\n\n")
        f.write(prompt)
    
    print(f"[Bedrock-Log] Prompt saved to: {prompt_file}")
    print(f"[Bedrock-{model_name}] Sending prompt ({len(prompt)} chars) to model...")
    print(f"[Bedrock-Log] Model name cleaned: {model_name}")
    
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(retries):
        try:
            kwargs = {
                "body": json.dumps(body),
                "contentType": "application/json",
                "accept": "application/json",
                "modelId": model_ref,
            }
            resp = client.invoke_model(**kwargs)
            result = json.loads(resp["body"].read())
            text = result["content"][0]["text"]
            
            # Save response to file
            response_file = f"temp_response_{model_name}_{timestamp}.txt"
            with open(response_file, "w", encoding="utf-8") as f:
                f.write(f"=== MODEL RESPONSE ===\n")
                f.write(f"Model: {model_ref}\n")
                f.write(f"Timestamp: {datetime.now()}\n")
                f.write(f"Response Length: {len(text)} chars\n")
                f.write(f"{'='*50}\n\n")
                f.write(text)
            
            print(f"[Bedrock-Log] Response saved to: {response_file}")
            print(f"[Bedrock-{model_name}] returned {len(text)} chars")
            print(f"[Bedrock-Log] Response file size: {len(text)} bytes")
            
            # Check if response appears complete
            text_stripped = text.strip()
            is_complete = False
            
            # Check for various completion indicators
            if text_stripped.endswith('}') or text_stripped.endswith('```'):
                is_complete = True
                print(f"[Bedrock-{model_name}] ✅ Response appears complete (ends with closing bracket)")
            elif text_stripped.endswith('"') and text_stripped.count('{') == text_stripped.count('}'):
                is_complete = True
                print(f"[Bedrock-{model_name}] ✅ Response appears complete (balanced brackets)")
            elif len(text) >= max_tokens * 0.9:  # If we're close to max_tokens limit
                print(f"[Bedrock-{model_name}] ⚠️  Response may be truncated (near max_tokens limit)")
                print(f"[Bedrock-{model_name}] Response length: {len(text)} chars, Max tokens: {max_tokens}")
            else:
                print(f"[Bedrock-{model_name}] ❌ WARNING: Response may be incomplete")
                print(f"[Bedrock-{model_name}] Last 100 chars: {text[-100:]}")
            
            # If response seems incomplete and we haven't hit max retries, try again with higher limit
            if not is_complete and attempt < retries - 1:
                print(f"[Bedrock-{model_name}] Attempting retry with higher token limit...")
                body["max_tokens"] = min(max_tokens * 2, 8000)  # Double the limit, max 8000
                continue
            
            return text

        except client.exceptions.ServiceUnavailableException:
            wait = (2 ** attempt) + random.random()
            print(f"[Bedrock-Throttle] attempt {attempt+1}/{retries}, retrying in {wait:.1f}s")
            time.sleep(wait)

        except Exception as e:
            error_type = type(e).__name__
            print(f"[Bedrock-Error] {error_type}: {e}")
            
            # Handle timeout errors specifically
            if "timeout" in str(e).lower() or "ReadTimeoutError" in error_type:
                wait = (2 ** attempt) + random.random()
                print(f"[Bedrock-Timeout] attempt {attempt+1}/{retries}, retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            
            # Save error details for debugging
            with open("temp_error_prompt.txt", "w", encoding="utf-8") as f:
                f.write(f"Error Type: {error_type}\n")
                f.write(f"Error Message: {e}\n")
                f.write(f"Prompt:\n{prompt}")
            raise


    return ""


# ------------------------------
# Fetch blueprint from DB
# ------------------------------
def get_blueprint(class_name, subject, section=None):
    """
    Enhanced blueprint resolution with priority system:
    1. User-created exam blueprints (highest priority)
    2. Default template blueprints (fallback)
    3. Legacy hardcoded blueprints (last resort)
    """
    print(f"[Blueprint] Resolving blueprint for {class_name} {subject} (section: {section})")
    
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
        print(f"[Blueprint] ✅ Found exam blueprint: {exam_blueprint}")
        return exam_blueprint.blueprint
    
    # Priority 2: Look for default template
    template = BlueprintTemplate.objects.filter(
        class_name=class_name,
        subject__iexact=subject_lookup,
        is_default=True,
        is_active=True
    ).first()
    
    if template:
        print(f"[Blueprint] ✅ Found default template: {template.name}")
        return template.blueprint
    
    # Priority 3: Look for any template (fallback)
    template = BlueprintTemplate.objects.filter(
        class_name=class_name,
        subject__iexact=subject_lookup,
        is_active=True
    ).first()
    
    if template:
        print(f"[Blueprint] ✅ Found template: {template.name}")
        return template.blueprint
    
    # Priority 4: Legacy hardcoded blueprints (for backward compatibility)
    print(f"[Blueprint] ⚠️ No database blueprint found, using legacy system")
    return get_legacy_blueprint(class_name, subject, section)

def get_legacy_blueprint(class_name, subject, section=None):
    """Legacy blueprint system for backward compatibility"""
    normalized_subject = subject.strip().lower()
    
    # Legacy blueprint definitions
    legacy_blueprints = {
        "11": {
            "english core": {
                "sections": [
                    {"name": "A", "title": "Reading", "marks": 20, "question_types": ["unseen_passage", "case_based"]},
                    {"name": "B", "title": "Writing", "marks": 30, "question_types": ["grammar", "writing_tasks"]},
                    {"name": "C", "title": "Literature", "marks": 30, "question_types": ["extract_based", "short_answer", "long_answer"]},
                    {"name": "D", "title": "Flamingo", "marks": 20, "question_types": ["short_answer", "long_answer"]}
                ]
            },
            "biology": {
                "sections": [
                    {"name": "A", "title": "Multiple Choice", "marks": 20, "question_types": ["mcq"]},
                    {"name": "B", "title": "Assertion-Reason", "marks": 10, "question_types": ["assertion_reason"]},
                    {"name": "C", "title": "Very Short Answer", "marks": 20, "question_types": ["very_short_answer"]},
                    {"name": "D", "title": "Short Answer", "marks": 30, "question_types": ["short_answer"]},
                    {"name": "E", "title": "Long Answer", "marks": 20, "question_types": ["long_answer"]}
                ]
            }
        }
    }
    
    blueprint = legacy_blueprints.get(class_name, {}).get(normalized_subject)
    if blueprint:
        print(f"[Blueprint] ✅ Found legacy blueprint for {class_name} {subject}")
        return blueprint
    
    # Final fallback - raise error
    raise ValueError(f"No blueprint found for {class_name} {subject} (section: {section}). Please create a blueprint template or exam blueprint.")

# ------------------------------
# Universal Context Retrieval
# ------------------------------
def get_universal_context(class_name, subject, chapters, question_types=None):
    """
    Universal context retrieval system that works for all subjects and question types.
    
    Args:
        class_name: Class (e.g., "11", "12")
        subject: Subject name (e.g., "English", "Biology")
        chapters: List of chapters to include
        question_types: List of question types to optimize context for
    
    Returns:
        dict: Context information with documents and metadata
    """
    print(f"[Context] Retrieving universal context for {class_name} {subject}")
    print(f"[Context] Chapters: {chapters}")
    print(f"[Context] Question types: {question_types}")
    
    all_contexts = []
    context_metadata = {
        "total_chapters": len(chapters),
        "question_types": question_types or [],
        "retrieval_timestamp": datetime.now().isoformat()
    }
    
    # Build optimized queries based on question types
    base_queries = [f"{subject} important NCERT concepts"]
    
    if question_types:
        # Add subject-specific queries based on question types
        for qtype in question_types:
            if qtype in ["unseen_passage", "case_based"]:
                base_queries.append(f"{subject} reading comprehension passages")
                base_queries.append(f"{subject} case studies examples")
            elif qtype in ["mcq", "assertion_reason"]:
                base_queries.append(f"{subject} multiple choice questions")
                base_queries.append(f"{subject} facts and concepts")
            elif qtype in ["writing_tasks", "grammar"]:
                base_queries.append(f"{subject} writing skills")
                base_queries.append(f"{subject} grammar rules")
            elif qtype in ["extract_based", "short_answer", "long_answer"]:
                base_queries.append(f"{subject} detailed explanations")
                base_queries.append(f"{subject} important topics")
            elif qtype in ["numerical", "proof"]:
                base_queries.append(f"{subject} solved examples")
                base_queries.append(f"{subject} mathematical problems")
    
    # Remove duplicates while preserving order
    unique_queries = list(dict.fromkeys(base_queries))
    print(f"[Context] Using queries: {unique_queries}")
    
    # Retrieve context for each chapter and query combination
    for chapter in chapters:
        chapter_contexts = []
        
        for query in unique_queries:
            try:
                results = embeddings.query(
                    class_name=class_name, 
                    subject=subject, 
                    unit=chapter,
                    query_text=query, 
                    n_results=50  # Reduced per query, but multiple queries
                )
                
                if results and "documents" in results:
                    for docs in results["documents"]:
                        chapter_contexts.extend(docs)
                        
            except Exception as e:
                print(f"[Context] ⚠️ Error retrieving context for {chapter} with query '{query}': {e}")
                continue
        
        # Deduplicate and limit chapter contexts
        chapter_contexts = list(dict.fromkeys(chapter_contexts))  # Remove duplicates
        chapter_contexts = chapter_contexts[:100]  # Limit per chapter
        
        all_contexts.extend(chapter_contexts)
        print(f"[Context] Retrieved {len(chapter_contexts)} contexts for chapter {chapter}")
    
    # Final deduplication and limiting
    all_contexts = list(dict.fromkeys(all_contexts))  # Remove duplicates
    all_contexts = all_contexts[:500]  # Global limit
    
    context_text = "\n".join(all_contexts)
    
    context_metadata.update({
        "total_contexts": len(all_contexts),
        "context_length": len(context_text),
        "queries_used": unique_queries
    })
    
    print(f"[Context] ✅ Retrieved {len(all_contexts)} total contexts ({len(context_text)} characters)")
    
    return {
        "context_text": context_text,
        "contexts": all_contexts,
        "metadata": context_metadata
    }

def get_question_type_instructions(question_types, subject):
    """
    Get specific instructions for different question types.
    
    Args:
        question_types: List of question types
        subject: Subject name
    
    Returns:
        str: Formatted instructions for the question types
    """
    if not question_types:
        return ""
    
    instructions = []
    
    for qtype in question_types:
        if qtype == "unseen_passage":
            instructions.append("• Unseen Passage: Include a reading comprehension passage with 5-6 questions based on the passage")
        elif qtype == "case_based":
            instructions.append("• Case-based: Create scenario-based questions that test application of concepts")
        elif qtype == "mcq":
            instructions.append("• Multiple Choice: Create 4-option MCQs with one correct answer and plausible distractors")
        elif qtype == "assertion_reason":
            instructions.append("• Assertion-Reason: Create statements with assertion and reason, test logical relationship")
        elif qtype == "grammar":
            instructions.append("• Grammar: Focus on grammatical concepts, sentence correction, and language usage")
        elif qtype == "writing_tasks":
            instructions.append("• Writing Tasks: Include essay writing, letter writing, or other composition tasks")
        elif qtype == "extract_based":
            instructions.append("• Extract-based: Provide literary extracts and ask questions based on them")
        elif qtype == "short_answer":
            instructions.append("• Short Answer: Create questions requiring brief, focused responses (2-3 sentences)")
        elif qtype == "long_answer":
            instructions.append("• Long Answer: Create questions requiring detailed, comprehensive responses")
        elif qtype == "very_short_answer":
            instructions.append("• Very Short Answer: Create questions requiring one-word or one-sentence responses")
        elif qtype == "numerical":
            instructions.append("• Numerical: Create problems requiring mathematical calculations and solutions")
        elif qtype == "proof":
            instructions.append("• Proof: Create questions requiring mathematical proofs or logical reasoning")
        elif qtype == "or_choice":
            instructions.append("• Either/Or: Provide alternative questions where students choose one to answer")
    
    return "\n".join(instructions) if instructions else ""

# ------------------------------
# JSON enforcement
# ------------------------------
def enforce_json(validated_json):
    print(f"[JSON-Validator] Starting JSON enforcement process...")
    print(f"[JSON-Validator] Input length: {len(validated_json)} characters")
    
    # Save raw response
    with open("temp_raw.json", "w", encoding="utf-8") as f:
        f.write(validated_json)
    print(f"[JSON-Validator] Raw response saved to temp_raw.json")

    # Clean up markdown code blocks
    if validated_json.strip().startswith("```"):
        print(f"[JSON-Validator] Removing markdown code blocks...")
        validated_json = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", validated_json.strip())
        print(f"[JSON-Validator] After markdown cleanup: {len(validated_json)} characters")

    # Try to parse as-is first
    data = None
    try:
        data = json.loads(validated_json)
        print("[JSON-Validator] ✅ Successfully parsed JSON on first attempt")
        print(f"[JSON-Validator] Parsed JSON has {len(data)} top-level keys: {list(data.keys())}")
    except Exception as e:
        print(f"[JSON-Validator] ❌ First attempt failed: {e}")
        print(f"[JSON-Validator] Attempting to fix JSON issues...")
        
        # Try to fix common JSON issues
        fixed_json = fix_json_issues(validated_json)
        
        try:
            data = json.loads(fixed_json)
            print("[JSON-Validator] Successfully parsed JSON after fixing issues")
        except Exception as e2:
            print(f"[JSON-Validator] Fixed JSON still invalid: {e2}")
            
            # Try extracting JSON from text
            try:
                match = re.search(r"\{.*\}", fixed_json, re.S)
                if match:
                    candidate = match.group(0)
                    data = json.loads(candidate)
                    print("[JSON-Validator] Successfully extracted and parsed JSON")
            except Exception as e3:
                print(f"[JSON-Validator] JSON extraction failed: {e3}")

    # Save the processed JSON
    with open("temp_validated.json", "w", encoding="utf-8") as f:
        f.write(validated_json)

    if data:
        with open("temp_clean.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data

    raise ValueError("Validator did not return valid JSON. Check temp_raw.json and temp_validated.json")

def fix_json_issues(json_text):
    """Fix common JSON formatting issues"""
    print("[JSON-Fixer] Attempting to fix JSON issues...")
    
    # Remove any leading/trailing whitespace
    json_text = json_text.strip()
    
    # Fix common issues
    fixes_applied = []
    
    # 1. Fix missing closing brackets/braces
    open_braces = json_text.count('{')
    close_braces = json_text.count('}')
    open_brackets = json_text.count('[')
    close_brackets = json_text.count(']')
    
    if open_braces > close_braces:
        missing_braces = open_braces - close_braces
        json_text += '}' * missing_braces
        fixes_applied.append(f"Added {missing_braces} missing closing braces")
    
    if open_brackets > close_brackets:
        missing_brackets = open_brackets - close_brackets
        json_text += ']' * missing_brackets
        fixes_applied.append(f"Added {missing_brackets} missing closing brackets")
    
    # 2. Fix trailing commas
    json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
    if re.search(r',(\s*[}\]])', json_text):
        fixes_applied.append("Removed trailing commas")
    
    # 3. Fix unescaped quotes in strings
    # This is more complex, so we'll try a simpler approach first
    
    # 4. Fix incomplete strings at the end
    if json_text.endswith('"') and not json_text.endswith('""'):
        # Check if we have an incomplete string
        last_quote_pos = json_text.rfind('"', 0, -1)
        if last_quote_pos > 0:
            # Look for the opening quote
            before_last_quote = json_text[:last_quote_pos]
            if before_last_quote.count('"') % 2 == 1:  # Odd number of quotes means incomplete
                json_text = json_text[:-1]  # Remove the incomplete quote
                fixes_applied.append("Removed incomplete string quote")
    
    # 5. Fix incomplete objects/arrays
    # If the JSON ends abruptly, try to close it properly
    if not json_text.endswith(('}', ']', '"')):
        # Find the last complete structure
        lines = json_text.split('\n')
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line and not line.endswith(','):
                # This might be the last complete line
                if line.endswith('"') or line.endswith('}') or line.endswith(']'):
                    # Close any open structures
                    if open_braces > close_braces:
                        json_text += '}' * (open_braces - close_braces)
                    if open_brackets > close_brackets:
                        json_text += ']' * (open_brackets - close_brackets)
                    fixes_applied.append("Closed incomplete structures")
                break
    
    # 6. Handle specific case from temp_raw.json - incomplete extract
    # If the JSON ends with an incomplete string or object, try to complete it
    if json_text.endswith('"') and '"' in json_text:
        # Check if we have an incomplete string at the end
        lines = json_text.split('\n')
        last_line = lines[-1].strip()
        
        # If the last line looks like an incomplete string, try to close it
        if last_line.count('"') == 1 and not last_line.endswith('",'):
            # This might be an incomplete string, try to close it properly
            if last_line.endswith('"'):
                json_text = json_text[:-1]  # Remove the incomplete quote
                # Add proper closing for the structure
                if open_braces > close_braces:
                    json_text += '}' * (open_braces - close_braces)
                if open_brackets > close_brackets:
                    json_text += ']' * (open_brackets - close_brackets)
                fixes_applied.append("Fixed incomplete string and closed structures")
    
    # 7. Fix incomplete extract objects (specific to your case)
    if '"extract":' in json_text and not json_text.endswith('}'):
        # Look for incomplete extract objects
        extract_pos = json_text.rfind('"extract":')
        if extract_pos > 0:
            # Find the end of the extract value
            after_extract = json_text[extract_pos + 10:]
            # Look for the next quote or end
            if '"' in after_extract:
                # Find the end of the extract string
                end_quote = after_extract.find('"', 1)
                if end_quote > 0:
                    # Check if we have proper closing after the extract
                    after_extract_value = after_extract[end_quote + 1:].strip()
                    if not after_extract_value.startswith(','):
                        # Add missing comma and closing
                        json_text = json_text[:extract_pos + 10 + end_quote + 1] + '",'
                        # Close any remaining structures
                        if open_braces > close_braces:
                            json_text += '}' * (open_braces - close_braces)
                        if open_brackets > close_brackets:
                            json_text += ']' * (open_brackets - close_brackets)
                        fixes_applied.append("Fixed incomplete extract object")
    
    if fixes_applied:
        print(f"[JSON-Fixer] Applied fixes: {', '.join(fixes_applied)}")
    else:
        print("[JSON-Fixer] No obvious fixes needed")
    
    return json_text


# ------------------------------
# PDF helper
# ------------------------------
def draw_wrapped(can, text, x, y, max_width, font="Helvetica", size=11, line_height=16):
    can.setFont(font, size)
    lines = simpleSplit(text, font, size, max_width)
    for line in lines:
        if y < 100:
            can.showPage()
            can.setFont(font, size)
            y = 760
        can.drawString(x, y, line)
        y -= line_height
    return y


# ------------------------------
# Flexible renderer for English
# ------------------------------
def render_section_questions(all_questions, data, blueprint):
    q_counter = 1
    
    print("=" * 50)
    print("RENDER_SECTION_QUESTIONS CALLED!")
    print("=" * 50)
    print(f"[DEBUG] Starting render_section_questions")
    print(f"[DEBUG] Data keys: {list(data.keys())}")
    print(f"[DEBUG] Blueprint keys: {list(blueprint.keys())}")
    
    # Handle the new JSON structure where sections are at the top level
    if "sections" in data:
        # Old structure: {"sections": {"A": {...}}}
        sections_data = data["sections"]
        print(f"[DEBUG] Using old structure with sections key")
    else:
        # New structure: {"A": {"title": "...", "subsections": {...}}}
        sections_data = data
        print(f"[DEBUG] Using new structure, sections_data keys: {list(sections_data.keys())}")
    
    for sec, sec_info in blueprint.items():
        print(f"[DEBUG] Processing section {sec}: {sec_info['title']}")
        all_questions.append(("header", f"SECTION – {sec} {sec_info['title'].upper()} ({sec_info['marks']} MARKS)"))
        
        # Get section data - handle both old and new structures
        if sec in sections_data:
            section_data = sections_data[sec]
            print(f"[DEBUG] Found section data for {sec}, keys: {list(section_data.keys())}")
            
            # Check if it's the new structure with subsections
            if "subsections" in section_data:
                print(f"[DEBUG] Processing subsections for {sec}")
                for sub, q_list in section_data["subsections"].items():
                    print(f"[DEBUG] Processing subsection {sub} with {len(q_list)} questions")
                    # Remove subheader - don't add "READING", "GRAMMAR" etc.
                    # all_questions.append(("subheader", f"{sub.upper()}"))
                    for q in q_list:
                        print(f"[DEBUG] Processing question: {q.get('qnum', 'no qnum')} - {q.get('type', 'no type')}")
                        q_counter = process_question(all_questions, q, q_counter)
            else:
                # Old structure - direct list of questions
                print(f"[DEBUG] Processing old structure for {sec}")
                for q in section_data:
                    q_counter = process_question(all_questions, q, q_counter)
        else:
            print(f"[DEBUG] No section data found for {sec}")
            all_questions.append(("q", f"No questions found for section {sec}"))
    
    print(f"[DEBUG] Total questions processed: {len(all_questions)}")
    return all_questions

def process_question(all_questions, q, q_counter):
    qnum = q.get("qnum", q_counter)
    print(f"[DEBUG] Processing question {qnum}, type: {q.get('type', 'no type')}, keys: {list(q.keys())}")

    # If it has an instruction field, treat it as an instruction (no number)
    if "instruction" in q and q.get("type") not in ["unseen_passage_or_case_based"]:
        all_questions.append(("instruction", q['instruction']))  # No number for instructions
        
        # Handle gap_filling type with text field
        if q.get("type") == "gap_filling" and "text" in q:
            all_questions.append(("passage", q["text"]))
        
        # Handle reordering type with sentences array
        elif q.get("type") == "reordering" and "sentences" in q:
            for item in q["sentences"]:
                all_questions.append(("subq", f"- {item}"))
        
        # Handle other types with items, sentences, phrases
        else:
            for k in ("items", "sentences", "phrases"):
                if k in q:
                    for item in q[k]:
                        all_questions.append(("subq", f"- {item}"))
        return q_counter + 1

    elif "extract" in q:
        # Handle literature extracts with instruction
        if "instruction" in q:
            all_questions.append(("instruction", q['instruction']))  # No number for instructions
        else:
            all_questions.append(("instruction", "Read the extract:"))  # No number for instructions
        all_questions.append(("passage", q["extract"]))
        for i, subq in enumerate(q.get("questions", []), start=1):
            # Handle both string and dict formats for questions
            if isinstance(subq, dict):
                # Check for both "text" and "q" fields
                question_text = subq.get("text", subq.get("q", str(subq)))
                # Also check for marks field
                marks = subq.get("marks", "")
                if marks:
                    question_text = f"{question_text} ({marks} marks)"
            else:
                question_text = str(subq)
            all_questions.append(("subq", f"({i}) {question_text}"))

    elif q.get("type") == "unseen_passage_or_case_based":
        print(f"[DEBUG] Processing unseen_passage_or_case_based with {len(q.get('options', []))} options")
        all_questions.append(("instruction", q['instruction']))  # No number for instructions
        for opt in q["options"]:
            print(f"[DEBUG] Processing option: {opt.get('kind')} with {len(opt.get('questions', []))} questions")
            all_questions.append(("passage", f"[{opt['kind'].replace('_',' ').title()}]\n{opt['passage']}"))
            for i, subq in enumerate(opt.get("questions", []), start=1):
                print(f"[DEBUG] Processing sub-question {i}: {subq}")
                # Handle both string and dict formats for questions
                if isinstance(subq, dict):
                    # Check for both "text" and "q" fields
                    question_text = subq.get("text", subq.get("q", str(subq)))
                    # Also check for marks field
                    marks = subq.get("marks", "")
                    if marks:
                        question_text = f"{question_text} ({marks} marks)"
                else:
                    question_text = str(subq)
                all_questions.append(("subq", f"({i}) {question_text}"))

    elif "passage" in q and "questions" in q:
        print(f"[DEBUG] Found passage with questions, type: {q.get('type')}")
        all_questions.append(("instruction", "Read the passage:"))  # No number for instructions
        all_questions.append(("passage", q["passage"]))
        for i, subq in enumerate(q["questions"], start=1):
            # Handle both string and dict formats for questions
            if isinstance(subq, dict):
                # Check for both "text" and "q" fields
                question_text = subq.get("text", subq.get("q", str(subq)))
                # Also check for marks field
                marks = subq.get("marks", "")
                if marks:
                    question_text = f"{question_text} ({marks} marks)"
            else:
                question_text = str(subq)
            all_questions.append(("subq", f"({i}) {question_text}"))

    elif "passage" in q:
        instr = q.get("instruction", "Based on passage:")
        all_questions.append(("instruction", instr))  # No number for instructions
        all_questions.append(("passage", q["passage"]))

    # This case is now handled above

    elif "text" in q and not ("passage" in q or "extract" in q):
        # Handle questions that have only "text" field (new structure)
        all_questions.append(("q", f"{qnum}. {q['text']}"))

    elif "question" in q and "or" in q:
        all_questions.append(("q", f"{qnum}. {q['question']}"))
        all_questions.append(("or", "OR"))
        all_questions.append(("q", q["or"]))

    elif "question" in q:
        all_questions.append(("q", f"{qnum}. {q['question']}"))
        
        # Handle long answers with options
        if "options" in q:
            for i, option in enumerate(q["options"], start=1):
                all_questions.append(("subq", f"({chr(96+i)}) {option}"))

    return q_counter + 1


# ------------------------------
# Science/Maths generator
# ------------------------------
def generate_science_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file=None):
    contexts = []
    for ch in chapters:
        results = embeddings.query(class_name=class_name, subject=subject, unit=ch,
                                   query_text=f"{subject} important NCERT concepts", n_results=100)
        for docs in results["documents"]:
            contexts.extend(docs)
    context_text = "\n".join(contexts)

    # Use pattern sections if available, otherwise fall back to blueprint
    pattern_sections = None
    if hasattr(pattern, 'sections') and pattern.sections:
        # Ensure pattern.sections is a list, not a string
        if isinstance(pattern.sections, list):
            pattern_sections = pattern.sections
        elif isinstance(pattern.sections, str):
            # If it's a string, treat it as a single section description
            pattern_sections = [pattern.sections]
    
    schema = """
{ "sections": { "A": [{"qnum": int, "text": str, "options": [str]}],
                "B": [{"qnum": int, "text": str}],
                "C": [{"qnum": int, "text": str}],
                "D": [{"qnum": int, "text": str}],
                "E": [{"qnum": int, "question": str, "or": str}] } }
"""

    # Build rules based on pattern or blueprint
    if pattern_sections:
        rules_text = f"Follow this exam pattern: {pattern.name}\n"
        for section in pattern_sections:
            # Handle both dict and string formats
            if isinstance(section, dict):
                rules_text += f"- Section {section['name']}: {section['questions']} questions ({section['marks']} marks each)\n"
            elif isinstance(section, str):
                # If section is a string, use it as is
                rules_text += f"- {section}\n"
    else:
        rules_text = f"""- Section A: {blueprint['A'][0]} MCQs (1 mark each), include Assertion–Reason.
- Section B: {blueprint['B'][0]} VSA (2 marks).
- Section C: {blueprint['C'][0]} SA (3 marks).
- Section D: {blueprint['D'][0]} Case-based (4 marks).
- Section E: {blueprint['E'][0]} Long with OR choice (5 marks)."""

    gen_prompt = f"""
You are an expert CBSE paper setter.

Generate exam questions strictly in JSON format.
Schema:
{schema}

Rules:
{rules_text}
- Use only NCERT context from the selected chapters: {', '.join(chapters)}
- Difficulty level: {difficulty}
- Output raw JSON only.

Context:
{context_text}
"""
    raw_json = call_bedrock(gen_prompt, GEN_MODEL_ID, max_tokens=6000, temperature=0.7)

    validator_prompt = f"""
You are a strict JSON validator.
Input will be JSON text. If it is already valid JSON, return unchanged.
If it is invalid, fix it but preserve all content.
Output only JSON.

{raw_json}
"""
    validated = call_bedrock(validator_prompt, VAL_MODEL_ID, max_tokens=6000, temperature=0.3)
    data = enforce_json(validated)
    
    # Log generation results to summary file
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"=== GENERATION RESULTS ===\n")
            f.write(f"Raw JSON Length: {len(raw_json)} chars\n")
            f.write(f"Validated JSON Length: {len(validated)} chars\n")
            f.write(f"Questions Generated: {len(data.get('sections', {}))} sections\n")
            f.write(f"{'='*50}\n\n")

    all_questions, summary = [], {}
    q_counter = 1
    for sec, (count, marks) in blueprint.items():
        sec_data = data.get("sections", {}).get(sec, [])
        all_questions.append(("header", f"SECTION {sec} ({count} × {marks} = {count*marks})"))
        for i in range(count):
            if i < len(sec_data):
                q = sec_data[i]
                if sec == "A":
                    all_questions.append(("q", f"{q_counter}) {q['text']}"))
                    for j, opt in enumerate(q.get("options", [])):
                        all_questions.append(("subq", f"   {chr(97+j)}) {opt.strip()}"))
                elif sec == "E":
                    all_questions.append(("q", f"{q_counter}) {q['question']}"))
                    all_questions.append(("or", "OR"))
                    all_questions.append(("q", q['or']))
                else:
                    all_questions.append(("q", f"{q_counter}) {q['text']}"))
            else:
                all_questions.append(("q", f"{q_counter}) [Placeholder]"))
            q_counter += 1
        summary[sec] = {"questions": count, "marks_each": marks}

    return render_pdf(class_name, subject, chapters, all_questions, summary)


# ------------------------------
# English Core generator
# ------------------------------
def generate_english_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file=None):
    lesson_names = [
        "The Portrait of a Lady", "We're Not Afraid to Die... if We Can Be Together",
        "Discovering Tut: The Saga Continues", "A Photograph",
        "The Laburnum Top", "The Voice of the Rain",
        "The Summer of the Beautiful White Horse", "The Address", "Mother's Day"
    ]

    # Use selected chapters if available, otherwise use all lesson names
    selected_lessons = chapters if chapters else lesson_names

    print(f"[Embeddings] Querying embeddings for {len(selected_lessons)} chapters...")
    contexts = []
    for ch in selected_lessons:
        print(f"[Embeddings] Querying chapter: {ch}")
        results = embeddings.query(class_name=class_name, subject=subject, unit=ch,
                                   query_text="important NCERT extract content", n_results=50)
        print(f"[Embeddings] Found {len(results['documents'])} document chunks for {ch}")
        for docs in results["documents"]:
            contexts.extend(docs)
    
    context_text = "\n".join(contexts)
    print(f"[Embeddings] Total context chunks retrieved: {len(contexts)}")
    print(f"[Embeddings] Total context length: {len(context_text)} characters")

    # Use pattern sections if available, otherwise use blueprint
    pattern_sections = None
    if hasattr(pattern, 'sections') and pattern.sections:
        # Ensure pattern.sections is a list, not a string
        if isinstance(pattern.sections, list):
            pattern_sections = pattern.sections
        elif isinstance(pattern.sections, str):
            # If it's a string, treat it as a single section description
            pattern_sections = [pattern.sections]
    
    if pattern_sections:
        rules_text = f"Follow this exam pattern: {pattern.name}\n"
        for section in pattern_sections:
            # Handle both dict and string formats
            if isinstance(section, dict):
                rules_text += f"- Section {section['name']}: {section['questions']} questions ({section['marks']} marks each)\n"
            elif isinstance(section, str):
                # If section is a string, use it as is
                rules_text += f"- {section}\n"
        rules_text += f"- Focus on selected chapters: {', '.join(selected_lessons)}\n"
        rules_text += f"- Difficulty level: {difficulty}\n"
    else:
        rules_text = f"""- Section A: One unseen passage OR one case-based passage (Answer ANY ONE). Then Note making + Summary.
- Section B: Grammar + Writing (Gap filling, reordering, ad/poster, speech, debate).
- Section C: Extracts, short answers, long answers ONLY from Hornbill and Snapshots NCERT chapters.
- Focus on selected chapters: {', '.join(selected_lessons)}
- Difficulty level: {difficulty}"""

    # Clean and limit context text to avoid corruption
    print(f"[Context] Original context length: {len(context_text)} characters")
    
    # Clean the context more carefully
    clean_context = context_text.replace('\n', ' ').replace('\r', ' ')
    # Remove any non-printable characters but preserve more content
    clean_context = re.sub(r'[^\x20-\x7E]', ' ', clean_context)
    clean_context = ' '.join(clean_context.split())  # Normalize whitespace
    
    # Increase limit to get more NCERT content
    clean_context = clean_context[:3000]  # Limit to 3000 chars to get more context
    
    print(f"[Context] Cleaned context length: {len(clean_context)} characters")
    print(f"[Context] Context preview: {clean_context[:200]}...")
    
    gen_prompt = f"""
You are an expert CBSE paper setter for ENGLISH CORE CLASS XI.

Generate exam questions strictly in JSON format following this exact schema:
{json.dumps(blueprint, indent=2)}

IMPORTANT RULES:
{rules_text}

SELECTED CHAPTERS FOR LITERATURE QUESTIONS:
{", ".join(selected_lessons)}

NCERT CONTEXT (use for literature questions only):
{clean_context}

QUESTION REQUIREMENTS:
- Section A: Create ONE unseen passage (300-400 words) OR case-based passage with 4-5 questions
- Section B: Grammar questions (gap filling, reordering) + Writing tasks (advertisement, poster, speech, debate)
- Section C: Literature questions ONLY from the selected chapters above
- All questions must be appropriate for Class XI level
- Difficulty: {difficulty}

OUTPUT FORMAT:
- Return ONLY valid JSON
- Do not include answers or explanations
- Follow the exact schema structure provided
- Ensure all required fields are present

Generate the question paper now:
"""
    # Step 1: Get complete response from generation model
    print(f"[Generation] Starting question paper generation...")
    print(f"[Generation] Using model: {GEN_MODEL_ID}")
    print(f"[Generation] Max tokens set to 6000 to ensure complete response")
    
    raw_json = call_bedrock(gen_prompt, GEN_MODEL_ID, max_tokens=6000, temperature=0.7)
    
    # Log the complete raw response
    print(f"[Generation] Raw response received: {len(raw_json)} characters")
    print(f"[Generation] Raw response preview: {raw_json[:200]}...")
    
    # Check if the response is complete
    if not raw_json.strip().endswith('}') and not raw_json.strip().endswith('```'):
        print(f"[Generation] ⚠️  WARNING: Response appears incomplete!")
        print(f"[Generation] Last 200 chars: {raw_json[-200:]}")
        
        # Try to complete the JSON if it's clearly cut off
        if raw_json.strip().endswith('"') and raw_json.count('{') > raw_json.count('}'):
            print(f"[Generation] Attempting to complete truncated JSON...")
            # Add missing closing brackets
            missing_braces = raw_json.count('{') - raw_json.count('}')
            raw_json += '"}' * missing_braces
            print(f"[Generation] Added {missing_braces} closing brackets")
    
    # Step 2: Validate the complete response with validator model
    print(f"[Validation] Starting JSON validation...")
    print(f"[Validation] Using model: {VAL_MODEL_ID}")
    
    validator_prompt = f"""
You are a JSON validator and fixer for CBSE question papers.

TASK: Fix the following JSON to ensure it's valid and complete.

REQUIREMENTS:
- Must be valid JSON syntax
- Must follow the exact schema structure
- All required fields must be present
- No missing brackets, quotes, or commas
- All question numbers must be sequential
- All marks must add up correctly

INPUT JSON TO FIX:
{raw_json}

OUTPUT: Return ONLY the corrected JSON, no explanations.
"""
    
    validated = call_bedrock(validator_prompt, VAL_MODEL_ID, max_tokens=6000, temperature=0.3)
    
    print(f"[Validation] Validation response received: {len(validated)} characters")
    print(f"[Validation] Validation response preview: {validated[:200]}...")
    
    # Step 3: Final JSON enforcement and cleanup
    print(f"[Final-Validation] Starting final JSON enforcement...")
    data = enforce_json(validated)
    
    print(f"[Final-Validation] JSON enforcement completed successfully!")
    print(f"[Final-Validation] Final data structure: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
    
    # Log generation results to summary file
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"=== GENERATION RESULTS ===\n")
            f.write(f"Generation Model: {GEN_MODEL_ID}\n")
            f.write(f"Validation Model: {VAL_MODEL_ID}\n")
            f.write(f"Raw JSON Length: {len(raw_json)} chars\n")
            f.write(f"Validated JSON Length: {len(validated)} chars\n")
            f.write(f"Final JSON Structure: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}\n")
            f.write(f"Questions Generated: {len(data.get('sections', {}))} sections\n")
            f.write(f"Generation Process: Complete\n")
            f.write(f"{'='*50}\n\n")

    print("=" * 50)
    print("USING DIRECT JSON APPROACH")
    print("=" * 50)
    
    # Write debug output to file
    debug_file = "debug_render.txt"
    with open(debug_file, "w", encoding="utf-8") as debug_f:
        debug_f.write("=" * 50 + "\n")
        debug_f.write("RENDER DEBUG LOG\n")
        debug_f.write("=" * 50 + "\n")
    
    # Read the temp_clean.json file directly
    try:
        with open("temp_clean.json", "r", encoding="utf-8") as f:
            direct_data = json.load(f)
        print(f"[DIRECT] Successfully loaded temp_clean.json with keys: {list(direct_data.keys())}")
        
        with open(debug_file, "a", encoding="utf-8") as debug_f:
            debug_f.write(f"Loaded temp_clean.json with keys: {list(direct_data.keys())}\n")
        
        # Use the direct data instead of the processed data
        all_questions = render_section_questions([], direct_data, blueprint)
        print(f"[DIRECT] Generated {len(all_questions)} questions from temp_clean.json")
        
        with open(debug_file, "a", encoding="utf-8") as debug_f:
            debug_f.write(f"Generated {len(all_questions)} questions\n")
            debug_f.write("First 10 questions:\n")
            for i, (typ, text) in enumerate(all_questions[:10]):
                debug_f.write(f"  {i+1}. [{typ}] {text[:100]}...\n")
        
    except Exception as e:
        print(f"[DIRECT] Error loading temp_clean.json: {e}")
        with open(debug_file, "a", encoding="utf-8") as debug_f:
            debug_f.write(f"Error: {e}\n")
        # Fallback to original approach
        all_questions = render_section_questions([], data, blueprint)
    
    summary = {sec: {"title": sec_info["title"], "marks": sec_info["marks"]}
               for sec, sec_info in blueprint.items()}
    return render_pdf(class_name, subject, chapters, all_questions, summary)


# ------------------------------
# PDF renderer
# ------------------------------
def render_pdf(class_name, subject, chapters, all_questions, summary):
    writer = PdfWriter()
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    y = 650  # Much more space from header to avoid clash

    if not all_questions:
        all_questions = [("header", "NO QUESTIONS GENERATED"),
                         ("q", "Check blueprint or JSON parsing")]

    print("DEBUG all_questions sample:", all_questions[:10])

    for typ, text in all_questions:
        if typ == "header":
            can.setFont("Helvetica-Bold", 14)
            can.drawCentredString(300, y, text)
            y -= 60  # Even more spacing after header to avoid clash

        elif typ == "subheader":
            can.setFont("Helvetica-Bold", 12)
            y = draw_wrapped(can, text, 60, y, 470)
            y -= 10

        elif typ == "instruction":
            can.setFont("Helvetica", 11)
            y = draw_wrapped(can, text, 60, y, 470)  # Instructions without numbers

        elif typ == "q":
            can.setFont("Helvetica", 11)
            y = draw_wrapped(can, text, 60, y, 470)

        elif typ == "subq":
            can.setFont("Helvetica", 11)
            y = draw_wrapped(can, text, 80, y, 440)

        elif typ == "passage":
            can.setFont("Helvetica-Oblique", 10)
            y = draw_wrapped(can, text, 60, y, 470, size=10, line_height=14)
            y -= 5

        elif typ == "or":
            can.setFont("Helvetica-Bold", 11)
            can.drawCentredString(300, y, "OR")
            y -= 20

    # Summary Page
    can.showPage()
    can.setFont("Helvetica-Bold", 14)
    can.drawCentredString(300, 800, "SUMMARY OF PAPER GENERATION")
    y = 760
    can.setFont("Helvetica", 11)
    for sec, info in summary.items():
        if "marks_each" in info:
            line = f"Section {sec}: {info['questions']} questions | Marks each: {info['marks_each']}"
        else:
            line = f"Section {sec}: {info['title']} | Total Marks: {info['marks']}"
        y = draw_wrapped(can, line, 60, y, 470)

    can.save()
    packet.seek(0)
    overlay_reader = PdfReader(packet)

    base_path = r"D:\qpg\core\data\base.pdf"
    if os.path.exists(base_path):
        base_reader = PdfReader(base_path)
        for i, overlay_page in enumerate(overlay_reader.pages):
            if i < len(base_reader.pages):
                base_page = base_reader.pages[i]
                overlay_page.merge_page(base_page)
                writer.add_page(overlay_page)
            else:
                writer.add_page(overlay_page)
    else:
        for page in overlay_reader.pages:
            writer.add_page(page)

    output_dir = os.path.join(settings.MEDIA_ROOT, "question_papers")
    os.makedirs(output_dir, exist_ok=True)

    safe_subject = subject.replace(" ", "_")
    filename = f"{safe_subject}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    file_path = os.path.join(output_dir, filename)

    with open(file_path, "wb") as f:
        writer.write(f)

    return f"question_papers/{filename}", summary


# ------------------------------
# Entrypoint
# ------------------------------
def generate_universal_paper(class_name, subject, chapters, difficulty, pattern, section=None):
    """
    Universal question paper generator that works for all subjects and question types.
    Uses database-driven blueprints and adaptive prompt generation.
    """
    # Create generation summary log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = f"temp_generation_summary_{timestamp}.txt"
    
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(f"=== UNIVERSAL QUESTION PAPER GENERATION ===\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write(f"Class: {class_name}\n")
        f.write(f"Subject: {subject}\n")
        f.write(f"Chapters: {', '.join(chapters) if chapters else 'All'}\n")
        f.write(f"Difficulty: {difficulty}\n")
        f.write(f"Pattern: {pattern.name}\n")
        f.write(f"Section: {section or 'All'}\n")
        f.write(f"{'='*50}\n\n")
    
    print(f"[Universal-Generator] Starting generation for {class_name} {subject}")
    print(f"[Universal-Generator] Summary saved to: {summary_file}")
    
    try:
        # Get blueprint using enhanced resolution
        blueprint = get_blueprint(class_name, subject, section)
        print(f"[Universal-Generator] ✅ Blueprint resolved: {len(blueprint.get('sections', []))} sections")
        
        # Extract all question types from blueprint
        all_question_types = []
        
        # Check if this is a complex blueprint (has sections with subsections) or simple blueprint
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
        print(f"[Universal-Generator] Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}")
        print(f"[Universal-Generator] Question types: {all_question_types}")
        
        # Get universal context
        context_data = get_universal_context(class_name, subject, chapters, all_question_types)
        context_text = context_data['context_text']
        
        # Generate the paper using universal prompt
        paper_data = generate_with_universal_prompt(
            class_name, subject, chapters, difficulty, pattern, blueprint, 
            context_text, all_question_types, summary_file
        )
        
        return paper_data
        
    except Exception as e:
        error_msg = f"Universal generation failed: {str(e)}"
        print(f"[Universal-Generator] ❌ {error_msg}")
        
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"\n❌ ERROR: {error_msg}\n")
            f.write(f"Traceback: {traceback.format_exc()}\n")
        
        raise Exception(error_msg)

def generate_with_universal_prompt(class_name, subject, chapters, difficulty, pattern, blueprint, context_text, question_types, summary_file):
    """Generate paper using universal prompt system"""
    
    print(f"[Universal-Prompt] Building adaptive prompt for {subject}")
    print(f"[Universal-Prompt] Blueprint structure: {list(blueprint.keys())}")
    
    # Check if this is a complex blueprint (has sections with subsections) or simple blueprint
    is_complex_blueprint = False
    for section_key, section_data in blueprint.items():
        if isinstance(section_data, dict) and 'subsections' in section_data:
            is_complex_blueprint = True
            break
    
    print(f"[Universal-Prompt] Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}")
    
    if is_complex_blueprint:
        # Use the complex blueprint directly as the schema
        blueprint_schema = json.dumps(blueprint, indent=2)
        sections_spec = "Follow the exact blueprint structure provided below."
    else:
        # Build sections specification from simple blueprint
        sections_spec = ""
        for section_data in blueprint.get('sections', []):
            section_name = section_data.get('name', '')
            section_title = section_data.get('title', '')
            section_marks = section_data.get('marks', 0)
            section_qtypes = section_data.get('question_types', [])
            
            sections_spec += f"""
Section {section_name} - {section_title} ({section_marks} marks):
Question Types: {', '.join(section_qtypes)}
"""
        blueprint_schema = json.dumps(blueprint, indent=2)
    
    # Get question type instructions
    question_type_instructions = get_question_type_instructions(question_types, subject)
    
    # Build the universal prompt
    prompt = f"""You are an expert question paper generator for CBSE {class_name} {subject} examinations.

CONTEXT MATERIAL:
{context_text}

EXAMINATION SPECIFICATIONS:
- Class: {class_name}
- Subject: {subject}
- Difficulty Level: {difficulty}
- Chapters to Cover: {', '.join(chapters) if chapters else 'All chapters'}

QUESTION PAPER STRUCTURE:
{sections_spec}

BLUEPRINT SCHEMA (Follow this exact structure):
{blueprint_schema}

QUESTION TYPE REQUIREMENTS:
{question_type_instructions}

GENERATION GUIDELINES:
1. Create questions that are appropriate for {class_name} level students
2. Ensure questions test understanding, application, and analysis
3. Use the provided context material as the primary source
4. Maintain consistency with CBSE examination patterns
5. Include a variety of question types as specified
6. Ensure proper mark distribution across sections
7. Make questions clear, unambiguous, and well-structured

DIFFICULTY LEVEL GUIDELINES:
- Easy: Basic recall and understanding questions
- Medium: Application and analysis questions  
- Hard: Complex analysis, synthesis, and evaluation questions

OUTPUT FORMAT:
Generate a complete question paper following the EXACT blueprint schema provided above.
Fill in all the empty fields (passage, questions, text, etc.) with appropriate content.
Ensure the JSON structure matches the blueprint schema exactly.

IMPORTANT: 
- Follow the EXACT blueprint schema structure provided
- Fill in all empty fields with appropriate content
- Ensure all questions are based on the provided context material
- Make sure the JSON is valid and complete
- Do not include any text outside the JSON structure"""

    print(f"[Universal-Prompt] Prompt length: {len(prompt)} characters")
    
    # Log prompt to summary file
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== UNIVERSAL PROMPT ===\n")
        f.write(f"Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}\n")
        f.write(f"Prompt length: {len(prompt)} characters\n")
        f.write(f"Question types: {question_types}\n")
        f.write(f"Context length: {len(context_text)} characters\n")
        f.write(f"{'='*50}\n\n")
    
    # Call Bedrock with the universal prompt
    try:
        response = call_bedrock(prompt, GEN_MODEL_ID, max_tokens=6000, temperature=0.7)
        print(f"[Universal-Prompt] ✅ Received response from Bedrock")
        
        # Validate and enforce JSON
        validated_json = enforce_json(response)
        paper_data = json.loads(validated_json)
        
        print(f"[Universal-Prompt] ✅ Successfully generated paper with {len(paper_data.get('sections', {}))} sections")
        
        # Log success to summary file
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"✅ Paper generated successfully\n")
            f.write(f"Sections: {list(paper_data.get('sections', {}).keys())}\n")
            f.write(f"Total marks: {paper_data.get('paper_info', {}).get('total_marks', 'N/A')}\n")
        
        return paper_data
        
    except Exception as e:
        error_msg = f"Universal prompt generation failed: {str(e)}"
        print(f"[Universal-Prompt] ❌ {error_msg}")
        
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"\n❌ ERROR: {error_msg}\n")
            f.write(f"Traceback: {traceback.format_exc()}\n")
        
        raise Exception(error_msg)

def generate_paper(class_name, subject, chapters, difficulty, pattern, section=None):
    """
    Main entry point for question paper generation.
    Now uses the universal generator by default, with fallback to legacy system.
    """
    print(f"[Generator] Starting paper generation for {class_name} {subject}")
    
    try:
        # Try universal generator first
        print(f"[Generator] Attempting universal generation...")
        return generate_universal_paper(class_name, subject, chapters, difficulty, pattern, section)
        
    except Exception as e:
        print(f"[Generator] ⚠️ Universal generation failed: {e}")
        print(f"[Generator] Falling back to legacy system...")
        
        # Fallback to legacy system
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_file = f"temp_generation_summary_{timestamp}.txt"
        
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(f"=== LEGACY QUESTION PAPER GENERATION ===\n")
            f.write(f"Timestamp: {datetime.now()}\n")
            f.write(f"Class: {class_name}\n")
            f.write(f"Subject: {subject}\n")
            f.write(f"Chapters: {', '.join(chapters) if chapters else 'All'}\n")
            f.write(f"Difficulty: {difficulty}\n")
            f.write(f"Pattern: {pattern.name}\n")
            f.write(f"Fallback reason: Universal generation failed - {e}\n")
            f.write(f"{'='*50}\n\n")
        
        print(f"[Generator] Using legacy system - Summary saved to: {summary_file}")
        
        blueprint = get_blueprint(class_name, subject, section)
        if subject.lower() in ["english", "english core"]:
            return generate_english_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file)
        else:
            return generate_science_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file)
