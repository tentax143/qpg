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
def get_chroma_client(class_name, subject, school_id=None):
    namespace = "shared" if school_id is None else f"school_{school_id}"
    db_dir = os.path.join("vector_store", namespace, f"{normalize_label(class_name)}_{normalize_label(subject)}")
    os.makedirs(db_dir, exist_ok=True)
    return chromadb.PersistentClient(path=db_dir, settings=chromadb.Settings(anonymized_telemetry=False))


def _reset_collection(chroma_client, name):
    try:
        chroma_client.delete_collection(name=name)
    except Exception:
        pass
    return chroma_client.create_collection(name=name, metadata={"hnsw:space": "cosine"})


def get_collection(class_name, subject, provider='local', reset_if_corrupted=False, school_id=None):
    name = COLLECTION_NAMES.get(provider, 'default')
    chroma_client = get_chroma_client(class_name, subject, school_id=school_id)
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


# ── Copy shared store to a school's private store ─────────────────────────────
def copy_shared_to_school(school_id):
    import shutil
    shared_base = os.path.join("vector_store", "shared")
    school_base = os.path.join("vector_store", f"school_{school_id}")
    if not os.path.exists(shared_base):
        print(f"[Embeddings] No shared store found — nothing to copy")
        return 0
    os.makedirs(school_base, exist_ok=True)
    count = 0
    for dir_name in os.listdir(shared_base):
        src = os.path.join(shared_base, dir_name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(school_base, dir_name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        count += 1
        print(f"[Embeddings] Copied shared/{dir_name} → school_{school_id}/{dir_name}")
    return count


# ── Ingest ────────────────────────────────────────────────────────────────────
def ingest_pdf(class_name, subject, unit, pdf_path, title=None, material_type="textbook", provider='local', school_id=None, page_range=None):
    """Ingest a PDF (or a page range of it) as `unit`. page_range=(start, end) ingests only
    pages [start, end) — used to ingest one chapter out of a whole-book PDF."""
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
        if page_range and not (page_range[0] <= page_num < page_range[1]):
            continue
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

    collection = get_collection(class_name, subject, provider, school_id=school_id)
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
            collection = get_collection(class_name, subject, provider, reset_if_corrupted=True, school_id=school_id)
            collection.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)
        else:
            raise Exception(f"DB error for '{pdf_filename}': {e}")
    return len(ids)


def ingest_text(class_name, subject, unit, text, title=None, material_type="textbook", provider='local', school_id=None):
    """Ingest a raw text blob as `unit` (e.g. one chapter extracted from an HTML book).
    Same chunk → embed → add path as ingest_pdf, minus the PDF reading. Returns chunk count."""
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    if not (text or "").strip():
        return 0

    chunks = [(i, c) for i, c in enumerate(text[j:j+800] for j in range(0, len(text), 800)) if c.strip()]
    if not chunks:
        return 0

    vectors = get_embeddings_batch([c for _, c in chunks], provider)
    collection = get_collection(class_name, subject, provider, school_id=school_id)
    ids, embs, docs, metas = [], [], [], []
    for (i, chunk), emb in zip(chunks, vectors):
        ids.append(f"{class_name}_{subject}_{unit}_{i}")
        embs.append(emb)
        docs.append(chunk)
        metas.append({"class": class_name, "subject": subject, "unit": unit,
                      "title": title or unit, "type": material_type})
    try:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            collection = get_collection(class_name, subject, provider, reset_if_corrupted=True, school_id=school_id)
            collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
        else:
            raise Exception(f"DB error ingesting unit '{unit}': {e}")
    return len(ids)


def ingest_bulk(class_name, subject, chapters, material_type="textbook", provider='local', school_id=None):
    print(f"[Embeddings] Bulk ingest — class={class_name} subject={subject} files={len(chapters)} provider={provider} school_id={school_id}")
    total, failed = 0, []
    for ch in chapters:
        pdf_filename = os.path.basename(ch["file_path"])
        try:
            n = ingest_pdf(class_name, subject, ch["unit"], ch["file_path"],
                           title=ch.get("title"), material_type=material_type, provider=provider, school_id=school_id)
            total += n
            print(f"[Embeddings] OK: {pdf_filename} ({n} chunks)")
        except Exception as e:
            print(f"[Embeddings ERROR] {pdf_filename}: {e}")
            failed.append({"filename": pdf_filename, "error": str(e)})
    if failed:
        print(f"[Embeddings] {len(failed)} PDF(s) failed: {[f['filename'] for f in failed]}")
    return total


# ── Query ─────────────────────────────────────────────────────────────────────
# Remember which collections we've already warned are dimension-mismatched, so a
# broken collection produces ONE clear actionable line — not a stack trace per query.
_DIM_MISMATCH_WARNED = set()


def query(class_name, subject, unit, query_text, n_results=5, provider='local', school_id=None):
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def _do_query(coll, nr):
        return coll.query(
            query_embeddings=[get_embedding(query_text, provider)],
            n_results=nr,
            where={"unit": unit} if unit else {},
            include=["embeddings", "documents", "metadatas", "distances"]
        )

    try:
        collection = get_collection(class_name, subject, provider, school_id=school_id)

        # If the school-specific store is empty, fall back to the shared store automatically.
        effective_school_id = school_id
        if school_id and collection.count() == 0:
            print(f"[Embeddings] school_{school_id}/{class_name}_{subject} is empty — falling back to shared store")
            collection = get_collection(class_name, subject, provider, school_id=None)
            effective_school_id = None

        total = collection.count()
        safe_n = min(n_results, total) if total > 0 else 0
        if safe_n == 0:
            return empty

        # Guard: the collection must have been built with the same embedding model we
        # query with, or ChromaDB rejects every query on a dimension mismatch and we'd
        # silently generate ungrounded papers. Detect it cheaply and surface it ONCE.
        expected_dim = EMBED_DIMS.get(provider)
        try:
            embs = collection.get(limit=1, include=["embeddings"]).get("embeddings")
            coll_dim = len(embs[0]) if embs is not None and len(embs) > 0 and embs[0] is not None else None
        except Exception:
            coll_dim = None
        if expected_dim and coll_dim and coll_dim != expected_dim:
            key = (class_name, subject, effective_school_id)
            if key not in _DIM_MISMATCH_WARNED:
                _DIM_MISMATCH_WARNED.add(key)
                print(f"[Embeddings] ⚠️  DIM MISMATCH {class_name}/{subject} "
                      f"(school_id={effective_school_id}): collection is {coll_dim}-dim but the "
                      f"'{provider}' model is {expected_dim}-dim. Returning NO context — fix with "
                      f"`python manage.py fix_embedding_dims --apply`.")
            return empty

        return _do_query(collection, safe_n)
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            try:
                get_collection(class_name, subject, provider, reset_if_corrupted=True, school_id=school_id)
            except Exception:
                pass
            return empty
        raise


# ── Delete embeddings ─────────────────────────────────────────────────────────
def delete_unit_embeddings(class_name, subject, unit, school_id=None):
    """Remove all embedding chunks for a unit from every provider's collection."""
    class_name = normalize_label(class_name)
    subject    = normalize_label(subject)
    unit       = normalize_label(unit)
    if not unit:
        return
    for provider in COLLECTION_NAMES:
        try:
            col = get_collection(class_name, subject, provider, school_id=school_id)
            ids = col.get(where={"unit": unit}, include=[])["ids"]
            if ids:
                col.delete(ids=ids)
                print(f"[Embeddings] Deleted {len(ids)} chunks for unit='{unit}' ({provider}) school_id={school_id}")
        except Exception as e:
            print(f"[Embeddings] Could not delete embeddings for unit='{unit}' ({provider}): {e}")


def delete_subject_embeddings(class_name, subject, school_id=None):
    """Drop the entire vector store directory for a class+subject."""
    import shutil
    namespace = "shared" if school_id is None else f"school_{school_id}"
    db_dir = os.path.join("vector_store", namespace, f"{normalize_label(class_name)}_{normalize_label(subject)}")
    if os.path.exists(db_dir):
        try:
            shutil.rmtree(db_dir)
            print(f"[Embeddings] Deleted vector store: {db_dir}")
        except Exception as e:
            print(f"[Embeddings] Could not delete vector store '{db_dir}': {e}")


# ── List units ────────────────────────────────────────────────────────────────
def list_units(class_name, subject, provider='local', school_id=None):
    try:
        col = get_collection(class_name, subject, provider, school_id=school_id)
        results = col.get(include=["metadatas"])
        return sorted(set(m["unit"] for m in results["metadatas"]))
    except Exception as e:
        if "invalid literal for int" in str(e) or "base 16" in str(e):
            try:
                get_collection(class_name, subject, provider, reset_if_corrupted=True, school_id=school_id)
            except Exception:
                pass
            return []
        raise
