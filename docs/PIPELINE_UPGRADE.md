# QPG Pipeline Upgrade — Robust Multi-Stage Validation Architecture

**Status:** ✅ COMPLETE — all 17 stages implemented  
**Scope:** `core/section_generator.py`, `core/image_finder.py`, `core/generator.py`, `core/embeddings.py`  
**Constraint:** Time and LLM cost are not constraints — maximise quality.

---

## 1. Current Pipeline — Honest Map

```
User triggers generate_paper_task
        │
        ▼
[generator.py] generate_universal_paper()
        │
        ├─► get_section_context_map()            ← one ChromaDB query batch per section
        │       └─► get_section_context()        ← embedding similarity only
        │               └─► embeddings.query()   ← school → shared fallback
        │
        └─► generate_paper_parallel()            ← 3 ThreadPoolExecutor workers
                │
                ├─► [Section A] generate_section(wo)
                │       │
                │       ├─ build_section_prompt()    ← injects context (capped 8000 chars)
                │       ├─ mantle_client.converse()  ← deepseek.v3.2, up to 3 attempts
                │       ├─ extract_section_json()    ← parse + regex fallback
                │       ├─ validate_section_output() ← count, text field, options, marks
                │       │   (checks first 3 questions only)
                │       └─ if CBQ: _post_process_cbq_images()
                │               └─► image_finder.generate_image_for_question()
                │                       ├─ _route_and_extract()      ← rdkit vs diagram
                │                       ├─ _render_rdkit() OR Wikimedia OR Pollinations
                │                       └─ _verify_and_correct()     ← Kimi vision
                │
                ├─► [Section B] (same)
                ├─► [Section C] (same)
                └─► [Section D] (same)
                        │
                        ▼
                cross_section_validate()           ← renumber qnums only
                validate_competency_distribution() ← report only, does not block
                        │
                        ▼
                render_paper_from_data()           ← DOCX rendering
```

### Current Validation — What It Actually Checks

| Check | Scope | How |
|---|---|---|
| Question count == expected | Section | Code |
| `text` field exists | First 3 questions only | Code |
| 4 options for MCQ/AR | First 3 questions only | Code |
| Marks per question correct | All questions | Code |
| qnum sequential | All sections | Code (post-gen) |
| Competency distribution | Paper level | Code (report, no block) |
| Sub-question correctness vs image | CBQ image questions | Kimi vision |

### Identified Weaknesses

1. **Context retrieval**: Only embedding similarity. Misses proper nouns, dates, formulas. All 4 sections query the same store and get overlapping chunks, producing similar questions across sections.
2. **Context sizing**: Fixed 8000-char cap regardless of question type. LA questions need richer context; MCQs need dense factual chunks.
3. **Structural validation gap**: Only first 3 questions checked for text/options. Q4 onwards can be malformed and will pass.
4. **No content quality gate**: Questions are not checked for correctness, clarity, or NCERT faithfulness before being accepted.
5. **No answer verification**: MCQ answers are not verified. An LLM can confidently generate a wrong answer key.
6. **No uniqueness check**: Two questions in the same section can ask about the same concept from the same chapter.
7. **No cross-section coherence**: All 4 sections can repeat the same chapter's content.
8. **CBQ passage not validated**: Passage content is not checked to confirm sub-questions are actually answerable from it.
9. **Competency distribution only reported**: If distribution is off, the paper is still accepted.
10. **No final paper-level audit**: No holistic check that the assembled paper matches the CBSE pattern specification.
11. **Image pipeline single-shot**: Only one Wikimedia query strategy. Pollinations generates one image with no ranking.

---

## 2. Upgraded Pipeline — Architecture Overview

