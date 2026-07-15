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
    # Non-ASCII chars must survive: Indic-script chapter names (Tamil/Hindi/…) otherwise
    # normalize to "" — ChunkChapter links were never created for them at ingestion and the
    # unit filter in query() silently vanished, so every "per-chapter" retrieval searched
    # the whole book. ASCII labels keep the exact old behavior (a-z, 0-9, _ only).
    if not label:
        return None
    clean = label.lower().replace(" ", "_").replace("-", "_")
    clean = "".join(
        ch for ch in clean
        if not ch.isascii() or ch == "_" or "a" <= ch <= "z" or "0" <= ch <= "9"
    )
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
    """Deprecated no-op. Sharing is now scope-based (core.access.visibility_q): a school granted
    access_shared_vector_store sees the shared store directly at query time, so there is nothing
    to copy. Kept as a stub so existing callers don't break."""
    return 0


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  pgvector-backed store (replaces ChromaDB).                                ║
# ║  One MaterialChunk row per chunk, embedded once; chapter membership is a   ║
# ║  many-to-many (ChunkChapter) so a multi-chapter note is stored ONCE.       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Separator hierarchy, most-natural boundary first: paragraph → line → sentence → clause → word.
_CHUNK_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def _split_recursive(text, size, seps):
    """Break `text` into pieces each <= `size`, splitting on the FIRST separator in `seps` that
    occurs — so we cut on paragraph breaks before line breaks before sentences before words, and
    only hard-cut mid-word as a last resort. Returns a flat list of pieces (separators retained)."""
    if len(text) <= size:
        return [text]
    sep, rest = "", []
    for i, s in enumerate(seps):
        if s == "":
            break  # exhausted natural separators → hard split below
        if s in text:
            sep, rest = s, seps[i + 1:]
            break
    if sep == "":
        return [text[j:j + size] for j in range(0, len(text), size)]
    pieces = []
    parts = text.split(sep)
    for k, part in enumerate(parts):
        piece = part + (sep if k < len(parts) - 1 else "")
        if not piece:
            continue
        if len(piece) > size:
            pieces.extend(_split_recursive(piece, size, rest))
        else:
            pieces.append(piece)
    return pieces


def _merge_with_overlap(pieces, size, overlap):
    """Greedily pack pieces into chunks <= ~size, carrying a word-aligned `overlap` tail from the
    previous chunk into the next so context isn't severed at a boundary."""
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) > size:
            chunks.append(cur.strip())
            if overlap > 0:
                tail = cur[-overlap:]
                sp = tail.find(" ")               # start overlap at a word boundary
                cur = tail[sp + 1:] if sp != -1 else tail
            else:
                cur = ""
        cur += p
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _chunk_text(text, size=1000, overlap=150):
    """Structure-aware chunking (Tier 0): split on natural boundaries (paragraph → line → sentence
    → word) and pack into ~`size`-char chunks with ~15% overlap, instead of arbitrary fixed-width
    cuts. Keeps definitions / worked examples coherent and avoids severing sentences mid-way.
    Returns [(index, chunk_text), …]."""
    text = (text or "").strip()
    if not text:
        return []
    pieces = _split_recursive(text, size, _CHUNK_SEPARATORS)
    chunks = _merge_with_overlap(pieces, size, overlap)
    # Fold a tiny trailing fragment back into the previous chunk so we don't embed a stub.
    if len(chunks) >= 2 and len(chunks[-1]) < size * 0.25:
        chunks[-2] = (chunks[-2] + " " + chunks[-1]).strip()
        chunks.pop()
    return [(i, c) for i, c in enumerate(chunks) if c.strip()]


def _emb_field(provider):
    """Which embedding column a provider writes to / queries (dims differ, so columns differ)."""
    return "embedding_or" if provider == "openrouter" else "embedding_local"


