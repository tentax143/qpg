import os
import re
import requests
import threading
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from django.conf import settings
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from . import embeddings

# Assign systems to sections
SECTIONS = {
    "A": ("172.16.71.102", "llama3:latest", 800),    # Section A (MCQs)
    "B": ("172.16.71.107", "gemma3:27b", 1200),      # Section B
    "C": ("172.16.71.108", "gemma3:27b", 1500),      # Section C
    "D": ("172.16.71.109", "gemma3:27b", 1500),      # Section D
    "E": ("172.16.71.110", "gemma3:27b", 2000),      # Section E
}

def call_remote_ollama(prompt, ip, model="llama3:latest", num_predict=800):
    try:
        url = f"http://{ip}:11434/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": num_predict}
        }
        resp = requests.post(url, json=payload, timeout=1000000)
        resp.raise_for_status()
        return resp.json()["response"]
    except Exception as e:
        return f"[Error contacting {ip}: {e}]"

def clean_questions(lines):
    """Format questions and collect answer key for Section A."""
    formatted = []
    answer_key = []
    q_number = 1

    for line in lines:
        text = line.strip()

        # Section headers
        if text.upper().startswith("SECTION"):
            formatted.append(text)
            continue

        # Question numbers like **Q1** or Q1.
        if re.match(r"(\*\*Q\d+\*\*|Q\d+\.?)", text):
            clean = re.sub(r"(\*\*Q\d+\*\*|Q\d+\.?)", "", text).strip()
            formatted.append(f"{q_number}) {clean}")
            q_number += 1
            continue

        # Options
        if text.lower().startswith(("a)", "b)", "c)", "d)", "(a)", "(b)", "(c)", "(d)")):
            formatted.append("   " + text)
            continue

        # Answers → put into key
        if text.startswith("Answer:"):
            answer_key.append(text)
            continue

        # Normal text
        formatted.append(text)

    return formatted, answer_key

def generate_paper(class_name, subject, unit, difficulty):
    # 1. Retrieve NCERT context
    results = embeddings.query(
        class_name=class_name,
        subject=subject,
        unit=unit,
        query_text="important exam topics",
        n_results=20
    )
    chunks = results["documents"]
    context = "\n".join([doc for docs in chunks for doc in docs]) if chunks else "No context found"

    # 2. Prompts per section
    prompts = {
        "A": f"""
        SECTION A (1 mark each) (16 × 1 = 16)
        Generate exactly 16 multiple-choice questions (Q1–Q16).
        - Each question MUST have 4 options (a, b, c, d).
        - Only one correct option.
        - Show the answer key immediately after each question in the format: "Answer: (a)".
        - Each question must end with (1 mark).
        After Q16, STOP.
        Use ONLY this NCERT context: {context}
        """,

        "B": f"""
        SECTION B (2 marks each) (5 × 2 = 10)
        Generate exactly 5 questions (Q17–Q21), each 2 marks.
        Provide internal choice in Q20 or Q21.
        After Q21, STOP.
        Use ONLY this NCERT context: {context}
        """,

        "C": f"""
        SECTION C (3 marks each) (7 × 3 = 21)
        Generate exactly 7 questions (Q22–Q28), each 3 marks.
        Provide internal choice in Q25 or Q26.
        After Q28, STOP.
        Use ONLY this NCERT context: {context}
        """,

        "D": f"""
        SECTION D (Case-based, 4 marks each) (2 × 4 = 8)
        Generate exactly 2 case-based questions (Q29–Q30), each 4 marks.
        Each question should have a passage + 2 sub-questions.
        Provide internal choice in one question.
        After Q30, STOP.
        Use ONLY this NCERT context: {context}
        """,

        "E": f"""
        SECTION E (Long-answer, 5 marks each) (3 × 5 = 15)
        Generate exactly 3 questions (Q31–Q33), each 5 marks.
        Provide internal choice in one question.
        After Q33, STOP.
        Use ONLY this NCERT context: {context}
        """
    }

    # 3. Run in parallel
    results_sections = {}
    threads = []

    def run_section(sec):
        ip, model, num_predict = SECTIONS[sec]
        print(f"[INFO] Generating Section {sec} using {model} on {ip}...")
        results_sections[sec] = call_remote_ollama(
            prompts[sec], ip, model=model, num_predict=num_predict
        )
        print(f"[INFO] Section {sec} complete.")

    for sec in prompts:
        t = threading.Thread(target=run_section, args=(sec,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 4. Merge results
    full_paper_text = "\n\n".join([
        results_sections.get("A", ""),
        results_sections.get("B", ""),
        results_sections.get("C", ""),
        results_sections.get("D", ""),
        results_sections.get("E", "")
    ])

    raw_lines = [line.strip() for line in full_paper_text.splitlines() if line.strip()]
    questions, answer_key = clean_questions(raw_lines)

    # 5. Create PDF
    base_pdf = os.path.join(os.path.dirname(__file__), "data", "base.pdf")
    reader = PdfReader(base_pdf)
    writer = PdfWriter()

    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)

    y = 780
    for q in questions:
        # Section headers
        if q.upper().startswith("SECTION"):
            can.setFont("Helvetica-Bold", 14)
            if y < 100:
                can.showPage()
                y = 780
            can.drawCentredString(300, y, q)
            y -= 30
            continue

        # Question numbers
        if re.match(r"^\d+\)", q):
            can.setFont("Helvetica-Bold", 12)
            if y < 100:
                can.showPage()
                y = 780
            can.drawString(60, y, q)
            y -= 20
            continue

        # Options
        if q.strip().startswith(("a)", "b)", "c)", "d)", "(a)", "(b)", "(c)", "(d)")):
            can.setFont("Helvetica", 11)
            if y < 100:
                can.showPage()
                y = 780
            can.drawString(90, y, q)
            y -= 18
            continue

        # Default text
        can.setFont("Helvetica", 11)
        if y < 100:
            can.showPage()
            y = 780
        can.drawString(60, y, q)
        y -= 18

    # Answer Key
    if answer_key:
        can.showPage()
        can.setFont("Helvetica-Bold", 14)
        can.drawCentredString(300, 800, "ANSWER KEY (SECTION A)")
        y = 760
        can.setFont("Helvetica", 11)
        for ans in answer_key:
            if y < 100:
                can.showPage()
                y = 780
            can.drawString(60, y, ans)
            y -= 20

    can.save()
    packet.seek(0)

    overlay_reader = PdfReader(packet)

    for i, overlay_page in enumerate(overlay_reader.pages):
        if i == 0:
            base_page = reader.pages[0]
            base_page.merge_page(overlay_page)
            writer.add_page(base_page)
        else:
            writer.add_page(overlay_page)

    output_dir = os.path.join(settings.MEDIA_ROOT, "question_papers")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{class_name}_{subject}_unit{unit}_{difficulty}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    file_path = os.path.join(output_dir, filename)

    with open(file_path, "wb") as f:
        writer.write(f)

    return f"question_papers/{filename}"