```
User triggers generate_paper_task
        │
        ▼
═══════════════════════════════════════════
  PHASE 1 — CONTEXT RETRIEVAL (upgraded)
═══════════════════════════════════════════
        │
        ├─► Hybrid RAG per section
        │     ├─ Embedding similarity (existing)
        │     ├─ Keyword/BM25 pass for proper nouns
        │     └─ Cross-section deduplication (used_ids set)
        │
        ├─► Per-question-type context routing
        │     ├─ MCQ context (dense facts)
        │     ├─ LA context (explanatory passages)
        │     └─ CBQ context (narrative passages)
        │
        └─► Context quality pre-check (LLM)
              "Is there enough here to generate N questions?"
              Retry with broader query if NO.
        │
        ▼
═══════════════════════════════════════════
  PHASE 2 — GENERATION (upgraded)
═══════════════════════════════════════════
        │
        ├─► Per-section LLM generation (existing, enhanced schema)
        │     ├─ Richer output schema (bloom level, chapter tag)
        │     ├─ Adaptive temperature per question type
        │     └─ Adaptive max_tokens per question type
        │
        └─► [For LA/CBQ] Individual question generation
              One LLM call per question, not all at once
        │
        ▼
═══════════════════════════════════════════
  PHASE 3 — VALIDATION CHAIN (10 stages)
═══════════════════════════════════════════
        │
        ├─[V1]─► Full Structural Validation (code, no LLM)
        │           All questions checked (not just first 3)
        │           Type-specific field completeness
        │           Answer key validity (MCQ)
        │           Marks sum == section total
        │           Competency tag valid
        │           Fail → retry generate_section()
        │
        ├─[V2]─► Per-Question Content Quality (LLM critic)
        │           Send each question + context to qwen.qwen3-32b
        │           Score: clarity, faithfulness, difficulty, answer
        │           Score < 7 → flag; regenerate that question alone
        │
        ├─[V3]─► NCERT Grounding Check (RAG + LLM)
        │           Re-query vector store using question text as query
        │           Send question + retrieved passage to validator
        │           "Can this be answered from NCERT?" → YES/NO
        │           Not grounded → regenerate
        │
        ├─[V4]─► Answer Verification (MCQ only, LLM blind test)
        │           Send MCQ to fresh LLM with NO context
        │           "Answer this question" → compare to stored answer
        │           Mismatch or low confidence → flag for review
        │           Check answer distribution (not all 'a' or all 'b')
        │
        ├─[V5]─► Inter-Question Uniqueness (code + LLM)
        │           Token overlap check between question pairs
        │           Named entity overlap (same person/place/event)
        │           Duplicate concept → regenerate one
        │
        ├─[V6]─► CBQ Passage Validation (LLM)
        │           "Can each sub-question be answered from passage?"
        │           Passage length/difficulty appropriate for Class 10
        │           OR alternative is genuinely different concept
        │           Fail → regenerate CBQ section
        │
        ├─[V7]─► Bloom's Taxonomy Enforcement (code + targeted regen)
        │           Compute distribution per section
        │           Off-policy? Identify lowest-value questions
        │           Attempt targeted swap (regenerate 1-2 questions)
        │           to fix distribution before accepting
        │
        ├─[V8]─► Cross-Section Coherence (LLM audit)
        │           Extract key concepts from all sections
        │           Check concept repeats across sections
        │           Check chapter coverage matches selected chapters
        │           LLM: "Does this paper cover all 4 subjects?"
        │
        ├─[V9]─► Image Pipeline Validation (upgraded Kimi)
        │           Multi-image generation + ranking
        │           Scientific accuracy check per diagram
        │           Label visibility check
        │           Sub-question answerability from this image
        │
        └─[V10]─► Final Paper-Level LLM Audit (deepseek.v3.2)
                    Full paper JSON + CBSE pattern spec
                    Holistic compliance check
                    Returns: approved bool + issues list
                    Not approved → targeted fix round
        │
        ▼
═══════════════════════════════════════════
  PHASE 4 — RENDERING
═══════════════════════════════════════════
        Existing DOCX rendering (unchanged)
```

---

## 3. Phase 1 — Context Retrieval Upgrades

### 3.1 Cross-Section Deduplication

**Problem:** All sections query the same vector store and receive overlapping chunks. Section A (History) and Section C (Political Science) both retrieve the "Nationalism in India" chapter because it scores high for both. This leads to overlapping question concepts.

**Implementation — `section_generator.py: get_section_context_map()`**

Add a shared `used_doc_ids: set` that persists across section queries. Each call to `embeddings.query()` must exclude IDs already used.

```python
# In get_section_context_map():
used_doc_ids: set = set()

for sec_name, sec_data in blueprint.items():
    ctx, new_ids = get_section_context(
        class_name, effective_subject, chapters, hints,
        school_id=school_id,
        exclude_ids=used_doc_ids,        # NEW PARAM
    )
    used_doc_ids.update(new_ids)         # track what was used
    context_map[sec_name] = ctx
```

In `get_section_context()`, after `embeddings.query()` returns results, extract the document IDs from `results["ids"]` and pass them as a `where_not_in` filter to the next query call.

ChromaDB supports `where` clause filtering. To exclude IDs, use:
```python
coll.query(
    ...,
    where={"$and": [
        {"unit": {"$eq": chapter}},
        {"$not": {"chunk_id": {"$in": list(exclude_ids)}}}
    ]}
)
```
Note: this requires that documents were ingested with a `chunk_id` in their metadata. Verify metadata schema in `embeddings.py: ingest()`. If `chunk_id` is not present, use the document content hash as the exclusion key (build a set of seen content strings — current `seen` set already does this).

**Alternative (simpler):** Keep the existing `seen: set` (which deduplicates by content string) and additionally return the set for cross-section accumulation. No metadata changes needed.

### 3.2 Per-Question-Type Context Routing

**Problem:** One context blob for an entire section is used for all question types in that section. MCQ needs different content (dense facts, definitions) than LA (conceptual explanations) than CBQ (narrative passages).

**Implementation — new function `get_typed_context_map()`**

```python
TYPE_CONTEXT_PROFILES = {
    "mcq":           {"hints_fn": "facts_hints",    "max_chars": 4000,  "chunks": 20},
    "assertion":     {"hints_fn": "principle_hints", "max_chars": 3000,  "chunks": 15},
    "vsa":           {"hints_fn": "def_hints",       "max_chars": 3000,  "chunks": 15},
    "sa":            {"hints_fn": "explain_hints",   "max_chars": 5000,  "chunks": 25},
    "la":            {"hints_fn": "deep_hints",      "max_chars": 8000,  "chunks": 35},
    "cbq_image":     {"hints_fn": "visual_hints",    "max_chars": 6000,  "chunks": 20},
    "source_based":  {"hints_fn": "passage_hints",   "max_chars": 10000, "chunks": 40},
    "map_work":      {"hints_fn": "map_hints",       "max_chars": 4000,  "chunks": 20},
}
```