def _read_pdf_text(pdf_path, page_range=None):
    """Extract text from a PDF (or a page range), with a pdfplumber fallback for pages PyPDF2
    chokes on. Returns the concatenated text; raises on unreadable files / no text."""
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
    # Legacy non-Unicode font (Walkman-Chanakya905 / Kruti Dev / DevLys): the extracted bytes are
    # ASCII gibberish. Transcode to real Unicode Devanagari so chunks embed meaningfully. No-op for
    # ordinary Unicode/Latin PDFs (their fonts don't match the legacy-font list).
    from . import legacy_font
    text = legacy_font.decode_if_legacy(pdf_path, text)
    if not text.strip():
        raise ValueError(f"No text extracted from '{pdf_filename}'")
    return text


def _store_chunks(class_name, subject, unit_labels, text, title, material_type, provider, school_id, source_id):
    """Embed `text` once and persist MaterialChunk rows + ChunkChapter links for each unit label.
    The chunk is stored ONE time; `unit_labels` only multiplies the (cheap) chapter links — no
    re-embedding or chunk duplication when a note spans several chapters. Returns chunk count."""
    from .models import MaterialChunk, ChunkChapter
    cls = normalize_label(class_name)
    subj = normalize_label(subject)
    labels = [u for u in (normalize_label(u) for u in unit_labels) if u]

    if not (text or "").strip():
        return 0
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    print(f"[Embeddings] '{title}' — {len(chunks)} chunks, provider={provider}")
    vectors = get_embeddings_batch([c for _, c in chunks], provider)
    field = _emb_field(provider)

    objs = []
    for (i, content), vec in zip(chunks, vectors):
        kwargs = dict(
            material_id=source_id, school_id=school_id, class_name=cls, subject=subj,
            title=(title or "")[:255], material_type=material_type, chunk_index=i,
            content=content, provider=provider,
        )
        kwargs[field] = list(vec)
        objs.append(MaterialChunk(**kwargs))
    created = MaterialChunk.objects.bulk_create(objs)

    if labels:
        links = [ChunkChapter(chunk=c, unit=u) for c in created for u in labels]
        ChunkChapter.objects.bulk_create(links, ignore_conflicts=True)

    print(f"[Embeddings] Stored {len(created)} chunks for '{title}'"
          + (f" across {len(labels)} chapters" if len(labels) > 1 else ""))
    return len(created)


# ── Ingest ────────────────────────────────────────────────────────────────────
def ingest_pdf(class_name, subject, unit, pdf_path, title=None, material_type="textbook",
               provider='local', school_id=None, page_range=None, units=None, source_id=None):
    """Ingest a PDF (or a page range) as one or more chapter labels.

    `units` (plural) attaches the SAME file to several chapters — the file is read + embedded
    ONCE and a single set of chunk rows is linked to every chapter (no duplication). `source_id`
    is the owning Material row id (FK), so a chunk cascades away when its Material is deleted and
    `delete_material_embeddings` can target it precisely."""
    text = _read_pdf_text(pdf_path, page_range)
    unit_labels = units if units else [unit]
    return _store_chunks(class_name, subject, unit_labels, text,
                         title or os.path.basename(pdf_path), material_type, provider, school_id, source_id)


def ingest_text(class_name, subject, unit, text, title=None, material_type="textbook",
                provider='local', school_id=None, source_id=None, units=None):
    """Ingest a raw text blob (e.g. a chapter extracted from an HTML book). Same store path as
    ingest_pdf, minus the PDF reading."""
    unit_labels = units if units else [unit]
    return _store_chunks(class_name, subject, unit_labels, text,
                         title or unit or "", material_type, provider, school_id, source_id)


def ingest_bulk(class_name, subject, chapters, material_type="textbook", provider='local', school_id=None):
    print(f"[Embeddings] Bulk ingest — class={class_name} subject={subject} files={len(chapters)} provider={provider} school_id={school_id}")
    total, failed = 0, []
    for ch in chapters:
        pdf_filename = os.path.basename(ch["file_path"])
        try:
            n = ingest_pdf(class_name, subject, ch["unit"], ch["file_path"],
                           title=ch.get("title"), material_type=material_type, provider=provider,
                           school_id=school_id, units=ch.get("chapters") or None,
                           source_id=ch.get("material_id"))
            total += n
            print(f"[Embeddings] OK: {pdf_filename} ({n} chunks)")
        except Exception as e:
            print(f"[Embeddings ERROR] {pdf_filename}: {e}")
            failed.append({"filename": pdf_filename, "error": str(e)})
    if failed:
        print(f"[Embeddings] {len(failed)} PDF(s) failed: {[f['filename'] for f in failed]}")
    return total


