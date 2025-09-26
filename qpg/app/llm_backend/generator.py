import os, re, json
import boto3
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from django.conf import settings
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from . import embeddings

# ------------------------------
# Load exam patterns configuration
# ------------------------------
def load_exam_patterns():
    """Load exam patterns from JSON configuration file"""
    config_path = os.path.join(os.path.dirname(__file__), "exam_patterns.json")
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: exam_patterns.json not found at {config_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing exam_patterns.json: {e}")
        return {}

# ------------------------------
# Bedrock setup - Claude 3.7 Sonnet
# ------------------------------
client = boto3.client("bedrock-runtime", region_name="eu-north-1")
MODEL_ARN = "arn:aws:bedrock:eu-north-1:659260838757:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0"

# ------------------------------
# Bedrock helper
# ------------------------------
def call_bedrock(prompt):
    body = {
        "anthropic_version": "bedrock-2023-05-31",   # required
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ]
            }
        ],
        "max_tokens": 3000,
        "temperature": 0.7
    }
    resp = client.invoke_model(
        modelId=MODEL_ARN,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body)
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]

# ------------------------------
# Cleaning helper
# ------------------------------
def clean_and_split(text, expected_count, offset=0, section="A"):
    questions = []
    if not text:
        return questions, []

    text = re.sub(r"\*\*|##|STOP.*|Note:.*", "", text)
    text = re.sub(r"(Here are.*|Okay.*|I've.*|Now.*)", "", text)
    text = text.replace("■", "")
    text = re.sub(r"Q\s*(\d+)[\.:]?", r"\1)", text)
    text = re.sub(r"(\d+)\.", r"\1)", text)
    text = re.sub(r"(\d+\))\s*:", r"\1", text)

    # For sections with internal choice, preserve "OR"
    if "OR" in text:
        return text.split("\n"), []

    raw_qs = re.split(r"(?:^|\n)(\d+\))", text)
    cleaned = []
    for i in range(1, len(raw_qs), 2):
        qnum = raw_qs[i].strip()
        qbody = raw_qs[i+1].strip() if i+1 < len(raw_qs) else ""
        cleaned.append(f"{qnum} {qbody}")

    if not cleaned:
        return [text.strip()], []

    for i, raw in enumerate(cleaned[:expected_count], 1):
        q_lines = [line.strip() for line in raw.split("\n") if line.strip() and not line.lower().startswith("answer:")]
        if ")" in q_lines[0]:
            formatted = f"{i+offset}) {q_lines[0].split(')',1)[1].strip()}"
        else:
            formatted = f"{i+offset}) {q_lines[0]}"
        questions.append(formatted)
        for line in q_lines[1:]:
            if re.match(r"^[a-d]\)", line.lower()):
                questions.append("   " + line)  # indent options
            else:
                questions.append(line)

    return questions, []

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
            y = 780
        can.drawString(x, y, line)
        y -= line_height
    return y