Instead of one `context_text: str` per section, the work order carries a `context_by_type: dict[str, str]`. `build_section_prompt()` then selects the appropriate context slice for the current question type block.

This requires a schema change to `SectionWorkOrder`:
```python
# Add to SectionWorkOrder:
context_by_type: dict = field(default_factory=dict)  # {type_key: context_str}
```

### 3.3 Context Quality Pre-Check

**Problem:** Context is retrieved and used blindly. If only 2 relevant chunks exist for a chapter, the section gets generated with thin context and produces hallucinated questions.

**Implementation — `_validate_context_quality()` called before `build_work_orders()`**

```python
def _validate_context_quality(context: str, wo: SectionWorkOrder) -> bool:
    """
    Quick LLM check: is context sufficient to generate wo.questions_count
    questions of the expected types?
    Returns True if sufficient, False if we should retry with broader query.
    """
    if len(context) < 500:
        return False  # obvious fail, skip LLM cost

    prompt = f"""Context quality check.
Subject: {wo.subject} Class {wo.class_name}
Chapter(s): {', '.join(wo.chapters)}
Need to generate: {wo.questions_count} questions of types: {wo.question_types}

Context available ({len(context)} chars):
---
{context[:3000]}
---

Answer with JSON only:
{{"sufficient": true/false, "reason": "one sentence"}}
"""
    raw, _, _ = mantle_client.converse(
        model_id=mantle_client.VAL_MODEL,
        prompt=prompt,
        max_tokens=100,
        temperature=0.1,
    )
    try:
        result = json.loads(raw.strip())
        return result.get("sufficient", True)
    except Exception:
        return True  # assume ok if check fails
```

If `_validate_context_quality()` returns False, retry `get_section_context()` with:
1. Broader query hints (remove type-specific terms, use only `"{subject} {chapter}"`)
2. Double `n_results`
3. If still empty: use `unit=None` (query entire subject without chapter filter)

---

## 4. Phase 2 — Generation Upgrades

### 4.1 Schema Enrichment

Add these fields to every generated question's schema:

```json
{
  "qnum": 1,
  "type": "MCQ",
  "text": "...",
  "chapter_tag": "The Rise of Nationalism in Europe",
  "bloom_level": "application",
  "competency_type": "application",
  "difficulty_rating": "medium",
  "marks": 1,
  "options": {"a": "...", "b": "...", "c": "...", "d": "..."},
  "answer": "b",
  "answer_explanation": "Brief reason why b is correct."
}
```

`chapter_tag`: which chapter this question is from (helps cross-section dedup and audit)  
`bloom_level`: remember / understand / apply / analyse / evaluate / create  
`answer_explanation`: required for MCQ — used by V4 answer verification

### 4.2 Adaptive Generation Parameters

```python
# In estimate_token_budget() — upgrade to also return temperature
TYPE_PARAMS = {
    "mcq":          {"temp": 0.6, "budget_per_q": 200},  # factual accuracy
    "assertion":    {"temp": 0.6, "budget_per_q": 220},
    "vsa":          {"temp": 0.7, "budget_per_q": 180},
    "sa":           {"temp": 0.75, "budget_per_q": 280},
    "la":           {"temp": 0.8, "budget_per_q": 450},
    "cbq_image":    {"temp": 0.72, "budget_per_q": 350},
    "source_based": {"temp": 0.78, "budget_per_q": 600},
    "map_work":     {"temp": 0.5, "budget_per_q": 200},  # factual locations
}
```

### 4.3 Individual Question Generation for LA and CBQ

For LA (5-mark) and CBQ (4-mark with sub-questions), generate each question individually:

```python
def generate_single_question(qtype: str, wo: SectionWorkOrder, 
                              q_index: int, used_chapters: set) -> dict:
    """
    Generates exactly ONE question of qtype for the given work order.
    used_chapters: chapters already used by prior questions in this section
    → forces this question to use a DIFFERENT chapter if possible.
    """
    avoid_chapters = list(used_chapters)
    prompt = build_single_question_prompt(wo, qtype, q_index, avoid_chapters)
    raw, in_tok, out_tok = mantle_client.converse(
        model_id=GEN_MODEL,
        prompt=prompt,
        max_tokens=TYPE_PARAMS[qtype]["budget_per_q"],
        temperature=TYPE_PARAMS[qtype]["temp"],
    )
    return extract_question_json(raw), in_tok, out_tok
```

This is more expensive (one call per LA/CBQ question) but dramatically improves quality for complex question types. For a standard Social Science paper with 3 LA questions and 2 CBQ questions, this adds 5 LLM calls but ensures each question has dedicated context attention.

---

## 5. Phase 3 — Validation Chain (10 Stages)

### V1 — Full Structural Validation (Code, No LLM)

**Location:** Replace `validate_section_output()` in `section_generator.py`  
**Current:** Checks first 3 questions only  
**Upgraded:** Checks ALL questions with full type-aware rules

