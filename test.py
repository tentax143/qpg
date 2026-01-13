import json, os
from datetime import datetime
from io import BytesIO
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit

# ---------------------------
# Config
# ---------------------------
BASE_PATH = r"D:\qpg\core\data\base.pdf"       # path to your base template
INPUT_JSON = r"D:\qpg\temp_raw.json"      # your generated questions
OUTPUT_PDF = r"D:\qpg\core\final_question_paper.pdf"


# ---------------------------
# Helpers
# ---------------------------
def draw_wrapped(can, text, x, y, max_width, font="Helvetica", size=11, line_height=16):
    """Draw text with word wrapping + auto page break."""
    can.setFont(font, size)
    lines = simpleSplit(text, font, size, max_width)
    for line in lines:
        if y < 100:  # start new page if space runs out
            can.showPage()
            can.setFont(font, size)
            y = 780
        can.drawString(x, y, line)
        y -= line_height
    return y


# ---------------------------
# PDF Rendering
# ---------------------------
def render_pdf(data):
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    y = 700  # start lower to avoid clashing with base.pdf header

    # Title
    can.setFont("Helvetica-Bold", 16)
    can.drawCentredString(300, 780, "Class XI English Core Question Paper")
    can.setFont("Helvetica", 11)
    can.drawCentredString(300, 760, f"Generated on {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    # Iterate sections
    for sec, sec_info in data.items():
        y -= 40
        can.setFont("Helvetica-Bold", 14)
        can.drawString(60, y, f"SECTION {sec} – {sec_info['title']} ({sec_info['marks']} Marks)")
        y -= 30

        # Subsections
        subsections = sec_info.get("subsections", {})
        for sub, q_list in subsections.items():
            can.setFont("Helvetica-Bold", 12)
            y = draw_wrapped(can, sub.upper(), 60, y, 470)
            y -= 10

            for q in q_list:
                qnum = q.get("qnum", "")
                if "question" in q:
                    y = draw_wrapped(can, f"{qnum}. {q['question']}", 60, y, 470)
                elif "passage" in q:
                    y = draw_wrapped(can, f"{qnum}. {q.get('instruction','Read the passage:')}", 60, y, 470)
                    y = draw_wrapped(can, q["passage"], 80, y, 440, font="Helvetica-Oblique", size=10, line_height=14)
                elif "extract" in q:
                    y = draw_wrapped(can, f"{qnum}. Extract:", 60, y, 470)
                    y = draw_wrapped(can, q["extract"], 80, y, 440, font="Helvetica-Oblique", size=10, line_height=14)

                # Handle nested questions
                if "questions" in q:
                    for i, subq in enumerate(q["questions"], start=1):
                        if isinstance(subq, dict):
                            y = draw_wrapped(can, f"({i}) {subq['question']}", 80, y, 440)
                        else:
                            y = draw_wrapped(can, f"({i}) {subq}", 80, y, 440)

                # Gap filling / items
                if "sentences" in q:
                    for s in q["sentences"]:
                        y = draw_wrapped(can, f"- {s}", 80, y, 440)
                if "words" in q:
                    y = draw_wrapped(can, " ".join(q["words"]), 80, y, 440)

                y -= 10

    can.save()
    packet.seek(0)

    # Merge with base.pdf
    overlay_reader = PdfReader(packet)
    base_reader = PdfReader(BASE_PATH)
    writer = PdfWriter()

    for i, overlay_page in enumerate(overlay_reader.pages):
        if i < len(base_reader.pages):
            base_page = base_reader.pages[i]
            base_page.merge_page(overlay_page)   # overlay text on top of base
            writer.add_page(base_page)
        else:
            writer.add_page(overlay_page)

    with open(OUTPUT_PDF, "wb") as f:
        writer.write(f)

    print(f"✅ PDF generated: {OUTPUT_PDF}")


# ---------------------------
# Main
# ---------------------------
if __name__ == "__main__":
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    render_pdf(data)
