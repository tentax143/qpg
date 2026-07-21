# QPG Codebase Sweep — Findings (2026-07-21)

Method: 17 area reviewers deep-read the backend, frontend, generation pipeline, and
docs; every critical/high finding was then adversarially re-verified by independent
agents (criticals got two — code-accuracy + real-world-impact — before being accepted).
69 agents total. Findings below are **confirmed** (survived verification) unless marked
otherwise. Known items already on your radar (datadump.json leak, dev-server deploy,
ALLOWED_HOSTS wildcard, no login rate-limit, tokens-never-expire, billing-is-a-flag,
no Sentry/CI/Docker) are excluded except where a *new, distinct* problem sits on top.

Line numbers are as of HEAD `4e8cd9a` + current working tree.

---

## The shape of it

The generation hardening you documented in `LAUNCH_FIXES.md` **mostly holds** — verifiers
confirmed PLAN bugs 1–5 fixed, the V1–V10 chain, two-pass MCQ correction (#2), top-up/refill
(#20/#22), marks audit (#9), and the thread-local request state are all real. The risk has
**moved outward** to three places the launch checklist didn't cover:

1. **Tenant isolation on the *peripheral* models** — patterns and blueprint-templates. The
   paper/material ViewSets are well-scoped; patterns and templates are not, and that's now the
   biggest hole (cross-tenant read *and write*, plus cascade data loss).
2. **Auth/token lifecycle** — logout is broken, tokens are never revocable, and the default
   entry page silently skips the first-login password change.
3. **Silent-failure paths that ship wrong exam content** — placeholder text printed as real
   questions, ungrounded generation, answer-key override, filename collisions.

43 confirmed crit/high (deduped to ~30 unique below), 107 medium/low, 2 refuted.

---

## TIER 0 — Fix this week (a single ordinary action *right now* corrupts/leaks/loses live exam data)

### 0.1 [CRITICAL] Deleting a shared pattern CASCADE-deletes every paper made from it — school-wide
`core/models.py:151` — `QuestionPaper.pattern` is `on_delete=CASCADE`, and patterns are shared
across the whole school (every member sees all of them, `api/views.py:294`). Any teacher deleting
a colleague's pattern silently deletes **every QuestionPaper built from it** — including finished
exam papers the deleter can't even see — plus each paper's `AnswerKey` (OneToOne CASCADE) and
`GeneratedQuestion` rows. No warning, no soft-delete. With exams running, one click destroys papers
school-wide.
→ Change to `PROTECT` (or `SET_NULL, null=True`) + migration; refuse deletion when papers reference
the pattern.

### 0.2 [CRITICAL] Any teacher can edit/delete the shared blueprint templates every school generates from
`api/views.py:2131` — `BlueprintTemplateViewSet` is a full `ModelViewSet` with only
`IsAuthenticated` and no object-level write guard. `get_queryset` deliberately includes shared
superadmin/default templates, so DRF's `update`/`destroy` resolve them — any teacher in any school
can `PATCH` a shared template's JSON (poisoning the structure other schools build exams from) or
`DELETE` it. `is_default` is also writable (`api/serializers.py:125`), so a teacher can publish
their own template globally. The frontend even shows Edit/Delete buttons on these
(`frontend/src/app/blueprints/page.js:157`). Contradicts LAUNCH #11.
→ Object-level permission: only superadmin writes shared/default templates; make `is_default`
read-only for non-superadmins.

### 0.3 [CRITICAL] Paper create/update accepts *any* school's pattern id (cross-tenant IDOR)
`api/views.py:780` — `pattern_id = data.get("pattern")` is written straight onto the paper with no
scope check (unlike `blueprint_id`, scoped two lines up). The create response nests the **full**
`ExamPatternSerializer` including `sections` and `ai_prompt` — for imported patterns, `ai_prompt`
is the complete extracted text of another school's uploaded board/sample paper. IDs are sequential
integers → trivial enumeration. Same hole on PATCH via `QuestionPaperSerializer.pattern_id`
(`queryset=ExamPattern.objects.all()`, `serializers.py:33`).
→ Resolve `pattern_id` through the caller's school-scoped queryset (404 otherwise); scope the
serializer field's queryset per-request.

### 0.4 [CRITICAL] The manual paper editor silently discards edits — teacher fixes a wrong question, ships the wrong one anyway
`frontend/src/app/papers/[id]/edit/page.js:274` — Edit mode makes the iframe `contentEditable`, but
Save/Export compute `content = docText || getIframeText()`, and `docText` is loaded from the server
at page load and never re-synced from typing. The stale server text always wins; the teacher's typed
correction is never read. Save then POSTs the old content and shows "Saved". Compounding it, Export
calls `/rerender/` which rebuilds from `paper_data` and never reads edited content at all
(`api/views.py:1132`), and inserted images are never persisted (`edit/page.js:527`). **The entire
manual-edit feature is non-functional while reporting success.** Also `papers/page.js:256` gates the
Download/Edit buttons on `paper.pdf_url`, a field the API doesn't return (it's `file`) — so every
paper older than the dashboard's top-10 has *no* download/edit path in the UI.
→ Read the iframe as source of truth on Save/Export (or route all edits through the AI/JSON flow);
fix `paper.pdf_url` → `paper.file`.

### 0.5 [HIGH] LLM-failure placeholder text ships as real exam questions (three paths)
- `core/section_generator.py:2884` — the individual LA/CBQ path appends `"[Individual generation
  failed: <exception>]"` as a real question on LLM/parse failure, sets no `_partial`/`_errors`, and
  the renderer doesn't strip `_generation_error`. Marks stay correct so the audit passes — a printed
  paper can contain the exception text as a 5-mark question with no warning badge.
- `core/section_generator.py:5220` — exactly **one** hard-failed section is tolerated (only ≥2 triggers
  fallback); the missing section renders as the literal line `"No questions found for section X"`
  (`core/generator.py:1217`), paper marked Completed⚠.
- `core/generator.py:1000` — in the single-prompt fallback, section-matching strategies 2–4 are dead
  code (`section_key` inits to `None`, gated on `section_key == sec` which can never be true), so
  unmatched sections also ship as `"No questions found"`.
→ Treat 1 failed section as failure; drop `_generation_error` questions and surface them; fix
`section_key` init so the fallback strategies run.

### 0.6 [HIGH] Live Redis dump with generated exam content is git-tracked and pushed to GitHub
`redis/dump.rdb` (+ `temp-*.rdb`, `server_log.txt`) are tracked (`git ls-files redis/`) and the repo
pushes to `github.com/tentax143/qpg`. The committed dump contains celery-task-meta SUCCESS results
**including generated question-paper content**, and `run_commands.txt` starts Redis with `dir ./`
inside the repo so the live broker state is rewritten into the working tree continuously
(`git status` shows `M redis/dump.rdb` right now). This is a *separate* leak from the known
datadump.json one, and it re-leaks fresh exam content on every commit.
→ `git rm --cached` the redis data/binaries, point Redis `dir` outside the repo, scrub history if the
GitHub repo is/becomes shared.

---

## TIER 1 — Tenant isolation (cross-school read/write beyond Tier 0)

- **[HIGH] "Already asked" question stems leak across schools** — `core/section_generator.py:67`.
  The LAUNCH #4 dedup block queries `GeneratedQuestion` by `class_name`+`subject` only; the model has
  **no school field**. Class names ("10-A") and subjects collide across your 3 schools, so School A's
  live exam question texts (up to 40 stems) are injected verbatim into School B's generation prompts
  (and written to project-root debug files). → Add a `school` FK + filter, or join via
  `paper_id__created_by`.
- **[HIGH] `BlueprintManager.get_blueprint` is tenant-blind** — `core/blueprint_manager.py:124`. The
  generation fallback (when a pattern is missing/empty) resolves a blueprint by `class_name`+`subject`
  only and takes `.first()` — School A's paper can be structured by School B's blueprint. (Also
  crashes with `FieldError` on sectioned classes like "11-A" — `ExamBlueprint` has no `section` field.)
- **[HIGH] Deleting a user leaks that school's patterns/templates globally** — `api/views.py:333`,
  `models.py:87`. `created_by` is `SET_NULL`; both "shared template" queries treat NULL creator as a
  global template. Delete a departed teacher → their patterns vanish from their own school and reappear
  as cloneable "premade" templates visible to **every** school (with `sections` + `ai_prompt`).
- **[HIGH] `/media/generated_images/` is unprotected and enumerable** — `core/media_access.py:18`,
  `core/views.py:83`. Only `question_papers/` and `materials/` are signed. Images extracted from real
  exam papers are written as `edit_{paper_id}_{idx}.png` — sequential, unauthenticated. Anyone can walk
  `edit_1_0.png`, `edit_2_0.png`… and pull every school's exam diagrams/source images.
- **[HIGH] SSRF via material URL import** — `core/material_intel.py:1000`. `fetch_url()` does
  `requests.get()` on any user-supplied URL with no host/IP allowlist and follows redirects;
  `preview_url` returns the fetched content as a response oracle. Any teacher can hit
  `http://127.0.0.1/…`, cloud metadata, or internal panels on the deploy box.
- **[HIGH] `upload_image` accepts any file with no validation** — `api/views.py:1489`. Whole file read
  into memory (no size cap), extension from user-controlled name, stored in unsigned public
  `paper_images/`. Upload an SVG/HTML with script → stored XSS on the backend origin (which also hosts
  `/admin` and the token API). Unbounded read = memory-DoS.
- **[HIGH] Media rename-suffix fallback can serve a *different* school's file** — `qpg/urls.py:40`. When
  a signed path is missing on disk, the code strips Django's `_XXXXXXX` collision suffix and serves
  whatever base-named file exists — which is precisely another school's file (that's why the suffix
  existed). Cross-tenant wrong-content delivery.