```python
def validate_section_output_v2(data: dict, wo: SectionWorkOrder) -> list[str]:
    errors = []

    if not isinstance(data, dict):
        return ["Response is not a JSON object"]
    questions = data.get("questions", [])
    if not questions:
        return ["No 'questions' array found in response"]

    # Q-COUNT
    expected = wo.provided_count if (wo.provided_count and wo.provided_count > wo.questions_count) \
               else wo.questions_count
    if len(questions) != expected:
        errors.append(f"Expected {expected} questions, got {len(questions)}")

    # PER-QUESTION CHECKS (ALL questions, not first 3)
    valid_competency = {"recall", "application", "constructed"}
    valid_mcq_answers = {"a", "b", "c", "d"}
    answer_dist = {}

    for i, q in enumerate(questions):
        n = i + 1

        # Text field
        if not q.get("text", "").strip():
            errors.append(f"Q{n}: missing or empty 'text' field")

        # Marks
        if abs(float(q.get("marks", 0)) - wo.marks_per_question) > 0.1 and not wo.mixed_marks:
            errors.append(f"Q{n}: marks={q.get('marks')} expected {wo.marks_per_question}")

        # Competency tag
        ct = q.get("competency_type", "")
        if ct and ct not in valid_competency:
            errors.append(f"Q{n}: invalid competency_type '{ct}'")

        # Chapter tag (warn if missing, do not block)
        # if not q.get("chapter_tag"):
        #     errors.append(f"Q{n}: missing chapter_tag")

        type_str_lower = _type_str(q.get("type", ""))

        # MCQ/AR specific
        if type_str_lower in ("mcq", "assertion-reason", "assertion_reason"):
            opts = q.get("options", {})
            if len(opts) < 4:
                errors.append(f"Q{n}: MCQ must have 4 options, found {len(opts)}")
            answer = str(q.get("answer", "")).lower().strip()
            if answer not in valid_mcq_answers:
                errors.append(f"Q{n}: answer '{answer}' not in {{a,b,c,d}}")
            else:
                answer_dist[answer] = answer_dist.get(answer, 0) + 1

        # LA specific — OR alternative
        if type_str_lower in ("la", "long_answer", "long answer"):
            if not q.get("or_alternative"):
                errors.append(f"Q{n}: LA question missing 'or_alternative'")
            elif not q["or_alternative"].get("text", "").strip():
                errors.append(f"Q{n}: or_alternative has empty text")

        # CBQ/Source specific — sub_questions
        if type_str_lower in ("source_based", "image_based", "cbq"):
            sqs = q.get("sub_questions", [])
            if not sqs:
                errors.append(f"Q{n}: CBQ missing sub_questions")
            else:
                sq_marks_sum = sum(sq.get("marks", 0) for sq in sqs)
                if abs(sq_marks_sum - float(q.get("marks", wo.marks_per_question))) > 0.1:
                    errors.append(f"Q{n}: sub_question marks sum={sq_marks_sum} != question marks={q.get('marks')}")

    # ANSWER DISTRIBUTION CHECK (MCQ only)
    if answer_dist:
        total_mcq = sum(answer_dist.values())
        for letter, count in answer_dist.items():
            if total_mcq >= 4 and count > total_mcq * 0.6:
                errors.append(f"Answer key bias: '{letter}' used {count}/{total_mcq} times (>60%)")

    # MARKS SUM
    actual_total = sum(float(q.get("marks", 0)) for q in questions)
    if abs(actual_total - wo.marks) > 0.5:
        errors.append(f"Total marks={actual_total:.1f} expected {wo.marks}")

    return errors
```

**Trigger:** Same as current — errors → retry with `prior_error` injection. V1 must pass before V2 begins.

---

### V2 — Per-Question Content Quality (LLM Critic)

**Location:** New function `validate_question_quality()` called from `generate_section()` after V1 passes  
**Model:** `qwen.qwen3-32b` (fast, accurate, cheap relative to deepseek)  
**Runs:** Per-question in parallel using `ThreadPoolExecutor`

```python
QUALITY_PROMPT = """You are a CBSE question paper quality inspector.
Evaluate this Class {class_name} {subject} question strictly.

QUESTION (type={qtype}, marks={marks}, difficulty={difficulty}):
{question_json}

NCERT REFERENCE CONTEXT:
---
{context}
---

Score each dimension 1–10. Be strict — reserve 9-10 for exceptional quality.

Output JSON only:
{{
  "scores": {{
    "clarity": <1-10>,
    "ncert_faithfulness": <1-10>,
    "difficulty_match": <1-10>,
    "answer_correctness": <1-10>,
    "distractor_quality": <1-10 or null if not MCQ>,
    "competency_alignment": <1-10>
  }},
  "overall": <average of above non-null scores, rounded to 1dp>,
  "critical_issues": ["..."],
  "fix_suggestion": "...",
  "pass": <true if overall >= 7.0 and no score < 5>
}}"""
```

**Flow:**
1. After V1 passes, run `validate_question_quality()` on all questions in parallel (max 5 workers).
2. Questions with `pass: false` are collected.
3. If ≤ 30% of questions fail: attempt individual question regeneration for each failed question (call `generate_single_question()` targeting the same chapter_tag).
4. If > 30% fail: trigger full section regeneration (increment attempt counter, pass V2 failure summary as `prior_error`).
5. After fix, re-run V1 + V2 on regenerated questions only.