# ── Query ─────────────────────────────────────────────────────────────────────
def _scoped_chunks(cls, subj, field, school_id):
    """Chunks for class+subject that have an embedding in the requested provider's column, scoped
    by MATERIAL VISIBILITY (single source of truth, core.access.visibility_q):
        own school's chunks  ∪  institutional (any school)  ∪  shared (if school granted access).
    school_id None (superadmin / no-school) → shared ∪ institutional. This replaces the old
    copy-shared-into-each-school approach — access changes take effect instantly, no duplication."""
    from .models import MaterialChunk, School
    from .access import visibility_q
    # kind='summary' rows (LLM chapter summaries, core/enrichment.py) are excluded from
    # ordinary ANN retrieval for now — they get their own retrieval path when the
    # metadata-filtered context assembly lands (docs/CHAPTER_ENRICHMENT_PLAN.md §usage).
    base = (MaterialChunk.objects.filter(class_name=cls, subject=subj, **{f"{field}__isnull": False})
            .exclude(kind='summary'))
    school = School.objects.filter(id=school_id).first() if school_id else None
    return base.filter(visibility_q(school, visibility_field="material__visibility",
                                    school_field="school", store_field="material__vector_store"))


def query(class_name, subject, unit, query_text, n_results=5, provider='local', school_id=None):
    """ANN retrieval over the pgvector store. Returns the SAME shape the ChromaDB layer did
    (list-of-one-list per key) so existing consumers in generator/section_generator are unchanged.
    `unit` falsy → search across all chapters of the subject."""
    from pgvector.django import CosineDistance
    cls = normalize_label(class_name)
    subj = normalize_label(subject)
    u = normalize_label(unit)
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    field = _emb_field(provider)

    try:
        vec = get_embedding(query_text, provider)
    except Exception as e:
        print(f"[Embeddings] query embed failed ({provider}): {e}")
        return empty

    try:
        qs = _scoped_chunks(cls, subj, field, school_id)
        if u:
            qs = qs.filter(chapter_links__unit=u)
        rows = list(
            qs.annotate(distance=CosineDistance(field, vec))
              .order_by("distance")[:max(1, int(n_results))]
        )
    except Exception as e:
        print(f"[Embeddings] query failed for {cls}/{subj} unit='{u}': {e}")
        return empty

    if not rows:
        return empty

    ids   = [str(r.id) for r in rows]
    docs  = [r.content for r in rows]
    dists = [float(getattr(r, "distance", 0.0) or 0.0) for r in rows]
    metas = [{"class": cls, "subject": subj, "unit": u, "title": r.title or "",
              "type": r.material_type, "material_id": r.material_id} for r in rows]
    def _vec(v):
        if v is None:
            return []
        return v.tolist() if hasattr(v, "tolist") else list(v)
    embs  = [_vec(getattr(r, field)) for r in rows]
    return {"ids": [ids], "documents": [docs], "metadatas": [metas],
            "distances": [dists], "embeddings": [embs]}


