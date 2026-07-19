"""LLM metadata enrichment for stored material chunks.

Reads one material's chunks in document order, sends the whole text to the LLM in
batches (chunk boundaries marked, response = chunk_id -> labels mapping) and persists
per-chunk metadata on MaterialChunk. Deliberately minimal (user decision 2026-07-15 —
no content-kind taxonomy): every chunk ends up carrying chapter name + class + subject
+ chapter summary + its actual content:

  - unit          : TRUE per-chunk chapter attribution — rewrites ChunkChapter links
                    when the material declares several chapters (fixes the
                    every-chunk-linked-to-every-chapter blind spot); class/subject are
                    already on the row from upload
  - content_clean : the chunk's ACTUAL content — a cleaned copy returned only for
                    mixed/noisy chunks (page noise or glued-on unrelated matter
                    removed, kept text verbatim); empty = original is already the
                    actual content. The original `content` is never mutated
  - garbled       : legacy-font / mojibake extraction-noise flag (corpus quality)

plus one 300-500 char chapter summary per declared chapter from the same call, stored
as a special MaterialChunk row (kind='summary', negative chunk_index so it can never
splice into a verbatim span) with a normal ChunkChapter link.

Textbook uploads store TWO copies of every chunk (shared store school=None + the
uploading school) with identical content and chunk_index — the LLM labels ONE copy and
the labels are mirrored to siblings by (chunk_index, identical content), so the LLM is
never paid twice for the same text.

Design doc: docs/CHAPTER_ENRICHMENT_PLAN.md. Fail-open philosophy (house rule for
classification): any LLM/parse failure leaves chunks unlabeled (enriched_at NULL) so a
later run retries them — generation never depends on enrichment having run.
"""

import json
import threading

from django.utils import timezone

from . import mantle_client
from .embeddings import normalize_label, get_embeddings_batch, _emb_field
from .answer_key_generator import _extract_json_object, calculate_cost  # noqa: F401 (cost re-exported for tasks)


# Chunk text budget per LLM call (~1000-char chunks -> ~16 chunks/call). Sized so that
# even a worst-case response (labels + summaries + selective cleaned rewrites of every
# chunk) fits the max_tokens budget without truncating the JSON. Chapters larger than
# this are split into consecutive batches; each batch still carries the material header
# + declared chapter list so attribution stays grounded.
MAX_BATCH_CHARS = 16000

# Parallel enrichment: materials in flight PER API KEY at once. mantle_client rotates
# keys round-robin per call, so a pool of (keys × N) threads keeps ≈N concurrent calls
# on each key. Materials are grouped to this size by enrich_materials_group_task.
# If the console starts showing frequent "[Mantle] HTTP 429" retries, dial this back.
ENRICH_PARALLEL_PER_KEY = 5


def enrich_concurrency():
    """Total concurrent enrichment LLM calls: ENRICH_PARALLEL_PER_KEY per configured
    Mantle key (min 1 key)."""
    return ENRICH_PARALLEL_PER_KEY * max(1, mantle_client.num_keys())


# Process-wide budget on concurrent enrichment LLM calls. One group task already sizes
# its own thread pool to enrich_concurrency(), but on a multi-task worker pool
# (--pool=threads) SEVERAL group tasks can execute at once — without this gate their
# budgets would stack (e.g. 4 tasks × 10 calls = 40 in flight). Every labeling call
# acquires a slot here, so the total stays at the budget however tasks are scheduled.
_CALL_GATE = threading.BoundedSemaphore(max(1, enrich_concurrency()))


# Summary chunks get indices far below 0: fetch_contiguous_span expands +-a few indices
# around a body seed, so a summary at -1000-i can never be spliced into a passage.
SUMMARY_INDEX_BASE = -1000

# Key used for the summary of a material with no declared chapter labels.
NO_UNIT_KEY = "__material__"

# Chapter-LEVEL kinds (ChapterInfo.kind). ONE kind per chapter — deliberately NOT the
# rejected per-chunk taxonomy: a prose lesson whose chunks include back-exercises and a
# grammar box is still, as a whole, prose.
CHAPTER_KINDS = ("prose", "poem", "drama", "supplementary", "grammar")