**Token cost estimate:** ~1500 tokens per question × 38 questions (full Social Science paper) = ~57,000 tokens for V2. Acceptable.

---

### V3 — NCERT Grounding Check (RAG + LLM)

**Location:** New function `validate_grounding()` called after V2  
**Model:** `qwen.qwen3-32b`  
**Runs:** Per-question, grouped into batches of 5

**Flow:**
1. For each question, use `question["text"]` as a RAG query against the section's subject vector store.
2. Retrieve top 3 passages.
3. Send question + passages to validator:

```python
GROUNDING_PROMPT = """You are verifying NCERT curriculum compliance.

QUESTION: {question_text}
{mcq_options_if_any}
CLAIMED ANSWER: {answer_if_mcq}

TOP NCERT PASSAGES RETRIEVED:
---
{passages}
---

Determine:
1. Is this question answerable from standard Class {class_name} NCERT {subject}?
2. If MCQ: is the stated answer CORRECT?
3. Does the question contain any factually incorrect statements?

Output JSON only:
{{
  "ncert_grounded": true/false,
  "answer_correct": true/false/null,
  "factual_errors": ["..."],
  "grounding_evidence": "which passage supports this question"
}}"""
```

4. Questions with `ncert_grounded: false` → regenerate.
5. Questions with `answer_correct: false` → fix the answer key (attempt targeted correction, not full regen).
6. Questions with `factual_errors` → regenerate.

**Note on false positives:** If the question topic is not in the vector store (chapter not ingested), `ncert_grounded` may incorrectly return false. Guard: if context retrieval returned 0 chars for that chapter, skip V3 for questions tagged with that chapter and log the skip.

---

### V4 — MCQ Answer Verification (Blind LLM Test)

**Location:** New function `verify_mcq_answers()` called after V3  
**Model:** `deepseek.v3.2` (knows CBSE curriculum well)  
**Runs:** MCQ questions only, batched 10 per call

```python
BLIND_TEST_PROMPT = """Answer these CBSE Class {class_name} {subject} multiple choice questions.
Choose the single best answer. Do not explain — just pick the option.

{questions_block}

Output JSON:
[{{"qnum": 1, "answer": "a", "confidence": "high"}}, ...]
Confidence: "high" (certain), "medium" (likely), "low" (guessing)."""
```

**Rules:**
- If blind LLM answer matches stored answer: confidence "high" → pass.
- Mismatch: flag as `answer_suspect`. Do NOT auto-correct (could be a tricky question where the LLM is wrong). Instead: log and inject into V10 final audit's attention list.
- Confidence "low" from LLM AND mismatch → strong signal to regenerate the question.
- Answer key distribution check: if same letter appears > 60% of MCQs in a section → force regeneration of enough questions to balance.

---

### V5 — Inter-Question Uniqueness (Code + LLM)

**Location:** New function `validate_uniqueness()` called after V4  
**Two layers:**

**Layer 1 — Token overlap (code, fast):**
```python
def _concept_overlap(q1_text: str, q2_text: str) -> float:
    """Returns 0.0–1.0. >0.45 = likely duplicate."""
    STOP = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "on",
            "to", "by", "for", "with", "which", "what", "how", "why", "and"}
    t1 = {w.lower() for w in q1_text.split() if w.lower() not in STOP and len(w) > 3}
    t2 = {w.lower() for w in q2_text.split() if w.lower() not in STOP and len(w) > 3}
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / min(len(t1), len(t2))

# In validate_uniqueness():
for i, qi in enumerate(questions):
    for j, qj in enumerate(questions):
        if i >= j:
            continue
        overlap = _concept_overlap(qi["text"], qj["text"])
        if overlap > 0.45:
            duplicate_pairs.append((i, j, overlap))
```

**Layer 2 — Semantic uniqueness (LLM, for pairs flagged by Layer 1):**
Only called when Layer 1 flags a pair. Send both questions to LLM: "Do these two questions test the same knowledge?" → regenerate the one with lower V2 quality score.

**Cross-section uniqueness:** After all sections pass individual V5, run an inter-section check using `chapter_tag` fields: if the same `chapter_tag` appears in 3+ questions across different sections, flag for V8 coherence review.

---

### V6 — CBQ / Source-Based Passage Validation (LLM)

**Location:** New function `validate_cbq_passage()` — only runs for sections with `has_passage or has_cbq`  
**Model:** `qwen.qwen3-32b`

```python
CBQ_VALIDATION_PROMPT = """Validate this CBSE source-based/CBQ question for Class {class_name} {subject}.

PASSAGE:
---
{passage}
---

SUB-QUESTIONS:
{sub_questions_block}

Check:
1. Is each sub-question answerable SOLELY from the passage? (not from general knowledge)
2. Is the passage appropriate for Class {class_name} (age-appropriate, not too academic)?
3. Is the passage length appropriate? (200–350 words for case-based, 400–600 for source-based)
4. Are sub-question marks proportional to the complexity of answering?
5. If there is an OR-alternative for the main question, is it genuinely different in concept?

Output JSON:
{{
  "sub_question_answerability": [{{"sq_index": 0, "answerable": true/false, "issue": "..."}}],
  "passage_appropriate": true/false,
  "passage_length_ok": true/false,
  "marks_proportional": true/false,
  "overall_pass": true/false,
  "issues": ["..."],
  "suggested_fixes": ["..."]
}}"""
```