def fetch_contiguous_span(chunk_id, before=1, after=4, max_chars=3500):
    """Extend one chunk with its physical neighbours (same material, adjacent chunk_index)
    into ONE continuous passage as printed in the source, deduping the ~150-char ingestion
    overlap. A single ~1000-char chunk holds only ~170 words, so any pattern that wants a
    longer verbatim extract (e.g. "approximately 500 words") is impossible to satisfy from
    isolated retrieval chunks — this rebuilds the printed page around a retrieved seed."""
    from .models import MaterialChunk
    row = MaterialChunk.objects.filter(id=chunk_id).first()
    if not row:
        return ""
    if row.material_id is None or row.kind == 'summary':
        # No material FK to anchor neighbour order (or an LLM summary chunk, which has no
        # physical neighbours) — the seed chunk is all we can trust.
        return (row.content or "").strip()
    rows = list(
        MaterialChunk.objects.filter(
            material_id=row.material_id,
            kind='body',  # never splice an LLM summary chunk into a verbatim passage
            chunk_index__gte=row.chunk_index - max(0, int(before)),
            chunk_index__lte=row.chunk_index + max(0, int(after)),
        ).order_by("chunk_index").values_list("chunk_index", "content")
    )
    # Keep only the run of CONSECUTIVE indices containing the seed — a gap means missing
    # chunks, and text spliced across it would not be continuous as printed.
    run, cur = [(row.chunk_index, row.content)], []
    for idx, content in rows:
        if cur and idx != cur[-1][0] + 1:
            if any(i == row.chunk_index for i, _ in cur):
                run = cur
                break
            cur = []
        cur.append((idx, content))
    if cur and any(i == row.chunk_index for i, _ in cur):
        run = cur

    span = ""
    for _, content in run:
        c = (content or "").strip()
        if not c:
            continue
        if not span:
            span = c
            continue
        # Adjacent chunks share a word-aligned overlap tail: the next chunk starts with a
        # suffix of the previous one. Find it and splice without duplicating text.
        k = 0
        for size in range(min(len(span), 250), 19, -1):
            if c.startswith(span[-size:]):
                k = size
                break
        span = span + (c[k:] if k else " " + c)
        if len(span) >= max_chars:
            break
    # End at a sentence boundary: both the max_chars cut and an exhausted chunk run can
    # stop mid-sentence, and a model quoting to the block's end would then ship a clipped
    # fragment that the extract validator rejects.
    span = span[:max_chars].strip()
    if span and span[-1] not in ".!?\"'”’…।":
        m = max(span.rfind(". "), span.rfind("? "), span.rfind("! "), span.rfind("।"))
        if m > len(span) * 0.5:
            span = span[:m + 1]
    return span.strip()


# ── Delete ────────────────────────────────────────────────────────────────────
def delete_unit_embeddings(class_name, subject, unit, school_id=None):
    """Delete chunks linked to a chapter label in a given store. For textbooks (1 material ↔ 1
    chapter) this is exact; multi-chapter notes should be deleted via delete_material_embeddings."""
    from .models import MaterialChunk
    cls = normalize_label(class_name)
    subj = normalize_label(subject)
    u = normalize_label(unit)
    if not u:
        return
    qs = MaterialChunk.objects.filter(class_name=cls, subject=subj, chapter_links__unit=u)
    qs = qs.filter(school_id=school_id) if school_id else qs.filter(school__isnull=True)
    n, _ = qs.delete()
    if n:
        print(f"[Embeddings] Deleted {n} rows for unit='{u}' school_id={school_id}")


def delete_material_embeddings(class_name, subject, material_id, school_id=None):
    """Delete only the chunks owned by one Material row (precise — never touches a textbook
    chapter that shares the same unit label)."""
    from .models import MaterialChunk
    if material_id is None:
        return
    n, _ = MaterialChunk.objects.filter(material_id=material_id).delete()
    if n:
        print(f"[Embeddings] Deleted {n} rows for material_id={material_id}")


def delete_subject_embeddings(class_name, subject, school_id=None):
    """Delete every chunk for a class+subject in a given store."""
    from .models import MaterialChunk
    cls = normalize_label(class_name)
    subj = normalize_label(subject)
    qs = MaterialChunk.objects.filter(class_name=cls, subject=subj)
    qs = qs.filter(school_id=school_id) if school_id else qs.filter(school__isnull=True)
    n, _ = qs.delete()
    if n:
        print(f"[Embeddings] Deleted {n} rows for {cls}/{subj} school_id={school_id}")


# ── List units ────────────────────────────────────────────────────────────────
def list_units(class_name, subject, provider='local', school_id=None):
    from .models import ChunkChapter
    cls = normalize_label(class_name)
    subj = normalize_label(subject)
    qs = ChunkChapter.objects.filter(chunk__class_name=cls, chunk__subject=subj)
    qs = qs.filter(chunk__school_id=school_id) if school_id else qs.filter(chunk__school__isnull=True)
    return sorted(set(qs.values_list("unit", flat=True)))
