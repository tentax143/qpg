import os, re, requests
import chromadb
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
import concurrent.futures

# ── OpenRouter ────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY    = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL      = 'nvidia/llama-nemotron-embed-vl-1b-v2:free'
OPENROUTER_DIM        = 2048
OPENROUTER_BATCH_SIZE = 64

# ── Ollama (local) ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL     = 'nomic-embed-text'
OLLAMA_DIM       = 768
OLLAMA_SUB_BATCH = 32   # chunks per single Ollama request
OLLAMA_WORKERS   = 4    # parallel Ollama requests (match OLLAMA_NUM_PARALLEL env var)

# ── Collection names (separate per provider to avoid dim mismatch) ────────────
COLLECTION_NAMES = {
    'local':       'default',
    'openrouter':  'openrouter',
}
EMBED_DIMS = {
    'local':       OLLAMA_DIM,
    'openrouter':  OPENROUTER_DIM,
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize_label(label: str) -> str:
    if not label:
        return None
    clean = label.lower().replace(" ", "_").replace("-", "_")
    clean = re.sub(r"[^a-z0-9_]", "", clean)
    return re.sub(r"_+", "_", clean).strip("_")


# ── OpenRouter ────────────────────────────────────────────────────────────────
def _openrouter_embed_batch(texts: list) -> list:
    if not OPENROUTER_API_KEY:
        return [[0.0] * OPENROUTER_DIM for _ in texts]
    try:
        r = requests.post(
            'https://openrouter.ai/api/v1/embeddings',
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}', 'Content-Type': 'application/json'},
            json={'model': OPENROUTER_MODEL, 'input': texts},
            timeout=60,
        )
        r.raise_for_status()
        data = sorted(r.json()['data'], key=lambda x: x['index'])
        return [item['embedding'] for item in data]
    except Exception as e:
        print(f"[Embeddings/OpenRouter] Batch failed: {e}")
        return [[0.0] * OPENROUTER_DIM for _ in texts]


def _embed_openrouter(texts: list) -> list:
    out = []
    for i in range(0, len(texts), OPENROUTER_BATCH_SIZE):
        batch = texts[i:i + OPENROUTER_BATCH_SIZE]
        print(f"[Embeddings/OpenRouter] batch {i // OPENROUTER_BATCH_SIZE + 1}/{-(-len(texts) // OPENROUTER_BATCH_SIZE)} ({len(batch)} chunks)")
        out.extend(_openrouter_embed_batch(batch))
    return out


# ── Ollama (local, parallel) ──────────────────────────────────────────────────
def _ollama_embed_sub_batch(texts: list) -> list:
    """Single Ollama request for a sub-batch of texts."""
    try:
        r = requests.post(
            f'{OLLAMA_BASE_URL}/v1/embeddings',
            json={'model': OLLAMA_MODEL, 'input': texts},
            timeout=120,
        )
        r.raise_for_status()
        data = sorted(r.json()['data'], key=lambda x: x['index'])
        return [item['embedding'] for item in data]
    except Exception as e:
        print(f"[Embeddings/Ollama] Sub-batch failed: {e}")
        return [[0.0] * OLLAMA_DIM for _ in texts]


def _embed_ollama(texts: list) -> list:
    """Split into sub-batches and run OLLAMA_WORKERS in parallel."""
    sub_batches = [texts[i:i + OLLAMA_SUB_BATCH] for i in range(0, len(texts), OLLAMA_SUB_BATCH)]
    results = [None] * len(sub_batches)
    print(f"[Embeddings/Ollama] {len(texts)} chunks → {len(sub_batches)} sub-batches × {OLLAMA_WORKERS} workers")
    with concurrent.futures.ThreadPoolExecutor(max_workers=OLLAMA_WORKERS) as pool:
        futures = {pool.submit(_ollama_embed_sub_batch, batch): idx for idx, batch in enumerate(sub_batches)}
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    return [v for batch in results for v in batch]


# ── Public API ────────────────────────────────────────────────────────────────
def get_embeddings_batch(texts: list, provider: str = 'local') -> list:
    if provider == 'openrouter':
        return _embed_openrouter(texts)
    return _embed_ollama(texts)


def get_embedding(text: str, provider: str = 'local') -> list:
    return get_embeddings_batch([text], provider)[0]


# ── ChromaDB helpers ──────────────────────────────────────────────────────────
def get_chroma_client(class_name, subject):
    db_dir = os.path.join("vector_store", f"{normalize_label(class_name)}_{normalize_label(subject)}")
    os.makedirs(db_dir, exist_ok=True)
    return chromadb.PersistentClient(path=db_dir, settings=chromadb.Settings(anonymized_telemetry=False))


def _reset_collection(chroma_client, name):
    try:
        chroma_client.delete_collection(name=name)
    except Exception:
        pass
    return chroma_client.create_collection(name=name, metadata={"hnsw:space": "cosine"})


def get_collection(class_name, subject, provider='local', reset_if_corrupted=False):
    name = COLLECTION_NAMES.get(provider, 'default')
    chroma_client = get_chroma_client(class_name, subject)
    try:
        col = chroma_client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
    except Exception as e:
        print(f"[Embeddings] Collection open failed ({e}), resetting…")
        return _reset_collection(chroma_client, name)
    try:
        col.count()
    except Exception as e:
        print(f"[Embeddings] Collection read failed ({e}), resetting…")
        return _reset_collection(chroma_client, name)
    if reset_if_corrupted:
        return _reset_collection(chroma_client, name)
    return col