**On failure:** Regenerate the entire CBQ question (passage + sub-questions) using `generate_single_question("cbq")`. V6 is re-run on the new question. Max 2 regen attempts before accepting with logged warning.

---

### V7 — Bloom's Taxonomy Enforcement

**Location:** Upgrade existing `validate_competency_distribution()` from report-only to enforcement  
**Model:** `qwen.qwen3-32b` (targeted regen only)

```python
CBSE_POLICY = {
    "application":  {"min": 0.45, "target": 0.50},  # ≥45%
    "recall":       {"max": 0.25, "target": 0.20},  # ≤25%
    "constructed":  {"min": 0.25, "target": 0.30},  # ≥25%
    "untagged":     {"max": 0.10},
}
```

**Enforcement flow:**
1. Compute distribution.
2. If compliant: pass.
3. If violation:
   a. Identify which questions are "cheapest to swap" (lowest V2 quality score in the offending competency category).
   b. For each: call `generate_single_question()` with explicit competency type instruction.
   c. Recompute. If still violated after 2 rounds: accept paper with violation logged in `_competency_report` (do not block indefinitely).

---

### V8 — Cross-Section Coherence (LLM Audit)

**Location:** New function `validate_cross_section_coherence()` called from `generate_paper_parallel()` after all sections pass V1–V7  
**Model:** `deepseek.v3.2`

```python
COHERENCE_PROMPT = """You are reviewing a complete Class {class_name} {subject} question paper 
for CBSE compliance.

PATTERN SPECIFICATION:
{pattern_summary}

PAPER SUMMARY (question texts only, no options/answers):
Section A ({subject_a}): {q_count_a} questions
{q_texts_a}

Section B ({subject_b}): {q_count_b} questions  
{q_texts_b}

...

Check:
1. Are the specified chapters represented? ({chapters})
2. Are any concepts repeated across sections?
3. Does each section focus on its designated sub-subject?
4. Is the overall difficulty appropriate?
5. Are there any questions that seem factually problematic?

Output JSON:
{{
  "chapter_coverage": {{"covered": [...], "missing": [...]}},
  "cross_section_repeats": [{{"concept": "...", "appears_in": ["A", "C"]}}],
  "subject_focus_violations": [{{"section": "B", "issue": "..."}}],
  "overall_coherence_score": 1-10,
  "critical_issues": ["..."],
  "pass": true/false
}}"""
```

**On failure:** Log issues. Only trigger targeted section re-generation if `critical_issues` is non-empty and `overall_coherence_score < 6`. Otherwise accept with logged report.

---

### V9 — Image Pipeline Validation (Upgraded)

**Current:** Router → render/generate → Kimi verify sub-questions  
**Upgraded:** Add 3 new steps

#### V9.1 — Multi-Image Generation + Ranking (Pollinations path)

Instead of generating one Pollinations image, generate 3 with varied prompts:

```python
def _generate_pollinations_candidates(base_prompt: str, n: int = 3) -> list:
    """Generate n Pollinations images with prompt variations."""
    variations = [
        base_prompt,
        base_prompt + ", highly detailed, all parts clearly labeled",
        base_prompt + ", NCERT textbook style, simple clean diagram",
    ]
    candidates = []
    for prompt in variations[:n]:
        try:
            img_bytes, mime = _generate_pollinations(prompt)
            candidates.append({"bytes": img_bytes, "mime": mime, "prompt": prompt})
        except Exception:
            continue
    return candidates
```

Then have Kimi rank the candidates:

```python
RANK_PROMPT = """You are evaluating {n} scientific diagrams for a Class 10 CBSE question paper.
The question is: {question_text}

Rate each image 1-10 on:
- Scientific accuracy
- Label clarity  
- Suitability for the question's sub-questions
- Overall quality for a student exam paper

Pick the BEST one.

Output JSON: {{"best_index": 0/1/2, "scores": [N, N, N], "reason": "..."}}"""
```

Use best-ranked image.

#### V9.2 — Scientific Accuracy Check

After selecting the final image, run a dedicated accuracy check:

```python
ACCURACY_PROMPT = """You are a Class 10 NCERT {subject} expert.

This diagram is intended to show: {image_intent}
(For chapter: {chapter})

Evaluate:
1. Is this scientifically accurate for Class 10 level?
2. Are all visible labels correct?
3. Is there anything misleading that could confuse a student?
4. Is this consistent with what NCERT textbooks show?

Score 1-10. Score < 7 = reject this image.

Output JSON:
{{"accuracy_score": N, "accurate": true/false, "issues": ["..."], "verdict": "accept/reject"}}"""
```

If `verdict == "reject"`: try next-best candidate, or fall back to Wikimedia, or regenerate Pollinations with corrected prompt.

#### V9.3 — Sub-Question Upgrade (Existing Kimi verify — enhanced)

Current Kimi verify prompt only fixes label references. Upgrade to also:
- Check each sub-question is at the appropriate difficulty level
- Ensure sub-questions progress from simpler (1 mark) to more complex (2 marks)
- Verify no sub-question asks something a student cannot determine from the image alone

