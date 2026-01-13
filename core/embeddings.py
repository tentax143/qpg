import os, json, boto3, re, requests
import chromadb
from chromadb.config import Settings
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
from django.conf import settings

# ------------------------------
# Embedding Configuration
# ------------------------------
OLLAMA_SERVER = getattr(settings, 'OLLAMA_SERVER', 'http://172.16.71.183:11434')
OLLAMA_MODEL = getattr(settings, 'OLLAMA_MODEL', 'all-minilm:l6-v2')
USE_OLLAMA = getattr(settings, 'USE_OLLAMA', True)

# ------------------------------
# Ollama Embedding Client
# ------------------------------
def ollama_embed(text: str, model_name: str = OLLAMA_MODEL):
    """Get embedding vector from local Ollama server"""
    try:
        response = requests.post(
            f"{OLLAMA_SERVER}/api/embeddings",
            json={
                "model": model_name,
                "prompt": text
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result["embedding"]
    except Exception as e:
        print(f"[Ollama Error] Failed to get embedding: {e}")
        # Fallback to AWS if Ollama fails
        if USE_OLLAMA:
            print("[Ollama] Falling back to AWS Bedrock...")
            return titan_embed(text)
        raise e

# ------------------------------
# AWS Bedrock Titan Client (Fallback)
# ------------------------------
client = boto3.client("bedrock-runtime", region_name="us-east-1")

def titan_embed(text: str):
    """Get embedding vector from Titan Text Embeddings V2 (Fallback)"""
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
# Main Embedding Function
# ------------------------------
def get_embedding(text: str):
    """Get embedding using configured method (Ollama or AWS)"""
    if USE_OLLAMA:
        return ollama_embed(text)
    else:
        return titan_embed(text)

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

def get_collection(class_name, subject, reset_if_corrupted=False):
    """Always get 'default' collection inside that DB"""
    chroma_client = get_chroma_client(class_name, subject)
    try:
        collection = chroma_client.get_or_create_collection(name="default")
        # Test if collection is accessible by trying to get count
        try:
            collection.count()
        except Exception as e:
            if "invalid literal for int" in str(e) or "base 16" in str(e) or reset_if_corrupted:
                print(f"[Embeddings] Collection appears corrupted, resetting...")
                try:
                    chroma_client.delete_collection(name="default")
                except:
                    pass
                collection = chroma_client.create_collection(name="default")
        return collection
    except Exception as e:
        print(f"[Embeddings] Error accessing collection: {e}")
        # Try to reset if corrupted
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            try:
                chroma_client.delete_collection(name="default")
            except:
                pass
            return chroma_client.create_collection(name="default")
        raise

# ------------------------------
# Ingest a single PDF
# ------------------------------
def ingest_pdf(class_name, subject, unit, pdf_path, title=None, material_type="textbook"):
    class_name = normalize_label(class_name)
    subject = normalize_label(subject)
    unit = normalize_label(unit)

    # Get PDF filename for error reporting
    pdf_filename = os.path.basename(pdf_path)
    
    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        error_msg = f"[Embeddings ERROR] Failed to open PDF file: {pdf_filename} | Error: {str(e)}"
        print(error_msg)
        raise Exception(f"Cannot read PDF file '{pdf_filename}': {str(e)}")
    
    text = ""
    pages_processed = 0
    pages_skipped = 0
    
    for page_num, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
            text += page_text
            pages_processed += 1
        except Exception as e:
            # Handle all PDF parsing errors (PyPDF2 errors, ValueError, etc.)
            error_msg = str(e)
            error_type = type(e).__name__
            
            # Check if it's a PDF parsing error
            is_pdf_error = (
                isinstance(e, PdfReadError) or
                isinstance(e, ValueError) or
                "invalid literal for int" in error_msg or
                "base 16" in error_msg or
                "hex" in error_msg.lower() or
                "Invalid Elementary Object" in error_msg or
                "PdfReadError" in error_type or
                "malformed" in error_msg.lower() or
                "corrupted" in error_msg.lower()
            )
            
            if is_pdf_error:
                print(f"[Embeddings] Warning: PDF '{pdf_filename}' - Skipping page {page_num + 1} due to PDF parsing error ({error_type}): {error_msg[:80]}")
                pages_skipped += 1
                # Try alternative: use pdfplumber if available
                try:
                    import pdfplumber
                    with pdfplumber.open(pdf_path) as pdf:
                        if page_num < len(pdf.pages):
                            alt_page = pdf.pages[page_num]
                            alt_text = alt_page.extract_text() or ""
                            if alt_text:
                                text += alt_text
                                pages_processed += 1
                                pages_skipped -= 1
                                print(f"[Embeddings] PDF '{pdf_filename}' - Successfully extracted page {page_num + 1} using pdfplumber fallback")
                except ImportError:
                    # pdfplumber not available, just skip the page
                    pass
                except Exception as fallback_error:
                    # Fallback also failed, skip the page
                    print(f"[Embeddings] PDF '{pdf_filename}' - Fallback extraction also failed for page {page_num + 1}: {str(fallback_error)[:50]}")
            else:
                # Re-raise if it's a different error (not PDF-related)
                print(f"[Embeddings ERROR] PDF '{pdf_filename}' - Non-PDF error on page {page_num + 1}: {error_type}: {error_msg[:100]}")
                raise Exception(f"Error processing PDF '{pdf_filename}' on page {page_num + 1}: {error_msg}")
    
    if pages_skipped > 0:
        print(f"[Embeddings] PDF '{pdf_filename}' - Processed {pages_processed} pages, skipped {pages_skipped} pages due to parsing errors")
    
    if not text.strip():
        error_msg = f"[Embeddings ERROR] No text could be extracted from PDF: {pdf_filename} (path: {pdf_path})"
        print(error_msg)
        raise ValueError(f"No text could be extracted from PDF: {pdf_filename}")

    # Chunk text (approx 500–800 chars each)
    chunks = [text[i:i+800] for i in range(0, len(text), 800)]
    collection = get_collection(class_name, subject)

    ids, embeddings, docs, metas = [], [], [], []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        emb = get_embedding(chunk)
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
        try:
            collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)
            print(f"[Embeddings] Successfully added {len(ids)} chunks from PDF: {pdf_filename}")
        except Exception as e:
            if "invalid literal for int" in str(e) or "base 16" in str(e):
                print(f"[Embeddings] PDF '{pdf_filename}' - Collection corrupted during add, resetting and retrying...")
                # Get fresh collection (will reset if corrupted)
                collection = get_collection(class_name, subject, reset_if_corrupted=True)
                # Retry the add operation
                collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)
                print(f"[Embeddings] PDF '{pdf_filename}' - Successfully added {len(ids)} chunks after collection reset")
            else:
                error_msg = f"[Embeddings ERROR] Failed to add chunks to database for PDF: {pdf_filename} | Error: {str(e)}"
                print(error_msg)
                raise Exception(f"Database error while processing PDF '{pdf_filename}': {str(e)}")

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
    failed_pdfs = []
    
    for ch in chapters:
        pdf_path = ch["file_path"]
        pdf_filename = os.path.basename(pdf_path)
        
        try:
            chunks = ingest_pdf(
                class_name=class_name,
                subject=subject,
                unit=ch["unit"],
                pdf_path=pdf_path,
                title=ch.get("title")
            )
            total_chunks += chunks
            print(f"[Embeddings] Successfully processed PDF: {pdf_filename} ({chunks} chunks)")
        except Exception as e:
            error_msg = f"[Embeddings ERROR] Failed to process PDF: {pdf_filename} | Unit: {ch.get('unit', 'N/A')} | Title: {ch.get('title', 'N/A')} | Error: {str(e)}"
            print(error_msg)
            failed_pdfs.append({
                "filename": pdf_filename,
                "unit": ch.get("unit"),
                "title": ch.get("title"),
                "error": str(e)
            })
            # Continue processing other PDFs even if one fails
            continue
    
    if failed_pdfs:
        print(f"\n[Embeddings ERROR] Summary: {len(failed_pdfs)} PDF(s) failed to process:")
        for failed in failed_pdfs:
            print(f"  - {failed['filename']} (Unit: {failed['unit']}, Title: {failed['title']}): {failed['error'][:100]}")
    
    return total_chunks