# prose/poem/drama only mean anything for LANGUAGE subjects — a Mathematics chapter is
# not "prose" in any useful sense (user requirement 2026-07-17). Deterministic gate, no
# LLM needed: matched by token against the normalized subject, so "english core",
# "hindi course b", "tamil" all qualify while mathematics/science/social science never do.
LANGUAGE_SUBJECT_TOKENS = (
    "english", "tamil", "hindi", "sanskrit", "urdu", "french", "german", "spanish",
    "malayalam", "telugu", "kannada", "marathi", "bengali", "punjabi", "gujarati",
    "odia", "assamese",
)


def is_language_subject(subject):
    """True when `subject` is a language/literature paper — the only subjects whose
    chapters get a prose/poem/drama/supplementary/grammar kind."""
    s = normalize_label(subject or "")
    return any(tok in s for tok in LANGUAGE_SUBJECT_TOKENS)

# Chapters per classification LLM call — the whole-corpus backfill (~2000 chapters)
# stays around 70 small calls.
CLASSIFY_BATCH = 30

_SYSTEM_PROMPT = (
    "You label textbook text chunks for a school question-paper generator. "
    "You read any language (English, Tamil, Hindi, Sanskrit, ...). "
    "You always return ONLY a valid JSON object — no markdown fences, no commentary."
)


def _make_batches(rows, max_chars=MAX_BATCH_CHARS):
    """Split ordered chunk rows into consecutive batches of <= max_chars total content."""
    batches, cur, size = [], [], 0
    for r in rows:
        n = len(r.content or "")
        if cur and size + n > max_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += n
    if cur:
        batches.append(cur)
    return batches


def _batch_prompt(mat, declared_display, batch, id_of, correction=None):
    """Whole-batch classification prompt: material header + closed taxonomy + chunk texts."""
    if declared_display:
        chapter_block = "DECLARED CHAPTERS (the ONLY allowed values for \"unit\"):\n" + \
            "\n".join(f"- {u}" for u in declared_display)
        summary_rule = (
            "Also return \"summaries\": for EACH declared chapter that has content in these "
            "chunks, a 300-500 character summary IN ENGLISH of what it covers (topics, "
            "characters, themes). Use the exact chapter strings above as keys."
        )
    else:
        chapter_block = "DECLARED CHAPTERS: none — return null for every \"unit\"."
        summary_rule = (
            "Also return \"summaries\": one 300-500 character summary IN ENGLISH of this "
            f"material under the key \"{NO_UNIT_KEY}\"."
        )

    chunk_lines = []
    for r in batch:
        chunk_lines.append(f"[{id_of[r.pk]}]\n{(r.content or '').strip()}")

    parts = [
        f"MATERIAL: class {mat.class_name} {mat.subject} — \"{mat.title}\" (type: {mat.type})",
        chapter_block,
        (
            f"Below are {len(batch)} consecutive text chunks from this material, in document "
            "order. For EVERY chunk id, return:\n"
            "- \"unit\": which DECLARED CHAPTER the chunk belongs to — copy the exact string "
            "from the list above, or null if unsure.\n"
            "- \"garbled\": true if the text is extraction noise / mojibake / mostly "
            "unreadable symbol soup rather than real words.\n"
            "- \"clean\": OPTIONAL — include ONLY when the chunk mixes unrelated content "
            "or contains extraction noise (page numbers, running headers/footers, stray "
            "garbled fragments). Value = the chunk's ACTUAL content reproduced VERBATIM "
            "with the noise / foreign parts removed. Never paraphrase, translate or "
            "reorder the kept text. OMIT this key entirely for chunks that are already "
            "clean."
        ),
        summary_rule,
        (
            "Return ONLY this JSON shape (every chunk id present, no extra ids):\n"
            "{\"chunks\": {\"c0\": {\"unit\": \"<declared chapter or null>\", "
            "\"garbled\": false, \"clean\": \"<only if needed>\"}, ...}, "
            "\"summaries\": {\"<chapter>\": \"...\"}}"
        ),
    ]
    if correction:
        parts.append(f"CORRECTION: {correction}")
    parts.append("CHUNKS:\n\n" + "\n\n".join(chunk_lines))
    return "\n\n".join(parts)