---

## TIER 2 — Auth & token lifecycle

- **[HIGH] Logout is broken and tokens are irrevocable** — `api/auth_views.py:49`. `django_logout()`
  sets `request.user = AnonymousUser()`, so the next line `request.user.auth_token.delete()` raises
  → 500, token never deleted. The frontend never calls logout anyway (`Sidebar.jsx:92` only clears
  localStorage). Net: a DRF token, once issued, can never be revoked by any user action, and a 24h
  Django session cookie survives on shared school computers after "logout".
- **[HIGH] Password change doesn't rotate tokens** — `api/auth_views.py:172`. Changing a password never
  deletes/rotates the token, so a compromised account stays compromised after a password change.
  `first_login_password` turns a stolen token into full credentials (no old password required, gated
  only on the default-True `require_password_change` flag).
- **[HIGH] `school_admin` can create and promote peer `school_admin`s** — `api/admin_views.py:175`. The
  `school_users` POST only downgrades `superadmin`; `school_admin` passes through, and
  `school_user_remove` PATCH lets a school_admin promote any teacher to school_admin. Contradicts the
  documented (LAUNCH #12) teacher-only policy — within-school privilege escalation.
- **[HIGH] Root `/` login page bypasses the first-login password change, billing notice, and superadmin
  routing** — `frontend/src/app/page.js:35`. There are two login forms; `/login` implements #13's
  change-password redirect + billing notice + superadmin routing, but `/` (the default landing page,
  and where logout dumps you) unconditionally goes to `/dashboard`. Admin-created users keep their
  temporary password; billing-lapsed schools never see the notice; superadmins land on the teacher
  dashboard. → Delete the duplicate form; make `/` render/redirect to the one real login.

---

## TIER 3 — Billing & quota enforcement

- **[HIGH] Material-upload billing gate is dead code** — `api/views.py:1712`. `MaterialViewSet` defines
  `create()` twice; the second (bulk/multi-chapter) shadows the first, which held the
  `_billing_blocked` 402 check. So uploads — which queue paid embedding + LLM chapter-naming — bypass
  billing on every path. A school marked `billing_period_over=True` can still incur cost. → Merge the
  check into the surviving method; delete the shadowed one.
- **[HIGH] Budget/billing is checked only at enqueue (TOCTOU)** — `core/tasks.py:656`. Neither
  `dispatch_next_queued_paper` nor `generate_paper_task` re-checks budget/billing. A user can stack N
  papers while under budget and all run to completion after the block; two simultaneous requests both
  pass the check before either records spend. Spend can arbitrarily exceed the cap.
- **[HIGH] `monthly_token_budget` never resets — it's a lifetime cap** — `api/views.py:102` (LAUNCH #5
  caveat, confirmed still true). Compared against ever-growing `total_tokens_used`, so any school with
  a budget hits a permanent mid-term hard-stop. Also only paper create/retry/regenerate are gated —
  answer keys, ai_edit/ai_correct, and enrichment spend tokens *and* increment the counter but are
  never budget-checked. → Compute month-to-date from `UsageEvent`; gate the other endpoints.

