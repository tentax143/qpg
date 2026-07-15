"""LLM metadata enrichment for stored material chunks.

Reads one material's chunks in document order, sends the whole text to the LLM in
batches (chunk boundaries marked, response = chunk_id -> labels mapping) and persists
per-chunk labels on MaterialChunk:

  - content_kinds : 1-2 of the CLOSED enum below (free-form labels rot — see the
                    AI-pattern question_types -> "other" failure)
  - language      : dominant language of the chunk (lowercase word, e.g. "tamil")
  - garbled       : legacy-font / mojibake extraction-noise flag
  - unit          : TRUE per-chunk chapter attribution — rewrites ChunkChapter links
                    when the material declares several chapters (fixes the
                    every-chunk-linked-to-every-chapter blind spot)
  - content_clean : SELECTIVE cleaned copy, returned only for mixed/noisy chunks
                    (page noise or glued-on book-back questions removed, kept text
                    verbatim); the original `content` is never mutated

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

from django.utils import timezone

from . import mantle_client
from .embeddings import normalize_label, get_embeddings_batch, _emb_field
from .answer_key_generator import _extract_json_object, calculate_cost  # noqa: F401 (cost re-exported for tasks)


# Closed taxonomy, subject-agnostic: prose/poem/grammar cover languages & literature,
# concept/example/activity cover science, maths and social science, exercise catches
# book-back questions in any subject.
CONTENT_KINDS = {"prose", "poem", "grammar", "concept", "example", "activity",
                 "exercise", "supplementary", "intro", "other"}

# Chunk text budget per LLM call (~1000-char chunks -> ~16 chunks/call). Sized so that
# even a worst-case response (labels + summaries + selective cleaned rewrites of every
# chunk) fits the max_tokens budget without truncating the JSON. Chapters larger than
# this are split into consecutive batches; each batch still carries the material header
# + declared chapter list so attribution stays grounded.
MAX_BATCH_CHARS = 16000

# Summary chunks get indices far below 0: fetch_contiguous_span expands +-a few indices
# around a body seed, so a summary at -1000-i can never be spliced into a passage.
SUMMARY_INDEX_BASE = -1000

# Key used for the summary of a material with no declared chapter labels.
NO_UNIT_KEY = "__material__"

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
            "order. For EVERY chunk id, classify:\n"
            "- \"kinds\": 1-2 of \"prose\" (story/essay/lesson narrative), \"poem\" (verse/"
            "poetry including its stanzas), \"grammar\" (teaches language structure: letters/"
            "sounds, spelling, sandhi/joining rules, word forms, sentence structure), "
            "\"concept\" (explains a theory/topic — science, maths, social science), "
            "\"example\" (worked example / solved problem), \"activity\" (experiment, "
            "activity, project task), \"exercise\" (book-back questions, workbook tasks), "
            "\"supplementary\" (supplementary-reader content), \"intro\" (preface, contents "
            "page, author bio, acknowledgements), \"other\".\n"
            "- \"unit\": which DECLARED CHAPTER the chunk belongs to — copy the exact string "
            "from the list above, or null if unsure.\n"
            "- \"lang\": dominant language of the chunk text, one lowercase word (e.g. "
            "\"english\", \"tamil\", \"hindi\").\n"
            "- \"garbled\": true if the text is extraction noise / mojibake / mostly "
            "unreadable symbol soup rather than real words.\n"
            "- \"clean\": OPTIONAL — include ONLY when the chunk mixes unrelated content "
            "(e.g. lesson text with book-back questions glued on) or contains extraction "
            "noise (page numbers, running headers/footers, stray garbled fragments). Value "
            "= the chunk's DOMINANT content reproduced VERBATIM with the noise / foreign "
            "parts removed. Never paraphrase, translate or reorder the kept text. OMIT this "
            "key entirely for chunks that are already clean."
        ),
        summary_rule,
        (
            "Return ONLY this JSON shape (every chunk id present, no extra ids):\n"
            "{\"chunks\": {\"c0\": {\"kinds\": [\"prose\"], \"unit\": \"<declared chapter or null>\", "
            "\"lang\": \"english\", \"garbled\": false, \"clean\": \"<only if needed>\"}, ...}, "
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
        kinds_raw = lab.get("kinds") or lab.get("kind") or []
        if isinstance(kinds_raw, str):
            kinds_raw = [kinds_raw]
        kinds = [str(k).strip().lower() for k in kinds_raw if isinstance(k, str)]
        kinds = [k for k in kinds if k in CONTENT_KINDS][:2]
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
            "kinds": kinds,
            "unit": unit,
            "language": str(lab.get("lang") or lab.get("language") or "").strip().lower()[:32],
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
    # Budget: labels + summaries (~1500) plus room for selective cleaned rewrites — worst
    # case the whole batch text comes back cleaned (~1 token per 3 chars).
    batch_chars = sum(len_of.values())
    max_tokens = min(8000, 1500 + 55 * len(batch) + batch_chars // 3)
    total_in = total_out = 0
    correction = None
    last_problem = "no response"
    for attempt in range(2):
        prompt = _batch_prompt(mat, declared_display, batch, id_of, correction=correction)
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
        r.content_kinds = lab["kinds"]
        r.language = lab["language"]
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


def enrich_material(material_id, force=False):
    """Enrich every store copy of one material's chunks. LLM-labels the first copy that
    needs work, mirrors labels to identical sibling copies, and only spends more LLM
    calls on copies the mirror could not cover. Returns a stats dict; raises only on
    unexpected errors (per-batch LLM failures are recorded in stats['errors'])."""
    from .models import Material, MaterialChunk

    stats = {"material_id": material_id, "chunks_labeled": 0, "summaries_created": 0,
             "garbled": 0, "input_tokens": 0, "output_tokens": 0, "skipped": False,
             "errors": []}

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
    if any_work:
        print(f"[Enrich] material {material_id}: labeled {stats['chunks_labeled']} chunks, "
              f"{stats['summaries_created']} summaries, {stats['garbled']} garbled, "
              f"{len(stats['errors'])} errors")
    return stats