# ------------------------------
# Main generator
# ------------------------------
def generate_paper(class_name, subject, unit, difficulty):
    """
    Generate a question paper based on class, subject, unit, and difficulty.
    
    Args:
        class_name (str): Class (e.g., "11", "12")
        subject (str): Subject name (e.g., "Biology", "English", "Mathematics")
        unit (str): Unit/topic (e.g., "Unit 1", "Algebra")
        difficulty (str): Difficulty level (e.g., "easy", "medium", "hard")
    
    Returns:
        tuple: (file_path, summary_dict)
    """
    # Normalize class name
    if class_name.upper() == "XI":
        class_name = "11"
    elif class_name.upper() == "XII":
        class_name = "12"
    
    # Normalize subject (capitalize first letter)
    subject = subject.capitalize()
    
    # Load exam patterns
    exam_patterns = load_exam_patterns()
    class_key = f"Class {class_name}"
    
    # Check if we have patterns for this class and subject
    if class_key not in exam_patterns or subject not in exam_patterns[class_key]:
        raise ValueError(f"No exam pattern found for {class_key} {subject}")
    
    subject_config = exam_patterns[class_key][subject]
    sections_config = subject_config["sections"]
    
    all_questions, q_offset = [], 0
    summary = {
        "class": class_name,
        "subject": subject,
        "unit": unit,
        "difficulty": difficulty,
        "total_marks": subject_config["total_marks"],
        "duration": subject_config["duration"],
        "sections": {}
    }

    # Generate questions for each section
    for sec, sec_config in sections_config.items():
        count = sec_config["count"]
        marks_per_q = sec_config["marks_per_question"]
        chapters = sec_config["chapters"]
        
        # Pull relevant context from embeddings
        contexts = []
        for chapter in chapters:
            try:
                results = embeddings.query(
                    class_name=class_name, 
                    subject=subject.lower(), 
                    unit=chapter,
                    query_text=subject.lower(), 
                    n_results=30
                )
                chunks = results["documents"]
                if chunks:
                    contexts.extend([doc for docs in chunks for doc in docs])
            except Exception as e:
                print(f"Warning: Could not fetch context for chapter {chapter}: {e}")
        
        context = "\n".join(contexts) if contexts else "No context found"
        print(f"[Section {sec}] Context length: {len(context)} chars")
        
        # Generate prompt using template
        prompt_template = sec_config["prompt_template"]
        prompt = prompt_template.format(
            q_start=count,
            difficulty=difficulty,
            class_name=class_name,
            subject=subject,
            chapters=", ".join(chapters),
            context=context
        )
        
        # Generate questions using Bedrock
        text = call_bedrock(prompt)
        qs, _ = clean_and_split(text, count, offset=q_offset, section=sec)
        
        # Add section header
        total_marks = count * marks_per_q
        header = f"SECTION {sec}: {sec_config['name']} ({marks_per_q} mark each)" if marks_per_q == 1 else f"SECTION {sec}: {sec_config['name']} ({marks_per_q} marks each)"
        all_questions.append(("header", f"{header} ({count} × {marks_per_q} = {total_marks})"))
        
        # Add questions
        for q in qs:
            all_questions.append(("q", q))
        
        q_offset += count
        
        # Save section summary
        summary["sections"][sec] = {
            "name": sec_config["name"],
            "description": sec_config["description"],
            "chapters": chapters,
            "questions": count,
            "marks_per_question": marks_per_q,
            "total_marks": total_marks,
            "chars_used": len(context)
        }

    # Generate PDF
    base_pdf = os.path.join(os.path.dirname(__file__), "data", "base.pdf")
    reader = PdfReader(base_pdf)
    writer = PdfWriter()
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    
    # Add title page
    y = 700
    can.setFont("Helvetica-Bold", 18)
    can.drawCentredString(300, y, f"Class {class_name} {subject}")
    y -= 30
    can.setFont("Helvetica-Bold", 16)
    can.drawCentredString(300, y, f"Unit: {unit}")
    y -= 30
    can.setFont("Helvetica-Bold", 14)
    can.drawCentredString(300, y, f"Difficulty: {difficulty.capitalize()}")
    y -= 30
    can.drawCentredString(300, y, f"Total Marks: {summary['total_marks']}")
    y -= 30
    can.drawCentredString(300, y, f"Duration: {summary['duration']}")
    y -= 50
    
    # Add questions
    for typ, text in all_questions:
        if typ == "header":
            can.setFont("Helvetica-Bold", 14)
            can.drawCentredString(300, y, text)
            y -= 40
        elif typ == "q":
            y = draw_wrapped(can, text, 60, y, 470, font="Helvetica", size=11)
    
    can.showPage()
    
    # Add summary page
    can.setFont("Helvetica-Bold", 16)
    can.drawCentredString(300, 800, "QUESTION PAPER GENERATION SUMMARY")
    y = 760
    
    # Paper details
    can.setFont("Helvetica-Bold", 12)
    can.drawString(60, y, f"Class: {class_name}")
    y -= 20
    can.drawString(60, y, f"Subject: {subject}")
    y -= 20
    can.drawString(60, y, f"Unit: {unit}")
    y -= 20
    can.drawString(60, y, f"Difficulty: {difficulty.capitalize()}")
    y -= 20
    can.drawString(60, y, f"Total Marks: {summary['total_marks']}")
    y -= 20
    can.drawString(60, y, f"Duration: {summary['duration']}")
    y -= 40
    
    # Section details
    can.setFont("Helvetica-Bold", 12)
    can.drawString(60, y, "Section Details:")
    y -= 25
    
    can.setFont("Helvetica", 10)
    for sec, info in summary["sections"].items():
        line = f"Section {sec} ({info['name']}): {info['questions']} questions | {info['marks_per_question']} mark each | Total: {info['total_marks']} marks"
        y = draw_wrapped(can, line, 60, y, 470, font="Helvetica", size=10, line_height=14)
        y -= 5
        
        # Add chapter info
        chapter_line = f"  Chapters: {', '.join(info['chapters'])} | Context: {info['chars_used']} chars"
        y = draw_wrapped(can, chapter_line, 80, y, 450, font="Helvetica", size=9, line_height=12)
        y -= 10
    
    can.save()
    packet.seek(0)
    overlay_reader = PdfReader(packet)
    
    # Merge with base PDF
    for i, overlay_page in enumerate(overlay_reader.pages):
        if i == 0:
            base_page = reader.pages[0]
            base_page.merge_page(overlay_page)
            writer.add_page(base_page)
        else:
            writer.add_page(overlay_page)
    
    # Save PDF
    output_dir = os.path.join(settings.MEDIA_ROOT, "question_papers")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"{class_name}_{subject.lower()}_{unit.replace(' ', '_')}_{difficulty}_{timestamp}.pdf"
    file_path = os.path.join(output_dir, filename)
    
    with open(file_path, "wb") as f:
        writer.write(f)
    
    # Return both file path and summary
    return f"question_papers/{filename}", summary