---

## TIER 4 — Silent-failure / wrong-content beyond Tier 0

- **[HIGH] OpenRouter-embedded materials are invisible to all retrieval → ungrounded generation,
  silently** — `core/embeddings.py:389`. Upload accepts `embedding_provider='openrouter'` and stores
  only `embedding_or`, but every retrieval call defaults to `provider='local'` and filters
  `embedding_local__isnull=False`. Those chunks never match; `get_section_context` returns `""`; the
  paper generates with zero grounding and **no log** — the #14 defense-in-depth guarantee regressed.
- **[HIGH] Embedding-backend outage persists all-zero vectors** — `core/embeddings.py:88`. Ollama/
  OpenRouter failures return `[[0.0]*dim]` per chunk, stored without validation. Zero-norm vectors give
  NaN cosine distance (sorted last), so any chunk ingested during a restart is permanently dead weight —
  material shows "uploaded" but never retrieves, no flag, no repair tool.
- **[HIGH] Answer-key MCQ options come from a single LLM pass that silently overrides the twice-verified
  answer** — `core/answer_key_generator.py:262`. The paper's stored answer is protected by #2's two-pass
  guard, but the answer-key generator (the DOCX teachers grade from) makes one call at temp 0.2, is told
  to treat the existing answer as "a draft to verify", and never compares its `correct_option` back to
  the verified answer. Disagreement ships silently. → Compare to the stored answer; warn/override on
  mismatch.
