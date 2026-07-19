# Chapter Metadata Enrichment + Distribution Fixes

Status: **PHASE 1 (enrichment pipeline) IMPLEMENTED 2026-07-15** — see §5. Companion
fixes 1–5 (§4) and retrieval usage of the labels (§3 "Usage at retrieval") are still
pending.
Origin: user report — generated papers sometimes have multiple questions coming from the
same unit/chapter. Full pipeline audit performed; root causes below are verified with
file:line references against the code as of this date.

---

## 1. Problem

Questions cluster on one unit even though a per-question chapter plan exists. The audit
found the plan is advisory-only, and retrieval usually hands the LLM context from a
single chapter regardless of the plan.

## 2. What exists today (verified)

### Checks currently performed
| Stage | Mechanism | Where | Strength |
|---|---|---|---|
| Planning | `_allocate_chapters_to_slots` — per-slot plan, score `weight/(1+covered)`, paper-wide `covered` dict | `core/section_generator.py:4170`, `plan_chapter_allocation:4191` | Deterministic, works. Languages get uniform weight 1 (`UNIT_MARKS_WEIGHTS` in `core/data/cbse_patterns.py:1145` covers only 10 English-named subjects). |
| Prompt | `CHAPTER ASSIGNMENT — MANDATORY` block; plan collapsed via `Counter` to aggregate counts | `core/section_generator.py:688-698` | Text-only. Per-slot spec lines (926-1048) carry **no chapter**, so plan[i] is never bound to slot i. |
| Prompt | "no chapter monopoly" strict rule 7; LA/CBQ individual path's `AVOID chapters already used` list from self-reported `chapter_tag` | `:661-664`, `:2730-2734`, `:2874-2876` | Advisory; defeated by omitted/variant tags. |
| Validation | `validate_section_output` (drives retries) | `:1886-2054` | **Never reads `chapter_tag`.** No retry ever fires for chapter violations. |
| Top-up | `_top_up_short_section` seeds coverage from tags, allocates `topup_plan` | `:3119-3222` | Runs only on COUNT shortfall; acceptance filter never checks chapter; fresh section-local `covered` dict. |
| Audit | `audit_chapter_coverage` | `core/paper_audit.py:216-281` | Coverage FLOOR only: ok if every planned chapter got ≥1 question anywhere paper-wide. `offplan` counted but unused. Teacher badge ("Completed ⚠") appears only when a chapter got ZERO questions. |
| Audit | V8 coherence audit asks LLM "any chapter >50% over-represented?" | `core/section_generator.py:4611-4679` | Fed `set(chapter_tags)` (counts destroyed), result stored write-only (`_coherence_report`), stripped before DOCX, returns `coherent:True` on LLM failure. |
| Dedup | V5 L1/L2, cross-section dedup | `:2119`, `:2175`, `:4437` | Text/concept similarity only — two different questions from the same unit pass. |
| Cross-paper | `check_question_similarity` | `core/generator.py:377` | **Dead code** (zero call sites); `save_generated_question` records `chapter=chapters[0]`, not the real tag. |

### Root causes of same-unit clustering (ranked)
1. **Retrieval tail-truncation (HIGH, verified).** `get_section_context`
   (`core/section_generator.py:3626-3664`) queries per chapter with weighted quotas but
   appends docs chapter-by-chapter and returns `context[:8000]` (~8 chunks of ~1000
   chars). The FIRST chapter alone yields 12k–60k chars → later chapters get zero
   representation. Prompt then demands both "base questions strictly on these excerpts"
   (:654) and "EXACTLY this distribution" (:694) — unsatisfiable; the model clusters or
   fabricates tags.
2. **Plan advisory-only (HIGH).** No enforcement anywhere post-generation (see table).
3. **Tamil Unicode bug (FIXED, pending regen).** `normalize_label` stripped non-ASCII →
   no ChunkChapter links → whole-book retrieval. Fixed + migration 0039 backfill.
   Pre-fix papers must be regenerated; migration must run on prod.
4. **By-design repetition.** Pigeonhole (slots > chapters) and D'Hondt weighting (heavy
   CBSE chapter repeats before light one is covered — only affects the 10 weighted
   subjects; docstring at :4174 is misleading for skewed weights).