---

### V10 — Final Paper-Level LLM Audit

**Location:** New function `audit_complete_paper()` called at end of `generate_paper_parallel()`  
**Model:** `deepseek.v3.2` (most capable — paper-level reasoning)  
**Runs:** Once per paper generation

```python
FINAL_AUDIT_PROMPT = """You are a senior CBSE examination board expert conducting a final review.

PAPER SPECIFICATION:
Subject: {subject} | Class: {class_name} | Pattern: {pattern_name}
Total Marks: {total_marks} | Total Questions: {total_questions}
Chapters tested: {chapters}
Difficulty: {difficulty}

SECTION STRUCTURE REQUIRED:
{pattern_structure}

COMPLETE PAPER (question texts + types + marks):
{paper_summary}

Perform a comprehensive compliance audit:

STRUCTURAL:
□ Question count per section matches pattern
□ Marks per question match pattern  
□ Total marks across sections sum correctly
□ Internal choices (OR alternatives) present where required by pattern

CONTENT:
□ All selected chapters have at least one question
□ No chapter dominates (>40% of questions from one chapter)
□ Question difficulty distribution appropriate for {difficulty} setting
□ No two questions test identical knowledge

CBSE POLICY:
□ Competency distribution: ≥45% application, ≤25% recall, ≥25% constructed
□ Assertion-reason questions use standard CBSE 4-option format
□ Map work questions list specific, examinable locations
□ CBQ/source passages are passage-worthy (not just facts)

Output JSON:
{{
  "overall_compliance_score": 1-10,
  "approved": true/false,
  "structural_issues": ["..."],
  "content_issues": ["..."],
  "policy_violations": ["..."],
  "attention_items": ["minor issues, not blockers"],
  "section_verdicts": {{"A": "pass/fail", "B": "pass/fail", ...}},
  "recommendation": "approve | approve_with_warnings | reject_section_X | reject_all"
}}"""
```

**Action on result:**
- `recommendation: approve` or `approve_with_warnings` → proceed to rendering, log warnings.
- `recommendation: reject_section_X` → trigger single-section regeneration for section X, rerun V1-V7 for that section, then re-run V10.
- `recommendation: reject_all` → this should be rare; if it happens, attempt full paper regeneration once, then accept best result.

---

## 6. Data Schema Changes

### 6.1 `SectionWorkOrder` — New Fields

```python
@dataclass
class SectionWorkOrder:
    # ... existing fields ...
    context_by_type: dict = field(default_factory=dict)   # {type_key: context_str}
    validation_report: dict = field(default_factory=dict) # filled by validation stages
```

### 6.2 Generated Question — New Fields

```json
{
  "qnum": 1,
  "type": "MCQ",
  "text": "...",
  "chapter_tag": "Nationalism in India",
  "bloom_level": "application",
  "competency_type": "application",
  "difficulty_rating": "medium",
  "answer_explanation": "Gandhi's Non-Cooperation Movement began in 1920...",
  "marks": 1,
  "options": {"a": "...", "b": "...", "c": "...", "d": "..."},
  "answer": "b",
  "_v2_score": 8.2,
  "_v3_grounded": true,
  "_v4_answer_verified": true
}
```

The `_v*` fields are stripped before rendering (prefixed with `_` for easy exclusion).

### 6.3 Paper-Level Metadata

```json
{
  "_pipeline_report": {
    "v1_passed": true,
    "v2_failed_questions": [],
    "v3_ungrounded_questions": [],
    "v4_suspect_answers": [{"qnum": 5, "stored": "c", "llm_answer": "a"}],
    "v5_duplicate_pairs": [],
    "v6_cbq_issues": [],
    "v7_competency": {"compliant": true, "application_pct": 52.1},
    "v8_coherence_score": 8,
    "v9_image_accuracy": {"section_a_q8": {"score": 8.5, "source": "pollinations"}},
    "v10_audit": {"approved": true, "score": 8.8}
  }
}
```

This report is stored in `QuestionPaper.paper_data` and can be surfaced in the admin UI.

---

## 7. Implementation Roadmap

### Priority Order (implement in sequence)

| Priority | Stage | File(s) | Est. LLM calls added per paper |
|---|---|---|---|
| 1 | ✅ V1 — Full structural validation | `section_generator.py` | 0 (code only) |
| 2 | ✅ V5 — Inter-question uniqueness (Layer 1) | `section_generator.py` | 0 (code only) |
| 3 | ✅ V7 — Bloom's enforcement | `section_generator.py` | 0–6 (targeted regen) |
| 4 | ✅ 3.1 — Cross-section dedup | `section_generator.py` | 0 (code only) |
| 5 | ✅ 4.1 — Schema enrichment (chapter_tag, explanation) | `section_generator.py` | 0 (prompt change) |
| 6 | ✅ V4 — MCQ answer verification | `section_generator.py` | ~20 (batched) |
| 7 | ✅ V2 — Content quality critic | `section_generator.py` | ~38 individual |
| 8 | ✅ V6 — CBQ passage validation | `section_generator.py` | ~4 (one per CBQ) |
| 9 | ✅ V3 — NCERT grounding | `section_generator.py` | ~38 individual |
| 10 | ✅ V9.1 — Multi-image + ranking | `image_finder.py` | ~6 per image question |
| 11 | ✅ V9.2 — Scientific accuracy | `image_finder.py` | ~1 per image question |
| 12 | ✅ V8 — Cross-section coherence | `section_generator.py` | 1 |
| 13 | ✅ V10 — Final paper audit | `section_generator.py` | 1 |
| 14 | ✅ 3.2 — Per-type context routing | `section_generator.py` | 0 (code only) |
| 15 | ✅ 3.3 — Context quality pre-check | `section_generator.py` | 1 per section |
| 16 | ✅ 4.3 — Individual LA/CBQ generation | `section_generator.py` | +5 per paper |
| 17 | ✅ V5 Layer 2 — Semantic uniqueness | `section_generator.py` | 0–5 (only on flag) |

