    # QPG Improvement Plan

> **Order: Fix bugs → Fix format → Go agentic.**
> Nothing else matters until active silent failures are stopped.

---

## Phase 1 — Bug Fixes (1–2 days)

These are silent failures happening right now on every generation run.

### Bug 1 — Global Variable Race Condition *(Severity 1 — Data Corruption)*

**File:** `core/generator.py` ~line 2892 and ~line 1895  
**Symptom:** Under concurrent Celery workers, Paper A gets Paper B's class name, time, and max marks in the Word header. No exception raised. Paper marked "done". Teacher receives wrong paper silently.  
**Root cause:** `globals()['__HEADER_META__'] = ...` is set in `generate_with_universal_prompt()` and read in `render_docx()`. Two workers writing the same global at the same time corrupt each other's data.  
**Fix:** Pass `header_meta` as an explicit parameter from `generate_with_universal_prompt()` through to `render_docx()`. Remove the `globals()` write entirely.

---

### Bug 2 — MCQ Options Silently Dropped in PDF *(Severity 1 — Unanswerable Papers)*

**File:** `core/generator.py` — `render_pdf()` function  
**Symptom:** Any paper delivered as PDF has MCQ questions with no answer options. Students receive an unanswerable paper.  
**Root cause:** `render_pdf()` has no `elif typ == "opts_block":` branch. The 2×2 MCQ option table produced by `render_section_questions()` is silently ignored.  
**Fix:** Add the missing `elif` branch in `render_pdf()` that draws options in a 2×2 grid using ReportLab canvas coordinates.

---

### Bug 3 — Embedding Fallback Permanently Broken *(Severity 1 — Any Ollama Outage Kills All Generation)*

**File:** `core/embeddings.py` — `ollama_embed()` and `titan_embed()`  
**Symptom:** Any Ollama restart, timeout, or memory pressure causes an unhandled `RuntimeError` that propagates through the Celery task. Paper status set to "failed" with no useful error message for the teacher.  
**Root cause:** `ollama_embed()` falls back to `titan_embed()` → `titan_embed()` calls `mantle_client.invoke_embed()` → `invoke_embed()` unconditionally raises `RuntimeError("bedrock-runtime is not accessible")`.  
**Fix:** In `ollama_embed()` exception handler, replace `titan_embed()` with a graceful degradation — log a warning and either return a zero vector (generation continues without RAG context) or raise a domain-specific `EmbeddingUnavailableError` with a human-readable message.

---

### Bug 4 — Teacher Instructions Lost Before LLM *(Severity 2 — Wrong Papers, 30-min Fix)*

**File:** `core/blueprint_manager.py` — `normalize_blueprint()`  
**Symptom:** A teacher sets "limit passage to 300–400 words" or custom section instructions via the pattern AI generator. Those instructions are stored correctly in `ExamPattern.sections` JSON. They are silently discarded before the LLM prompt is built. The LLM never sees them.  
**Root cause:** `normalize_blueprint()` strips `passage_instruction`, `extract_instruction`, `instructions`, and `constraints` when processing the `{"sections": [...]}` array format.  
**Fix:** In the array-format processing branch of `normalize_blueprint()`, preserve these four fields per section.

---

### Bug 5 — `total_marks` Drift in ExamPattern *(Severity 3)*

**File:** `core/models.py` — `ExamPattern` model  
**Symptom:** A teacher edits section marks via the API. `total_marks` and `total_questions` stored on the model disagree with the actual sum of sections. The LLM prompt includes the wrong total marks and generates a paper for the wrong mark total.  
**Root cause:** No `save()` override recalculates these denormalised fields.  
**Fix:** Override `ExamPattern.save()` to call `self.total_marks = self.get_total_marks()` and `self.total_questions = self.get_total_questions()` before `super().save()`.

---

### Bug 6 — Semantic Deduplication Never Active *(Severity 3)*

**File:** `core/generator.py` — `check_question_similarity()`  
**Symptom:** Duplicate questions across papers are not caught. Semantic similarity check silently falls back to naive 70% word overlap every time.  
**Root cause:** `collection.query()` call does not include `include=["embeddings"]`, so `results["embeddings"]` is always falsy.  
**Fix:** Add `include=["embeddings", "documents", "metadatas"]` to the `collection.query()` call. One word change.

---

## Phase 2 — Format Fix (3–4 days)

> The LLM is producing reasonable content. The renderer is throwing it away.  
> This is an 80% rendering problem, not a generation problem.

### 2.1 — School Name from Settings

**File:** `core/generator.py`, `qpg/settings.py`  
**Problem:** `"RAMCO VIDYA MANDIR SR. SEC. SCHOOL, THAMARAIKULAM"` hardcoded in both `render_docx()` and `render_pdf()`.  
**Fix:** Add `QPG_SCHOOL_NAME = os.environ.get('QPG_SCHOOL_NAME', '')` to `settings.py`. Thread through `additional_context` → `generate_universal_paper()` → `render_docx()`. Every school gets the right name.

---

