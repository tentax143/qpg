# QPG — Question Paper Generator

Turns a school's own study material into exam-ready question papers. Point it at textbooks and
notes, define the shape of the exam (sections, question types, marks), pick chapters and a
difficulty, and a formatted Word paper comes back a couple of minutes later — school name in the
header, marks against every question, diagrams where a question needs one, and an answer key on
request.

Questions are written **from the source material you uploaded**, then put through a dozen automated
checks before anyone sees them. Two schools using different books get different papers.

> **Status: live beta.** More than five institutions are running QPG, and real exams are being sat
> on papers it generated. It is still actively developed — treat scale claims carefully and see
> [`docs/PRODUCT_OVERVIEW.md`](docs/PRODUCT_OVERVIEW.md) before promising anything to a customer.

---

## Contents

- [How it works](#how-it-works)
- [Stack](#stack)
- [Running it locally](#running-it-locally)
- [Operational rules that matter](#operational-rules-that-matter)
- [Project layout](#project-layout)
- [The generation pipeline](#the-generation-pipeline)
- [Quality checks](#quality-checks)
- [Tests](#tests)
- [Documentation](#documentation)

---

## How it works

```
Upload PDF ──► chunk ──► embed ──► MaterialChunk rows (pgvector / Chroma)
                                          │
Teacher picks pattern + chapters ─────────┤
                                          ▼
                            retrieve relevant excerpts per chapter
                                          │
                                          ▼
                          generate each section in parallel (LLM)
                                          │
                                          ▼
                             V1–V11 quality gates + marks audit
                                          │
                                          ▼
                                  DOCX  (+ answer key)
```

The HTTP request **returns before the paper exists**. Generation runs on a Celery worker and the
browser polls until the row flips to `done`. A paper takes roughly 2–4 minutes and around 40–60 LLM
calls.

Retrieval is per-chapter and per-section: each section gets its own excerpt set chosen for the
question types it must produce, and every printed question is bound to one chapter and one numbered
excerpt of it, so a chapter owing three questions gives them three different passages rather than
three questions off the same paragraph.

---

## Stack

| Layer | What |
|---|---|
| Backend | Django + Django REST Framework |
| Queue | Celery 5.3 + Redis (vendored for Windows in `redis/`) |
| Database | PostgreSQL + pgvector — falls back to SQLite when `POSTGRES_DB` is unset |
| Vector store | pgvector, with ChromaDB under `vector_store/{shared,school_<id>}/<class>_<subject>/` |
| Generation LLM | `deepseek.v3.2` via AWS Bedrock Mantle |
| Validation LLM | `qwen.qwen3-32b` · audit `zai.glm-5` |
| Embeddings | `nomic-embed-text` (768-d, local Ollama) |
| Images | Together AI `flash-image-2.5`, Pollinations fallback |
| Frontend | Next.js 16 + React 19, Tailwind, axios, `docx-preview` |
| Output | `python-docx` (DOCX), `reportlab` (PDF) |

LLM transport is a plain `requests.post` to the Mantle chat-completions endpoint — no boto3. Two API
keys are round-robined with automatic failover on `401`/`403` and exponential backoff on
`429`/`503`. See [`core/mantle_client.py`](core/mantle_client.py).

Python 3.11 (conda env `tpm`). Note that `requirements.txt` pins `Django==5.0.1` but the working
environment runs **4.2.30** — the pin is aspirational, not what the code is tested against.

---

## Running it locally

### Configure

Copy the required environment variables into `.env` at the repo root (git-ignored — **never commit
it**):

```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=1
POSTGRES_DB=qpg
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Unset `POSTGRES_DB` to roll back to `db.sqlite3` instantly. Mantle API keys and image-provider keys
are read from the environment too — see `core/mantle_client.py` for the names.

```bash
pip install -r requirements.txt
python manage.py migrate
cd frontend && npm install
```

### Start — four terminals, in this order

```bash
# 1. Redis — the broker. Nothing queued runs without it.
cd redis && redis-server redis.windows.conf

# 2. Django API
conda activate tpm && python manage.py runserver 0.0.0.0:1223

# 3. Frontend  (http://localhost:4000)
cd frontend && npm run dev

# 4. Celery — ONE worker handles everything: papers, patterns, ingest, answer keys
conda activate tpm && celery -A qpg worker --loglevel=info --pool=threads -Q celery,patterns
```

### Verify

```bash
python manage.py celery_health              # exits 1 if anything is wrong
python manage.py celery_health --check-keys # one live call per API key
```

Healthy output:

```
workers  1 responding
queue    OK    celery    waiting=0
queue    OK    patterns  waiting=0
RESULT   healthy
```

Run this any time someone reports *"it's just loading."* A missing worker raises nothing —
`.delay()` still succeeds and the row simply says `queued` forever. `queue ORPHAN <name>` means the
worker isn't consuming that queue.

---

## Operational rules that matter

Three settings make the single-worker setup safe. Don't change them casually.

- **`--pool=threads`** — the whole point. `--pool=solo` runs one task at a time regardless of any
  setting, so a 20-minute paper blocked every 40-second pattern behind it. That was the original
  *"AI pattern just keeps loading"* bug. `prefork` is not usable on Windows.
- **`-Q celery,patterns`** — the worker must name **both** queues. Patterns are routed separately
  (`CELERY_TASK_ROUTES`) so they can move to a dedicated worker later; until then, drop either name
  and that half of the app silently stops while the UI spins.
- **No `--concurrency`** — deliberate. It comes from `CELERY_WORKER_CONCURRENCY` (6) so there is one
  source of truth. Six because papers hold a slot for minutes and patterns for seconds; the headroom
  keeps a slot free for a pattern while several papers build.

**LLM rate limiting.** Raising worker concurrency does *not* raise LLM load without bound. Each paper
already fans out 3 sections at once (`section_generator.MAX_PARALLEL_SECTIONS`), so 6 concurrent
papers would want 18 simultaneous calls. `mantle_client.MAX_CONCURRENT_CALLS` caps total in-flight
requests per process at 6 (override with `QPG_MAX_CONCURRENT_LLM_CALLS`). Without that cap you trade
a queue wait for HTTP 429s — and a 429 doesn't merely slow a paper, it can drop a whole section out
of it. Raise it only as more API keys go live. When saturated the log says
`[Mantle] WAIT ... all 6 call slots busy`.

**Known cost of one worker.** `mantle_client._run_stats` is a process-global tally reset at the start
of each task, so when several papers run at once their token and cost totals interleave. The
per-call `[Mantle] OK ...` lines stay accurate and are stamped with the stage, so individual calls
remain attributable — only the per-paper summary is approximate under load.

---

## Project layout

```
core/                     the application
  section_generator.py    retrieval, prompt assembly, per-section generation, most QC gates
  generator.py            paper assembly, DOCX/PDF rendering, blueprint conversion
  tasks.py                Celery tasks (papers, patterns, ingest, answer keys)
  models.py               School, ExamPattern, QuestionPaper, Material, MaterialChunk, ...
  mantle_client.py        Bedrock Mantle transport: key rotation, backoff, concurrency cap
  embeddings.py           chunking, embedding, vector queries
  enrichment.py           chapter labelling and summaries over uploaded material
  pattern_structure.py    pattern/slot schema — attempt-N-of-M, marks arithmetic
  paper_audit.py          marks and chapter-coverage audits
  image_finder.py         diagram sourcing and generation
  material_intel.py       book/chapter structure detection
  answer_key_*.py         answer key generation and rendering
  management/commands/    celery_health, import_sqp_patterns, seed_cbse_patterns, audit_papers, ...
api/                      REST API: auth, serializers, permissions, admin views
qpg/                      Django project — settings, celery app, urls
frontend/                 Next.js app (port 4000)
docs/                     architecture and planning notes
sqp/                      CBSE sample papers, imported as board patterns
redis/                    vendored Redis for Windows (only .conf is tracked)
```

`core/tests.py` is ~9,000 lines and `core/section_generator.py` ~8,400 — the two files worth reading
first if you're new to the codebase.

---

## The generation pipeline

1. **Ingest.** PDF → text → 1,000-char chunks with 150-char overlap → embedded with
   `nomic-embed-text` → `MaterialChunk` rows. Chapter membership goes in the `ChunkChapter` link
   table. Enrichment adds chapter summaries, cleaned text, and a `garbled` flag.
2. **Pattern.** A teacher's exam structure — sections, question types, counts, marks, instructions.
   Patterns can be authored by hand, generated by AI from a plain-text description, or imported
   one-to-one from a CBSE sample paper (`import_sqp_patterns`).
3. **Blueprint.** Optionally pins a specific chapter to each printed question. Without one, chapters
   are allocated automatically, CBSE-mark weighted and coordinated across the whole paper.
4. **Retrieve.** Per section and per chapter: an ANN query filtered to the chapter, excluding
   summary and garbled rows, with query hints derived from the section's question types. Results are
   spread across the chapter rather than taken from the top of the ranking.
5. **Generate.** Three sections at a time. Each printed question gets one chapter and one numbered
   source excerpt.
6. **Validate.** V1–V11 below.
7. **Assemble and render.** Marks reconciliation, section headings, DOCX/PDF, optional answer key.

### Marks and "answer any six"

A section reading *"Answer any SIX of the following"* over eight 2-mark questions is worth **12**
marks, not 16 — every printed question still carries 2m, but only six count. Two numbers therefore
coexist and both are correct:

- **Attemptable** — what a student can earn. This is what the paper header prints (80 for the
  reference Class 6 Science pattern).
- **Printed** — the sum of all printed questions (90 for the same pattern). This is what the
  per-section marks audit checks.

`pattern_structure.attemptable_marks` / `section_attempt` compute the former. A pattern saved before
attempt-N-of-M was understood still stores the printed sum in `total_marks`; `_paper_total_marks`
prefers the recomputed blueprint value, so the printed paper is right without a re-save.

When a pattern states its own section headings, they print the way the teacher wrote them — roman
numeral, their words, and the arithmetic of what a student *answers*:

```
I. Answer all the Multiple Choice Questions.          20 x 1 = 20
II. Answer any SIX of the following.                  6 x 2 = 12
III. Answer any SEVEN of the following.               7 x 3 = 21
```

---

## Quality checks

Every paper passes through these before a teacher sees it. Most warn and record rather than block —
a flagged paper still ships, with the issue stored for review.

| Gate | What it checks |
|---|---|
| **V1** | Full structural validation — every question, not a sample |
| **V2** | Content quality critic (LLM, batched per section) |
| **V3** | NCERT grounding — is the question actually supported by the material? |
| **V4** | Blind answer-key verification with confident auto-correction |
| **V5** | Duplicate detection — layer 1 lexical uniqueness, layer 2 semantic on flagged pairs |
| **V5x** | Cross-section duplicates |
| **V6** | Case-based / source passage validation |
| **V7** | Competency distribution (Bloom's taxonomy enforcement) |
| **V8** | Cross-section coherence |
| **V9** | Diagram quality — multi-image generation, ranking, and scientific-accuracy check (`core/image_finder.py`) |
| **V10** | Final paper-level audit — the master gate |
| **V11** | Answer-leak audit — one question giving away another's answer |

Plus non-LLM audits: `paper_audit.audit_paper_marks` (OR-aware, per-section marks) and
`audit_chapter_coverage` (did every planned chapter get a question?). Findings land in
`QuestionPaper.status_detail` as a teacher-facing note.

---

## Tests

```bash
PYTHONIOENCODING=utf-8 python manage.py test core
```

~700 tests in about 30 seconds. LLM and vision calls are mocked, so the suite costs nothing to run —
log lines like `[ImageFinder] vision call failed: endpoint down` are injected failures being
exercised on purpose, not a broken endpoint.

`PYTHONIOENCODING=utf-8` is required: existing prints contain emoji and cp1252 will crash on
Windows.

---

## Documentation

| Document | For |
|---|---|
| [`docs/PRODUCT_OVERVIEW.md`](docs/PRODUCT_OVERVIEW.md) | What the product does, who it's for, where its edges are — no code |
| [`docs/generate-paper-flow.md`](docs/generate-paper-flow.md) | End-to-end flow from *Generate* to rendered DOCX, with Mermaid diagrams |
| [`docs/PER_QUESTION_STRUCTURE.md`](docs/PER_QUESTION_STRUCTURE.md) | The slot schema — how a pattern describes each printed question |
| [`docs/PIPELINE_UPGRADE.md`](docs/PIPELINE_UPGRADE.md) | Generation pipeline design notes |
| [`docs/CHAPTER_ENRICHMENT_PLAN.md`](docs/CHAPTER_ENRICHMENT_PLAN.md) | Chapter labelling and enrichment |
| [`docs/PLAN.md`](docs/PLAN.md) · [`docs/LAUNCH_FIXES.md`](docs/LAUNCH_FIXES.md) | Known bugs and launch blockers — **check these first** |
| [`run_commands.txt`](run_commands.txt) | Canonical start order and maintenance commands |

---

## Maintenance

```bash
# Import the CBSE sample papers in sqp/ as board patterns.
# Re-run only when sqp/ is refreshed for a new academic year, or after adding a PDF
# (add its stem to SUBJECT_BY_STEM first).
python manage.py import_sqp_patterns
python manage.py import_sqp_patterns --dry-run   # preview, no DB writes

python manage.py seed_cbse_patterns   # seed the built-in CBSE pattern library
python manage.py audit_papers         # marks/coverage audit across existing papers
python manage.py fix_embedding_dims   # repair embedding dimensionality drift
```

---

## Notes for contributors

- `db.sqlite3` and `datadump.json` in the repo root are **stale**. Production is Postgres; ignore
  them.
- Never commit `.env`, `datadump.json` (password hashes), or anything under `media/`.
- The generation path writes `temp_*` debug artifacts to the repo root on every run. They're
  git-ignored and safe to delete.
- `core/generator.py`'s `render_section_questions` calls `save_generated_question` internally — it
  writes `GeneratedQuestion` rows. Stub it out if you call the render path from a throwaway script.
