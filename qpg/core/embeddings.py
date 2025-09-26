import os, json, boto3, re
import chromadb
from chromadb.config import Settings
from PyPDF2 import PdfReader

# ------------------------------
# Bedrock Titan Client
# ------------------------------
client = boto3.client("bedrock-runtime", region_name="us-east-1")

def titan_embed(text: str):
    """Get embedding vector from Titan Text Embeddings V2"""
    body = {"inputText": text}
    resp = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body)
    )
    result = json.loads(resp["body"].read())
    return result["embedding"]

# ------------------------------
# Helpers
# ------------------------------
def normalize_label(label: str) -> str:
    """Normalize unit/chapter/subject labels for consistency"""
    if not label:
        return None
    # Lowercase
    clean = label.lower()
    # Replace spaces and hyphens with underscores
    clean = clean.replace(" ", "_").replace("-", "_")
    # Remove punctuation/special chars (keep only letters, numbers, underscores)
    clean = re.sub(r"[^a-z0-9_]", "", clean)
    # Remove multiple underscores
    clean = re.sub(r"_+", "_", clean)
    # Strip leading/trailing underscores
    return clean.strip("_")

# ------------------------------
# Per-Class+Subject DB Manager
# ------------------------------
def get_chroma_client(class_name, subject):
    """Each class+subject gets its own ChromaDB directory"""
    db_dir = os.path.join("vector_store", f"{normalize_label(class_name)}_{normalize_label(subject)}")
    os.makedirs(db_dir, exist_ok=True)
    return chromadb.PersistentClient(path=db_dir)

def get_collection(class_name, subject):
    """Always get 'default' collection inside that DB"""
    chroma_client = get_chroma_client(class_name, subject)
    return chroma_client.get_or_create_collection(name="default")

# ------------------------------
# Ingest a single PDF
# ------------------------------
def ingest_pdf(class_name, subject, unit, pdf_path, title=None, material_type="textbook"):
    class_name = normalize_label(class_name)
    subject = normalize_label(subject)
    unit = normalize_label(unit)

    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""

    # Chunk text (approx 500–800 chars each)
    chunks = [text[i:i+800] for i in range(0, len(text), 800)]
    collection = get_collection(class_name, subject)

    ids, embeddings, docs, metas = [], [], [], []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        emb = titan_embed(chunk)
        doc_id = f"{class_name}_{subject}_{unit}_{i}"
        ids.append(doc_id)
        embeddings.append(emb)
        docs.append(chunk)
        metas.append({
            "class": class_name,
            "subject": subject,
            "unit": unit,
            "title": title or os.path.basename(pdf_path),
            "type": material_type
        })

    if ids:
        collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)

    return len(ids)

# ------------------------------
# Bulk ingest multiple PDFs
# ------------------------------
def ingest_bulk(class_name, subject, chapters):
    """
    chapters = [
      {"unit": "Animal Kingdom", "title": "Ch-4 Animal Kingdom", "file_path": "Ch4.pdf"},
      {"unit": "Morphology of Flowering Plants", "title": "Ch-5 Morphology", "file_path": "Ch5.pdf"}
    ]
    """
    total_chunks = 0
    for ch in chapters:
        total_chunks += ingest_pdf(
            class_name=class_name,
            subject=subject,
            unit=ch["unit"],
            pdf_path=ch["file_path"],
            title=ch.get("title")
        )
    return total_chunks

# ------------------------------
# Query embeddings
# ------------------------------
def query(class_name, subject, unit, query_text, n_results=5):
    class_name = normalize_label(class_name)
    subject = normalize_label(subject)
    unit = normalize_label(unit)

    collection = get_collection(class_name, subject)
    query_emb = titan_embed(query_text)

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=n_results,
        where={"unit": unit} if unit else {}
    )
    return results

# ------------------------------
# List all available units for a class+subject
# ------------------------------
def list_units(class_name, subject):
    """Return all distinct unit names already ingested for given class+subject"""
    collection = get_collection(class_name, subject)
    # fetch metadata only
    results = collection.get(include=["metadatas"])
    units = sorted(set(m["unit"] for m in results["metadatas"]))
    return units