# ── Ingest ────────────────────────────────────────────────────────────────────
def ingest_pdf(class_name, subject, unit, pdf_path, title=None, material_type="textbook", provider='local'):
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    pdf_filename = os.path.basename(pdf_path)

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        raise Exception(f"Cannot read PDF '{pdf_filename}': {e}")

    text = ""
    pages_skipped = 0
    for page_num, page in enumerate(reader.pages):
        try:
            text += page.extract_text() or ""
        except Exception as e:
            err = str(e)
            is_pdf_err = (
                isinstance(e, (PdfReadError, ValueError)) or
                any(k in err.lower() for k in ("invalid literal", "base 16", "hex", "malformed", "corrupted", "invalid elementary"))
            )
            if is_pdf_err:
                pages_skipped += 1
                try:
                    import pdfplumber
                    with pdfplumber.open(pdf_path) as pdf:
                        if page_num < len(pdf.pages):
                            alt = pdf.pages[page_num].extract_text() or ""
                            if alt:
                                text += alt
                                pages_skipped -= 1
                except Exception:
                    pass
            else:
                raise Exception(f"Error on page {page_num + 1} of '{pdf_filename}': {e}")

    if pages_skipped:
        print(f"[Embeddings] '{pdf_filename}' — skipped {pages_skipped} pages")
    if not text.strip():
        raise ValueError(f"No text extracted from '{pdf_filename}'")

    chunks = [(i, c) for i, c in enumerate(text[j:j+800] for j in range(0, len(text), 800)) if c.strip()]
    if not chunks:
        return 0

    print(f"[Embeddings] '{pdf_filename}' — {len(chunks)} chunks, provider={provider}")
    vectors = get_embeddings_batch([c for _, c in chunks], provider)

    collection = get_collection(class_name, subject, provider)
    ids, embeddings, docs, metas = [], [], [], []
    for (i, chunk), emb in zip(chunks, vectors):
        ids.append(f"{class_name}_{subject}_{unit}_{i}")
        embeddings.append(emb)
        docs.append(chunk)
        metas.append({"class": class_name, "subject": subject, "unit": unit,
                      "title": title or pdf_filename, "type": material_type})
    try:
        collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)
        print(f"[Embeddings] Added {len(ids)} chunks from '{pdf_filename}'")
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            collection = get_collection(class_name, subject, provider, reset_if_corrupted=True)
            collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)
        else:
            raise Exception(f"DB error for '{pdf_filename}': {e}")
    return len(ids)


def ingest_bulk(class_name, subject, chapters, material_type="textbook", provider='local'):
    print(f"[Embeddings] Bulk ingest — class={class_name} subject={subject} files={len(chapters)} provider={provider}")
    total, failed = 0, []
    for ch in chapters:
        pdf_filename = os.path.basename(ch["file_path"])
        try:
            n = ingest_pdf(class_name, subject, ch["unit"], ch["file_path"],
                           title=ch.get("title"), material_type=material_type, provider=provider)
            total += n
            print(f"[Embeddings] OK: {pdf_filename} ({n} chunks)")
        except Exception as e:
            print(f"[Embeddings ERROR] {pdf_filename}: {e}")
            failed.append({"filename": pdf_filename, "error": str(e)})
    if failed:
        print(f"[Embeddings] {len(failed)} PDF(s) failed: {[f['filename'] for f in failed]}")
    return total


# ── Query ─────────────────────────────────────────────────────────────────────
def query(class_name, subject, unit, query_text, n_results=5, provider='local'):
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    try:
        collection = get_collection(class_name, subject, provider)
        query_emb  = get_embedding(query_text, provider)
        return collection.query(
            query_embeddings=[query_emb],
            n_results=n_results,
            where={"unit": unit} if unit else {},
            include=["embeddings", "documents", "metadatas", "distances"]
        )
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            try:
                get_collection(class_name, subject, provider, reset_if_corrupted=True)
            except Exception:
                pass
            return empty
        raise


# ── Delete embeddings ─────────────────────────────────────────────────────────
def delete_unit_embeddings(class_name, subject, unit):
    """Remove all embedding chunks for a unit from every provider's collection."""
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    if not unit:
        return
    for provider in COLLECTION_NAMES:
        try:
            col = get_collection(class_name, subject, provider)
            ids = col.get(where={"unit": unit}, include=[])["ids"]
            if ids:
                col.delete(ids=ids)
                print(f"[Embeddings] Deleted {len(ids)} chunks for unit='{unit}' ({provider})")
        except Exception as e:
            print(f"[Embeddings] Could not delete embeddings for unit='{unit}' ({provider}): {e}")


def delete_subject_embeddings(class_name, subject):
    """Drop the entire vector store directory for a class+subject."""
    import shutil
    db_dir = os.path.join("vector_store", f"{normalize_label(class_name)}_{normalize_label(subject)}")
    if os.path.exists(db_dir):
        try:
            shutil.rmtree(db_dir)
            print(f"[Embeddings] Deleted vector store: {db_dir}")
        except Exception as e:
            print(f"[Embeddings] Could not delete vector store '{db_dir}': {e}")


# ── List units ────────────────────────────────────────────────────────────────
def list_units(class_name, subject, provider='local'):
    try:
        col = get_collection(class_name, subject, provider)
        results = col.get(include=["metadatas"])
        return sorted(set(m["unit"] for m in results["metadatas"]))
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            try:
                get_collection(class_name, subject, provider, reset_if_corrupted=True)
            except Exception:
                pass
            return []
        raise