def _clean_labels(raw_chunks, pk_of, declared_norm, len_of=None):
    """Validate the LLM's chunk map against the input ids and the closed enums.
    Hallucinated ids and out-of-enum values are silently dropped (fail open)."""
    labels = {}
    if not isinstance(raw_chunks, dict):
        return labels
    for cid, lab in raw_chunks.items():
        pk = pk_of.get(str(cid).strip())
        if pk is None or not isinstance(lab, dict):
            continue
        unit = None
        unit_raw = lab.get("unit")
        if isinstance(unit_raw, str) and unit_raw.strip():
            unit = normalize_label(unit_raw)
            if unit not in declared_norm:
                unit = None
        # Selective cleaned copy: must be a real reduction of THIS chunk — a "clean" text
        # noticeably longer than the original is hallucinated content, not a cleanup.
        clean = lab.get("clean")
        clean = clean.strip() if isinstance(clean, str) else ""
        if clean and len_of is not None and len(clean) > 2 * max(200, len_of.get(pk, 0)):
            clean = ""
        labels[pk] = {
            "unit": unit,
            "garbled": bool(lab.get("garbled")),
            "clean": clean,
        }
    return labels


def _clean_summaries(raw_summaries, declared_norm):
    """Keep summaries keyed by a declared (normalized) unit — or NO_UNIT_KEY — and long
    enough to be a real summary. Truncated to 700 chars."""
    out = {}
    if not isinstance(raw_summaries, dict):
        return out
    for key, text in raw_summaries.items():
        if not isinstance(text, str) or len(text.strip()) < 40:
            continue
        if str(key).strip() == NO_UNIT_KEY:
            out[NO_UNIT_KEY] = text.strip()[:700]
            continue
        norm = normalize_label(key)
        if norm in declared_norm:
            out[norm] = text.strip()[:700]
    return out


