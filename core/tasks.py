from celery import shared_task
from .models import QuestionPaper, ExamPattern, School
from . import generator, embeddings
from django.conf import settings
from django.db.models import F
import os


def _fill_section_counts(sections):
    """Fill questions_count / marks_per_question for any section that has marks but left
    them blank — the AI pattern generator sometimes omits them, which would otherwise make
    the section generate zero questions. Compound sections (with subsections) are left alone."""
    def typical(types):
        text = " ".join(str(t).lower() for t in (types or []))
        if "long answer" in text:
            return 5.0
        if "very short" in text:
            return 2.0
        if "short answer" in text:
            return 3.0
        if any(k in text for k in ("case", "source", "cbq")):
            return 4.0
        return 1.0

    def _num(v, default=0):
        try:
            return type(default)(v) if v not in (None, "", "varies") else default
        except (TypeError, ValueError):
            return default

    for s in sections or []:
        if not isinstance(s, dict) or s.get("subsections"):
            continue
        # Slot-authored sections get their aggregates (incl. deliberately
        # absent marks_per_question on mixed-marks sections) from
        # pattern_structure.derive_aggregates_from_slots — don't reinvent them.
        if s.get("question_slots"):
            continue
        marks = _num(s.get("marks"), 0)
        qc = _num(s.get("questions_count") or s.get("questions"), 0)
        mpq = _num(s.get("marks_per_question"), 0.0)
        if mpq <= 0:
            mpq = round(marks / qc, 2) if qc else typical(s.get("question_types"))
        if qc <= 0 and marks and mpq:
            qc = max(1, round(marks / mpq))
        if qc:
            s["questions_count"] = qc
        if mpq:
            s["marks_per_question"] = mpq
    return sections


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_pattern_task(self, pattern_id):
    """Parse teacher's text prompt into structured pattern sections via AI. Runs in Celery worker."""
    from api.ai_service import generate_pattern_via_api

    try:
        pattern = ExamPattern.objects.get(id=pattern_id)
    except ExamPattern.DoesNotExist:
        print(f"[generate_pattern_task] Pattern {pattern_id} not found")
        return

    pattern.status = 'generating'
    pattern.task_id = self.request.id
    pattern.save(update_fields=['status', 'task_id'])
    print(f"[generate_pattern_task] Starting — pattern_id={pattern_id} subject={pattern.subject} class={pattern.class_name}")

    try:
        from . import pattern_structure

        pattern_data = generate_pattern_via_api(
            teacher_input=pattern.ai_prompt,
            class_name=pattern.class_name,
            subject=pattern.subject,
            exam_name=pattern.name,
        )
        sections = pattern_structure.normalize_slots(pattern_data.get('sections', []))
        errors = pattern_structure.validate_pattern_structure(
            sections, declared_total=pattern_data.get('total_marks'))

        if errors:
            # One repair round: resend the teacher's text + failed JSON + the
            # numbered errors. Keep the repair only if it didn't get worse.
            from api.ai_service import repair_pattern_via_api
            print(f"[generate_pattern_task] {len(errors)} structure error(s) — attempting repair round")
            try:
                repaired = repair_pattern_via_api(
                    teacher_input=pattern.ai_prompt,
                    class_name=pattern.class_name,
                    subject=pattern.subject,
                    exam_name=pattern.name,
                    previous_json=pattern_data,
                    errors_text=pattern_structure.format_structure_errors(errors),
                )
                r_sections = pattern_structure.normalize_slots(repaired.get('sections', []))
                r_errors = pattern_structure.validate_pattern_structure(
                    r_sections, declared_total=repaired.get('total_marks'))
                # Accept the repair only if it did not delete or de-value any
                # question slot — a repair that reconciles marks by dropping
                # questions (Q19/Q20) or lowering slot marks destroys teacher
                # content; keeping the faithful original WITH warnings is better.
                if r_sections and len(r_errors) <= len(errors) and \
                        pattern_structure.repair_preserves_slots(sections, r_sections):
                    pattern_data, sections, errors = repaired, r_sections, r_errors
                else:
                    print("[generate_pattern_task] Repair rejected "
                          f"(errors {len(errors)} -> {len(r_errors)}, "
                          f"slots preserved: {pattern_structure.repair_preserves_slots(sections, r_sections)})")
            except Exception as repair_exc:
                print(f"[generate_pattern_task] Repair round failed — keeping original: {repair_exc}")

        # Residual errors become teacher-visible warnings on the sections they
        # concern (paper-level ones land on the first section).
        for e in errors:
            idx = e.get('section')
            target = sections[idx] if idx is not None and 0 <= idx < len(sections) else (sections[0] if sections else None)
            if isinstance(target, dict):
                target.setdefault('_structure_warnings', []).append(e['msg'])
        if errors:
            print(f"[generate_pattern_task] {len(errors)} unresolved structure warning(s) saved on pattern {pattern_id}")

        pattern_structure.derive_aggregates_from_slots(sections)
        pattern.sections       = _fill_section_counts(sections)
        pattern.total_marks    = pattern_data.get('total_marks', 0)
        pattern.total_questions = pattern_data.get('total_questions', 0)
        pattern.status = 'done'
        pattern.save()
        print(f"[generate_pattern_task] Done — pattern_id={pattern_id} sections={len(pattern.sections)} marks={pattern.total_marks}")
        return {'id': pattern_id, 'status': 'done', 'sections': len(pattern.sections)}
    except Exception as exc:
        print(f"[generate_pattern_task] Error — pattern_id={pattern_id}: {exc}")
        pattern.status = 'failed'
        pattern.save(update_fields=['status'])
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def ingest_material_task(self, class_name, subject, materials, material_type="textbook", provider="local", school_id=None, auto_name=False):
    """Ingest PDFs into ChromaDB. Textbooks go to shared + school store; private materials go to school store only.

    auto_name=True: before ingesting, detect each PDF's chapter name from its content (snapping
    to the CBSE catalog) and update both the unit used for ingestion and the Material row — so a
    file with a random name still gets a clean, consistent unit. Best-effort per file."""
    try:
        if auto_name:
            from .models import Material
            from . import material_intel
            for m in materials:
                try:
                    detected = material_intel.detect_unit_name(m["file_path"], class_name, subject)
                    if detected:
                        old = m.get("unit")
                        m["unit"] = detected
                        if m.get("material_id"):
                            Material.objects.filter(id=m["material_id"]).update(unit=detected, title=detected)
                        print(f"[ingest_material_task] auto-named '{os.path.basename(m['file_path'])}': "
                              f"'{old}' → '{detected}'")
                except Exception as e:
                    print(f"[ingest_material_task] auto-name failed for '{m.get('file_path')}': {e}")

        if material_type == "textbook":
            # Textbooks go to the shared namespace (source of truth for copying)
            embeddings.ingest_bulk(class_name, subject, materials, material_type=material_type, provider=provider, school_id=None)
            # Also ingest to the uploading school's store for immediate use
            if school_id:
                embeddings.ingest_bulk(class_name, subject, materials, material_type=material_type, provider=provider, school_id=school_id)
            chunks_label = "shared + school"
        else:
            # Private materials: school store only
            embeddings.ingest_bulk(class_name, subject, materials, material_type=material_type, provider=provider, school_id=school_id)
            chunks_label = f"school_{school_id}"
        print(f"[ingest_material_task] Done — {class_name}/{subject} → {chunks_label} via {provider}")
        _enqueue_enrichment([m.get("material_id") for m in materials])
        return {"count": len(materials), "provider": provider, "school_id": school_id}
    except Exception as exc:
        print(f"[ingest_material_task] Error: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True)
def split_book_task(self, class_name, subject, file_path, material_type="textbook",
                    provider="local", school_id=None, uploaded_by_id=None, base_material_id=None,
                    vector_store_id=None):
    """Split a whole-textbook PDF into per-chapter units: detect chapter page ranges, create one
    Material row per chapter (all referencing the same uploaded file) and ingest each chapter's
    pages as its own unit. The placeholder 'source book' Material (base_material_id) is reused as
    the first chapter so the uploaded file is never orphaned. Falls back to a single unit if the
    book can't be split into 2+ chapters."""
    from .models import Material
    from . import material_intel

    chapters = material_intel.detect_book_chapters(file_path, class_name, subject, school_id=school_id,
                                                   persist_toc=True)
    if not chapters:
        # Couldn't split — treat the whole file as one auto-named unit.
        name = material_intel.detect_unit_name(file_path, class_name, subject) or \
            os.path.splitext(os.path.basename(file_path))[0]
        chapters = [{"unit": name, "start_page": 0, "end_page": material_intel.page_count(file_path)}]
    print(f"[split_book_task] '{os.path.basename(file_path)}' → {len(chapters)} chapter(s)")

    base = Material.objects.filter(id=base_material_id).first() if base_material_id else None
    file_name = base.file.name if base else None

    def _ingest(unit, pr, material_id):
        if material_type == "textbook":
            embeddings.ingest_pdf(class_name, subject, unit, file_path, title=unit,
                                  material_type=material_type, provider=provider, school_id=None, page_range=pr, source_id=material_id)
            if school_id:
                embeddings.ingest_pdf(class_name, subject, unit, file_path, title=unit,
                                      material_type=material_type, provider=provider, school_id=school_id, page_range=pr, source_id=material_id)
        else:
            embeddings.ingest_pdf(class_name, subject, unit, file_path, title=unit,
                                  material_type=material_type, provider=provider, school_id=school_id, page_range=pr, source_id=material_id)

    created = 0
    ingested_ids = []
    for idx, ch in enumerate(chapters):
        unit = ch["unit"]
        pr = (ch["start_page"], ch["end_page"])
        meta = {"auto_split": True, "pages": [ch["start_page"], ch["end_page"]]}
        try:
            if idx == 0 and base is not None:
                # Reuse the placeholder row as chapter 1 (keeps the uploaded file owned).
                base.unit = unit
                base.title = unit
                base.metadata = meta
                base.save(update_fields=["unit", "title", "metadata"])
                mat = base
            else:
                mat = Material.objects.create(
                    class_name=class_name, subject=subject, unit=unit, title=unit,
                    type=material_type, file=file_name, school_id=school_id,
                    vector_store_id=vector_store_id,
                    visibility=('store' if vector_store_id else ('shared' if school_id is None else 'private')),
                    uploaded_by_id=uploaded_by_id, metadata=meta,
                )
            _ingest(unit, pr, mat.id)
            created += 1
            ingested_ids.append(mat.id)
        except Exception as e:
            print(f"[split_book_task] chapter '{unit}' failed: {e}")

    print(f"[split_book_task] Done — created/ingested {created}/{len(chapters)} chapter unit(s)")
    _enqueue_enrichment(ingested_ids)
    return {"chapters": created, "school_id": school_id}


@shared_task(bind=True)
def ingest_url_task(self, class_name, subject, url, material_type="textbook",
                    provider="local", school_id=None, uploaded_by_id=None, vector_store_id=None):
    """Import a whole-book HTML page (e.g. a TN-schools textbook URL): fetch it, split into
    per-chapter units by heading tags, save the source HTML once, create one Material row per
    chapter (all referencing that file) and ingest each chapter's text as its own unit. Clean
    Unicode text — works for Tamil/Hindi where PDF extraction fails."""
    import re as _re
    from django.core.files.base import ContentFile
    from .models import Material
    from . import material_intel

    html = material_intel.fetch_url(url)
    chapters = material_intel.extract_html_chapters(html, subject)
    if not chapters:
        print(f"[ingest_url_task] no usable text extracted from {url}")
        return {"chapters": 0}
    if len(chapters) == 1 and not chapters[0].get("unit"):
        chapters[0]["unit"] = material_intel.detect_unit_name(
            None, class_name, subject, sample_text=chapters[0]["text"][:2500]) or "Imported Material"
    print(f"[ingest_url_task] {url} → {len(chapters)} chapter(s)")

    slug = _re.sub(r'[^a-zA-Z0-9]+', '_', f"{class_name}_{subject}_book")[:60] or "book"
    saved_name = None
    created = 0

    def _ingest(unit, text, material_id):
        if material_type == "textbook":
            embeddings.ingest_text(class_name, subject, unit, text, title=unit,
                                   material_type=material_type, provider=provider, school_id=None, source_id=material_id)
            if school_id:
                embeddings.ingest_text(class_name, subject, unit, text, title=unit,
                                       material_type=material_type, provider=provider, school_id=school_id, source_id=material_id)
        else:
            embeddings.ingest_text(class_name, subject, unit, text, title=unit,
                                   material_type=material_type, provider=provider, school_id=school_id, source_id=material_id)

    ingested_ids = []
    for ch in chapters:
        unit = ch.get("unit")
        if not unit:
            continue
        try:
            mat = Material(class_name=class_name, subject=subject, unit=unit, title=unit,
                           type=material_type, school_id=school_id, uploaded_by_id=uploaded_by_id,
                           vector_store_id=vector_store_id,
                           visibility=('store' if vector_store_id else ('shared' if school_id is None else 'private')),
                           metadata={"source_url": url, "imported_html": True})
            if saved_name is None:
                mat.file.save(f"{slug}.html", ContentFile(html.encode("utf-8")), save=False)
                saved_name = mat.file.name
            else:
                mat.file = saved_name
            mat.save()
            _ingest(unit, ch["text"], mat.id)
            created += 1
            ingested_ids.append(mat.id)
        except Exception as e:
            print(f"[ingest_url_task] chapter '{unit}' failed: {e}")

    print(f"[ingest_url_task] Done — created/ingested {created}/{len(chapters)} chapter unit(s) from {url}")
    _enqueue_enrichment(ingested_ids)
    return {"chapters": created, "school_id": school_id}


# ── Chunk enrichment (LLM metadata labeling) ──────────────────────────────────

def _enqueue_enrichment(material_ids):
    """Fire-and-forget: push freshly ingested materials through the LLM chunk-enrichment
    pipeline (core/enrichment.py). One small task per material so the solo worker stays
    responsive; enrichment problems must never break ingestion."""
    for mid in {m for m in (material_ids or []) if m}:
        try:
            enrich_material_task.delay(mid)
        except Exception as e:
            print(f"[Enrich] could not enqueue material {mid}: {e}")


@shared_task(bind=True)
def enrich_material_task(self, material_id, run_id=None, force=False):
    """LLM-label one material's chunks (content kind / language / per-chunk chapter /
    garbled flag + chapter summary chunks — see core/enrichment.py). Deliberately small:
    one material per task so a corpus backfill interleaves with paper generation on the
    solo worker and stays far under the Celery hard time limit. Idempotent — already
    enriched chunks are skipped unless force=True, so retries never re-bill the LLM.

    `run_id` ties the task to an EnrichmentRun row (superadmin backfill); counters are
    updated there so the frontend polls durable DB state, not Celery's result backend."""
    from django.utils import timezone
    from .models import EnrichmentRun, UsageEvent, Material
    from . import enrichment

    ok, stats, err = True, None, None
    try:
        stats = enrichment.enrich_material(material_id, force=force)
    except Exception as e:
        ok = False
        err = str(e)[:300]
        print(f"[enrich_material_task] material {material_id} failed: {e}")

    stats = stats or {}
    input_tokens = int(stats.get("input_tokens") or 0)
    output_tokens = int(stats.get("output_tokens") or 0)
    cost = enrichment.calculate_cost(input_tokens, output_tokens) if (input_tokens or output_tokens) else 0

    mat = Material.objects.filter(id=material_id).first()
    run = EnrichmentRun.objects.filter(id=run_id).first() if run_id else None

    if input_tokens or output_tokens:
        try:
            if mat and mat.school_id:
                School.objects.filter(pk=mat.school_id).update(
                    total_tokens_used=F('total_tokens_used') + input_tokens + output_tokens,
                    total_cost_accumulated=F('total_cost_accumulated') + (cost or 0),
                )
        except Exception as _se:
            print(f"[enrich_material_task] Could not update school cumulative stats: {_se}")
        user = (run.created_by if run else None) or (mat.uploaded_by if mat else None)
        if user:
            try:
                UsageEvent.record(user=user, school=(mat.school if mat else None), kind='enrichment',
                                  input_tokens=input_tokens, output_tokens=output_tokens, cost=cost or 0)
            except Exception as _ue:
                print(f"[enrich_material_task] Could not record usage event: {_ue}")

    if run:
        try:
            EnrichmentRun.objects.filter(id=run.id).update(
                done_groups=F('done_groups') + (1 if ok else 0),
                failed_groups=F('failed_groups') + (0 if ok else 1),
                chunks_labeled=F('chunks_labeled') + int(stats.get('chunks_labeled') or 0),
                summaries_created=F('summaries_created') + int(stats.get('summaries_created') or 0),
                garbled_found=F('garbled_found') + int(stats.get('garbled') or 0),
                input_tokens=F('input_tokens') + input_tokens,
                output_tokens=F('output_tokens') + output_tokens,
                cost=F('cost') + (cost or 0),
                updated_at=timezone.now(),  # .update() skips auto_now — set it so staleness checks work
            )
            run.refresh_from_db()
            errs = [str(e) for e in (stats.get('errors') or [])]
            if err:
                errs.append(err)
            if errs and len(run.error_samples or []) < 20:
                run.error_samples = ((run.error_samples or []) +
                                     [f"material {material_id}: {e}" for e in errs])[:20]
                run.save(update_fields=['error_samples', 'updated_at'])
            if run.status == 'running' and run.done_groups + run.failed_groups >= run.total_groups:
                run.status = 'failed' if (run.failed_groups and not run.done_groups) else 'done'
                run.save(update_fields=['status', 'updated_at'])
        except Exception as e:
            print(f"[enrich_material_task] run bookkeeping failed: {e}")

    return {"material_id": material_id, "ok": ok,
            "chunks_labeled": stats.get("chunks_labeled", 0),
            "summaries_created": stats.get("summaries_created", 0),
            "skipped": stats.get("skipped", False)}


@shared_task(bind=True)
def copy_shared_vectorstore_task(self, school_id):
    """Deprecated no-op. Granting a school access_shared_vector_store now takes effect immediately
    via scope-based visibility (core.access.visibility_q) — the school sees the shared store's
    materials and chunks directly at query time, with no copying or duplicated Material rows.
    Retained so the admin grant/resync endpoints keep working."""
    print(f"[copy_shared_vectorstore_task] no-op (scope-based sharing) for school {school_id}")
    return {'copied': 0, 'note': 'scope-based sharing — nothing to copy'}


# ── Per-user serial generation queue ──────────────────────────────────────────
# A user runs ONE paper generation at a time. A request made while another is active
# is stored as 'queued' *without* a task_id (waiting in line) instead of being refused;
# when the active generation finishes it is promoted into a real Celery task here.

def dispatch_paper(paper):
    """Enqueue the generation Celery task for `paper` using its stored gen_params, and record the
    resulting task_id. This is what turns a 'waiting' (queued, no task_id) paper into a running one."""
    params = paper.gen_params or {}
    task = generate_paper_task.delay(
        paper.id,
        blueprint_id=params.get('blueprint_id') or None,
        model_source=params.get('model_source') or 'aws',
        additional_context=params.get('additional_context') or "",
    )
    paper.task_id = task.id
    paper.save(update_fields=['task_id'])
    return task


def dispatch_next_queued_paper(user_id):
    """Promote this user's oldest *waiting* paper (status 'queued', no task_id) into a running task.
    No-op if the user still has an active generation. Row-locks the user's non-terminal papers so a
    completion and a cancel racing on the same user can't both dispatch — only one wins per call."""
    from django.db import transaction
    with transaction.atomic():
        rows = list(QuestionPaper.objects
                    .select_for_update()
                    .filter(created_by_id=user_id, status__in=['queued', 'generating'])
                    .order_by('created_at'))
        # 'active' = already occupying/about to occupy a worker: generating, or queued+dispatched.
        if any(p.status == 'generating' or (p.status == 'queued' and p.task_id) for p in rows):
            return None
        waiting = next((p for p in rows if p.status == 'queued' and not p.task_id), None)
        if waiting is None:
            return None
        return dispatch_paper(waiting)


@shared_task(bind=True)
def generate_paper_task(self, paper_id, blueprint_id=None, model_source='local', additional_context=""):
    paper = QuestionPaper.objects.get(id=paper_id)
    paper.status = "generating"
    paper.task_id = self.request.id  # Store the actual task ID
    paper.status_detail = ""         # clear any prior failure reason / warning
    paper.save()

    try:
        # Extract section from class_name if present (e.g., "11-A" -> section="A")
        class_name = paper.class_name
        section = None
        if "-" in class_name:
            class_name, section = class_name.split("-", 1)
        
        # Resolve school for vector store routing + paper header.
        school_id = None
        school_name = ""
        try:
            _school = paper.created_by.profile.school
            if _school:
                school_id = _school.id
                school_name = _school.name or ""
        except Exception:
            pass

        # One Mark Test: override pattern sections dynamically
        import json as _json
        pattern_obj = paper.pattern
        extra_meta = {}
        try:
            extra_meta = _json.loads(additional_context) if additional_context else {}
        except Exception:
            pass

        # Always stamp the paper's school on the header. The create-flow meta can arrive empty
        # (e.g. session quirks) and the header would otherwise render with no school name.
        if school_name and not extra_meta.get("school_name"):
            extra_meta["school_name"] = school_name
            additional_context = _json.dumps(extra_meta)

        if pattern_obj and pattern_obj.pattern_source == 'one_mark_test':
            n = int(extra_meta.get('num_one_mark_questions') or 20)
            pattern_obj.sections = [{
                'name': 'A',
                'title': 'One Mark Multiple Choice Questions',
                'marks': n,
                'questions_count': n,
                'marks_each': 1,
                'internal_choice': False,
                'question_types': ['mcq'],
                'notes': (
                    'Each question has EXACTLY 4 options (a, b, c, d). '
                    'CRITICAL: Distribute correct answers RANDOMLY across options — '
                    'roughly equal frequency of a, b, c, d as the correct answer. '
                    'Do NOT bias toward any single option. '
                    'No two consecutive questions may share the same correct answer letter.'
                ),
            }]
            pattern_obj.total_marks = n
            pattern_obj.total_questions = n

        file_path, summary, total_cost, input_tokens, output_tokens = generator.generate_paper(
            class_name=class_name,
            subject=paper.subject,
            chapters=paper.chapters,
            difficulty=paper.difficulty,
            pattern=pattern_obj,
            section=section,
            model_source=model_source,
            additional_context=additional_context,
            school_id=school_id,
        )

        # file_path is relative like "question_papers/filename.docx"
        # Point the FileField at the already-saved disk file.
        # Do NOT use paper.file.save() — Django renames to avoid collisions,
        # storing a different path in the DB than what's on disk → 404 on download.
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        if os.path.exists(full_path):
            paper.file.name = file_path

        paper.cost = total_cost
        paper.input_tokens = input_tokens
        paper.output_tokens = output_tokens
        paper.status = "done"
        # Persist the raw generated JSON so we can re-render later without calling the LLM.
        # Read from thread-local state set by generator.enforce_json() or
        # generator._render_paper_from_data() — avoids the shared temp_clean.json race condition.
        try:
            paper.paper_data = getattr(generator._request_state, 'paper_data', None)
            if paper.paper_data is None:
                print(f"[Task] paper_data not available in request state; paper_data will be empty")
        except Exception as _e:
            print(f"[Task] Could not save paper_data: {_e}")

        # Teacher-facing note: warn if generated without materials (#8) and if the whole-paper
        # marks total drifts from the pattern total (#9).
        notes = []
        try:
            from .models import Material
            cls_num = (class_name or '').split('-')[0]
            if not Material.objects.filter(class_name=cls_num, subject__iexact=paper.subject).exists():
                notes.append("Generated without uploaded materials for this class/subject — "
                             "verify the questions against the syllabus.")
        except Exception:
            pass
        try:
            # OR-aware, per-section marks audit: sum per-question marks (an OR /
            # internal-choice pair counts once) and compare to the pattern, section
            # by section, so a mismatch names the exact section and cause.
            from .paper_audit import audit_paper_marks, summary_line
            if paper.pattern:
                result = audit_paper_marks(paper.paper_data or {}, paper.pattern)
                if not result["ok"]:
                    notes.append("Marks check — " + summary_line(result))
        except Exception:
            pass
        try:
            # Chapter-coverage audit: did every planned (weighted) chapter get a question?
            from .paper_audit import audit_chapter_coverage, coverage_summary_line
            cov = audit_chapter_coverage(paper.paper_data or {})
            cov_line = coverage_summary_line(cov)
            if cov_line:
                notes.append("Coverage — " + cov_line)
        except Exception:
            pass
        paper.status_detail = " ".join(notes)
        paper.save()

        # Update school cumulative usage (atomic — persists even after paper is deleted)
        school = None
        try:
            school = paper.created_by.profile.school
            if school:
                School.objects.filter(pk=school.pk).update(
                    total_papers_generated=F('total_papers_generated') + 1,
                    total_tokens_used=F('total_tokens_used') + input_tokens + output_tokens,
                    total_cost_accumulated=F('total_cost_accumulated') + (total_cost or 0),
                )
                print(f"[Task] Updated school '{school.name}' cumulative stats")
        except Exception as _se:
            print(f"[Task] Could not update school cumulative stats: {_se}")

        # Per-user usage log — survives paper deletion, so the team-usage page stays accurate
        # (a regenerate re-runs this task and correctly logs another event).
        try:
            from .models import UsageEvent
            UsageEvent.record(
                user=paper.created_by, school=school, paper_id=paper.id, kind="generate",
                input_tokens=input_tokens, output_tokens=output_tokens, cost=total_cost or 0,
            )
        except Exception as _ue:
            print(f"[Task] Could not record usage event: {_ue}")

        return summary
        
    except Exception as e:
        # Mark the paper as failed (no auto-retry) and record a short reason for the teacher.
        paper.status = "failed"
        paper.status_detail = str(e)[:500]
        paper.save()

        # Log the error and let the task fail once
        print(f"[Task Failed] Paper ID {paper_id}: {str(e)}")
        raise

    finally:
        # This generation is over (done or failed) — hand off to the user's next waiting paper,
        # if any. Best-effort: a failure here must not mask the task's own result/exception.
        try:
            dispatch_next_queued_paper(paper.created_by_id)
        except Exception as _dq:
            print(f"[Task] dispatch_next_queued failed for user {paper.created_by_id}: {_dq}")


# ── Answer key generation ─────────────────────────────────────────────────────

@shared_task(bind=True)
def generate_answer_key_task(self, answer_key_id):
    """Generate the teacher answer key for one paper (one LLM call per question, so it
    runs async). Stores the structured JSON on AnswerKey.data; the DOCX is rendered on
    demand at download time from that JSON, so there is no file to keep in sync."""
    from .models import AnswerKey, UsageEvent
    from . import answer_key_generator

    key = AnswerKey.objects.select_related('paper', 'requested_by').get(id=answer_key_id)
    key.status = 'generating'
    key.task_id = self.request.id
    key.error_detail = ''
    key.save(update_fields=['status', 'task_id', 'error_detail', 'updated_at'])

    paper = key.paper
    try:
        school = None
        school_id = None
        try:
            school = paper.created_by.profile.school
            school_id = school.id if school else None
        except Exception:
            pass

        data, input_tokens, output_tokens = answer_key_generator.build_answer_key(
            paper, school_id=school_id)
        cost = answer_key_generator.calculate_cost(input_tokens, output_tokens)

        key.data = data
        key.source_revision_hash = answer_key_generator.paper_revision_hash(paper.paper_data)
        key.input_tokens = input_tokens
        key.output_tokens = output_tokens
        key.cost = cost
        key.status = 'done'
        key.save()

        # School cumulative usage (tokens/cost only — an answer key is not a new paper).
        try:
            if school:
                School.objects.filter(pk=school.pk).update(
                    total_tokens_used=F('total_tokens_used') + input_tokens + output_tokens,
                    total_cost_accumulated=F('total_cost_accumulated') + (cost or 0),
                )
        except Exception as _se:
            print(f"[AnswerKeyTask] Could not update school cumulative stats: {_se}")

        # Per-user usage log — the requester pays, not necessarily the paper's creator.
        try:
            UsageEvent.record(
                user=key.requested_by or paper.created_by, school=school,
                paper_id=paper.id, kind='answer_key',
                input_tokens=input_tokens, output_tokens=output_tokens, cost=cost or 0,
            )
        except Exception as _ue:
            print(f"[AnswerKeyTask] Could not record usage event: {_ue}")

        return {'generated_questions': data.get('generated_questions'),
                'errors': len(data.get('errors') or [])}

    except Exception as e:
        key.status = 'failed'
        key.error_detail = str(e)[:500]
        key.save(update_fields=['status', 'error_detail', 'updated_at'])
        print(f"[AnswerKeyTask Failed] AnswerKey {answer_key_id} (paper {paper.id}): {e}")
        raise


# ── CBSE pattern updater ──────────────────────────────────────────────────────

_CBSE_SYSTEM_PROMPT = """You are a CBSE curriculum expert with precise knowledge of official CBSE Sample Question Papers (SQP) 2024-25 and 2025-26.

Return ONLY a JSON object (no markdown, no explanation) with this exact structure:
{
  "sections": [
    {
      "name": "A",
      "title": "Descriptive section title",
      "marks": 16,
      "questions": 16,
      "marks_each": 1,
      "internal_choice": false,
      "internal_choice_count": 0,
      "question_types": ["MCQ", "Assertion-Reason"],
      "hots_count": 2,
      "competency_based_count": 4,
      "notes": "12 MCQ (1 mark) + 4 Assertion-Reason (1 mark)"
    }
  ],
  "total_marks": 70,
  "total_questions": 33,
  "duration_hours": 3,
  "paper_notes": "Theory paper. Practical: 30 marks (assessed separately)."
}

Rules:
- Use ONLY official CBSE 2025-26 SQP structure (fall back to 2024-25 if 2025-26 not available).
- The sum of (questions * marks_each) across all sections must exactly equal total_marks.
- Include HOTS (Higher Order Thinking Skills) counts where applicable per section.
- Include competency_based_count (case/source/passage/map-based questions) per section.
- Return only valid JSON."""


def _call_mantle(prompt: str) -> dict:
    import json as _json
    from . import mantle_client
    raw, _, _ = mantle_client.converse(
        model_id=mantle_client.GEN_MODEL,
        prompt=prompt,
        system_prompt=_CBSE_SYSTEM_PROMPT,
        max_tokens=2000,
        temperature=0.1,
    )
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    return _json.loads(text.strip())


@shared_task(bind=True)
def update_cbse_patterns_task(self, class_filter=None, subject_filter=None):
    """
    For each CBSE official ExamPattern:
      1. Scrape the actual SQP PDF from cbseacademic.nic.in (web scraper).
      2. Pass the extracted PDF text as grounding context to DeepSeek V3.2.
      3. Validate and save the updated sections to the DB.
    """
    from .models import ExamPattern
    from . import cbse_scraper

    qs = ExamPattern.objects.filter(pattern_source='cbse_official').order_by('class_name', 'subject')
    if class_filter:
        qs = qs.filter(class_name__in=class_filter)
    if subject_filter:
        qs = qs.filter(subject__in=subject_filter)

    TARGET_YEAR = '2025-26'
    results = []

    # Skip patterns already verified against the current year
    all_patterns = list(qs)
    skipped_current = [p for p in all_patterns if p.sqp_year == TARGET_YEAR]
    patterns = [p for p in all_patterns if p.sqp_year != TARGET_YEAR]

    for p in skipped_current:
        results.append({
            'id': p.id,
            'name': p.name,
            'subject': p.subject,
            'class_name': p.class_name,
            'status': 'skipped',
            'reason': f'Already at {TARGET_YEAR}',
        })
        print(f"[update_cbse_patterns] SKIP (already {TARGET_YEAR}): {p.subject} Class {p.class_name}")

    total = len(all_patterns)

    for i, pattern in enumerate(patterns):
        label = f"{pattern.subject} Class {pattern.class_name}"
        done_so_far = len(skipped_current) + i + 1
        self.update_state(state='PROGRESS', meta={
            'current': done_so_far,
            'total': total,
            'current_subject': f"Scraping SQP: {label}",
            'results': results,
        })
        print(f"[update_cbse_patterns] [{done_so_far}/{total}] Updating: {label}")

        # Step 1: Scrape actual SQP PDF text from CBSE website
        sqp_text = cbse_scraper.fetch_sqp_text(pattern.class_name, pattern.subject)
        if sqp_text:
            print(f"[update_cbse_patterns]   📄 Got {len(sqp_text)} chars from CBSE SQP PDF")
            grounding = (
                f"\n\nACTUAL CBSE SQP CONTENT (scraped from cbseacademic.nic.in):\n"
                f"{'='*60}\n{sqp_text}\n{'='*60}\n\n"
                f"Extract the exact section structure from the above real SQP content. "
                f"The scraped content is the ground truth — use it precisely."
            )
        else:
            print(f"[update_cbse_patterns]   ⚠ No SQP PDF found — using LLM knowledge only")
            grounding = (
                f"\n\nNote: Could not fetch the live SQP PDF. Use your best knowledge of "
                f"the official CBSE 2025-26 SQP structure for this subject."
            )

        self.update_state(state='PROGRESS', meta={
            'current': i + 1,
            'total': total,
            'current_subject': f"Analysing: {label}",
            'results': results,
        })

        prompt = (
            f"Return the LATEST official CBSE Board exam pattern for:\n"
            f"Subject: {pattern.subject}\n"
            f"Class: {pattern.class_name}\n"
            f"Exam: Annual Board Exam (theory paper only)\n"
            f"Academic Year: 2025-26 (STRICTLY use 2025-26 Sample Question Paper. "
            f"Only fall back to 2024-25 if 2025-26 SQP is genuinely not published yet.)\n\n"
            f"Current DB record: {pattern.total_marks} marks, {pattern.total_questions} questions.\n"
            f"Return the accurate 2025-26 structure even if it differs from the current DB record."
            f"{grounding}"
        )

        try:
            data = _call_mantle(prompt)
            sections = data.get('sections', [])
            if not sections:
                raise ValueError('AI returned empty sections')

            # Validate marks add up
            computed_marks = sum(s.get('marks', 0) for s in sections)
            if computed_marks != data.get('total_marks', 0):
                raise ValueError(f"Marks mismatch: sections sum={computed_marks} vs total={data.get('total_marks')}")

            old_marks = pattern.total_marks
            old_q = pattern.total_questions
            pattern.sections = sections
            pattern.sqp_year = TARGET_YEAR
            pattern.save()  # recalculates totals via get_total_marks / get_total_questions

            results.append({
                'id': pattern.id,
                'name': pattern.name,
                'subject': pattern.subject,
                'class_name': pattern.class_name,
                'status': 'updated',
                'marks': pattern.total_marks,
                'questions': pattern.total_questions,
                'changed_marks': pattern.total_marks != old_marks,
                'changed_questions': pattern.total_questions != old_q,
            })
            print(f"[update_cbse_patterns]   ✓ {label}: {pattern.total_marks}M {pattern.total_questions}Q")

        except Exception as exc:
            print(f"[update_cbse_patterns]   ✗ {label}: {exc}")
            results.append({
                'id': pattern.id,
                'name': pattern.name,
                'subject': pattern.subject,
                'class_name': pattern.class_name,
                'status': 'error',
                'error': str(exc),
            })

    return {'status': 'done', 'total': total, 'results': results}