5. **Per-MATERIAL chapter links.** `_store_chunks` links every chunk to ALL of a
   material's unit labels (`core/embeddings.py:315`) — multi-chapter materials match
   every unit filter. Migration 0039's backfill did the same.
6. **Source-blind plan.** `general`/`unseen` slots consume plan entries; all-general
   sections still burn paper-wide `covered` counts; `unseen` slots get no exemption in
   the chapter block (:694 vs :705-710).
7. **Misc:** Context-QC broad retry drops the chapter filter (:3990-3995, non-grammar);
   AR-repair defaults missing tag to `chapters[0]` (:3043); extract spans capped at
   first 3 chapters (:3689); `chapter_tag` self-reported, never verified vs content.

---

## 3. Decision: LLM metadata enrichment at ingestion (NOT full RAPTOR)

RAPTOR was considered and rejected: collapsed-tree top-k worsens chapter balance
(multi-chapter summary nodes dominate, fuzzy chapter attribution), summaries break
verbatim needs (extract passages, answer keys), big clustering/summarization infra, and
it fixes none of the enforcement gaps. The agreed direction:

**Read each chapter whole at ingestion, have an LLM classify its chunks, persist the
labels, and turn retrieval steering into hard DB filters.**

### Design (agreed)
- **When:** once at ingestion (or lazily on first use, cached). NEVER per-generation.
- **Granularity:** per-chunk labels, produced with the WHOLE chapter in the prompt
  (chunk boundaries marked, response = `chunk_id → labels` mapping). Batching unit =
  one chapter per LLM call (~20–50k chars; merge/split only for outliers).
- **Taxonomy: CLOSED enums** (free-form labels rot — see the AI-pattern
  `question_types`→"other" failure):
  - `content_kind`: `prose | poem | grammar | exercise | supplementary | intro | other`
    (allow 1–2 dominant labels per chunk — chunks straddle boundaries)
  - `language` (script/language of the chunk)
  - `unit` — TRUE per-chunk chapter attribution (fixes root cause #5: whole-book
    uploads where splitting failed)
  - `garbled: bool` — legacy-font extraction noise flag (e.g. மண்பாணையங்கள்-type
    gibberish), free corpus-quality detection
- **Bonus from the same call:** a 300–500 char **chapter summary**, stored as one extra
  special chunk (`kind='summary'`) with normal ChunkChapter links — whole-chapter
  grounding for LA/essay/theme questions (the useful part of RAPTOR for ~zero cost).
- **Storage:** new columns or metadata JSON on `MaterialChunk`; reuse pgvector,
  school/store scoping (`access.visibility_q`), and the unit filter unchanged.
- **Validation:** temperature 0; returned chunk IDs must exist; labels must be in enum;
  fail open to unlabeled. Same fail-open philosophy as `identify_grammar_chapters`.
- **Backfill:** Celery/management command over the existing corpus in batches
  (pattern: migration 0039 / `audit_papers`).
- **Usage at retrieval:** slot type → content-kind filter (extract→poem/prose,
  grammar→grammar, LA→summary+leaves, MCQ/VSA→leaves only). Existing
  `fetch_contiguous_span` stays for verbatim passages.
- **Cost:** ~15 chapters/book × 1 call at ingestion — trivial vs one paper generation.

### Companion fixes that MUST ride along (retrieval upgrade alone won't stop clustering)
1. **Interleave/per-chapter budget** in `get_section_context` BEFORE the `[:max_chars]`
   cut (fixes root cause #1; with chapter summaries, one 8000-char context can carry
   all planned chapters: summary + 1–2 filtered leaves each).
2. **Bind the plan per-slot:** append assigned chapter to each slot spec line
   (`| chapter: {plan[i]}`); enumerate allowed `chapter_tag` values in the schema
   instead of the free-form placeholder.
