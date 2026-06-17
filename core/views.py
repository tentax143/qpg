import os
import docx


def extract_text_from_pdf(pdf_path):
    """Extract text content from a PDF file."""
    if not os.path.exists(pdf_path):
        return f"PDF file not found: {pdf_path}"

    try:
        import PyPDF2
        from PyPDF2.errors import PdfReadError
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                try:
                    text += (page.extract_text() or "") + "\n"
                except Exception:
                    continue
            if text.strip():
                return text[:5000]
    except Exception as e:
        print(f"[PDF Extract] PyPDF2 error: {str(e)[:100]}, trying pdfplumber...")

    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    text += (page.extract_text() or "") + "\n"
                except Exception:
                    continue
        return text[:5000] if text.strip() else "Could not extract text from PDF (may be image-based)"
    except ImportError:
        return "pdfplumber not installed — run: pip install pdfplumber"
    except Exception as e:
        return f"Could not extract PDF content: {e}"


def extract_text_from_docx(docx_file):
    """Extract text content from a DOCX file."""
    try:
        document = docx.Document(docx_file)
        return "\n".join(p.text for p in document.paragraphs)
    except Exception as e:
        return f"Could not extract DOCX content: {e}"