### 2.2 — Move Header to Word Header Section

**File:** `core/generator.py` — `render_docx()`  
**Problem:** School name, subject, class, time, marks rendered in a body-area table. Appears on page 1 only. Multi-page papers have no identifying information on later pages.  
**Fix:** Write header content to `doc.sections[0].header` using python-docx header API. Shows on every page.

```python
def build_word_header(doc, school_name, subject, class_name, time_val, marks_val, test_type):
    section = doc.sections[0]
    header = section.header
    p1 = header.paragraphs[0]
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p1.add_run(school_name.upper())
    r.bold = True; r.font.size = Pt(13)
    # ... subject | class | time | marks row
```

---

### 2.3 — General Instructions Block

**File:** `core/generator.py`, new `core/cbse_instructions.py`  
**Problem:** Every CBSE paper starts with numbered general instructions (section structure, internal choices, marks per section, calculator rules). Current output has none.  
**Fix:** Create `core/cbse_instructions.py` with per-subject instruction templates. Emit `("general_instructions", list[str])` as the first tuple in `all_questions`. Add rendering branch in `render_docx()`.

---

### 2.4 — Bordered Passage Boxes

**File:** `core/generator.py` — `render_docx()`  
**Problem:** `("passage", str)` renders as plain italic text. CBSE papers have clearly set-off passages in a visually distinct box.  
**Fix:** Replace the current `para.italic = True` approach with a single-cell table using `OxmlElement` cell borders (single/12pt/black) and light grey shading (`F5F5F5`).

---

### 2.5 — Right-Aligned Marks Notation

**File:** `core/generator.py` — `render_docx()`  
**Problem:** Marks notation `[n marks]` is stripped and never re-added. CBSE papers show marks at the right margin of every question.  
**Fix:** Before stripping, extract the marks value. Add a right-aligned tab stop at 6 inches. Append `\t(n)` to the question run.

```python
para.paragraph_format.tab_stops.add_tab_stop(
    Inches(6.0), WD_TAB_ALIGNMENT.RIGHT
)
# run.add_run(f'\t({marks})')
```

---

### 2.6 — OR with Horizontal Rules

**File:** `core/generator.py` — `render_docx()`  
**Problem:** `("or", "OR")` renders as centered bold. Real CBSE papers have a thin horizontal rule above and below the OR separator.  
**Fix:** Add a paragraph bottom border (via `OxmlElement`) to the paragraph before OR, and a top border to the paragraph after OR.

---

### 2.7 — Assertion-Reason Hard-Coded Options

**File:** `core/generator.py` — `render_section_questions()` and `render_docx()`  
**Problem:** AR canonical options (`"Both A and R are true and R is the correct explanation of A"` etc.) are regenerated by the LLM each time and vary subtly. They must be verbatim and identical on every AR question.  
**Fix:** Add `("q_ar", {"stem": ..., "assertion": ..., "reason": ...})` tuple type. The renderer hard-codes the 4 canonical options — the LLM only generates the assertion and reason text.

---

### 2.8 — Footer with Page Numbers

**File:** `core/generator.py` — `render_docx()`  
**Problem:** No page numbers. No "P.T.O." on intermediate pages.  
**Fix:** Inject `w:fldChar`/`w:instrText` field codes into `doc.sections[0].footer` for "Page X of Y".

---

### 2.9 — Explicit Font Sizes on All Paragraphs

**File:** `core/generator.py` — `render_docx()`  
**Problem:** All paragraphs inherit the blank Document default (machine-dependent). Output looks different on different computers.  
**Fix:** Add explicit `run.font.size = Pt(11)` on all body paragraph types. Section headers get `Pt(13)`.

---

### 2.10 — Move Debug Files Out of Project Root

**File:** `core/generator.py` (all `open("temp_*.txt", "w")` calls)  
**Problem:** `temp_prompt_*.txt`, `temp_response_*.txt`, `temp_raw.json`, `temp_validated.json`, `temp_clean.json`, `debug_render.txt` accumulate in the project root on every generation. Contains full NCERT context and question content. Leaks content on shared servers. Fills disk after thousands of generations.  
**Fix:** Write to `MEDIA_ROOT/debug/`. Add a Celery beat task that deletes debug files older than 48 hours.

---

## Phase 3 — Agentic Pipeline (4–6 days)

> Only after Phase 1 and 2 are stable. Better-generated content in a broken renderer still looks bad.

### 3.1 — Problem with Current Single-Prompt Approach

The current `generate_with_universal_prompt()` sends a 200+ line prompt asking for the entire paper at once. LLM attention degrades on long prompts. A single truncation collapses the whole paper. 4096 token output cap is insufficient for complex papers (a 4-section paper with passages needs 6000+ tokens).

---

### 3.2 — New Pipeline Architecture