### Files Changed

| File | Changes |
|---|---|
| `core/section_generator.py` | V1–V10 all validation stages, cross-section dedup, per-type context routing, schema enrichment, Bloom's enforcement, final paper audit |
| `core/image_finder.py` | V9.1 multi-image + Kimi ranking, V9.2 scientific accuracy check |
| `core/generator.py` | Strip internal `_*` pipeline fields before DOCX rendering |

---

## 8. Configuration & Thresholds

All thresholds should be in a config block at the top of `section_generator.py`:

```python
# ─── Pipeline Validation Config ────────────────────────────────────────────
VALIDATION_CONFIG = {
    # V2 — Content quality
    "v2_pass_threshold":          7.0,    # overall score ≥ this to pass
    "v2_min_dimension_score":     5,      # no single dimension below this
    "v2_max_regen_fraction":      0.30,   # if >30% questions fail, full regen
    "v2_max_individual_regens":   2,      # max regen attempts per question

    # V3 — Grounding
    "v3_enabled":                 True,
    "v3_skip_if_no_context":      True,   # skip for chapters not in vector store

    # V4 — Answer verification
    "v4_block_on_mismatch":       False,  # mismatch → flag, not block
    "v4_answer_distribution_max": 0.60,   # same letter ≤60% of MCQs

    # V5 — Uniqueness
    "v5_token_overlap_threshold": 0.45,
    "v5_semantic_check_on_flag":  True,

    # V6 — CBQ passage
    "v6_max_regen_attempts":      2,

    # V7 — Bloom's enforcement
    "v7_max_fix_rounds":          2,
    "v7_application_min":         0.45,
    "v7_recall_max":              0.25,
    "v7_constructed_min":         0.25,

    # V8 — Cross-section coherence
    "v8_enabled":                 True,
    "v8_block_threshold":         6,      # coherence score < 6 → regen

    # V9 — Image pipeline
    "v9_pollinations_candidates": 3,      # generate N, rank, pick best
    "v9_accuracy_threshold":      7,      # score < this → reject image
    "v9_wikimedia_score_min":     7,      # existing threshold

    # V10 — Final audit
    "v10_enabled":                True,
    "v10_reject_triggers_regen":  True,
}
```

---

## 9. LLM Cost Estimate (Full Paper)

| Stage | Model | Calls | ~Input tokens | ~Output tokens |
|---|---|---|---|---|
| Generation (4 sections) | deepseek.v3.2 | 4 | 40,000 | 20,000 |
| V2 quality critic | qwen.qwen3-32b | 38 | 76,000 | 15,200 |
| V3 grounding | qwen.qwen3-32b | 38 | 57,000 | 7,600 |
| V4 MCQ blind test | deepseek.v3.2 | 4 batches | 12,000 | 2,000 |
| V6 CBQ validation | qwen.qwen3-32b | 2 | 6,000 | 2,000 |
| V8 coherence | deepseek.v3.2 | 1 | 15,000 | 3,000 |
| V9 image (per CBQ) | Kimi K2.5 vision | 6 | 8,000 | 4,200 |
| V10 final audit | deepseek.v3.2 | 1 | 20,000 | 2,000 |
| Context pre-check | qwen.qwen3-32b | 4 | 16,000 | 400 |
| **Total** | | **~98** | **~250,000** | **~56,400** |

Current pipeline: ~4–8 LLM calls, ~120,000–200,000 tokens.  
Upgraded pipeline: ~98 LLM calls, ~300,000 tokens.  
**Cost multiplier: ~2x–3x on tokens, ~15x on call count** (but calls are small and fast in parallel).

---

## 10. What This Achieves

| Quality Dimension | Before | After |
|---|---|---|
| Wrong answer in MCQ | Common | Near-zero (V4) |
| Sub-questions unanswerable from image | Occasional | Rare (V9.3 enhanced) |
| Structurally malformed questions (Q4+) | Possible | Blocked (V1) |
| Question repeats same concept twice | Common | Blocked (V5) |
| Chapter not represented in paper | Possible | Flagged (V8) |
| Hallucinated / non-NCERT question | Possible | Flagged (V3) |
| Wrong competency distribution | Report only | Corrected (V7) |
| CBQ sub-question requires external knowledge | Possible | Blocked (V6) |
| Poor-quality Pollinations image | Frequent | Reduced (V9.1 ranking) |
| Paper fails CBSE pattern spec | Possible | Audited (V10) |
| Answer key biased (all 'a') | Possible | Blocked (V1) |
