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
from reportlab.lib.utils import simpleSplit
from . import embeddings

# Section blueprint: (number of questions, marks each)
SECTION_INFO = {
    "A": (16, 1),  # MCQs
    "B": (5, 2),   # Short answer
    "C": (7, 3),   # Medium answer
    "D": (2, 4),   # Case-based
    "E": (3, 5),   # Long answer
}

SYSTEM_IPS = [f"172.16.71.{i}" for i in range(107, 122)]  # 107–121
MODEL = "gpt-oss:latest"
MAX_RETRIES = 5

# ------------------------------
# Call remote Ollama
# ------------------------------
def call_remote_ollama(prompt, ip, model=MODEL, num_predict=800):
    try:
        url = f"http://{ip}:11434/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": num_predict}
        }
        resp = requests.post(url, json=payload, timeout=100000)
        resp.raise_for_status()
        return resp.json()["response"]
    except Exception as e:
        print(f"[ERROR] {ip} exception: {e}")
        return None

# ------------------------------
# Section-specific prompts
# ------------------------------
SECTION_PROMPTS = {
    "A": """
    SECTION A (1 mark each)
    Generate exactly question {q_start}.
    Use ONLY this NCERT context: {context}.
    
    Format strictly as:
    {q_start}) Question text
       a) option
       b) option
       c) option
       d) option
    Answer: (a)

    Rules:
    - Restrict strictly to NCERT Class XI Biology, Chapters 4-7.
    - ONLY multiple-choice questions with 4 options and one correct answer.
    - Do not include explanations or hints.
    - Do not prefix with "Question" or "(1 mark)".
    """,

    "B": """
    SECTION B (2 marks each)
    Generate exactly question {q_start}.
    Each must be a 2-mark short descriptive BIOLOGY question.
    Use ONLY this NCERT context: {context}.
    Chapters allowed: Animal Kingdom, Morphology of Flowering Plants, Anatomy of Flowering Plants, Structural Organisation in Animals.

    Rules:
    - STRICTLY descriptive (2-3 sentences).
    - NEVER include a/b/c/d options.
    - NEVER include "Answer:" lines.
    - Do not provide hints or append "(2 marks)".
    - Format: "{q_start}) Question text"
    """,

    "C": """
    SECTION C (3 marks each)
    Generate exactly question {q_start}.
    Each must be a 3-mark medium descriptive BIOLOGY question.
    Use ONLY this NCERT context: {context}.
    Chapters allowed: Animal Kingdom, Morphology of Flowering Plants, Anatomy of Flowering Plants, Structural Organisation in Animals.

    Rules:
    - STRICTLY descriptive (4-5 sentences or structured points).
    - NEVER include a/b/c/d options.
    - NEVER include "Answer:" lines.
    - Do not provide hints or append "(3 marks)".
    - Format: "{q_start}) Question text"
    """,

    "D": """
    SECTION D (Case-based, 4 marks each)
    Generate exactly question {q_start}.
    Each should be a BIOLOGY passage followed by 2 descriptive sub-questions.
    Use ONLY this NCERT context: {context}.
    Chapters allowed: Animal Kingdom, Morphology of Flowering Plants, Anatomy of Flowering Plants, Structural Organisation in Animals.

    Rules:
    - STRICTLY descriptive passage + sub-questions.
    - NEVER include a/b/c/d options.
    - NEVER include "Answer:" lines.
    - Format:
      {q_start}) Passage text
         a) sub-question
         b) sub-question
    """,

    "E": """
    SECTION E (Long-answer, 5 marks each)
    Generate exactly question {q_start}.
    Each must be a 5-mark descriptive/long-answer BIOLOGY question.
    Use ONLY this NCERT context: {context}.
    Chapters allowed: Animal Kingdom, Morphology of Flowering Plants, Anatomy of Flowering Plants, Structural Organisation in Animals.

    Rules:
    - STRICTLY descriptive (long essay/structured).
    - NEVER include a/b/c/d options.
    - NEVER include "Answer:" lines.
    - Do not append "(5 marks)".
    - Format: "{q_start}) Question text"
    """
}

# ------------------------------
# Cleaning helper
# ------------------------------
def clean_and_split(text, expected_count, offset=0, section="A"):
    questions, answers = [], []
    if not text:
        return questions, answers

    text = re.sub(r"\*\*|##|STOP.*|Note:.*", "", text)
    text = re.sub(r"(Here are.*|Okay.*|I've.*|Now.*)", "", text)
    text = text.replace("■", "")
    text = re.sub(r"Q\s*(\d+)[\.:]?", r"\1)", text)
    text = re.sub(r"(\d+)\.", r"\1)", text)
    text = re.sub(r"(\d+\))\s*:", r"\1", text)

    raw_qs = re.split(r"(?:^|\n)(\d+\))", text)
    cleaned = []
    for i in range(1, len(raw_qs), 2):
        qnum = raw_qs[i].strip()
        qbody = raw_qs[i+1].strip() if i+1 < len(raw_qs) else ""
        cleaned.append(f"{qnum} {qbody}")

    if not cleaned:
        return [text.strip()], []

    for i, raw in enumerate(cleaned[:expected_count], 1):
        qtext = raw
        ans = None

        # Separate answer only in Section A
        if "Answer:" in raw and section == "A":
            parts = raw.split("Answer:")
            qtext = parts[0].strip()
            ans = parts[1].strip()

        q_lines = []
        for line in qtext.split("\n"):
            line = line.strip()
            # Strip MCQ-style lines from B–E
            if section != "A" and (re.match(r"^[a-d]\)", line.lower()) or line.lower().startswith("answer:")):
                continue
            q_lines.append(line)

        if ")" in q_lines[0]:
            formatted = f"{i+offset}) {q_lines[0].split(')',1)[1].strip()}"
        else:
            formatted = f"{i+offset}) {q_lines[0]}"
        questions.append(formatted)
        questions.extend(q_lines[1:])

        if ans:
            answers.append(f"Q{i+offset}. {ans}")

    return questions, answers