def _label_batch(mat, declared_display, declared_norm, batch, id_of):
    """One LLM classification call for a batch of chunks, with a single corrective retry.
    Returns (labels_by_pk, summaries, input_tokens, output_tokens); raises on failure."""
    # Validate ONLY against this batch's ids — a hallucinated id from another batch must
    # not overwrite a label for a chunk this call never saw.
    pk_of = {id_of[r.pk]: r.pk for r in batch}
    len_of = {r.pk: len(r.content or "") for r in batch}
    # Budget: labels + summaries (~1200) plus room for selective cleaned rewrites — worst
    # case the whole batch text comes back cleaned (~1 token per 3 chars).
    batch_chars = sum(len_of.values())
    max_tokens = min(8000, 1200 + 30 * len(batch) + batch_chars // 3)
    total_in = total_out = 0
    correction = None
    last_problem = "no response"
    for attempt in range(2):
        prompt = _batch_prompt(mat, declared_display, batch, id_of, correction=correction)
        # The gate stays held through converse's internal 429 backoff — throttling under
        # rate pressure is exactly when we don't want more calls piling in.
        with _CALL_GATE:
            raw, tin, tout = mantle_client.converse(
                model_id=mantle_client.GEN_MODEL, prompt=prompt,
                system_prompt=_SYSTEM_PROMPT, max_tokens=max_tokens, temperature=0.0,
            )
        total_in += tin
        total_out += tout
        payload = _extract_json_object(raw) if (raw or "").strip() else None
        if payload is None:
            last_problem = "response was not a JSON object"
        else:
            labels = _clean_labels(payload.get("chunks"), pk_of, declared_norm, len_of)
            if labels:
                summaries = _clean_summaries(payload.get("summaries"), declared_norm)
                return labels, summaries, total_in, total_out
            last_problem = "no valid chunk ids were labeled"
        correction = (
            f"Your previous response was invalid: {last_problem}. Return ONLY the JSON "
            "object in the exact shape requested, covering every chunk id."
        )
    raise ValueError(f"batch of {len(batch)} chunks failed: {last_problem}")


def _run_is_live(run_id):
    """Combined heartbeat + stop check, one UPDATE query: bump the run's updated_at while
    it is still 'running'. 0 rows updated means a stop was requested (status 'stopping')
    or the run was closed — the caller must pause at the next safe boundary. The bump is
    what keeps a long single-material run from tripping the 15-min staleness auto-fail."""
    if not run_id:
        return True
    from .models import EnrichmentRun
    return EnrichmentRun.objects.filter(id=run_id, status='running').update(
        updated_at=timezone.now()) == 1


def _write_summaries(mat, template_row, school_id, summaries, embedded=None):
    """Replace the summary chunks for one (material, store copy) with fresh ones.
    `embedded` maps unit-key -> vector to reuse embeddings when mirroring copies.
    Returns {unit_key: vector} for the rows written."""
    from .models import MaterialChunk, ChunkChapter
    if not summaries:
        return {}
    MaterialChunk.objects.filter(material_id=mat.id, kind='summary', school_id=school_id).delete()

    keys = sorted(summaries)
    if embedded is None:
        vectors = get_embeddings_batch([summaries[k] for k in keys], template_row.provider)
        embedded = dict(zip(keys, vectors))
    field = _emb_field(template_row.provider)

    vectors_out = {}
    for i, key in enumerate(keys):
        vec = embedded.get(key)
        title = f"Chapter summary — {key if key != NO_UNIT_KEY else mat.title}"[:255]
        kwargs = dict(
            material_id=mat.id, school_id=school_id, class_name=template_row.class_name,
            subject=template_row.subject, title=title, material_type=template_row.material_type,
            chunk_index=SUMMARY_INDEX_BASE - i, content=summaries[key],
            provider=template_row.provider, kind='summary',
            content_kinds=["summary"], enriched_at=timezone.now(),
        )
        if vec is not None:
            kwargs[field] = list(vec)
        row = MaterialChunk.objects.create(**kwargs)
        if key != NO_UNIT_KEY:
            ChunkChapter.objects.bulk_create([ChunkChapter(chunk=row, unit=key)], ignore_conflicts=True)
        vectors_out[key] = vec
    return vectors_out


def _apply_labels(rows, labels_by_pk, rewrite_units, now):
    """Persist labels onto chunk rows; rewrite ChunkChapter links to the LLM's per-chunk
    unit when the material spans several declared chapters. Returns (labeled, garbled)."""
    from .models import MaterialChunk, ChunkChapter
    to_update, relink = [], {}
    garbled = 0
    for r in rows:
        lab = labels_by_pk.get(r.pk)
        if lab is None:
            continue
        r.content_kinds = lab.get("kinds") or []   # legacy field — wiped on re-runs
        r.language = lab.get("language") or ""
        r.garbled = lab["garbled"]
        r.content_clean = lab.get("clean") or ""
        r.enriched_at = now
        garbled += 1 if lab["garbled"] else 0
        to_update.append(r)
        if rewrite_units and lab["unit"]:
            relink[r.pk] = lab["unit"]
    if to_update:
        MaterialChunk.objects.bulk_update(
            to_update, ["content_kinds", "language", "garbled", "content_clean", "enriched_at"],
            batch_size=500)
    if relink:
        ChunkChapter.objects.filter(chunk_id__in=list(relink)).delete()
        ChunkChapter.objects.bulk_create(
            [ChunkChapter(chunk_id=pk, unit=u) for pk, u in relink.items()],
            ignore_conflicts=True)
    return len(to_update), garbled


def classify_chapter_kinds(entries):
    """Batched chapter-kind classification: ONE kind per chapter, judged from the chapter
    NAME + its enrichment summary + a content sample (a poem's verse shape is visible in
    the sample; the book title identifies supplementary readers). Returns
    ({(class_name, subject, unit): kind}, input_tokens, output_tokens). Invalid or
    omitted answers are silently dropped — fail open, an unclassified chapter behaves
    exactly as before."""
    out, total_in, total_out = {}, 0, 0
    for start in range(0, len(entries), CLASSIFY_BATCH):
        batch = entries[start:start + CLASSIFY_BATCH]
        lines = []
        for j, e in enumerate(batch):
            lines.append(
                f"[c{j}] class {e['class_name']} {e['subject']} — chapter: \"{e.get('display') or e['unit']}\"\n"
                f"from book/material: \"{e.get('material_title') or 'unknown'}\"\n"
                f"chapter summary: {(e.get('summary') or '(none)')[:400]}\n"
                f"content sample:\n{(e.get('sample') or '(none)')[:600]}"
            )
        prompt = (
            "Classify each textbook CHAPTER below into exactly ONE kind:\n"
            "- poem: verse / poetry — short lines, stanza breaks, rhythm (any language: "
            "poem, கவிதை, செய்யுள், कविता, पद्य). The content sample's line SHAPE is "
            "strong evidence.\n"
            "- drama: a play — speaker names before their lines, stage directions.\n"
            "- grammar: the chapter TEACHES language rules/usage (grammar, இலக்கணம், "
            "व्याकरण).\n"
            "- supplementary: a chapter from a supplementary / extended reader (e.g. NCERT "
            "\"Footprints Without Feet\", \"Sanchayan\", துணைப்பாடம்) — judge from the "
            "book/material title. This wins over prose/poem when it applies.\n"
            "- prose: any other regular lesson — story, essay, biography, speech, letter.\n"
            "If genuinely unsure about a chapter, use null for it.\n\n"
            "Return ONLY this JSON shape (every id present):\n"
            '{"kinds": {"c0": "prose", "c1": "poem", ...}}\n\n'
            "CHAPTERS:\n\n" + "\n\n".join(lines)
        )
        try:
            with _CALL_GATE:
                raw, tin, tout = mantle_client.converse(
                    model_id=mantle_client.GEN_MODEL, prompt=prompt,
                    system_prompt=_SYSTEM_PROMPT,
                    max_tokens=min(2500, 200 + 30 * len(batch)), temperature=0.0)
            total_in += tin
            total_out += tout
        except Exception as e:
            print(f"[Enrich] chapter classify batch failed: {e}")
            continue
        payload = _extract_json_object(raw) if (raw or "").strip() else None
        kinds = payload.get("kinds") if isinstance(payload, dict) else None
        if not isinstance(kinds, dict):
            continue
        for j, e in enumerate(batch):
            k = kinds.get(f"c{j}")
            if isinstance(k, str) and k.strip().lower() in CHAPTER_KINDS:
                out[(e['class_name'], e['subject'], e['unit'])] = k.strip().lower()
    return out, total_in, total_out


def upsert_chapter_kinds(kind_map):
    """Persist classifier output onto ChapterInfo rows (create or update)."""
    from .models import ChapterInfo
    now = timezone.now()
    for (cls, subj, unit), kind in kind_map.items():
        ChapterInfo.objects.update_or_create(
            class_name=cls, subject=subj, unit=unit,
            defaults={'kind': kind, 'classified_at': now})


def _classify_material_chapters(mat, rows, labels_by_pk, declared_display, declared_norm,
                                summaries, force):
    """Chapter-kind hook for one material: classify its declared chapters that have no
    kind yet (all of them under force). Uses data already in hand — the just-computed
    summaries and per-chunk unit attributions — so it costs one tiny extra LLM call.
    Returns (input_tokens, output_tokens, chapters_classified)."""
    from .models import ChapterInfo
    cls, subj = rows[0].class_name, rows[0].subject
    if not is_language_subject(subj):
        return 0, 0, 0   # kinds are a language-subject concept — never label Maths "prose"
    display_of = {normalize_label(d): d for d in declared_display}
    todo = sorted(declared_norm) if force else sorted(
        set(declared_norm) - set(
            ChapterInfo.objects.filter(class_name=cls, subject=subj,
                                       unit__in=list(declared_norm))
            .exclude(kind='').values_list('unit', flat=True)))
    if not todo:
        return 0, 0, 0

    # One sample chunk per chapter, from the LLM's own unit attributions.
    samples = {}
    for r in rows:
        lab = labels_by_pk.get(r.pk) or {}
        u = lab.get("unit")
        if u and u not in samples and not lab.get("garbled"):
            samples[u] = lab.get("clean") or (r.content or "")
    fallback = next((r.content for r in rows if (r.content or "").strip()), "")

    entries = [{
        'class_name': cls, 'subject': subj, 'unit': u,
        'display': display_of.get(u, u),
        'material_title': mat.title or '',
        'summary': summaries.get(u, ''),
        'sample': samples.get(u) or (fallback if len(todo) == 1 else ''),
    } for u in todo]
    kind_map, tin, tout = classify_chapter_kinds(entries)
    upsert_chapter_kinds(kind_map)
    if kind_map:
        print(f"[Enrich] material {mat.id}: classified {len(kind_map)} chapter(s): "
              + ", ".join(f"{u}={k}" for (_, _, u), k in sorted(kind_map.items())))
    return tin, tout, len(kind_map)


def enrich_material(material_id, force=False, run_id=None):
    """Enrich every store copy of one material's chunks. LLM-labels the first copy that
    needs work, mirrors labels to identical sibling copies, and only spends more LLM
    calls on copies the mirror could not cover. Returns a stats dict; raises only on
    unexpected errors (per-batch LLM failures are recorded in stats['errors']).

    `run_id` ties the work to an EnrichmentRun: before every LLM batch the run is
    heartbeat-checked (_run_is_live) so a Stop takes effect mid-material, not just
    between materials. Aborts are per-copy ATOMIC: labels are only persisted after ALL
    of a copy's batches succeeded, so a stopped copy stays fully pending (enriched_at
    NULL) and the resume run redoes it cleanly — tokens already spent are still
    reported in stats for billing. stats['stopped'] tells the caller it was paused."""
    from .models import Material, MaterialChunk

    stats = {"material_id": material_id, "chunks_labeled": 0, "summaries_created": 0,
             "garbled": 0, "chapters_classified": 0, "input_tokens": 0, "output_tokens": 0,
             "skipped": False, "stopped": False, "errors": []}

    mat = Material.objects.filter(id=material_id).first()
    if mat is None:
        stats.update(skipped=True, reason="material missing")
        return stats

    def copy_qs(sid):
        qs = MaterialChunk.objects.filter(material_id=material_id, kind='body')
        return qs.filter(school__isnull=True) if sid is None else qs.filter(school_id=sid)

    school_ids = sorted(
        set(MaterialChunk.objects.filter(material_id=material_id, kind='body')
            .values_list('school_id', flat=True)),
        key=lambda s: (s is not None, s or 0))  # shared copy (None) first
    if not school_ids:
        stats.update(skipped=True, reason="no chunks")
        return stats

    raw_units = (mat.metadata or {}).get("chapters") or ([mat.unit] if mat.unit else [])
    declared_display = [str(u) for u in raw_units if str(u or "").strip()]
    declared_norm = {normalize_label(u) for u in declared_display if normalize_label(u)}
    # Per-chunk unit rewriting only helps (and is only safe) when the material spans
    # several declared chapters; single-chapter materials keep their exact link.
    rewrite_units = len(declared_norm) > 1

    done_schools = set()
    any_work = False
    while True:
        if not _run_is_live(run_id):
            stats["stopped"] = True
            break
        # target school_id can legitimately be None (the shared-store copy), so a separate
        # flag — not `target is None` — decides whether a copy still needs work.
        picked, target, rows = False, None, None
        for sid in school_ids:
            if sid in done_schools:
                continue
            qs = copy_qs(sid)
            if force or qs.filter(enriched_at__isnull=True).exists():
                picked, target, rows = True, sid, list(qs.order_by('chunk_index'))
                break
            done_schools.add(sid)
        if not picked:
            break
        if not rows:
            done_schools.add(target)
            continue
        any_work = True

        # ── LLM-label the target copy, batch by batch ──
        id_of = {r.pk: f"c{i}" for i, r in enumerate(rows)}
        labels_by_pk, summaries = {}, {}
        for batch in _make_batches(rows):
            if not _run_is_live(run_id):
                stats["stopped"] = True
                break
            try:
                labels, batch_summaries, tin, tout = _label_batch(
                    mat, declared_display, declared_norm, batch, id_of)
                labels_by_pk.update(labels)
                for k, v in batch_summaries.items():
                    if len(v) > len(summaries.get(k, "")):
                        summaries[k] = v
                stats["input_tokens"] += tin
                stats["output_tokens"] += tout
            except Exception as e:
                print(f"[Enrich] material {material_id}: {e}")
                stats["errors"].append(str(e)[:300])
        if stats["stopped"]:
            # Per-copy atomicity: nothing from a partially-labeled copy is persisted, so
            # the copy stays fully pending and the resume run redoes it whole. The tokens
            # spent on completed batches are already in stats and get billed.
            break

        now = timezone.now()
        labeled, garbled = _apply_labels(rows, labels_by_pk, rewrite_units, now)
        stats["chunks_labeled"] += labeled
        stats["garbled"] += garbled

        summary_vectors = {}
        try:
            summary_vectors = _write_summaries(mat, rows[0], target, summaries)
            stats["summaries_created"] += len(summary_vectors)
        except Exception as e:
            print(f"[Enrich] material {material_id}: summary write failed: {e}")
            stats["errors"].append(f"summary write failed: {str(e)[:200]}")
        done_schools.add(target)

        # Chapter-kind classification (ChapterInfo — one kind per chapter, school-
        # agnostic): once per material, from the first successfully labeled copy.
        if labels_by_pk and declared_norm and not stats["chapters_classified"]:
            try:
                tin, tout, n = _classify_material_chapters(
                    mat, rows, labels_by_pk, declared_display, declared_norm, summaries, force)
                stats["input_tokens"] += tin
                stats["output_tokens"] += tout
                stats["chapters_classified"] = n
            except Exception as e:
                print(f"[Enrich] material {material_id}: chapter classify failed: {e}")
                stats["errors"].append(f"chapter classify failed: {str(e)[:200]}")

        # ── Mirror to sibling copies: identical (chunk_index, content) rows get the same
        # labels for free; anything the mirror can't match stays pending and gets its own
        # LLM pass on the next loop iteration. ──
        by_index = {r.chunk_index: r for r in rows if r.pk in labels_by_pk}
        for sib in school_ids:
            if sib in done_schools:
                continue
            sib_rows = list(copy_qs(sib).order_by('chunk_index'))
            mirrored = {}
            for s in sib_rows:
                src = by_index.get(s.chunk_index)
                if src is not None and s.content == src.content:
                    mirrored[s.pk] = labels_by_pk[src.pk]
            if not mirrored:
                continue
            labeled, garbled = _apply_labels(sib_rows, mirrored, rewrite_units, now)
            stats["chunks_labeled"] += labeled
            stats["garbled"] += garbled
            try:
                stats["summaries_created"] += len(
                    _write_summaries(mat, sib_rows[0], sib, summaries, embedded=summary_vectors))
            except Exception as e:
                print(f"[Enrich] material {material_id}: sibling summary write failed: {e}")
            if len(mirrored) == len(sib_rows):
                # Fully covered by the mirror — never spend an LLM pass on it (matters
                # under force=True, where the pending check alone would re-target it).
                done_schools.add(sib)

    stats["skipped"] = not any_work
    if stats["stopped"]:
        print(f"[Enrich] material {material_id}: paused by stop request "
              f"({stats['input_tokens'] + stats['output_tokens']} tokens spent on aborted copy)")
    elif any_work:
        print(f"[Enrich] material {material_id}: labeled {stats['chunks_labeled']} chunks, "
              f"{stats['summaries_created']} summaries, {stats['garbled']} garbled, "
              f"{len(stats['errors'])} errors")
    return stats