```
ORCHESTRATOR AGENT  (qwen.qwen3-32b, temp=0.1)
  Input:  ExamPattern + chapters + difficulty
  Output: SectionWorkOrder list per section
           {id, marks, questions_count, types, instructions,
            passage_instruction, context_queries, token_budget}

  ── Parallel (max 3 concurrent, bounded by API keys) ──
  SECTION GENERATOR AGENT × N  (deepseek.v3.2, temp=0.80)
    Input:  One SectionWorkOrder + section-specific RAG context (2000 chars max)
    Output: Validated JSON for this section only
    Prompt: ~70 lines focused (vs current 200+ line monolith)
    max_tokens: computed — questions_count × 150 + passages × 600, capped at 8192

  CROSS-SECTION VALIDATOR AGENT  (qwen.qwen3-32b, temp=0.1)
    Input:  All section JSONs merged
    Output: Corrected JSON — sequential numbering, mark total verified, dedup checked

RENDERER  (pure Python, zero LLM calls)
  Input:  Validated merged JSON + ExamPattern metadata
  Output: CBSE-formatted Word document
```

**Benefits:**
- Section prompt is 70 lines vs 200+ — far less truncation
- Each section gets full token budget for quality
- Failed sections retry individually — no full paper re-generation
- Wall time: ~20-35s (parallel) vs ~45-90s (sequential) for 5-section paper

---

### 3.3 — New File: `core/section_generator.py`

```python
# Key classes/functions:
@dataclass
class SectionWorkOrder:
    id: str
    name: str
    marks: int
    questions_count: int
    marks_per_question: int
    question_types: list[str]
    passage_instruction: str | None
    extract_instruction: str | None
    instructions: list[str]
    context_text: str          # pre-fetched, section-specific
    estimated_output_tokens: int

def generate_section(work_order: SectionWorkOrder) -> dict
    # Focused prompt (~70 lines)
    # Pydantic schema validation
    # One retry with injected error on schema failure
    # Returns validated section dict

def generate_paper_parallel(pattern, context_map, additional_context) -> dict
    # Creates SectionWorkOrder per section
    # ThreadPoolExecutor(max_workers=3)
    # Merges + validates
    # Falls back to existing single-prompt path if 2+ sections fail
```

---

### 3.4 — Retry Architecture

```
Attempt 1: Generate section
  → Schema validation (Pydantic)
  → PASS → continue
  → FAIL (missing field) → inject error: "Field 'options' missing from Q3"
    Attempt 2 with error context
    → PASS → continue
    → FAIL → emit partial section, set paper.partial_generation = True

  → questions_count mismatch (generated 3, needed 5):
      Completion prompt: "Generate exactly 2 more questions from Q4 onwards"
      (Never retry from scratch for count mismatch)

  → HTTP 429: existing exponential backoff in mantle_client handles it
```

---

### 3.5 — RAG Improvements (alongside agentic work)

**Chunking — replace in `embeddings.py` `ingest_pdf()`:**
- Old: `[text[i:i+800] for i in range(0, len(text), 800)]` — fixed char stride, zero overlap
- New: sentence-aware, 512 tokens per chunk, 75 token overlap (~15%)
- Requires re-ingesting existing PDFs (plan a maintenance window)

**Metadata — add to every chunk:**
```python
{"class_level": int, "chapter": int, "content_type": "text|table|example",
 "page_number": int, "chunk_level": "coarse|fine", "language": "english|hindi|bilingual"}
```

**Context retrieval — replace `get_universal_context()`:**
- Old: 500 shuffled chunks for entire paper fed to one LLM call
- New: 8–10 chunks per section, 2000 chars max, returned as `Dict[section_id, str]`

**Embedding model upgrade:**
- Old: `all-minilm:l6-v2` — English only, 384-dimensional
- New: `BAAI/bge-m3` — multilingual (handles Hindi NCERT), 1024-dimensional

---

### 3.6 — Dynamic max_tokens Computation

Replace the current hardcoded 4096 default:

```python
def estimate_token_budget(sections: list) -> int:
    question_tokens = sum(s.questions_count * 150 for s in sections)
    passage_tokens  = sum(600 for s in sections if s.passage_instruction)
    return min(8192, 500 + question_tokens + passage_tokens)
```

---

### 3.7 — Integration Strategy

The agentic pipeline integrates inside `generate_universal_paper()` as the **first-attempt path**, with the existing single-prompt path as automatic fallback:

```python
try:
    data = generate_paper_parallel(pattern, context_map, additional_context)
except Exception as e:
    log.warning(f"Parallel generation failed: {e}. Falling back to single-prompt.")
    data = generate_with_universal_prompt(...)  # existing path unchanged
```

**Existing `generate_english_paper()` and `generate_science_paper()` are kept** as the final fallback throughout Phase 3. Only remove them after 50+ successful parallel generations in production.

---

## What NOT to Change

- The two-LLM generator-validator pattern — well-calibrated, Phase 3 refines it, doesn't replace it
- The Celery async architecture — changing to synchronous would block Django workers
- The DRF Token authentication model
- The round-robin key management in `mantle_client.py`
- SQLite — sufficient for single-school deployment; migrate to PostgreSQL only when concurrent write errors appear in production logs