3. **Enforce:** add a chapter_tag-vs-plan distribution check to
   `validate_section_output` so the existing retry loop fires on violations. Make the
   plan source-aware (skip `general`/`unseen` slots; don't burn `covered` for them).
4. **Surface:** extend `coverage_summary_line`/audit to report concentration
   (per-chapter counts + offplan), so teachers see a ⚠ badge for clustering, not just
   zero-coverage misses.
5. **Cheap cleanups:** keep chapter filter on Context-QC broad retry; pass plan into
   the LA/CBQ individual path; V5L2 regen targets an under-covered chapter; fix
   AR-repair `chapters[0]` default; wire up or delete dead `check_question_similarity`.

### Suggested order of implementation
1. Companion fixes 1–3 (small, deterministic, immediately measurable)
2. Enrichment pass: schema/migration → classification prompt + Celery task → backfill
3. Retrieval assembly switch to metadata filters + summaries
4. Audit/surfacing (fix 4) + measure with extended `audit_papers`
   (per-chapter question counts vs plan) before any further retrieval work

---

## 5. Implemented 2026-07-15 — enrichment pipeline (phase 1)

- **Schema (migrations 0040 + 0041):** `MaterialChunk` gained `kind` ('body'|'summary',
  indexed), `content_kinds` (JSON list, closed enum), `language`, `garbled`,
  `enriched_at` (null = pending, indexed), and `content_clean` (0041 — selective
  LLM-cleaned copy for mixed/noisy chunks only: page noise / glued-on book-back
  questions removed, kept text verbatim, original `content` never mutated; empty =
  already clean). New `EnrichmentRun` model = durable backfill progress row
  (status/counters/tokens/cost/error_samples). `UsageEvent` gained kind `enrichment`.
- **Taxonomy REMOVED (2026-07-15, user decision after seeing first results):** the
  content-kind classification (prose/poem/…/exercise) is NOT what the user wanted the
  pipeline to do. Enrichment now stores ONLY: chapter attribution (unit link) + class +
  subject (already on the row) + chapter summary + actual content (`content_clean` for
  noisy chunks) + `garbled` flag. `content_kinds`/`language` columns remain as legacy
  (summary rows still use content_kinds=["summary"]); re-runs wipe old taxonomy values.
  Retrieval phase should NOT plan on kind filters — use chapter links, summaries and
  content_clean instead.
- **`core/enrichment.py`:** `enrich_material(material_id, force)` — batches a
  material's body chunks (≤24k chars/call), one GEN_MODEL call per batch at temp 0.0,
  ids `c0..cN` validated against input (hallucinated ids/enums dropped, fail open),
  per-chunk unit re-links ChunkChapter ONLY when the material declares >1 chapters,
  chapter summaries stored as `kind='summary'` chunks at `chunk_index -1000-i` with
  normal unit links. Textbook double-copies (shared + school) are labeled once and
  mirrored by (chunk_index, identical content) — LLM never paid twice; unmirrorable
  copies get their own pass.
- **`core/tasks.py`:** `enrich_material_task` (one material per task — solo worker
  stays responsive, idempotent via enriched_at) + `_enqueue_enrichment` hooks at the
  end of `ingest_material_task`, `split_book_task`, `ingest_url_task` → every new
  upload auto-enriches. Re-ingest on chapter edit re-enriches automatically (chunks
  are recreated → enriched_at null).
- **Retrieval guards:** `_scoped_chunks` and `fetch_contiguous_span` exclude
  `kind='summary'` so summaries can't pollute ANN retrieval or verbatim spans until
  the metadata-aware retrieval phase lands.
- **API:** `GET /api/admin/enrichment/stats/` (live DB coverage counters + latest run),
  `POST /api/admin/enrichment/run/` ({force}) — 409 if a fresh run is in progress,
  auto-fails runs stale >15 min.
- **Frontend:** `/superadmin/enrichment` page (stats cards, Process Stored Chunks
  button, force checkbox, progress bar polling stats every 3 s — survives refresh) +
  Sidebar entry.
- **Tests:** `core.tests.EnrichmentTest` (6 tests: labeling/relink/summaries, skip,
  force, mirroring, fail-open, span/query exclusion).

*Context notes: Celery worker must be restarted by the user (never by Claude) for any
core/ change to take effect — required before the enrichment task exists in the worker.
Migration 0039 AND 0040 must run on prod at next deploy. Pre-fix
Tamil papers need regeneration to clear the whole-book-retrieval clustering.*
