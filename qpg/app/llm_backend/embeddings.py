import os
import glob
import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

# Path where NCERT/CBSE PDFs are stored
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Initialize Chroma client (persists embeddings in ./data/chroma_store/)
chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chroma_store"))

# Define embedding function (SentenceTransformers)
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# Create or get collection
collection = chroma_client.get_or_create_collection(
    name="qpg_ncert",
    embedding_function=embedding_fn
)

def parse_filename(file_path):
    """
    Example: data/class11/biology/Class11_biology_unit5.pdf
    """
    file_name = os.path.basename(file_path).replace(".pdf", "")
    parts = file_name.split("_")

    class_name = parts[0].replace("Class", "")   # "11"
    subject = parts[1].lower()                   # "biology"
    unit = parts[2].replace("unit", "") if "unit" in parts[2] else "0"

    return class_name, subject, unit


def ingest_pdf(file_path, class_name, subject, unit):
    """Extract text from PDF and store as embeddings in Chroma"""
    reader = PdfReader(file_path)
    text_chunks = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            chunks = [text[i:i+500] for i in range(0, len(text), 500)]
            text_chunks.extend(chunks)

    for i, chunk in enumerate(text_chunks):
        collection.add(
            documents=[chunk],
            metadatas=[{
                "class": class_name,
                "subject": subject,
                "unit": unit
            }],
            ids=[f"{os.path.basename(file_path)}_{i}"]
        )

    print(f"[+] Ingested {len(text_chunks)} chunks from {file_path}")


def ingest_class11_biology():
    """Ingest all Class 11 Biology PDFs"""
    path = os.path.join(DATA_DIR, "class11", "biology")
    pdf_files = glob.glob(f"{path}/*.pdf")

    for pdf in pdf_files:
        class_name, subject, unit = parse_filename(pdf)
        ingest_pdf(pdf, class_name, subject, unit)

    print(f"[+] Ingested {len(pdf_files)} Class 11 Biology PDFs")


def query(class_name, subject, unit, query_text, n_results=5):
    """Search for relevant text chunks with proper Chroma filters"""
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results,
        where={
            "$and": [
                {"class": {"$eq": class_name}},
                {"subject": {"$eq": subject}},
                {"unit": {"$eq": unit}},
            ]
        }
    )
    return results