# ------------------------------
# Query embeddings
# ------------------------------
def query(class_name, subject, unit, query_text, n_results=5):
    class_name = normalize_label(class_name)
    subject = normalize_label(subject)
    unit = normalize_label(unit)

    try:
        collection = get_collection(class_name, subject)
        query_emb = get_embedding(query_text)

        results = collection.query(
            query_embeddings=[query_emb],
            n_results=n_results,
            where={"unit": unit} if unit else {}
        )
        return results
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            print(f"[Embeddings] Collection corrupted during query, resetting...")
            # Reset collection and return empty results
            try:
                collection = get_collection(class_name, subject, reset_if_corrupted=True)
                # Return empty results structure
                return {
                    "ids": [[]],
                    "documents": [[]],
                    "metadatas": [[]],
                    "distances": [[]]
                }
            except:
                return {
                    "ids": [[]],
                    "documents": [[]],
                    "metadatas": [[]],
                    "distances": [[]]
                }
        raise

# ------------------------------
# List all available units for a class+subject
# ------------------------------
def list_units(class_name, subject):
    """Return all distinct unit names already ingested for given class+subject"""
    try:
        collection = get_collection(class_name, subject)
        # fetch metadata only
        results = collection.get(include=["metadatas"])
        units = sorted(set(m["unit"] for m in results["metadatas"]))
        return units
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            print(f"[Embeddings] Collection corrupted during list_units, resetting...")
            # Reset collection and return empty list
            try:
                get_collection(class_name, subject, reset_if_corrupted=True)
            except:
                pass
            return []
        raise