- **[HIGH] Teacher-selected blueprint is validated, stored, passed to the task — then ignored** —
  `core/tasks.py:677`. `generate_paper_task` accepts `blueprint_id` but never uses it; generation is
  driven only by `paper.pattern`, falling back to the (unscoped) `get_blueprint`. Teacher picks
  "Blueprint X", gets something else, no warning.
- **[HIGH] Single-prompt fallback truncates/alters the whole paper** — `core/generator.py:3878`. The
  fallback calls the LLM with no `max_tokens` (defaults to 4096; a full paper needs 6000+), "repairs"
  truncated JSON by appending `"}` * N and brace-counting (miscounts braces inside code/math questions),
  then asks the validator LLM to **re-emit the entire paper** (can paraphrase questions), also capped at
  4096. Only surfaces as a count-warning badge.
- **[HIGH] Output DOCX filename collision** — `core/generator.py:2990`. Saved as
  `{subject}_{YYYYmmddHHMMSS}.docx` in a shared flat dir, no paper id/uuid. Two renders of the same
  subject in the same second overwrite each other; both paper rows point at one file. Worst case across
  tenants: one school downloads another's exam. → Add paper id + uuid to the filename.

---

## TIER 5 — Reliability / ops regressions

- **[HIGH] `--pool=solo` nullifies your Celery safety net** — `core/tasks.py:609`, `run_commands.txt:15`.
  The production worker runs `--pool=solo` on Windows, where Celery time limits are **not enforced** and
  `revoke(terminate=True)` can't kill a running task. Consequences, all confirmed:
  - LAUNCH #6 regressed — a hung LLM call (retries=5 × ~295s) can pin the single worker ~25 min; all
    other schools' generations queue behind it (`core/generator.py:86`, `mantle_client.py:85`,
    `settings.py:202`).
  - `reap_stale_papers` assumes the (dead) time limit, so a legitimately long generation gets
    auto-failed at 30 min with a misleading "lost in a worker restart" message.
  - Cancel/delete is ineffective; the task's unconditional full `paper.save()` overwrites a concurrent
    `status='cancelled'` back to `done` **and resurrects deleted papers** (0-row UPDATE → INSERT with
    same pk) while billing anyway (`core/tasks.py:813`). `bulk_delete` doesn't revoke or promote the
    queue at all.
  → Run a pool that enforces limits (prefork/gevent), OR enforce a hard client-side deadline in code;
  finish with a conditional `.filter(status='generating').update(...)` and check rowcount before billing.
