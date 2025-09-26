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
    Parse filename to extract class, subject, and unit information.
    
    Examples:
    - data/class11/biology/Class11_biology_unit5.pdf → (11, biology, 5)
    - data/class11/english/Class11_english_unit1.pdf → (11, english, 1)
    - data/class11/english/Class11_english_contents.pdf → (11, english, contents)
    """
    file_name = os.path.basename(file_path).replace(".pdf", "")
    parts = file_name.split("_")

    if len(parts) >= 3:
        class_name = parts[0].replace("Class", "")   # "11"
        subject = parts[1].lower()                   # "biology", "english"
        
        # Handle different unit formats
        unit_part = parts[2]
        if "unit" in unit_part:
            unit = unit_part.replace("unit", "")
        elif "contents" in unit_part:
            unit = "contents"
        else:
            unit = unit_part
            
        return class_name, subject, unit
    else:
        # Fallback for files that don't follow the pattern
        return "unknown", "unknown", "unknown"

def ingest_pdf(file_path, class_name, subject, unit):
    """Extract text from PDF and store as embeddings in Chroma"""
    try:
        reader = PdfReader(file_path)
        text_chunks = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                # Split text into chunks of 500 characters
                chunks = [text[i:i+500] for i in range(0, len(text), 500)]
                text_chunks.extend(chunks)

        # Add chunks to collection with metadata
        for i, chunk in enumerate(text_chunks):
            collection.add(
                documents=[chunk],
                metadatas=[{
                    "class": class_name,
                    "subject": subject,
                    "unit": unit,
                    "source_file": os.path.basename(file_path)
                }],
                ids=[f"{os.path.basename(file_path)}_{i}"]
            )

        print(f"[+] Ingested {len(text_chunks)} chunks from {file_path}")
        return len(text_chunks)
        
    except Exception as e:
        print(f"[-] Error ingesting {file_path}: {e}")
        return 0

def ingest_all_pdfs():
    """Ingest all PDFs from the data directory structure"""
    total_chunks = 0
    total_files = 0
    
    # Walk through all subdirectories
    for root, dirs, files in os.walk(DATA_DIR):
        for file in files:
            if file.endswith('.pdf'):
                file_path = os.path.join(root, file)
                
                # Skip the base.pdf template file
                if os.path.basename(file_path) == 'base.pdf':
                    continue
                    
                # Parse filename to get metadata
                class_name, subject, unit = parse_filename(file_path)
                
                if class_name != "unknown":
                    chunks_added = ingest_pdf(file_path, class_name, subject, unit)
                    total_chunks += chunks_added
                    total_files += 1
                else:
                    print(f"[-] Skipping {file_path} - couldn't parse filename")
    
    print(f"[+] Total: {total_chunks} chunks from {total_files} PDF files ingested")
    return total_chunks, total_files

def ingest_class11_biology():
    """Ingest all Class 11 Biology PDFs (legacy function for backward compatibility)"""
    path = os.path.join(DATA_DIR, "class11", "biology")
    pdf_files = glob.glob(f"{path}/*.pdf")

    total_chunks = 0
    for pdf in pdf_files:
        class_name, subject, unit = parse_filename(pdf)
        chunks = ingest_pdf(pdf, class_name, subject, unit)
        total_chunks += chunks

    print(f"[+] Ingested {total_chunks} chunks from {len(pdf_files)} Class 11 Biology PDFs")
    return total_chunks

def ingest_class11_english():
    """Ingest all Class 11 English PDFs"""
    path = os.path.join(DATA_DIR, "class11", "english")
    pdf_files = glob.glob(f"{path}/*.pdf")

    total_chunks = 0
    for pdf in pdf_files:
        class_name, subject, unit = parse_filename(pdf)
        chunks = ingest_pdf(pdf, class_name, subject, unit)
        total_chunks += chunks

    print(f"[+] Ingested {total_chunks} chunks from {len(pdf_files)} Class 11 English PDFs")
    return total_chunks

def query(class_name, subject, unit, query_text, n_results=5):
    """Search for relevant text chunks with proper Chroma filters"""
    try:
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
    except Exception as e:
        print(f"[-] Error querying embeddings: {e}")
        # Return empty results structure
        return {
            "documents": [[]],
            "metadatas": [[]],
            "ids": [[]],
            "distances": [[]]
        }

def get_available_subjects():
    """Get list of available subjects in the embeddings database"""
    try:
        # Query all documents to get unique subjects
        results = collection.get(
            include=["metadatas"],
            limit=10000  # Get all documents
        )
        
        subjects = set()
        for metadata in results["metadatas"]:
            if metadata and "subject" in metadata:
                subjects.add(metadata["subject"])
        
        return sorted(list(subjects))
    except Exception as e:
        print(f"[-] Error getting available subjects: {e}")
        return []

def get_available_classes():
    """Get list of available classes in the embeddings database"""
    try:
        # Query all documents to get unique classes
        results = collection.get(
            include=["metadatas"],
            limit=10000  # Get all documents
        )
        
        classes = set()
        for metadata in results["metadatas"]:
            if metadata and "class" in metadata:
                classes.add(metadata["class"])
        
        return sorted(list(classes))
    except Exception as e:
        print(f"[-] Error getting available classes: {e}")
        return []

def get_available_units(subject, class_name):
    """Get list of available units for a specific subject and class"""
    try:
        # Query all documents to get unique units for the subject/class
        results = collection.get(
            include=["metadatas"],
            where={
                "$and": [
                    {"class": {"$eq": class_name}},
                    {"subject": {"$eq": subject}},
                ]
            },
            limit=10000
        )
        
        units = set()
        for metadata in results["metadatas"]:
            if metadata and "unit" in metadata:
                units.add(metadata["unit"])
        
        return sorted(list(units))
    except Exception as e:
        print(f"[-] Error getting available units: {e}")
        return []

