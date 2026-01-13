import os, re, json, random, time, traceback
import boto3
import hashlib
import numpy as np
from botocore.config import Config
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from django.conf import settings
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from . import embeddings
from .models import ExamBlueprint, BlueprintTemplate, GeneratedQuestion
from .blueprint_manager import BlueprintManager


# Ollama functionality removed

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
GEN_MODEL_ID = "amazon.nova-pro-v1:0"
VAL_MODEL_ID = "amazon.nova-lite-v1:0"



# ------------------------------
# Bedrock helper
# ------------------------------
def call_bedrock(
    prompt,
    model_ref,
    max_tokens=None,
    temperature=0.7,
    retries=5,
    model_source="aws",
):
    import json, time, random, re
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---------- Logging setup ----------
    model_name = model_ref.split("/")[-1] if "/" in model_ref else model_ref
    model_name = re.sub(r'[<>:"/\\|?*]', "_", model_name)

    prompt_file = f"temp_prompt_{model_name}_{timestamp}.txt"
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write("=== PROMPT SENT TO MODEL ===\n")
        f.write(f"Model: {model_ref}\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write(f"Max Tokens: {max_tokens if max_tokens else 'auto'}\n")
        f.write(f"Temperature: {temperature}\n")
        f.write("=" * 50 + "\n\n")
        f.write(prompt)

    print(f"[Log] Prompt saved to: {prompt_file}")
    print(f"[Bedrock-{model_name}] Sending prompt ({len(prompt)} chars)")

    # ---------- Model family detection (CRITICAL) ----------
    model_ref_clean = model_ref.strip().lower()

    is_nova = model_ref_clean.startswith("amazon.nova")
    is_claude = model_ref_clean.startswith("anthropic.")

    print(
        f"[Bedrock-Debug] model={model_ref_clean} "
        f"is_nova={is_nova} is_claude={is_claude}"
    )

    if not (is_nova or is_claude):
        raise ValueError(f"Unsupported Bedrock modelId: {model_ref}")

    # ---------- Token budget ----------
    default_max_tokens = 4096 if is_nova else 8192
    token_budget = max_tokens if max_tokens is not None else default_max_tokens

    # ---------- Payload construction ----------
    if is_nova:
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt
                        }
                    ],
                }
            ],
            "inferenceConfig": {
                "maxTokens": token_budget,
                "temperature": temperature,
                "topP": 0.9,
            },
        }


    else:  # Claude
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
            "max_tokens": token_budget,
            "temperature": temperature,
        }


    # ---------- Invoke with retries ----------
    input_tokens = 0
    output_tokens = 0

    for attempt in range(retries):
        try:
            resp = client.invoke_model(
                modelId=model_ref,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            result = json.loads(resp["body"].read())

            # ---------- Parse response ----------
            if is_nova:
                try:
                    text = result["output"]["message"]["content"][0]["text"]
                except (KeyError, IndexError, TypeError):
                    text = ""

                usage = result.get("usage", {})
                if not isinstance(usage, dict):
                    usage = {}
                input_tokens = usage.get(
                    "inputTokens",
                    usage.get("inputTokenCount", usage.get("input_token_count", 0)),
                )
                output_tokens = usage.get(
                    "outputTokens",
                    usage.get("outputTokenCount", usage.get("output_token_count", 0)),
                )

            else:  # Claude
                text = result["content"][0]["text"]
                input_tokens = result.get("usage", {}).get("input_tokens", 0)
                output_tokens = result.get("usage", {}).get("output_tokens", 0)

            # ---------- Save response ----------
            response_file = f"temp_response_{model_name}_{timestamp}.txt"
            with open(response_file, "w", encoding="utf-8") as f:
                f.write("=== MODEL RESPONSE ===\n")
                f.write(f"Model: {model_ref}\n")
                f.write(f"Timestamp: {datetime.now()}\n")
                f.write(f"Input Tokens: {input_tokens}\n")
                f.write(f"Output Tokens: {output_tokens}\n")
                f.write("=" * 50 + "\n\n")
                f.write(text)

            print(f"[Bedrock-{model_name}] ✅ Returned {len(text)} chars")
            print(f"[Bedrock-Log] Response saved to: {response_file}")

            return text.strip(), input_tokens, output_tokens

        except client.exceptions.ServiceUnavailableException:
            wait = (2 ** attempt) + random.random()
            print(f"[Bedrock-Throttle] retry {attempt+1}/{retries} in {wait:.1f}s")
            time.sleep(wait)

        except Exception as e:
            print(f"[Bedrock-Error] {type(e).__name__}: {e}")

            if attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                time.sleep(wait)
                continue

            with open("temp_error_prompt.txt", "w", encoding="utf-8") as f:
                f.write(f"Error: {e}\n\nPrompt:\n{prompt}")

            raise

    return "", 0, 0



# ------------------------------
# Fetch blueprint from DB
# ------------------------------
# DEPRECATED: Use BlueprintManager.normalize_blueprint instead
def convert_blueprint_to_dict(blueprint):
    """
    Convert blueprint from array format to dictionary format if needed.
    Input: {"sections": [{"name": "A", "title": "...", ...}]}
    Output: {"A": {"title": "...", ...}}
    """
    # Handle different blueprint formats
    if isinstance(blueprint, dict):
        if "sections" in blueprint:
            if isinstance(blueprint["sections"], list):
                # New blueprint format with sections array
                blueprint_dict = {}
                for section in blueprint["sections"]:
                    section_name = section.get("name", "")
                    blueprint_dict[section_name] = {
                        "title": section.get("title", ""),
                        "marks": section.get("marks", 0),
                        "question_types": section.get("question_types", []),
                        "subsections": section.get("subsections", {})  # Preserve subsections if they exist
                    }
                return blueprint_dict
            elif isinstance(blueprint["sections"], dict):
                # Old format where sections is a dict - just use it directly
                return blueprint["sections"]
            else:
                # sections key exists but is neither list nor dict
                print(f"[Blueprint-Convert] WARNING: 'sections' is neither list nor dict: {type(blueprint['sections'])}")
                return {}
        else:
            # No sections key - assume it's already in the right format
            # Check if it looks like a proper blueprint dict (has section keys like A, B, C)
            if any(key in ['A', 'B', 'C', 'D', 'E'] for key in blueprint.keys()):
                return blueprint
            else:
                print(f"[Blueprint-Convert] WARNING: Blueprint dict doesn't have expected structure")
                return blueprint
    elif isinstance(blueprint, list):
        # If blueprint is a list, try to convert it
        print(f"[Blueprint-Convert] WARNING: Blueprint is a list, attempting conversion")
        blueprint_dict = {}
        for idx, section in enumerate(blueprint):
            if isinstance(section, dict) and "name" in section:
                section_name = section.get("name", f"Section_{idx}")
                blueprint_dict[section_name] = {
                    "title": section.get("title", ""),
                    "marks": section.get("marks", 0),
                    "question_types": section.get("question_types", []),
                    "subsections": section.get("subsections", {})
                }
        return blueprint_dict if blueprint_dict else {}
    else:
        # Unknown format
        print(f"[Blueprint-Convert] ERROR: Blueprint is neither dict nor list: {type(blueprint)}")
        return {}

def get_blueprint(class_name, subject, section=None):
    """
    Get blueprint using the centralized BlueprintManager.
    This function is kept for backward compatibility but delegates to BlueprintManager.
    """
    return BlueprintManager.get_blueprint(class_name, subject, section)

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
def get_universal_context(class_name, subject, chapters, question_types=None, variation_offset=0):
    """
    Universal context retrieval system that works for all subjects and question types.
    Uses variation_offset to retrieve different context chunks each time for more variation.
    
    Args:
        class_name: Class (e.g., "11", "12")
        subject: Subject name (e.g., "English", "Biology")
        chapters: List of chapters to include
        question_types: List of question types to optimize context for
        variation_offset: Offset to vary context retrieval (default: random)
    
    Returns:
        dict: Context information with documents and metadata
    """
    print(f"[Context] Retrieving universal context for {class_name} {subject}")
    print(f"[Context] Chapters: {chapters}")
    print(f"[Context] Question types: {question_types}")
    
    # Use variation offset to get different context chunks
    if variation_offset == 0:
        variation_offset = random.randint(0, 10)  # Random offset for variation
    print(f"[Variation] Using context variation offset: {variation_offset}")
    
    all_contexts = []
    context_metadata = {
        "total_chapters": len(chapters),
        "question_types": question_types or [],
        "retrieval_timestamp": datetime.now().isoformat(),
        "variation_offset": variation_offset
    }
    
    # Build optimized queries based on question types - add variation to queries
    base_queries = [f"{subject} important NCERT concepts"]
    
    # Add variation to queries to get different context
    variation_terms = ["detailed", "examples", "applications", "concepts", "principles", "theories", "practical"]
    variation_term = random.choice(variation_terms)
    base_queries.append(f"{subject} {variation_term} NCERT content")
    
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
    # Shuffle queries for variation
    random.shuffle(unique_queries)
    print(f"[Context] Using queries: {unique_queries}")
    
    # Retrieve context for each chapter and query combination
    for chapter in chapters:
        chapter_contexts = []
        
        for query in unique_queries:
            try:
                # Vary n_results slightly for variation
                n_results = 50 + variation_offset % 10
                results = embeddings.query(
                    class_name=class_name, 
                    subject=subject, 
                    unit=chapter,
                    query_text=query, 
                    n_results=n_results
                )
                
                if results and "documents" in results:
                    for docs in results["documents"]:
                        chapter_contexts.extend(docs)
                        
            except Exception as e:
                print(f"[Context] ⚠️ Error retrieving context for {chapter} with query '{query}': {e}")
                continue
        
        # Deduplicate and limit chapter contexts - use offset to vary selection
        chapter_contexts = list(dict.fromkeys(chapter_contexts))  # Remove duplicates
        
        # Vary the context selection by using offset
        if len(chapter_contexts) > 100:
            # Start from different position based on offset
            start_idx = variation_offset % min(50, len(chapter_contexts) - 100)
            chapter_contexts = chapter_contexts[start_idx:start_idx+100]
        else:
            chapter_contexts = chapter_contexts[:100]
        
        all_contexts.extend(chapter_contexts)
        print(f"[Context] Retrieved {len(chapter_contexts)} contexts for chapter {chapter}")
    
    # Final deduplication and limiting - shuffle for more variation
    all_contexts = list(dict.fromkeys(all_contexts))  # Remove duplicates
    random.shuffle(all_contexts)  # Shuffle for variation
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

# ------------------------------
# Question Variation Helpers
# ------------------------------

def get_variation_temperature():
    """Get a slightly varied temperature between 0.75 and 0.85 for more variation"""
    return round(random.uniform(0.75, 0.85), 2)

def calculate_question_hash(question_text):
    """Calculate SHA256 hash of question text for quick duplicate detection"""
    cleaned = re.sub(r'\s+', ' ', question_text.strip().lower())
    return hashlib.sha256(cleaned.encode('utf-8')).hexdigest()

def check_question_similarity(new_question, class_name, subject, chapters, similarity_threshold=0.85):
    """
    Check if a question is too similar to previously generated questions.
    Uses both hash-based exact matching and embedding-based similarity.
    """
    # First, check for exact duplicates using hash
    question_hash = calculate_question_hash(new_question)
    existing_hash = GeneratedQuestion.objects.filter(
        class_name=class_name,
        subject=subject,
        question_hash=question_hash
    ).first()
    
    if existing_hash:
        print(f"[Variation] Exact duplicate detected: {new_question[:50]}...")
        return True, 1.0
    
    # Check for similar questions using embeddings
    try:
        # Get embeddings for the new question
        new_embedding_result = embeddings.query(
            class_name=class_name,
            subject=subject,
            unit="",
            query_text=new_question,
            n_results=1
        )
        
        if new_embedding_result and "embeddings" in new_embedding_result:
            new_embedding = new_embedding_result["embeddings"][0] if new_embedding_result["embeddings"] else None
        else:
            # Fallback: use simple text similarity
            return check_text_similarity(new_question, class_name, subject, chapters), None
        
        if not new_embedding:
            return False, 0.0
        
        # Compare with existing questions
        existing_questions = GeneratedQuestion.objects.filter(
            class_name=class_name,
            subject=subject,
            embedding__isnull=False
        )[:100]  # Limit to recent 100 for performance
        
        for existing in existing_questions:
            if existing.embedding:
                try:
                    # Calculate cosine similarity
                    similarity = cosine_similarity(new_embedding, existing.embedding)
                    if similarity >= similarity_threshold:
                        print(f"[Variation] Similar question detected (similarity: {similarity:.2f}): {new_question[:50]}...")
                        return True, similarity
                except Exception as e:
                    print(f"[Variation] Error calculating similarity: {e}")
                    continue
    except Exception as e:
        print(f"[Variation] Error in similarity check: {e}")
        # Fallback to text-based similarity
        return check_text_similarity(new_question, class_name, subject, chapters), None
    
    return False, 0.0

def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity between two vectors"""
    try:
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
    except Exception as e:
        print(f"[Variation] Error in cosine similarity calculation: {e}")
        return 0.0

def check_text_similarity(new_question, class_name, subject, chapters):
    """Fallback text-based similarity check"""
    # Simple word overlap check
    new_words = set(re.findall(r'\w+', new_question.lower()))
    
    existing_questions = GeneratedQuestion.objects.filter(
        class_name=class_name,
        subject=subject
    ).values_list('question_text', flat=True)[:50]
    
    for existing_text in existing_questions:
        existing_words = set(re.findall(r'\w+', existing_text.lower()))
        if len(new_words) > 0:
            overlap = len(new_words & existing_words) / len(new_words)
            if overlap > 0.7:  # 70% word overlap
                return True
    
    return False

def save_generated_question(question_text, class_name, subject, chapter, question_type, marks, paper_id=None):
    """Save a generated question to track it and avoid duplicates"""
    try:
        question_hash = calculate_question_hash(question_text)
        
        # Get embedding if possible
        embedding = None
        try:
            embedding_result = embeddings.query(
                class_name=class_name,
                subject=subject,
                unit=chapter or "",
                query_text=question_text,
                n_results=1
            )
            if embedding_result and "embeddings" in embedding_result:
                embedding = embedding_result["embeddings"][0] if embedding_result["embeddings"] else None
        except Exception as e:
            print(f"[Variation] Could not get embedding for question: {e}")
        
        GeneratedQuestion.objects.create(
            class_name=class_name,
            subject=subject,
            chapter=chapter,
            question_text=question_text,
            question_hash=question_hash,
            embedding=embedding,
            question_type=question_type or "",
            marks=marks,
            paper_id=paper_id
        )
    except Exception as e:
        print(f"[Variation] Error saving generated question: {e}")

def get_variation_instructions():
    """Get instructions to ensure question variation"""
    variation_hints = [
        "Generate questions from different angles and perspectives",
        "Use different examples and scenarios than typical questions",
        "Focus on different aspects of the topic",
        "Vary the complexity and approach",
        "Create unique questions that haven't been seen before",
        "Use creative problem-solving approaches",
        "Avoid repeating common question patterns",
        "Generate fresh, original questions each time"
    ]
    return random.sample(variation_hints, 3)  # Return 3 random hints

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
def render_section_questions(all_questions, data, blueprint, class_name=None, subject=None, chapters=None, paper_id=None):
    q_counter = 1
    
    print("=" * 50)
    print("RENDER_SECTION_QUESTIONS CALLED!")
    print("=" * 50)
    print(f"[DEBUG] Starting render_section_questions")
    print(f"[DEBUG] Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
    print(f"[DEBUG] Blueprint type: {type(blueprint)}")
    print(f"[DEBUG] Blueprint keys: {list(blueprint.keys()) if isinstance(blueprint, dict) else 'Not a dict'}")
    print(f"[DEBUG] Blueprint content preview: {str(blueprint)[:200]}")

    # Blueprint is already normalized by BlueprintManager.get_blueprint()
    # No conversion needed here
    print(f"[DEBUG] Blueprint is already normalized, keys: {list(blueprint.keys())}")
    
    # Handle the new JSON structure where sections are at the top level
    if "sections" in data:
        sections_data = data["sections"]
        print(f"[DEBUG] sections_data type: {type(sections_data)}")
        print(f"[DEBUG] sections_data is list: {isinstance(sections_data, list)}")

        # Check if sections_data is a list (array) or dict
        if isinstance(sections_data, list):
            print(f"[DEBUG] sections_data is a list with {len(sections_data)} items")
            # Convert list to dict using section names
            sections_dict = {}
            for section in sections_data:
                if isinstance(section, dict) and "name" in section:
                    sections_dict[section["name"]] = section
                else:
                    print(f"[DEBUG] WARNING: Section item is not dict with name: {section}")
            sections_data = sections_dict
            print(f"[DEBUG] Converted sections data from list to dict: {list(sections_data.keys())}")
        else:
            print(f"[DEBUG] sections_data is not a list, it's: {type(sections_data)}")
        print(f"[DEBUG] Using old structure with sections key")
    else:
        # New structure: {"A": {"title": "...", "subsections": {...}}}
        sections_data = data
        print(f"[DEBUG] Using new structure, sections_data keys: {list(sections_data.keys()) if isinstance(sections_data, dict) else 'Not a dict'}")
    
    
    for sec, sec_info in blueprint.items():
        # Debug check
        if not isinstance(sec_info, dict):
            print(f"[DEBUG] ERROR: Section {sec} info is not a dict: {type(sec_info)}")
            print(f"[DEBUG] Section info: {sec_info}")
            raise ValueError(f"Section {sec} has invalid format")

        print(f"[DEBUG] Processing section {sec}: {sec_info.get('title', 'NO TITLE')}")
        title = sec_info.get('title', 'Section')
        marks = sec_info.get('marks', 0)
        all_questions.append(("header", f"SECTION – {sec} {title.upper()} ({marks} MARKS)"))
        
        # Get section data - handle both old and new structures
        # Try exact match first
        section_key = None
        
        # First, try exact match
        if sec in sections_data:
            section_key = sec
            print(f"[DEBUG] Exact match found for '{sec}'")
        else:
            print(f"[DEBUG] Looking for section key '{sec}' in sections_data keys: {list(sections_data.keys())}")
            
            # Get section title for better matching
            section_title = sec_info.get('title', '').lower()
            section_question_types = sec_info.get('question_types', [])
            print(f"[DEBUG] Section '{sec}' not found. Title: '{section_title}', Question types: {section_question_types}")
            print(f"[DEBUG] Available JSON keys: {list(sections_data.keys())}")
            
            # Extract blueprint section name parts for matching
            sec_lower = sec.lower()
            
            # Try multiple matching strategies in order of preference
            # First, try keyword/content matching before letter matching
            sec_lower = sec.lower()
            
            # Strategy 1: Match by shared keywords in section names (highest priority)
            # Use specific keywords ordered by specificity
            keywords = ['case based', 'case study', 'multiple choice', 'very short answer', 'short answer', 'long answer', 'reading comprehension', 'reading', 'writing', 'grammar', 'literature']
            for keyword in keywords:
                if keyword in sec_lower:
                    # Blueprint section contains this keyword, find JSON section with SAME keyword
                    for key in sections_data.keys():
                        key_lower = key.lower()
                        # BOTH must contain the same keyword for a match
                        if keyword in key_lower:
                            # Extra validation: make sure it's not a substring match of a different section type
                            # e.g., "short answer" shouldn't match "very short answer"
                            if keyword == 'short answer' and 'very short' in key_lower:
                                continue  # Skip this, it's a different type
                            section_key = key
                            print(f"[DEBUG] Matched section {sec} to JSON key: {section_key} (by shared keyword: '{keyword}')")
                            break
                    if section_key != sec:
                        break
            
            # Strategy 2: Match by section title (e.g., "Case Based Questions")
            if section_key == sec and section_title:
                for key in sections_data.keys():
                    key_lower = key.lower()
                    if section_title in key_lower:
                        section_key = key
                        print(f"[DEBUG] Matched section {sec} ({section_title}) to JSON key: {section_key} (by title)")
                        break
            
            # Strategy 3: Match by overlapping question types
            if section_key == sec and section_question_types:
                for key in sections_data.keys():
                    key_data = sections_data[key]
                    if isinstance(key_data, dict):
                        json_qtypes = key_data.get('question_types', [])
                        if json_qtypes:
                            # Check if any question types overlap
                            json_qtypes_lower = [str(qt).lower() for qt in json_qtypes]
                            sec_qtypes_lower = [str(qt).lower() for qt in section_question_types]
                            overlap = [qt for qt in sec_qtypes_lower if qt in json_qtypes_lower]
                            if overlap:
                                section_key = key
                                print(f"[DEBUG] Matched section {sec} to JSON key: {section_key} (by overlapping question types: {overlap})")
                                break
            
            # Strategy 4: Match by section letter ONLY if content also matches
            # This prevents wrong matches like "Section D - Case Based" with "Section D - Long Answer"
            if section_key == sec:
                import re
                match = re.search(r'section\s+([a-z])', sec.lower())
                if match:
                    sec_letter = match.group(1).upper()
                    for key in sections_data.keys():
                        key_lower = key.lower()
                        # Check if JSON key has the same letter
                        key_match = re.search(r'section\s+([a-z])', key_lower)
                        if key_match:
                            key_letter = key_match.group(1).upper()
                            if sec_letter == key_letter:
                                # Also verify content similarity before matching
                                # Check if they share at least one keyword beyond the letter
                                shared_keywords = ['case', 'multiple', 'very', 'short', 'long', 'reading', 'writing', 'grammar', 'literature']
                                content_matches = any(kw in sec_lower and kw in key_lower for kw in shared_keywords)
                                if content_matches:
                                    section_key = key
                                    print(f"[DEBUG] Matched section {sec} (letter {sec_letter}) to JSON key: {section_key} (by letter with content validation)")
                                    break
        
        if section_key in sections_data:
            section_data = sections_data[section_key]
            print(f"[DEBUG] Found section data for {sec}, keys: {list(section_data.keys()) if isinstance(section_data, dict) else 'Not a dict'}")
            
            # Check if it's the new structure with subsections
            if "subsections" in section_data:
                subsections = section_data["subsections"]
                print(f"[DEBUG] Processing subsections for {sec}, type: {type(subsections)}")

                # Handle both list and dict formats for subsections
                if isinstance(subsections, dict):
                    # Dictionary format: {"reading": [...], "grammar": [...]}
                    for sub, q_list in subsections.items():
                        if not isinstance(q_list, list):
                            print(f"[DEBUG] WARNING: Subsection {sub} q_list is not a list: {type(q_list)}")
                            continue
                        print(f"[DEBUG] Processing subsection {sub} with {len(q_list)} questions")
                        for q in q_list:
                            if isinstance(q, dict):
                                print(f"[DEBUG] Processing question: {q.get('qnum', 'no qnum')} - {q.get('type', 'no type')}")
                                q_counter = process_question(all_questions, q, q_counter, class_name, subject, chapters, paper_id)
                            else:
                                print(f"[DEBUG] WARNING: Question in subsection {sub} is not a dict: {type(q)}")
                                all_questions.append(("q", f"{q_counter}. {str(q)}"))
                                q_counter += 1
                elif isinstance(subsections, list):
                    # List format: list of subsection objects
                    print(f"[DEBUG] Subsections is a list with {len(subsections)} items")
                    for subsection in subsections:
                        if not isinstance(subsection, dict):
                            print(f"[DEBUG] WARNING: Subsection is not a dict: {type(subsection)}")
                            continue
                        
                        # Handle subsection with passage/extract
                        subsection_name = subsection.get('name', 'Subsection')
                        print(f"[DEBUG] Processing subsection: {subsection_name}")
                        
                        # Add subsection instruction if present
                        if 'instructions' in subsection and subsection['instructions']:
                            instruction = subsection['instructions'][0] if isinstance(subsection['instructions'], list) else subsection['instructions']
                            all_questions.append(("instruction", instruction))
                        
                        # Handle passage/extract in subsection
                        if 'passage' in subsection:
                            passage_text = subsection.get('passage', '')
                            if passage_text:
                                all_questions.append(("instruction", "Read the passage:"))
                                all_questions.append(("passage", passage_text))
                                print(f"[DEBUG] Added passage for subsection {subsection_name}")

                        if 'extract' in subsection:
                            extract_text = subsection.get('extract', '')
                            if extract_text:
                                instruction_text = subsection.get('extract_instruction') or subsection.get('instruction')
                                all_questions.append(("instruction", instruction_text or "Read the extract:"))
                                all_questions.append(("passage", extract_text))
                                print(f"[DEBUG] Added extract for subsection {subsection_name}")
                        
                        # Handle picture_description in subsection
                        if 'picture_description' in subsection:
                            picture_desc = subsection.get('picture_description', '')
                            if picture_desc:
                                all_questions.append(("instruction", "Observe the picture:"))
                                # Check if it's a [Picture: ...] marker
                                if picture_desc.startswith('[Picture:') or picture_desc.startswith('[Picture '):
                                    all_questions.append(("q", picture_desc))  # Will be processed by materialize_images
                                else:
                                    all_questions.append(("instruction", picture_desc))
                        
                        # Handle questions in subsection
                        if 'questions' in subsection:
                            questions_list = subsection.get('questions', [])
                            if isinstance(questions_list, list):
                                print(f"[DEBUG] Processing {len(questions_list)} questions in subsection {subsection_name}")
                                for q in questions_list:
                                    if isinstance(q, dict):
                                        q_counter = process_question(all_questions, q, q_counter, class_name, subject, chapters, paper_id)
                                    else:
                                        print(f"[DEBUG] WARNING: Question in subsection is not a dict: {type(q)}")
                                        all_questions.append(("q", f"{q_counter}. {str(q)}"))
                                        q_counter += 1
                        else:
                            # If no questions key, treat the subsection itself as a question
                            print(f"[DEBUG] No questions key in subsection, treating as question")
                            q_counter = process_question(all_questions, subsection, q_counter, class_name, subject, chapters, paper_id)
                else:
                    print(f"[DEBUG] Unknown subsections format: {type(subsections)}")
            else:
                # Old structure - check if questions are in a 'questions' key or directly in section_data
                print(f"[DEBUG] Processing old structure for {sec}")
                
                # Handle sections with passages or extracts
                if isinstance(section_data, dict):
                    if 'passage' in section_data:
                        passage_text = section_data.get('passage', '')
                        if passage_text:
                            all_questions.append(("instruction", "Read the passage:"))
                            all_questions.append(("passage", passage_text))
                            print(f"[DEBUG] Added passage for section {sec}")

                    if 'extract' in section_data:
                        extract_text = section_data.get('extract', '')
                        if extract_text:
                            # Prefer instruction from section data if available
                            instruction_text = None
                            section_instructions = section_data.get('instructions')
                            if isinstance(section_instructions, list) and section_instructions:
                                instruction_text = section_instructions[0]
                            elif isinstance(section_instructions, str):
                                instruction_text = section_instructions
                            all_questions.append(("instruction", instruction_text or "Read the extract:"))
                            all_questions.append(("passage", extract_text))
                            print(f"[DEBUG] Added extract for section {sec}")
                
                # Handle both cases: questions in 'questions' key or section_data is directly a list
                if isinstance(section_data, dict) and 'questions' in section_data:
                    questions_list = section_data['questions']
                    print(f"[DEBUG] Found questions list with {len(questions_list) if isinstance(questions_list, list) else 'unknown'} items")
                    if isinstance(questions_list, list):
                        for q in questions_list:
                            if isinstance(q, dict):
                                q_counter = process_question(all_questions, q, q_counter, class_name, subject, chapters, paper_id)
                            else:
                                # Handle string questions
                                print(f"[DEBUG] Processing string question: {str(q)[:50]}...")
                                all_questions.append(("q", f"{q_counter}. {str(q)}"))
                                
                                # Save question if metadata available
                                if class_name and subject:
                                    try:
                                        chapter = chapters[0] if chapters else None
                                        save_generated_question(str(q), class_name, subject, chapter, "", 1, paper_id)
                                    except Exception as e:
                                        print(f"[Variation] Error saving question: {e}")
                                
                                q_counter += 1
                    else:
                        print(f"[DEBUG] WARNING: questions is not a list, it's {type(questions_list)}")
                elif isinstance(section_data, list):
                    # section_data is directly a list of questions
                    print(f"[DEBUG] section_data is directly a list with {len(section_data)} items")
                    for q in section_data:
                        if isinstance(q, dict):
                            q_counter = process_question(all_questions, q, q_counter, class_name, subject, chapters, paper_id)
                        else:
                            # Handle string questions
                            print(f"[DEBUG] Processing string question: {str(q)[:50]}...")
                            all_questions.append(("q", f"{q_counter}. {str(q)}"))
                            
                            # Save question if metadata available
                            if class_name and subject:
                                try:
                                    chapter = chapters[0] if chapters else None
                                    save_generated_question(str(q), class_name, subject, chapter, "", 1, paper_id)
                                except Exception as e:
                                    print(f"[Variation] Error saving question: {e}")
                            
                            q_counter += 1
                else:
                    print(f"[DEBUG] WARNING: section_data is neither dict with 'questions' key nor a list: {type(section_data)}")
                    print(f"[DEBUG] section_data content: {str(section_data)[:200]}")
        else:
            print(f"[DEBUG] No section data found for {sec}")
            all_questions.append(("q", f"No questions found for section {sec}"))
    
    print(f"[DEBUG] Total questions processed: {len(all_questions)}")
    return all_questions

def process_question(all_questions, q, q_counter, class_name=None, subject=None, chapters=None, paper_id=None):
    # Handle case where q might be a string instead of dict
    if not isinstance(q, dict):
        print(f"[DEBUG] WARNING: Question is not a dict, it's {type(q)}: {str(q)[:50]}...")
        question_text = str(q)
        all_questions.append(("q", f"{q_counter}. {question_text}"))
        
        # Save question if metadata available
        if class_name and subject:
            try:
                chapter = chapters[0] if chapters else None
                save_generated_question(question_text, class_name, subject, chapter, "", 1, paper_id)
            except Exception as e:
                print(f"[Variation] Error saving question: {e}")
        
        return q_counter + 1
    
    qnum = q.get("qnum", q_counter)
    print(f"[DEBUG] Processing question {qnum}, type: {q.get('type', 'no type')}, keys: {list(q.keys())}")

    # If it has an instruction field, treat it as an instruction (no number)
    if "instruction" in q and q.get("type") not in ["unseen_passage_or_case_based"]:
        all_questions.append(("instruction", q.get('instruction', '')))  # No number for instructions
        
        # Handle gap_filling type with text field
        if q.get("type") == "gap_filling" and "text" in q:
            text_content = q.get("text", "")
            if text_content:
                all_questions.append(("passage", text_content))
        
        # Handle reordering type with sentences array
        elif q.get("type") == "reordering" and "sentences" in q:
            sentences = q.get("sentences", [])
            if isinstance(sentences, list):
                for item in sentences:
                    all_questions.append(("subq", f"- {str(item)}"))
            else:
                print(f"[DEBUG] WARNING: sentences is not a list: {type(sentences)}")
        
        # Handle other types with items, sentences, phrases
        else:
            for k in ("items", "sentences", "phrases"):
                if k in q:
                    items = q.get(k, [])
                    if isinstance(items, list):
                        for item in items:
                            all_questions.append(("subq", f"- {str(item)}"))
                    else:
                        print(f"[DEBUG] WARNING: {k} is not a list: {type(items)}")
        return q_counter + 1

    elif "extract" in q:
        # Handle literature extracts with instruction
        if "instruction" in q:
            all_questions.append(("instruction", q.get('instruction', '')))  # No number for instructions
        else:
            all_questions.append(("instruction", "Read the extract:"))  # No number for instructions
        extract_text = q.get("extract", "")
        if extract_text:
            all_questions.append(("passage", extract_text))
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
        options = q.get('options', [])
        if not isinstance(options, list):
            print(f"[DEBUG] WARNING: options is not a list: {type(options)}")
            options = []
        print(f"[DEBUG] Processing unseen_passage_or_case_based with {len(options)} options")
        all_questions.append(("instruction", q.get('instruction', 'Read the following:')))  # No number for instructions
        for opt in options:
            if not isinstance(opt, dict):
                print(f"[DEBUG] WARNING: Option is not a dict: {type(opt)}")
                continue
            opt_questions = opt.get('questions', [])
            if not isinstance(opt_questions, list):
                opt_questions = []
            print(f"[DEBUG] Processing option: {opt.get('kind', 'unknown')} with {len(opt_questions)} questions")
            if 'passage' in opt:
                passage_text = opt.get('passage', '')
                if passage_text:
                    all_questions.append(("passage", f"[{opt.get('kind', '').replace('_',' ').title()}]\n{passage_text}"))
            for i, subq in enumerate(opt_questions, start=1):
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
        passage_text = q.get("passage", "")
        if passage_text:
            all_questions.append(("passage", passage_text))
        questions_list = q.get("questions", [])
        if not isinstance(questions_list, list):
            print(f"[DEBUG] WARNING: questions is not a list: {type(questions_list)}")
            questions_list = []
        for i, subq in enumerate(questions_list, start=1):
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
        passage_text = q.get("passage", "")
        if passage_text:
            all_questions.append(("passage", passage_text))

    # This case is now handled above

    elif "text" in q and not ("passage" in q or "extract" in q):
        # Handle questions that have only "text" field (new structure)
        text_content = q.get("text", "")
        options = q.get("options")
        
        # If options exist separately, strip inline options from question text
        if isinstance(options, list) and options and text_content:
            # Remove inline options patterns like (a) ... (b) ... etc.
            # Pattern to match everything from first option label onwards: (a) ... (b) ... (c) ... (d) ...
            # This removes all inline options that might be embedded in the question text
            inline_pattern = re.compile(r'\s*\([a-dA-D]\)\s*.*$', re.IGNORECASE)
            text_content = inline_pattern.sub('', text_content).strip()
            # Clean up any trailing whitespace
            text_content = text_content.strip()
        
        if text_content:
            all_questions.append(("q", f"{qnum}. {text_content}"))
            
            # Save question for tracking and deduplication
            if class_name and subject:
                try:
                    question_type = q.get("type", "")
                    marks = q.get("marks", 1)
                    chapter = chapters[0] if chapters else None
                    save_generated_question(text_content, class_name, subject, chapter, question_type, marks, paper_id)
                except Exception as e:
                    print(f"[Variation] Error saving question: {e}")
        
        # Render MCQ options if present as a block (for two-column layout later)
        if isinstance(options, list) and options:
            labeled = []
            for i, opt in enumerate(options, start=1):
                label = chr(64 + i)  # A, B, C, ...
                labeled.append(f"{label}) {str(opt).strip()}")
            all_questions.append(("opts_block", labeled))
        if 'image_prompt' in q:
            all_questions.append(('image_gen', q.get('image_prompt', '')))

    elif "question" in q and "or" in q:
        question_text = q.get("question", "")
        or_text = q.get("or", "")
        if question_text:
            all_questions.append(("q", f"{qnum}. {question_text}"))
        all_questions.append(("or", "OR"))
        if or_text:
            all_questions.append(("q", or_text))

    elif "question" in q:
        question_text = q.get("question", "")
        options = q.get("options")
        
        # If options exist separately, strip inline options from question text
        if isinstance(options, list) and options and question_text:
            # Remove inline options patterns like (a) ... (b) ... etc.
            # Pattern to match everything from first option label onwards
            inline_pattern = re.compile(r'\s*\([a-dA-D]\)\s*.*$', re.IGNORECASE)
            question_text = inline_pattern.sub('', question_text).strip()
            # Clean up any trailing whitespace
            question_text = question_text.strip()
        
        if question_text:
            all_questions.append(("q", f"{qnum}. {question_text}"))
        if 'image_prompt' in q:
            all_questions.append(('image_gen', q.get('image_prompt', '')))
        
        # Handle options for MCQ style
        if isinstance(options, list) and options:
            labeled = []
            for i, option in enumerate(options, start=1):
                label = chr(64 + i)
                labeled.append(f"{label}) {str(option).strip()}")
            all_questions.append(("opts_block", labeled))
        elif options and not isinstance(options, list):
            print(f"[DEBUG] WARNING: options is not a list: {type(options)}")

    return q_counter + 1


# ------------------------------
# Science/Maths generator
# ------------------------------
def generate_science_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file=None, model_source='aws'):
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
                name = section.get('name', 'Section')
                q_count = section.get('questions', section.get('questions_count', 0))
                marks_each = section.get('marks', 0)
                rules_text += f"- Section {name}: {q_count} questions ({marks_each} marks each)\n"
            elif isinstance(section, str):
                # If section is a string, use it as is
                rules_text += f"- {section}\n"
    else:
        # Handle both old format {'A': (count, marks)} and new format {'A': {'title': ..., 'marks': ...}}
        def get_section_info(sec_key):
            sec_data = blueprint.get(sec_key)
            if isinstance(sec_data, tuple) and len(sec_data) == 2:
                # Old format: (count, marks)
                return sec_data[0], sec_data[1]
            elif isinstance(sec_data, dict):
                # New format: {'title': ..., 'marks': ..., 'question_types': ...}
                # Try to get questions_count, or calculate from marks
                count = sec_data.get('questions_count', 0)
                marks = sec_data.get('marks', 0)
                if count == 0 and marks > 0:
                    # Estimate count from marks (assume 1 mark per question for MCQs)
                    marks_per_q = sec_data.get('marks_per_question', 1)
                    count = marks // marks_per_q if marks_per_q > 0 else marks
                return count, marks_per_q if marks_per_q > 0 else 1
            return 0, 1
        
        a_count, a_marks = get_section_info('A')
        b_count, b_marks = get_section_info('B')
        c_count, c_marks = get_section_info('C')
        d_count, d_marks = get_section_info('D')
        e_count, e_marks = get_section_info('E')
        
        rules_text = f"""- Section A: {a_count} MCQs ({a_marks} mark each), include Assertion–Reason.
- Section B: {b_count} VSA ({b_marks} marks).
- Section C: {c_count} SA ({c_marks} marks).
- Section D: {d_count} Case-based ({d_marks} marks).
- Section E: {e_count} Long with OR choice ({e_marks} marks)."""

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
    raw_json, _, _ = call_bedrock(gen_prompt, GEN_MODEL_ID, temperature=0.7)

    validator_prompt = f"""
You are a strict JSON validator.
Input will be JSON text. If it is already valid JSON, return unchanged.
If it is invalid, fix it but preserve all content.
Output only JSON.

{raw_json}
"""
    validated, _, _ = call_bedrock(validator_prompt, VAL_MODEL_ID, temperature=0.3)
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
    
    # Helper function to extract count and marks from blueprint section
    def get_section_info(sec_key):
        sec_data = blueprint.get(sec_key)
        if isinstance(sec_data, tuple) and len(sec_data) == 2:
            # Old format: (count, marks)
            return sec_data[0], sec_data[1]
        elif isinstance(sec_data, dict):
            # New format: {'title': ..., 'marks': ..., 'question_types': ...}
            count = sec_data.get('questions_count', 0)
            marks = sec_data.get('marks', 0)
            marks_per_q = sec_data.get('marks_per_question', 1)
            if count == 0 and marks > 0:
                # Estimate count from marks
                count = marks // marks_per_q if marks_per_q > 0 else marks
            return count, marks_per_q
        return 0, 1
    
    for sec in blueprint.keys():
        count, marks = get_section_info(sec)
        sec_data = data.get("sections", {}).get(sec, [])
        all_questions.append(("header", f"SECTION {sec} ({count} × {marks} = {count*marks})"))
        for i in range(count):
            if i < len(sec_data):
                q = sec_data[i]
                if not isinstance(q, dict):
                    print(f"[DEBUG] WARNING: Question is not a dict: {type(q)}")
                    continue
                if sec == "A":
                    text_content = q.get('text', '')
                    if text_content:
                        all_questions.append(("q", f"{q_counter}) {text_content}"))
                    options = q.get("options", [])
                    if isinstance(options, list):
                        for j, opt in enumerate(options):
                            opt_str = str(opt).strip() if opt else ""
                            if opt_str:
                                all_questions.append(("subq", f"   {chr(97+j)}) {opt_str}"))
                elif sec == "E":
                    question_text = q.get('question', '')
                    or_text = q.get('or', '')
                    if question_text:
                        all_questions.append(("q", f"{q_counter}) {question_text}"))
                    all_questions.append(("or", "OR"))
                    if or_text:
                        all_questions.append(("q", or_text))
                else:
                    text_content = q.get('text', '')
                    if text_content:
                        all_questions.append(("q", f"{q_counter}) {text_content}"))
            else:
                all_questions.append(("q", f"{q_counter}) [Placeholder]"))
            q_counter += 1
        summary[sec] = {"questions": count, "marks_each": marks}

    return render_docx(class_name, subject, chapters, all_questions, summary)


# ------------------------------
# English Core generator
# ------------------------------
def generate_english_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file=None, model_source='aws'):
    # Blueprint is already normalized by BlueprintManager.get_blueprint()
    print(f"[Blueprint] Blueprint structure (already normalized): {list(blueprint.keys()) if isinstance(blueprint, dict) else 'Not a dict'}")

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
                name = section.get('name', 'Section')
                q_count = section.get('questions', section.get('questions_count', 0))
                marks_each = section.get('marks', 0)
                rules_text += f"- Section {name}: {q_count} questions ({marks_each} marks each)\n"
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
    
    raw_json, _, _ = call_bedrock(gen_prompt, GEN_MODEL_ID, temperature=0.7)
    
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
    
    validated, _, _ = call_bedrock(validator_prompt, VAL_MODEL_ID, temperature=0.3)
    
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
        all_questions = render_section_questions([], direct_data, blueprint, class_name, subject, chapters, None)
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
        all_questions = render_section_questions([], data, blueprint, class_name, subject, chapters, None)
    
    summary = {sec: {"title": sec_info["title"], "marks": sec_info["marks"]}
               for sec, sec_info in blueprint.items()}
    return render_docx(class_name, subject, chapters, all_questions, summary)


# ------------------------------
# PDF renderer
# ------------------------------
def render_pdf(class_name, subject, chapters, all_questions, summary):
    writer = PdfWriter()
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    y = 650  # Much more space from header to avoid clash

    # Draw header fields onto the first page using provided coordinates
    try:
        page_width, page_height = A4

        def flip_y(y_top, height):
            return page_height - y_top - height

        can.setFont("Helvetica", 11)

        # Coordinates spec as provided by user
        coords = {
            "TESTTYPE": {"x": 253, "y": 86, "w": 190, "h": 14},
            "class": {"x": 128, "y": 109, "w": 285, "h": 19},
            "subject": {"x": 259, "y": 102, "w": 174, "h": 17},
            "time": {"x": 506, "y": 107, "w": 40, "h": 22},
            "marks": {"x": 506, "y": 131, "w": 45, "h": 14},
        }

        # Expand test type like PT-2 -> Periodic Test - 2
        def expand_test_type(pattern_name: str) -> str:
            if not pattern_name:
                return ""
            name = pattern_name.strip()
            import re
            m = re.match(r"(?i)\s*pt\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Periodic Test - {m.group(1)}"
            m = re.match(r"(?i)\s*fa\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Formative Assessment - {m.group(1)}"
            m = re.match(r"(?i)\s*sa\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Summative Assessment - {m.group(1)}"
            return name

        # Pull extra metadata if passed via additional_context (stored earlier in global tmp during generation)
        # Fallbacks will be provided by caller through summary if needed; we use globals set by universal path
        header_meta = globals().get("__HEADER_META__", {})

        test_type_val = expand_test_type(header_meta.get("test_type", header_meta.get("pattern_name", "")))
        class_val = header_meta.get("class_name", class_name)
        subject_val = header_meta.get("subject", subject)
        time_val = str(header_meta.get("duration", ""))
        marks_val = str(header_meta.get("marks", ""))

        # Draw each value if present
        def draw_in_rect(key, value):
            if not value:
                return
            r = coords[key]
            x = r["x"] + 2
            ty = flip_y(r["y"], r["h"]) + (r["h"] / 3)
            can.drawString(x, ty, str(value))

        draw_in_rect("TESTTYPE", test_type_val)
        draw_in_rect("class", class_val)
        draw_in_rect("subject", subject_val)
        draw_in_rect("time", time_val)
        draw_in_rect("marks", marks_val)

    except Exception as e:
        print(f"[PDF-Header] WARNING: Failed to render header fields: {e}")

    if not all_questions:
        all_questions = [("header", "NO QUESTIONS GENERATED"),
                         ("q", "Check blueprint or JSON parsing")]

    print("[PDF-Render] DEBUG all_questions sample:")
    for i, (typ, text) in enumerate(all_questions[:15]):
        if typ == "passage":
            print(f"  {i}. ({typ}): {text[:70]}... [{len(text)} chars]")
        else:
            print(f"  {i}. ({typ}): {text[:80] if len(text) > 80 else text}")

    for typ, text in all_questions:
        print(f"[PDF-Render-Loop] Processing: typ={typ}, y={y}, text_len={len(str(text))}")
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
            print(f"[PDF-Render] Rendering passage: {len(text)} chars, y={y}")
            can.setFont("Helvetica-Oblique", 10)
            y = draw_wrapped(can, text, 60, y, 470, size=10, line_height=14)
            print(f"[PDF-Render] After passage, y={y}")
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
            q_count = info.get('questions', info.get('questions_count', 0))
            line = f"Section {sec}: {q_count} questions | Marks each: {info.get('marks_each', 0)}"
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
# DOCX renderer (default)
# ------------------------------
TAMIL_DEFAULT_FONT = 'Latha'


def set_tamil_font(run, font_name: str = TAMIL_DEFAULT_FONT):
    """Set Tamil-compatible font for a text run"""
    if run is None:
        return
    
    tamil_font = font_name or TAMIL_DEFAULT_FONT
    
    run.font.name = tamil_font
    
    r = run._element
    rPr = r.get_or_add_rPr()
    
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.append(rFonts)
    
    for attr in ['ascii', 'hAnsi', 'cs', 'eastAsia']:
        rFonts.set(qn(f'w:{attr}'), tamil_font)


def has_tamil_text(text):
    """Check if text contains Tamil characters"""
    if not isinstance(text, str):
        return False
    return any('\u0B80' <= char <= '\u0BFF' for char in text)


def clear_paragraph(paragraph):
    """Remove all runs from a paragraph."""
    if paragraph is None:
        return
    p = paragraph._element
    for child in list(p):
        p.remove(child)


def apply_tamil_document_styles(doc: Document, font_name: str = TAMIL_DEFAULT_FONT):
    """Ensure common styles use a Tamil-compatible font."""
    if doc is None:
        return
    
    style_names = [
        'Normal', 'Heading 1', 'Heading 2', 'Heading 3',
        'List Bullet', 'List Number', 'Table Grid',
        'Title', 'Subtitle', 'Default Paragraph Font'
    ]
    
    for style_name in style_names:
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        
        style.font.name = font_name
        
        try:
            rPr = style._element.get_or_add_rPr()
        except AttributeError:
            rPr = getattr(style._element, 'rPr', None)
            if rPr is None:
                rPr = OxmlElement('w:rPr')
                style._element.append(rPr)
        
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.append(rFonts)
        
        for attr in ['ascii', 'hAnsi', 'cs', 'eastAsia']:
            rFonts.set(qn(f'w:{attr}'), font_name)


def render_docx(class_name, subject, chapters, all_questions, summary):
    # Create a fresh document (don't use base.docx)
    doc = Document()
    
    # Check if subject is Tamil or if any questions contain Tamil text
    is_tamil = subject.lower() in ['tamil', 'தமிழ்']
    if not is_tamil:
        # Check if any question text contains Tamil
        for typ, text in all_questions:
            if has_tamil_text(text):
                is_tamil = True
                break
    
    if is_tamil:
        print(f"[DOCX-Tamil] Tamil text detected - applying Tamil-compatible fonts")
        apply_tamil_document_styles(doc, TAMIL_DEFAULT_FONT)
    
    # Set document margins
    section = doc.sections[0]
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

    # Get header metadata
    try:
        header_meta = globals().get("__HEADER_META__", {})
        print(f"[DOCX-Header] Retrieved header_meta: {header_meta}")
        print(f"[DOCX-Header] class_name param: {class_name}, subject param: {subject}")

        # Expand test type like PT-2 -> Periodic Test - 2
        def expand_test_type(pattern_name: str) -> str:
            if not pattern_name:
                return ""
            name = pattern_name.strip()
            import re
            m = re.match(r"(?i)\s*pt\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Periodic Test - {m.group(1)}"
            m = re.match(r"(?i)\s*fa\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Formative Assessment - {m.group(1)}"
            m = re.match(r"(?i)\s*sa\s*[- ]?\s*(\d+)", name)
            if m:
                return f"Summative Assessment - {m.group(1)}"
            return name

        test_type_val = expand_test_type(header_meta.get("test_type", header_meta.get("pattern_name", "")))
        class_val = header_meta.get("class_name", class_name) or class_name
        subject_val = header_meta.get("subject", subject) or subject
        time_val = str(header_meta.get("duration", "")).strip()
        marks_val = str(header_meta.get("marks", "")).strip()
        
        print(f"[DOCX-Header] Final values - class: '{class_val}', subject: '{subject_val}', time: '{time_val}', marks: '{marks_val}', test_type: '{test_type_val}'")

        # Create header in the document body (appears only once at the top, not on every page)
        # Ensure no header/footer is set to repeat
        section = doc.sections[0]
        section.header_distance = Inches(0)
        section.footer_distance = Inches(0)
        # Clear any existing header/footer content
        header = section.header
        for paragraph in header.paragraphs:
            p = paragraph._element
            p.getparent().remove(p)
        for table in header.tables:
            t = table._element
            t.getparent().remove(t)
        
        # Create bordered header table in the document body (not in header section)
        # This will appear only once at the top of the document
        header_table = doc.add_table(rows=2, cols=1)
        header_table.autofit = False
        header_table.allow_autofit = False
        header_table.style = 'Normal Table'
        
        # Set table borders
        for row in header_table.rows:
            for cell in row.cells:
                # Set cell borders
                tcPr = cell._element.get_or_add_tcPr()
                tcBorders = OxmlElement('w:tcBorders')
                
                for border_name in ['top', 'left', 'bottom', 'right']:
                    border = OxmlElement(f'w:{border_name}')
                    border.set(qn('w:val'), 'single')
                    border.set(qn('w:sz'), '12')
                    border.set(qn('w:color'), '000000')
                    tcBorders.append(border)
                
                tcPr.append(tcBorders)
        
        # First row - School name, Subject, Test Type
        school_cell = header_table.rows[0].cells[0]
        
        # School name - centered, bold
        school_para = school_cell.paragraphs[0]
        school_run = school_para.add_run('RAMCO VIDYA   MANDIR  SR. SEC. SCHOOL, THAMARAIKULAM')
        school_run.bold = True
        school_run.font.size = Pt(12)
        if is_tamil:
            set_tamil_font(school_run)
        school_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        school_para.space_after = Pt(2)
        school_para.space_before = Pt(4)
        
        # Subject line - centered
        if subject_val:
            subject_para = school_cell.add_paragraph()
            subject_run = subject_para.add_run(f'Subject: {subject_val}')
            subject_run.font.size = Pt(10)
            if is_tamil:
                set_tamil_font(subject_run)
            subject_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            subject_para.space_after = Pt(2)
            subject_para.space_before = Pt(0)
        
        # Test type line - centered, bold
        if test_type_val:
            testtype_para = school_cell.add_paragraph()
            testtype_run = testtype_para.add_run(test_type_val)
            testtype_run.bold = True
            testtype_run.font.size = Pt(11)
            if is_tamil:
                set_tamil_font(testtype_run)
            testtype_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            testtype_para.space_after = Pt(4)
            testtype_para.space_before = Pt(0)
        
        # Second row - CLASS, EXAM NO, TIME, MARKS
        info_cell = header_table.rows[1].cells[0]
        
        # Create nested table for CLASS/EXAM NO and TIME/MARKS
        info_table = info_cell.add_table(rows=2, cols=2)
        info_table.autofit = False
        
        # Remove borders from nested table
        for row in info_table.rows:
            for cell in row.cells:
                tcPr = cell._element.get_or_add_tcPr()
                tcBorders = OxmlElement('w:tcBorders')
                for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
                    border = OxmlElement(f'w:{border_name}')
                    border.set(qn('w:val'), 'none')
                    tcBorders.append(border)
                tcPr.append(tcBorders)
        
        # Set column widths
        info_table.columns[0].width = Inches(3.25)
        info_table.columns[1].width = Inches(3.25)
        
        # Row 1: CLASS and TIME
        class_cell_table = info_table.rows[0].cells[0]
        class_para_table = class_cell_table.paragraphs[0]
        clear_paragraph(class_para_table)  # Clear any default text
        class_text = f'CLASS       :  {class_val}' if class_val else 'CLASS       :'
        class_run = class_para_table.add_run(class_text)
        if is_tamil:
            set_tamil_font(class_run)
        class_para_table.space_after = Pt(0)
        class_para_table.space_before = Pt(2)
        print(f"[DOCX-Header] Set CLASS text: '{class_text}'")
        
        time_cell_table = info_table.rows[0].cells[1]
        time_para_table = time_cell_table.paragraphs[0]
        clear_paragraph(time_para_table)  # Clear any default text
        time_text = f'TIME        :  {time_val}' if time_val else 'TIME        :'
        time_run = time_para_table.add_run(time_text)
        if is_tamil:
            set_tamil_font(time_run)
        time_para_table.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        time_para_table.space_after = Pt(0)
        time_para_table.space_before = Pt(2)
        print(f"[DOCX-Header] Set TIME text: '{time_text}'")
        
        # Row 2: EXAM NO and MARKS
        exam_cell_table = info_table.rows[1].cells[0]
        exam_para_table = exam_cell_table.paragraphs[0]
        clear_paragraph(exam_para_table)  # Clear any default text
        exam_run = exam_para_table.add_run('EXAM NO  :')
        if is_tamil:
            set_tamil_font(exam_run)
        exam_para_table.space_after = Pt(2)
        exam_para_table.space_before = Pt(0)
        
        marks_cell_table = info_table.rows[1].cells[1]
        marks_para_table = marks_cell_table.paragraphs[0]
        clear_paragraph(marks_para_table)  # Clear any default text
        marks_text = f'MARKS    :  {marks_val}' if marks_val else 'MARKS    :'
        marks_run = marks_para_table.add_run(marks_text)
        if is_tamil:
            set_tamil_font(marks_run)
        marks_para_table.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        marks_para_table.space_after = Pt(2)
        marks_para_table.space_before = Pt(0)
        print(f"[DOCX-Header] Set MARKS text: '{marks_text}'")
        
        # Add a paragraph break after header to ensure it's separate from content
        doc.add_paragraph("")
        
        print(f"[DOCX-Header] Header table created successfully in document body (will appear only once)")
        
    except Exception as e:
        print(f"[DOCX-Header] WARNING: Failed to create header: {e}")
        
        # Fallback: simple text header if table creation fails
        try:
            # School name
            school_para = doc.add_paragraph()
            school_run = school_para.add_run('RAMCO VIDYA MANDIR SR. SEC. SCHOOL, THAMARAIKULAM')
            school_run.bold = True
            school_run.font.size = Pt(12)
            if is_tamil:
                set_tamil_font(school_run)
            school_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Subject
            if subject_val:
                subject_para = doc.add_paragraph()
                subject_run = subject_para.add_run(f'Subject: {subject_val}')
                subject_run.font.size = Pt(10)
                if is_tamil:
                    set_tamil_font(subject_run)
                subject_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Test type
            if test_type_val:
                testtype_para = doc.add_paragraph()
                testtype_run = testtype_para.add_run(test_type_val)
                testtype_run.bold = True
                testtype_run.font.size = Pt(11)
                if is_tamil:
                    set_tamil_font(testtype_run)
                testtype_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # CLASS, TIME, MARKS info
            info_para = doc.add_paragraph()
            info_text = f'CLASS: {class_val}     TIME: {time_val}     MARKS: {marks_val}'
            info_run = info_para.add_run(info_text)
            info_run.font.size = Pt(10)
            if is_tamil:
                set_tamil_font(info_run)
            
            doc.add_paragraph("")
        except Exception as fallback_e:
            print(f"[DOCX-Header] Fallback also failed: {fallback_e}")
    except Exception as e:
        print(f"[DOCX-Header] WARNING: Failed to create header: {e}")

    # No separate title needed - already in header

    # Body
    import re
    marks_pattern = re.compile(r"\s*\[(\d+)\s*marks?\]", re.IGNORECASE)

    for typ, text in all_questions:
        # Remove trailing [n marks] if present in any text
        if isinstance(text, str):
            text = marks_pattern.sub("", text).rstrip()
        if typ == "header":
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(13)
            if is_tamil:
                set_tamil_font(r)
            doc.add_paragraph("")
        elif typ == "subheader":
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(12)
            if is_tamil:
                set_tamil_font(r)
        elif typ == "instruction":
            p = doc.add_paragraph()
            r = p.add_run(text)
            if is_tamil:
                set_tamil_font(r)
            p.style = doc.styles['List Bullet'] if 'List Bullet' in doc.styles else None
        elif typ == "q":
            p = doc.add_paragraph()
            r = p.add_run(text)
            if is_tamil:
                set_tamil_font(r)
            # Add a small space before options
            p.paragraph_format.space_after = Pt(4)
        elif typ == "subq":
            p = doc.add_paragraph()
            r = p.add_run(text)
            if is_tamil:
                set_tamil_font(r)
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_after = Pt(2)
        elif typ == "opts":
            p = doc.add_paragraph()
            r = p.add_run(text)
            if is_tamil:
                set_tamil_font(r)
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_after = Pt(8)
        elif typ == "opts_block":
            # text is a list of labeled options like ["A) ...", "B) ...", ...]
            try:
                opts = list(text) if isinstance(text, (list, tuple)) else []
                # Create 2x2 table for up to 4 options; if 3 options, last cell empty
                rows, cols = 2, 2
                tbl = doc.add_table(rows=rows, cols=cols)
                tbl.autofit = True
                # Fill cells row-wise: A B / C D
                for idx in range(rows * cols):
                    r, c = divmod(idx, cols)
                    cell_text = opts[idx] if idx < len(opts) else ""
                    cell = tbl.cell(r, c)
                    cell.text = ""  # Clear default paragraph
                    cell_para = cell.paragraphs[0]
                    cell_run = cell_para.add_run(cell_text)
                    if is_tamil:
                        set_tamil_font(cell_run)
                    # Compact style
                    for p in cell.paragraphs:
                        p.paragraph_format.space_after = Pt(2)
                doc.add_paragraph("")
            except Exception as e:
                print(f"[DOCX] opts_block failed: {e}")
        elif typ == "passage":
            p = doc.add_paragraph()
            r = p.add_run(text)
            if is_tamil:
                set_tamil_font(r)
            for run in p.runs:
                run.italic = True
        elif typ == "or":
            p = doc.add_paragraph()
            r = p.add_run("OR")
            r.bold = True
            if is_tamil:
                set_tamil_font(r)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif typ == "image":
            try:
                img_path = os.path.join(settings.MEDIA_ROOT, text) if not os.path.isabs(text) else text
                run = doc.add_paragraph().add_run()
                run.add_picture(img_path, width=Inches(5.5))
            except Exception as e:
                print(f"[DOCX] Image insert failed: {e}")

    output_dir = os.path.join(settings.MEDIA_ROOT, "question_papers")
    os.makedirs(output_dir, exist_ok=True)

    safe_subject = subject.replace(" ", "_")
    filename = f"{safe_subject}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
    file_path = os.path.join(output_dir, filename)
    doc.save(file_path)

    return f"question_papers/{filename}", summary


# ------------------------------
# Image generation helpers
# ------------------------------
def generate_ai_image(prompt: str, width: int = 512, height: int = 512, cfg_scale: float = 8.0) -> str:
    """Generate an image using Amazon Titan Image Generator v2 and save under MEDIA_ROOT/generated_images.
    Returns relative media path."""
    import base64, hashlib
    output_dir = getattr(settings, 'IMAGE_OUTPUT_DIR', os.path.join(settings.MEDIA_ROOT, 'generated_images'))
    os.makedirs(output_dir, exist_ok=True)
    if not prompt or not str(prompt).strip():
        raise ValueError("Empty image prompt")
    key = hashlib.sha256(f"{prompt}|{width}|{height}|{cfg_scale}".encode('utf-8')).hexdigest()[:24]
    rel_path = f"generated_images/{key}.png"
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    if os.path.exists(abs_path):
        return rel_path
    # Titan v2 accepts specific dimensions; default to 512x512 (known-good)
    if width != height:
        print(f"[ImageGen] INFO: Coercing size {width}x{height} to 512x512 for Titan compatibility")
        width = height = 512

    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width": width,
            "height": height,
            "cfgScale": cfg_scale,
            "seed": 0
        }
    }
    model_id = getattr(settings, 'BEDROCK_IMAGE_MODEL_ID', 'amazon.titan-image-generator-v2:0')
    print(f"[ImageGen] Calling {model_id} | prompt={prompt[:80]}... | size={width}x{height}")
    resp = client.invoke_model(body=json.dumps(body), contentType="application/json", accept="application/json", modelId=model_id)
    result = json.loads(resp["body"].read())
    images = result.get("images") or result.get("artifacts") or result.get("result", {}).get("images")
    if not images:
        print(f"[ImageGen] DEBUG Response keys: {list(result.keys())}")
        raise RuntimeError("No images key in Titan response")
    # Extract base64 from first item
    b64 = None
    first = images[0]
    if isinstance(first, str):
        b64 = first
    elif isinstance(first, dict):
        # Try common fields
        for k in ("base64", "b64", "bytesBase64Encoded", "image", "data"):
            v = first.get(k)
            if isinstance(v, str) and len(v) > 100:
                b64 = v
                break
        if not b64:
            # Try any str field
            for v in first.values():
                if isinstance(v, str) and len(v) > 100:
                    b64 = v
                    break
    if not b64:
        print(f"[ImageGen] DEBUG First image object: {first}")
        raise RuntimeError("Could not extract base64 from Titan response")
    with open(abs_path, 'wb') as f:
        f.write(base64.b64decode(b64))
    return rel_path


def materialize_images(all_questions, allow=True):
    """Convert ('image_gen', prompt) and [IMAGE:/[Picture:/[Diagram:] markers (case-insensitive) to ('image', rel_path).
    Supports markers embedded in any text type (q, subq, instruction, passage)."""
    if not allow:
        return all_questions
    import re
    # Match [Picture: ...], [Image: ...], or [Diagram: ...] (colon optional), any case
    pattern = re.compile(r"\[(image|picture|diagram)\s*:?\s*(.*?)\]", re.IGNORECASE)
    out = []
    for typ, text in all_questions:
        try:
            # Direct generation tuple
            if typ == 'image_gen':
                print(f"[ImageGen] image_prompt detected: {str(text)[:120]}...")
                rel = generate_ai_image(str(text))
                out.append(('image', rel))
                continue

            if isinstance(text, str):
                prompts = pattern.findall(text)
                if prompts:
                    cleaned = pattern.sub('', text).strip()
                    appended_text = False
                    # Track whether any image was generated for this text
                    generated_any = False

                    for _kind, prompt in prompts:
                        prompt_clean = prompt.strip()

                        # Skip common labels like "Based" that aren't real prompts
                        if not prompt_clean or prompt_clean.lower() in {"based", "picture based", "diagram based"}:
                            if not appended_text:
                                out.append((typ, text.strip()))
                                appended_text = True
                            continue

                        if not appended_text and cleaned:
                            out.append((typ, cleaned))
                            appended_text = True

                        print(f"[ImageGen] marker detected: {_kind} | {prompt_clean[:120]}...")
                        try:
                            rel = generate_ai_image(prompt_clean)
                            out.append(('image', rel))
                            generated_any = True
                        except Exception as ge:
                            print(f"[ImageGen] Generation failed for prompt '{prompt_clean[:60]}': {ge}")

                    if not appended_text and not generated_any:
                        out.append((typ, text))
                    continue

            # Default passthrough
            out.append((typ, text))
        except Exception as e:
            print(f"[ImageGen] WARNING: {e}")
            out.append((typ, text))
    return out


# ------------------------------
# Entrypoint
# ------------------------------
def pattern_sections_to_blueprint_dict(pattern):
    """
    Convert pattern.sections (list) to blueprint dict format expected by generators.
    Pattern sections: list of section objects with 'name', 'marks', 'questions_count', 'question_types'
    Blueprint format: dict with section name as key, section data as value
    """
    if not pattern or not pattern.sections:
        return {}

    blueprint_dict = {}
    for section in pattern.sections:
        section_name = section.get('name', 'Section')
        blueprint_dict[section_name] = {
            'marks': section.get('marks', 0),
            'questions_count': section.get('questions_count', 0),
            'question_types': section.get('question_types', []),
            'instructions': section.get('instructions', []),
            'constraints': section.get('constraints', {}),
            'subsections': section.get('subsections', [])
        }

    return blueprint_dict if blueprint_dict else None


def generate_universal_paper(class_name, subject, chapters, difficulty, pattern, section=None, model_source='aws', additional_context=""):
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
        f.write(f"Model Source: {model_source}\n")
        f.write(f"Additional Context Length: {len(additional_context)} chars\n")
        f.write(f"{'='*50}\n\n")
    
    print(f"[Universal-Generator] Starting generation for {class_name} {subject}")
    print(f"[Universal-Generator] Summary saved to: {summary_file}")
    
    try:
        # Use pattern's sections converted to blueprint format
        blueprint = pattern_sections_to_blueprint_dict(pattern)
        if not blueprint:
            # Fallback to old system if pattern conversion fails
            blueprint = get_blueprint(class_name, subject, section)
            print(f"[Universal-Generator] ✅ Blueprint resolved: {len(blueprint)} sections")
        
        # Extract all question types from blueprint
        all_question_types = []
        
        # Blueprint is already normalized by BlueprintManager.get_blueprint()
        blueprint_dict = blueprint

        # Debug: Verify normalized structure
        print(f"[Universal-Generator] Blueprint dict type: {type(blueprint_dict)}")
        print(f"[Universal-Generator] Blueprint dict keys: {list(blueprint_dict.keys())}")

        # Check if this is a complex blueprint (has sections with subsections) or simple blueprint
        is_complex_blueprint = False
        for section_key, section_data in blueprint_dict.items():
            if isinstance(section_data, dict) and 'subsections' in section_data:
                is_complex_blueprint = True
                break
        
        if is_complex_blueprint:
            # Extract question types from complex blueprint structure
            for section_key, section_data in blueprint_dict.items():
                if isinstance(section_data, dict) and 'subsections' in section_data:
                    subsections = section_data['subsections']
                    # Handle both list and dict formats for subsections
                    if isinstance(subsections, list):
                        for subsection in subsections:
                            if isinstance(subsection, dict):
                                subsec_types = subsection.get('question_types', [])
                                all_question_types.extend(subsec_types)
                    elif isinstance(subsections, dict):
                        for subsection_key, subsection_questions in subsections.items():
                            if isinstance(subsection_questions, list):
                                for question in subsection_questions:
                                    if isinstance(question, dict) and 'type' in question:
                                        all_question_types.append(question['type'])
        else:
            # Extract question types from simple blueprint structure
            for section_name, section_data in blueprint_dict.items():
                section_question_types = section_data.get('question_types', [])
                all_question_types.extend(section_question_types)
        
        # Remove duplicates while preserving order
        all_question_types = list(dict.fromkeys(all_question_types))
        print(f"[Universal-Generator] Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}")
        print(f"[Universal-Generator] Question types: {all_question_types}")
        
        # Get universal context with variation
        variation_offset = random.randint(0, 20)  # Random offset for context variation
        context_data = get_universal_context(class_name, subject, chapters, all_question_types, variation_offset=variation_offset)
        context_text = context_data['context_text']
        
        # Generate the paper using universal prompt
        file_path, summary, total_cost = generate_with_universal_prompt(
            class_name, subject, chapters, difficulty, pattern, blueprint, 
            context_text, all_question_types, summary_file, model_source, additional_context
        )
        
        return file_path, summary, total_cost
        
    except Exception as e:
        error_msg = f"Universal generation failed: {str(e)}"
        print(f"[Universal-Generator] ❌ {error_msg}")
        
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"\n❌ ERROR: {error_msg}\n")
            f.write(f"Traceback: {traceback.format_exc()}\n")
        
        raise Exception(error_msg)

def generate_with_universal_prompt(class_name, subject, chapters, difficulty, pattern, blueprint, context_text, question_types, summary_file, model_source, additional_context=""):
    """Generate paper using universal prompt system"""

    print(f"[Universal-Prompt] Building adaptive prompt for {subject}")
    print(f"[Universal-Prompt] Blueprint structure: {list(blueprint.keys())}")

    # Blueprint is already normalized by BlueprintManager.get_blueprint()
    blueprint_dict = blueprint

    # Extract passage and extract instructions from pattern sections
    passage_instructions = ""
    if hasattr(pattern, 'sections') and pattern.sections:
        print(f"[Universal-Prompt] Extracting passage instructions from pattern sections")
        for section in pattern.sections:
            if isinstance(section, dict):
                section_name = section.get('name', 'Section')
                # Check for passage_instruction field
                if 'passage_instruction' in section:
                    passage_instructions += f"\n- {section_name}: {section['passage_instruction']}"
                    print(f"[Universal-Prompt]   Found passage instruction for {section_name}")
                # Check for extract_instruction field
                if 'extract_instruction' in section:
                    passage_instructions += f"\n- {section_name}: {section['extract_instruction']}"
                    print(f"[Universal-Prompt]   Found extract instruction for {section_name}")
                # Check subsections for extract instructions
                if 'subsections' in section and isinstance(section['subsections'], list):
                    for subsection in section['subsections']:
                        if isinstance(subsection, dict) and 'extract_instruction' in subsection:
                            sub_name = subsection.get('name', 'Subsection')
                            passage_instructions += f"\n- {section_name} > {sub_name}: {subsection['extract_instruction']}"
                            print(f"[Universal-Prompt]   Found extract instruction for {sub_name}")

    # Check if this is a complex blueprint (has sections with subsections) or simple blueprint
    is_complex_blueprint = False
    for section_key, section_data in blueprint_dict.items():
        if isinstance(section_data, dict) and 'subsections' in section_data:
            is_complex_blueprint = True
            break

    print(f"[Universal-Prompt] Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}")

    if is_complex_blueprint:
        # Use the complex blueprint directly as the schema
        blueprint_schema = json.dumps(blueprint_dict, indent=2)
        sections_spec = "Follow the exact blueprint structure provided below."
    else:
        # Build sections specification from simple blueprint
        sections_spec = ""
        # Use blueprint_dict which has been converted to proper format
        for section_name, section_data in blueprint_dict.items():
            section_title = section_data.get('title', '')
            section_marks = section_data.get('marks', 0)
            section_qtypes = section_data.get('question_types', [])

            sections_spec += f"""
Section {section_name} - {section_title} ({section_marks} marks):
Question Types: {', '.join(section_qtypes)}
"""
        # Still use the original blueprint structure for the schema
        blueprint_schema = json.dumps(blueprint, indent=2)

    # Get question type instructions
    question_type_instructions = get_question_type_instructions(question_types, subject)
    
    # Build the universal prompt
    passage_section = f"""
PASSAGE AND EXTRACT GENERATION INSTRUCTIONS (CRITICAL):
{passage_instructions if passage_instructions else "No specific passage/extract instructions found in pattern"}

PASSAGE/EXTRACT REQUIREMENTS:
1. If a section requires passages: Generate passages inline and include in JSON with "passage" key
2. If a section requires extracts: Generate extract text and include in JSON with "extract" key
3. Questions must reference the passages/extracts you generate
4. Include passage/extract text directly in the section, NOT in a separate file

JSON STRUCTURE FOR SECTIONS WITH PASSAGES/EXTRACTS:
- Add "passage" key: "passage": "Generated passage text here"
- Add "extract" key: "extract": "Generated extract text here"
- Keep "questions" array with questions based on passage/extract
- Questions must reference and quote the passage/extract

Example with passage:
{{
  "Reading Comprehension": {{
    "marks": 5,
    "questions_count": 5,
    "question_types": ["Short Answer"],
    "instructions": ["Read the passage carefully"],
    "constraints": {{}},
    "passage": "Mrs. Jones had an unusual garden...[full passage text here]",
    "questions": [
      {{"qnum": "1a", "text": "What was unusual about Mrs. Jones' garden?", "marks": 1}},
      ...
    ]
  }}
}}

Example with extract:
{{
  "Literature": {{
    "marks": 5,
    "questions_count": 3,
    "question_types": ["Extract"],
    "instructions": ["Answer with reference to the extract"],
    "constraints": {{}},
    "extract": "[Extract text from literature piece here]",
    "questions": [
      {{"qnum": "2a", "text": "Extract question based on above text", "marks": 5}},
      ...
    ]
  }}
}}
"""

    # Build the universal prompt
    # Merge any caller-provided additional context with retrieved context
    combined_context = context_text
    if additional_context:
        combined_context = f"{context_text}\n\n[ADDITIONAL CONTEXT]\n{additional_context}"

    # Get variation instructions
    variation_hints = get_variation_instructions()
    variation_instructions = "\n".join([f"- {hint}" for hint in variation_hints])
    
    prompt = f"""You are an expert question paper generator for CBSE {class_name} {subject} examinations.

CONTEXT MATERIAL:
{combined_context}

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

CRITICAL VARIATION REQUIREMENTS:
IMPORTANT: Generate COMPLETELY DIFFERENT questions from any previous papers. Each question must be unique and original.
{variation_instructions}

GENERATION GUIDELINES:
1. Create questions that are appropriate for {class_name} level students
2. Ensure questions test understanding, application, and analysis
3. Use the provided context material as the primary source
4. Maintain consistency with CBSE examination patterns
5. Include a variety of question types as specified
6. Ensure proper mark distribution across sections
7. Make questions clear, unambiguous, and well-structured
8. Generate passages/extracts INLINE - do not reference external sources
9. Make passages/extracts contextually relevant to the chapters specified
10. CREATE UNIQUE QUESTIONS - Avoid repeating common question patterns or wordings
11. Use different examples, scenarios, and approaches for each question
12. Vary the complexity and angles of questions even for the same topic

{passage_section}

CRITICAL JSON OUTPUT INSTRUCTIONS:
1. Output ONLY valid JSON - no text before or after
2. Use section names as keys (e.g., "Reading Comprehension", "Writing", "Grammar", "Literature")
3. For sections with passages: Include "passage" key with passage text BEFORE questions
4. For sections with extracts: Include "extract" key with extract text BEFORE questions
5. Each section MUST have ONLY these keys: "marks", "questions_count", "question_types", "instructions", "constraints", "passage" (if applicable), "extract" (if applicable), "questions"
6. NO other keys allowed - do not add LIT_EXTRACT_SR, LIT_EXTRACT_PM or any other nested keys
7. Each question must have: {{"qnum": (number or string), "text": "question text", "marks": marks_value}}
8. Flatten ALL questions into the "questions" array - no subsections, no nested structures
9. Do NOT include markdown, explanations, or any text - ONLY JSON

EXAMPLE OUTPUT FORMAT (WITH PASSAGES):
{{
  "Reading Comprehension": {{
    "marks": 5,
    "questions_count": 5,
    "question_types": ["Short Answer"],
    "instructions": ["Read the passage carefully"],
    "constraints": {{}},
    "passage": "Mrs. Jones had an unusual garden that caught everyone's attention. Unlike traditional gardens filled with colorful flowers and lush greenery, her garden was full of stones...[continue passage to reach word limit]",
    "questions": [
      {{"qnum": "1a", "text": "What makes Mrs. Jones' garden different from traditional gardens?", "marks": 1}},
      {{"qnum": "1b", "text": "Name two features of Mrs. Jones' garden.", "marks": 1}}
    ]
  }},
  "Literature": {{
    "marks": 5,
    "questions_count": 2,
    "question_types": ["Extract"],
    "instructions": ["Answer with reference to the extract"],
    "constraints": {{}},
    "extract": "[Full extract from literature text - should be substantial enough to base questions on]",
    "questions": [
      {{"qnum": "2a", "text": "Extract-based question 1", "marks": 2}},
      {{"qnum": "2b", "text": "Extract-based question 2", "marks": 3}}
    ]
  }}
}}

DIFFICULTY GUIDELINES:
- {difficulty}: Create appropriately challenging questions for this difficulty level
- Include {"analysis, synthesis, evaluation" if difficulty == "Hard" else "understanding and application"}

OUTPUT REQUIREMENTS:
- Generate ONLY valid JSON
- Follow the example format above
- Include all sections from the blueprint
- Total marks and questions must match the blueprint
- ALL questions must be based on provided context OR generated passages/extracts
- Passages MUST be included inline in JSON with "passage" key
- Extracts MUST be included inline in JSON with "extract" key
- Do not include any text outside JSON"""

    print(f"[Universal-Prompt] Prompt length: {len(prompt)} characters")
    
    # Log prompt to summary file
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== UNIVERSAL PROMPT ===\n")
        f.write(f"Blueprint type: {'Complex' if is_complex_blueprint else 'Simple'}\n")
        f.write(f"Prompt length: {len(prompt)} characters\n")
        f.write(f"Question types: {question_types}\n")
        f.write(f"Context length: {len(context_text)} characters\n")
        f.write(f"{'='*50}\n\n")
    
    # Call Bedrock with the universal prompt - use varied temperature for more variation
    total_input_tokens = 0
    total_output_tokens = 0
    try:
        # Use varied temperature for more question variation
        variation_temp = get_variation_temperature()
        print(f"[Variation] Using temperature: {variation_temp} (varied for uniqueness)")
        raw_json, input_tokens_gen, output_tokens_gen = call_bedrock(prompt, GEN_MODEL_ID, temperature=variation_temp, model_source='aws')
        total_input_tokens += input_tokens_gen
        total_output_tokens += output_tokens_gen
        print(f"[Universal-Prompt] ✅ Received response from Bedrock")
        
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
        
        validated, input_tokens_val, output_tokens_val = call_bedrock(validator_prompt, VAL_MODEL_ID, temperature=0.3, model_source='aws')
        total_input_tokens += input_tokens_val
        total_output_tokens += output_tokens_val
        
        print(f"[Validation] Validation response received: {len(validated)} characters")
        print(f"[Validation] Validation response preview: {validated[:200]}...")
        
        # Step 3: Final JSON enforcement and cleanup
        print(f"[Final-Validation] Starting final JSON enforcement...")
        paper_data = enforce_json(validated)
        
        print(f"[Final-Validation] JSON enforcement completed successfully!")
        print(f"[Final-Validation] Final data structure: {list(paper_data.keys()) if isinstance(paper_data, dict) else 'Not a dict'}")

        # Calculate cost
        cost_per_input_1k_tokens = 0.49  # INR
        cost_per_output_1k_tokens = 1.47 # INR
        total_cost = (total_input_tokens / 1000) * cost_per_input_1k_tokens + \
                     (total_output_tokens / 1000) * cost_per_output_1k_tokens
        print(f"[Cost] Total Input Tokens: {total_input_tokens}")
        print(f"[Cost] Total Output Tokens: {total_output_tokens}")
        print(f"[Cost] Calculated Cost: {total_cost:.4f} INR")
        
        # Log generation results to summary file
        if summary_file:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(f"=== GENERATION RESULTS ===\n")
                f.write(f"Generation Model: {GEN_MODEL_ID}\n")
                f.write(f"Validation Model: {VAL_MODEL_ID}\n")
                f.write(f"Raw JSON Length: {len(raw_json)} chars\n")
                f.write(f"Validated JSON Length: {len(validated)} chars\n")
                f.write(f"Final JSON Structure: {list(paper_data.keys()) if isinstance(paper_data, dict) else 'Not a dict'}\n")
                f.write(f"Questions Generated: {len(paper_data.get('sections', {})) if isinstance(paper_data, dict) else len(paper_data)} sections\n")
                f.write(f"Total Input Tokens: {total_input_tokens}\n")
                f.write(f"Total Output Tokens: {total_output_tokens}\n")
                f.write(f"Calculated Cost: {total_cost:.4f} INR\n")
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
            all_questions = render_section_questions([], direct_data, blueprint, class_name, subject, chapters, None)
            # Attach AI-generated images if prompts/markers present
            allow_images = True
            try:
                if additional_context:
                    ctx = json.loads(additional_context) if isinstance(additional_context, str) else {}
                    if isinstance(ctx, dict):
                        allow_images = ctx.get('allow_ai_images', True) is not False
            except Exception:
                pass
            all_questions = materialize_images(all_questions, allow=allow_images)
            try:
                num_imgs = sum(1 for t, _ in all_questions if t == 'image')
                print(f"[ImageGen] Images attached: {num_imgs}")
            except Exception:
                pass
            print(f"[DIRECT] Generated {len(all_questions)} questions from temp_clean.json")
            
            with open(debug_file, "a", encoding="utf-8") as debug_f:
                debug_f.write(f"Generated {len(all_questions)} questions\n")
                for i, (typ, text) in enumerate(all_questions[:10]):
                    debug_f.write(f"  {i+1}. [{typ}] {text[:100]}...\n")
            
        except Exception as e:
            print(f"[DIRECT] Error loading temp_clean.json: {e}")
            with open(debug_file, "a", encoding="utf-8") as debug_f:
                debug_f.write(f"Error: {e}\n")
            # Fallback to original approach - use paper_data instead of undefined 'data'
            all_questions = render_section_questions([], paper_data, blueprint, class_name, subject, chapters, None)
            all_questions = materialize_images(all_questions)
            try:
                num_imgs = sum(1 for t, _ in all_questions if t == 'image')
                print(f"[ImageGen] Images attached (fallback): {num_imgs}")
            except Exception:
                pass
        
        summary = {sec: {"title": sec, "marks": paper_data.get(sec, {}).get('marks', 0)}
                   for sec in paper_data.keys()}

        # Prepare header meta for renderer
        header_meta = {}
        try:
            header_meta = {
                "class_name": class_name,
                "subject": subject,
                "pattern_name": getattr(pattern, 'name', ''),
                "marks": getattr(pattern, 'total_marks', 0),
            }
            # Parse additional_context for duration/marks/class_name if JSON
            if additional_context:
                import json as _json
                try:
                    ctx_obj = _json.loads(additional_context)
                    print(f"[Header-Meta] Parsed additional_context: {ctx_obj}")
                    if isinstance(ctx_obj, dict):
                        # Override with values from generate page if provided
                        if 'class_name' in ctx_obj and ctx_obj['class_name']:
                            header_meta['class_name'] = ctx_obj['class_name']
                            print(f"[Header-Meta] Using class_name from form: {ctx_obj['class_name']}")
                        if 'duration' in ctx_obj and ctx_obj['duration']:
                            header_meta['duration'] = ctx_obj['duration']
                            print(f"[Header-Meta] Using duration from form: {ctx_obj['duration']}")
                        if 'marks' in ctx_obj and ctx_obj['marks']:
                            header_meta['marks'] = ctx_obj['marks']
                            print(f"[Header-Meta] Using marks from form: {ctx_obj['marks']}")
                        if 'test_type' in ctx_obj and ctx_obj['test_type']:
                            header_meta['test_type'] = ctx_obj['test_type']
                            print(f"[Header-Meta] Using test_type from form: {ctx_obj['test_type']}")
                except Exception as e:
                    print(f"[Header-Meta] WARN: failed to parse additional_context: {e}")
                    print(f"[Header-Meta] Traceback: {traceback.format_exc()}")
            globals()['__HEADER_META__'] = header_meta
            print(f"[Header-Meta] ✅ Set header metadata: {header_meta}")
            print(f"[Header-Meta]   - class_name: '{header_meta.get('class_name')}'")
            print(f"[Header-Meta]   - duration: '{header_meta.get('duration')}'")
            print(f"[Header-Meta]   - marks: '{header_meta.get('marks')}'")
            print(f"[Header-Meta]   - test_type: '{header_meta.get('test_type')}'")
            print(f"[Header-Meta]   - subject: '{header_meta.get('subject')}'")
        except Exception as _e:
            print(f"[Header-Meta] ❌ WARN: failed to set header meta: {_e}")
            print(f"[Header-Meta] Traceback: {traceback.format_exc()}")

        # Render DOCX (download should be Word) and return (file_path, summary) tuple
        file_path, summary = render_docx(class_name, subject, chapters, all_questions, summary)
        return file_path, summary, total_cost
        
    except Exception as e:
        error_msg = f"Universal prompt generation failed: {str(e)}"
        print(f"[Universal-Prompt] ❌ {error_msg}")
        
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"\n❌ ERROR: {error_msg}\n")
            f.write(f"Traceback: {traceback.format_exc()}\n")
        
        raise Exception(error_msg)

def generate_paper(class_name, subject, chapters, difficulty, pattern, section=None, model_source='aws', additional_context=""):
    """
    Main entry point for question paper generation.
    Now uses the universal generator by default, with fallback to legacy system.
    """
    print(f"[Generator] Starting paper generation for {class_name} {subject}")
    
    try:
        # Try universal generator first
        print(f"[Generator] Attempting universal generation...")
        file_path, summary, total_cost = generate_universal_paper(class_name, subject, chapters, difficulty, pattern, section, model_source, additional_context)
        return file_path, summary, total_cost
        
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
            f.write(f"Model Source: {model_source}\n") # Log model source
            f.write(f"{'='*50}\n\n")
        
        print(f"[Generator] Using legacy system - Summary saved to: {summary_file}")

        # Use the pattern's structure converted to blueprint format
        blueprint = pattern_sections_to_blueprint_dict(pattern)
        if not blueprint:
            blueprint = get_blueprint(class_name, subject, section)

        if subject.lower() in ["english", "english core"]:
            file_path, summary = generate_english_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file, model_source)
            return file_path, summary, 0.0 # Legacy functions don't calculate cost
        else:
            file_path, summary = generate_science_paper(class_name, subject, chapters, difficulty, pattern, blueprint, summary_file, model_source)
            return file_path, summary, 0.0 # Legacy functions don't calculate cost