- **[HIGH] `requirements.txt` can't rebuild production** — `requirements.txt:2`. It pins Django **5.0.1**
  but the live env runs Django **4.2.30**, and has **no psycopg2** despite production running Postgres.
  A rebuild from it (your only DR path if the one machine dies mid-exam) produces a broken, untested
  stack that can't connect to the DB. → Regenerate from the live env.
- **[HIGH] Deleting a user erases their `UsageEvent` history and orphans their papers** —
  `core/models.py:342`. `UsageEvent.user` is CASCADE, so a school_admin removing a departed teacher wipes
  that teacher's token/cost audit trail (defeating #21's append-only design) and makes School counters
  disagree; their papers go `created_by=NULL` and become invisible to the school_admin. → Deactivate
  instead of delete, or `SET_NULL` + denormalized username.

---

## Refuted by verification (reported by a reviewer, dismissed on re-check — noted for the record)

1. *"Text-editor edits never mark the answer key stale"* — refuted because the text-editor export path
   is itself already broken (edits never reach the rendered file, see 0.4), so the staleness bug can't
   actually trigger. Fixing 0.4 will resurface this — re-check then.
2. *"Deleting papers CASCADE-deletes the anti-dup memory and degrades LAUNCH #4"* — refuted for
   *already-shipped* papers (their questions were already printed); real impact is only on future
   dedup breadth, which is minor.

---

## Long tail

107 medium/low findings were catalogued (63 medium, 44 low) — full detail retained separately. The
recurring themes worth a pass:

- **Dead code** to delete: `core/models_extended.py` (tables dropped in migration 0022),
  `core/pattern_question_generator.py` (would crash if invoked), `blueprint_handler.py` /
  `blueprint_detail_builder.py` / `blueprint_ai_generator.py` (zero importers), `qpg/celery_app.py`
  (byte-identical duplicate of `celery.py`), `check_question_similarity` (PLAN bug 6 — never wired up).
- **Prompt-injection**: material chunks + teacher free-text are interpolated raw into prompts with no
  delimiting (`core/generator.py:3740`).
- **CBSE scraper trust**: DDG fallback accepts any URL containing "cbseacademic" anywhere; fuzzy
  subject match on one shared word; stamps `sqp_year` "verified" even when the scrape failed and the LLM
  answered from memory — and these overwrite the `cbse_official` patterns *all* schools use
  (`core/cbse_scraper.py`, `core/tasks.py:1043`).
- **Frontend robustness**: the axios interceptor logs users out on *any* 403 (including legitimate
  business 403s), unguarded `JSON.parse` of localStorage can blank the app shell, dashboard polls every
  3s forever with no backoff, the superadmin Queue page is entirely hardcoded fake data.
- **Ops**: no `LOGGING` config (500s vanish with the console window), `SESSION_COOKIE_SECURE`/
  `CSRF_COOKIE_SECURE` not set over HTTPS, Redis has no `requirepass`, static files 404 in prod
  (whitenoise installed but not in MIDDLEWARE → `/admin` renders unstyled), no email backend / password
  reset, exam-content debug files (`temp_*.json`, `temp_prompt_*.txt`) written to project root on every
  generation, unbounded (PLAN 2.10, still open).

## Coverage note

`core/access.py` — the single source of truth for multi-tenant material visibility — was only touched
tangentially by the reviewers, not audited head-on. Given how much tenant isolation rides on it, it
deserves a dedicated pass. The management commands under `core/management/commands/` and the
`frontend/src/app/pattern/` (singular) and `create-pattern/` routes were also not covered.