# ------------------------------
# PDF text wrapping helper
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
# Node Health Management
# ------------------------------
node_failures = {ip: 0 for ip in SYSTEM_IPS}
unhealthy_nodes = set()

def get_next_node(current_ip):
    for ip in SYSTEM_IPS:
        if ip not in unhealthy_nodes and ip != current_ip:
            return ip
    return None

# ------------------------------
# Main generator
# ------------------------------
def generate_paper(class_name, subject, unit, difficulty):
    # 🔹 Build context from units 4–7
    units = ["4", "5", "6", "7"]
    contexts = []
    for u in units:
        results = embeddings.query(
            class_name=class_name,
            subject=subject,
            unit=u,
            query_text="biology",
            n_results=30
        )
        chunks = results["documents"]
        contexts.extend([doc for docs in chunks for doc in docs])
    context = "\n".join(contexts) if contexts else "No context found"

    # 🔹 Build jobs (1 question per job)
    jobs = []
    sys_index = 0
    for sec, (count, marks) in SECTION_INFO.items():
        for q_start in range(1, count + 1):
            prompt = SECTION_PROMPTS[sec].format(
                q_start=q_start, context=context
            )
            jobs.append((sec, q_start, q_start, SYSTEM_IPS[sys_index], prompt))
            sys_index = (sys_index + 1) % len(SYSTEM_IPS)

    job_results = {}
    lock = threading.Lock()

    def worker(sec, q_start, q_end, ip, prompt):
        success = False
        attempt = 1
        current_ip = ip

        while attempt <= MAX_RETRIES:
            print(f"[INFO] {current_ip} generating {sec} Q{q_start} (attempt {attempt})...")
            resp = call_remote_ollama(prompt, current_ip)
            if resp:
                with lock:
                    job_results[(sec, q_start)] = resp
                print(f"[INFO] {current_ip} finished {sec} Q{q_start}")
                success = True
                break
            else:
                print(f"[WARN] {current_ip} failed {sec} Q{q_start} (attempt {attempt})")
                node_failures[current_ip] += 1
                if node_failures[current_ip] >= MAX_RETRIES:
                    unhealthy_nodes.add(current_ip)
                    print(f"[ERROR] Marking {current_ip} as UNHEALTHY")
                    fallback_ip = get_next_node(current_ip)
                    if fallback_ip:
                        print(f"[INFO] Rerouting job {sec} Q{q_start} to {fallback_ip}")
                        current_ip = fallback_ip
                        attempt = 0
            attempt += 1

        if not success:
            print(f"[ERROR] FAILED {sec} Q{q_start} after trying multiple nodes")
            with lock:
                job_results[(sec, q_start)] = ""

    # 🔹 Run jobs in parallel
    threads = []
    for sec, q_start, q_end, ip, prompt in jobs:
        t = threading.Thread(target=worker, args=(sec, q_start, q_end, ip, prompt))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # 🔹 Merge results
    all_questions, answer_key, q_offset = [], [], 0
    for sec in ["A", "B", "C", "D", "E"]:
        count, marks = SECTION_INFO[sec]
        total = count * marks
        header = f"SECTION {sec} ({marks} mark each)" if marks == 1 else f"SECTION {sec} ({marks} marks each)"
        all_questions.append(("header", f"{header} ({count} × {marks} = {total})"))
        section_texts = [job_results[j] for j in sorted(job_results) if j[0] == sec]
        merged_text = "\n".join(section_texts)
        qs, ans = clean_and_split(merged_text, count, offset=q_offset, section=sec)
        for q in qs:
            all_questions.append(("q", q))
        if sec == "A":
            answer_key.extend(ans)
        q_offset += count

    # 🔹 Write PDF
    base_pdf = os.path.join(os.path.dirname(__file__), "data", "base.pdf")
    reader = PdfReader(base_pdf)
    writer = PdfWriter()
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    y = 700
    for typ, text in all_questions:
        if typ == "header":
            can.setFont("Helvetica-Bold", 14)
            parts = text.rsplit("(", 1)
            if len(parts) == 2:
                left_text = parts[0].strip()
                right_text = "(" + parts[1]
                can.drawCentredString(300, y, left_text)
                can.drawRightString(550, y, right_text)
            else:
                can.drawCentredString(300, y, text)
            y -= 40
            continue
        if typ == "q":
            if re.match(r"^\d+\)", text):
                y = draw_wrapped(can, text, 60, y, 470, font="Helvetica-Bold", size=12)
            else:
                y = draw_wrapped(can, text, 60, y, 470, font="Helvetica", size=11)
    if answer_key:
        can.showPage()
        can.setFont("Helvetica-Bold", 14)
        can.drawCentredString(300, 800, "ANSWER KEY (SECTION A)")
        y = 760
        can.setFont("Helvetica", 11)
        for ans in answer_key:
            y = draw_wrapped(can, ans, 60, y, 470, font="Helvetica", size=11)
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



# from app.llm_backend import generator

# # Example run
# pdf_path = generator.generate_paper(class_name="11",subject="biology",unit="term1",difficulty="medium")

# print("Generated PDF:", pdf_path)


# from app.llm_backend import embeddings

# # Query with a dummy text just to pull docs
# results = embeddings.query(class_name="11",subject="biology",unit="2",query_text="biology",n_results=10)

# print("Documents:", results.get("documents", []))
# print("Metadatas:", results.get("metadatas", []))

