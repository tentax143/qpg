from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from .models import QuestionPaper, ExamPattern, ExamBlueprint, School
from . import generator, embeddings, mantle_client
from django.conf import settings
from django.db.models import F
import os
import time
import threading as _threading


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


# --- Pattern generation ------------------------------------------------------------
# A pattern is a SHORT job (one LLM call, plus at most one repair round), but it used to
# share the single default queue with paper generation, which legitimately runs for many
# minutes. The Windows deploy runs the worker with `--pool=solo` - ONE task at a time - so
# a teacher who clicked "AI generate pattern" while any paper anywhere on the instance was
# building sat on a spinner until that paper finished. Patterns are therefore routed to
# their own `patterns` queue (CELERY_TASK_ROUTES in settings) served by a separate worker,
# and bounded by their own time limits so one wedged LLM call cannot hold that queue either.
# Sized against api.ai_service.PATTERN_CALL_TIMEOUT: one bounded generation call plus one
# bounded repair call always fit, an endlessly stalled one never does.
PATTERN_SOFT_TIME_LIMIT = 8 * 60    # raises SoftTimeLimitExceeded -> task fails itself cleanly
PATTERN_TIME_LIMIT      = 9 * 60    # hard kill

# A pattern whose task evaporated (worker restart, broker flush, revoked message, a crash
# before the status was written) would otherwise sit at 'queued'/'generating' FOREVER, and
# the create-pattern page polls it every 3s with no deadline - this is the "AI pattern just
# keeps loading" report. Mirrors reap_stale_papers for QuestionPaper.
STALE_PATTERN_QUEUED_SECONDS     = 12 * 60   # never picked up by any worker
STALE_PATTERN_GENERATING_SECONDS = 10 * 60   # started, then the worker died mid-run


def reap_stale_patterns(user_id=None, pattern_ids=None):
    """Auto-fail patterns stuck in 'queued'/'generating' past their window, so the polling
    UI gets a real answer instead of an endless spinner. Scoped to one user (the poller) or
    to explicit ids; with neither it sweeps every pattern. Returns the reaped ids."""
    from django.utils import timezone
    now = timezone.now()
    qs = ExamPattern.objects.filter(status__in=['queued', 'generating'])
    if pattern_ids is not None:
        qs = qs.filter(id__in=pattern_ids)
    if user_id is not None:
        qs = qs.filter(created_by_id=user_id)

    reaped = []
    for pat in qs:
        window = (STALE_PATTERN_GENERATING_SECONDS if pat.status == 'generating'
                  else STALE_PATTERN_QUEUED_SECONDS)
        # updated_at is auto_now, so it tracks the last status write (queued -> generating).
        if (now - pat.updated_at).total_seconds() > window:
            pat.status = 'failed'
            pat.save(update_fields=['status', 'updated_at'])
            reaped.append(pat.id)
    if reaped:
        print(f"[reap_stale_patterns] auto-failed stale pattern(s) {reaped}")
    return reaped


def build_validated_sections(pattern_data, *, teacher_input, class_name, subject,
                             exam_name, log=print):
    """normalize -> validate -> one repair round -> teacher-visible warnings -> derive
    aggregates. The single structural contract for every pattern that arrives as LLM JSON.

    Shared by generate_pattern_task (the live AI / PDF-import path) and the
    import_sqp_patterns management command, so a pattern seeded from a CBSE sample paper
    goes through exactly the same checks as one a teacher types in.

    Returns the (possibly repaired) sections list; `pattern_data` is updated in place when
    a repair is accepted, so its total_marks / total_questions stay consistent with them.
    """
    from . import pattern_structure

    sections = pattern_structure.normalize_slots(pattern_data.get('sections', []))
    errors = pattern_structure.validate_pattern_structure(
        sections, declared_total=pattern_data.get('total_marks'))

    if errors:
        # One repair round: resend the source text + failed JSON + the numbered errors.
        # Keep the repair only if it did not get worse and did not destroy question slots.
        from api.ai_service import repair_pattern_via_api
        log(f"{len(errors)} structure error(s) - attempting repair round")
        try:
            repaired = repair_pattern_via_api(
                teacher_input=teacher_input,
                class_name=class_name,
                subject=subject,
                exam_name=exam_name,
                previous_json=pattern_data,
                errors_text=pattern_structure.format_structure_errors(errors),
            )
            r_sections = pattern_structure.normalize_slots(repaired.get('sections', []))
            r_errors = pattern_structure.validate_pattern_structure(
                r_sections, declared_total=repaired.get('total_marks'))
            # Accept the repair only if it did not delete or de-value any question slot - a
            # repair that reconciles marks by dropping questions (Q19/Q20) or lowering slot
            # marks destroys content; keeping the faithful original WITH warnings is better.
            if r_sections and len(r_errors) <= len(errors) and \
                    pattern_structure.repair_preserves_slots(sections, r_sections):
                pattern_data.update(repaired)
                sections, errors = r_sections, r_errors
            else:
                log("Repair rejected "
                    f"(errors {len(errors)} -> {len(r_errors)}, slots preserved: "
                    f"{pattern_structure.repair_preserves_slots(sections, r_sections)})")
        except Exception as repair_exc:
            log(f"Repair round failed - keeping original: {repair_exc}")

    # Residual errors become teacher-visible warnings on the sections they concern
    # (paper-level ones land on the first section).
    for e in errors:
        idx = e.get('section')
        target = (sections[idx] if idx is not None and 0 <= idx < len(sections)
                  else (sections[0] if sections else None))
        if isinstance(target, dict):
            target.setdefault('_structure_warnings', []).append(e['msg'])
    if errors:
        log(f"{len(errors)} unresolved structure warning(s) saved on the pattern")

    pattern_structure.derive_aggregates_from_slots(sections)
    return sections


@shared_task(bind=True, max_retries=2, default_retry_delay=60,
             soft_time_limit=PATTERN_SOFT_TIME_LIMIT, time_limit=PATTERN_TIME_LIMIT)
def generate_pattern_task(self, pattern_id):
    """Parse the pattern's ai_prompt into structured sections via AI. For 'ai_generated'
    patterns the prompt is the teacher's description; for 'imported' ones it is the full
    text of an uploaded sample paper PDF. Runs in Celery worker."""
    from api.ai_service import generate_pattern_via_api, extract_pattern_from_sqp_via_api

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
        if pattern.pattern_source == 'imported':
            pattern_data = extract_pattern_from_sqp_via_api(
                sqp_text=pattern.ai_prompt,
                class_name=pattern.class_name,
                subject=pattern.subject,
                exam_name=pattern.name,
            )
        else:
            pattern_data = generate_pattern_via_api(
                teacher_input=pattern.ai_prompt,
                class_name=pattern.class_name,
                subject=pattern.subject,
                exam_name=pattern.name,
            )

        sections = build_validated_sections(
            pattern_data,
            teacher_input=pattern.ai_prompt,
            class_name=pattern.class_name,
            subject=pattern.subject,
            exam_name=pattern.name,
            log=lambda m: print(f"[generate_pattern_task] {m}"),
        )

        pattern.sections       = _fill_section_counts(sections)
        pattern.total_marks    = pattern_data.get('total_marks', 0)
        pattern.total_questions = pattern_data.get('total_questions', 0)
        pattern.status = 'done'
        pattern.save()
        print(f"[generate_pattern_task] Done — pattern_id={pattern_id} sections={len(pattern.sections)} marks={pattern.total_marks}")
        return {'id': pattern_id, 'status': 'done', 'sections': len(pattern.sections)}
    except SoftTimeLimitExceeded:
        # Don't retry a timeout — a pattern that couldn't be parsed in PATTERN_SOFT_TIME_LIMIT
        # won't parse in the next 6 minutes either, and retrying it holds the queue behind it.
        # Fail immediately so the polling UI stops spinning and the teacher can edit the prompt.
        print(f"[generate_pattern_task] Timed out after {PATTERN_SOFT_TIME_LIMIT}s — pattern_id={pattern_id}")
        pattern.status = 'failed'
        pattern.save(update_fields=['status'])
        return {'id': pattern_id, 'status': 'failed', 'reason': 'timeout'}
    except Exception as exc:
        print(f"[generate_pattern_task] Error — pattern_id={pattern_id}: {exc}")
        # Keep the row 'generating' between retries: flipping it to 'failed' here made the
        # polling UI give up and show an error while a retry that would have succeeded was
        # still scheduled. Only the FINAL attempt is allowed to mark the pattern failed.
        if self.request.retries >= self.max_retries:
            pattern.status = 'failed'
            pattern.save(update_fields=['status'])
            raise
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            pattern.status = 'failed'
            pattern.save(update_fields=['status'])
            raise


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
    pipeline (core/enrichment.py). Materials are grouped to the parallel pool size so a
    book upload's chapters enrich concurrently; enrichment problems must never break
    ingestion."""
    from . import enrichment
    ids = sorted({m for m in (material_ids or []) if m})
    size = max(1, enrichment.enrich_concurrency())
    for i in range(0, len(ids), size):
        group = ids[i:i + size]
        try:
            enrich_materials_group_task.delay(group)
        except Exception as e:
            print(f"[Enrich] could not enqueue materials {group}: {e}")


_run_error_lock = _threading.Lock()   # error_samples is read-modify-write — atomic per process


def _enrich_one_and_record(material_id, run_id=None, force=False):
    """Enrich ONE material and do all its bookkeeping (run gate + counters, school
    cumulative stats, usage event, run finalization). Shared by the single-material
    task and by each thread of the parallel group task, so stop/resume semantics and
    progress math are identical however the material was scheduled.

    Idempotent — already enriched chunks are skipped unless force=True, so retries
    never re-bill the LLM.

    Work only happens while the run is 'running'. Any other status means the run was
    stopped, auto-failed (stale) or closed — this drains as a no-op so a zombie queue
    (e.g. tasks that survived a Redis outage) can never race a newer run on the same
    material and double-bill the LLM. Draining under 'stopping' is counted in
    drained_groups; once every queued task is accounted for the run flips 'stopped'."""
    from django.utils import timezone
    from .models import EnrichmentRun, UsageEvent, Material
    from . import enrichment

    run = EnrichmentRun.objects.filter(id=run_id).first() if run_id else None
    if run and run.status != 'running':
        if run.status == 'stopping':
            # Count the drain so the run can flip to 'stopped' when fully accounted.
            EnrichmentRun.objects.filter(id=run.id).update(
                drained_groups=F('drained_groups') + 1, updated_at=timezone.now())
            run.refresh_from_db()
            _finalize_enrichment_run(run)
        # Terminal statuses (stopped/done/failed): pure no-op — never touch a closed run's
        # counters (redelivered tasks after a broker restart land here).
        return {"material_id": material_id, "ok": True, "skipped": True, "stopped": True}

    ok, stats, err = True, None, None
    try:
        stats = enrichment.enrich_material(material_id, force=force, run_id=run_id)
    except Exception as e:
        ok = False
        err = str(e)[:300]
        print(f"[enrich_material_task] material {material_id} failed: {e}")

    stats = stats or {}
    input_tokens = int(stats.get("input_tokens") or 0)
    output_tokens = int(stats.get("output_tokens") or 0)
    cost = enrichment.calculate_cost(input_tokens, output_tokens) if (input_tokens or output_tokens) else 0

    mat = Material.objects.filter(id=material_id).first()

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
            # A mid-material stop returns ok=True with stats['stopped']: the material was
            # NOT completed (its copy stayed pending) — count it drained, not done.
            stopped_early = bool(stats.get('stopped'))
            EnrichmentRun.objects.filter(id=run.id).update(
                done_groups=F('done_groups') + (1 if ok and not stopped_early else 0),
                failed_groups=F('failed_groups') + (0 if ok else 1),
                drained_groups=F('drained_groups') + (1 if ok and stopped_early else 0),
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
            if errs:
                with _run_error_lock:   # parallel group threads append concurrently
                    run.refresh_from_db()
                    if len(run.error_samples or []) < 20:
                        run.error_samples = ((run.error_samples or []) +
                                             [f"material {material_id}: {e}" for e in errs])[:20]
                        run.save(update_fields=['error_samples', 'updated_at'])
            _finalize_enrichment_run(run)
        except Exception as e:
            print(f"[enrich_material_task] run bookkeeping failed: {e}")

    return {"material_id": material_id, "ok": ok,
            "chunks_labeled": stats.get("chunks_labeled", 0),
            "summaries_created": stats.get("summaries_created", 0),
            "skipped": stats.get("skipped", False),
            "stopped": bool(stats.get("stopped"))}


@shared_task(bind=True)
def enrich_material_task(self, material_id, run_id=None, force=False):
    """LLM-label one material's chunks (see _enrich_one_and_record). Kept as a task in
    its own right so messages queued before a deploy (which reference this task name)
    still execute."""
    return _enrich_one_and_record(material_id, run_id=run_id, force=force)


@shared_task(bind=True)
def enrich_materials_group_task(self, material_ids, run_id=None, force=False):
    """Enrich a small GROUP of materials concurrently — one thread per material, pool
    sized enrichment.enrich_concurrency() (= 3 per configured Mantle API key; the
    round-robin key rotation in mantle_client keeps ≈3 in-flight calls per key).

    All bookkeeping stays PER MATERIAL via _enrich_one_and_record, so run progress,
    billing and stop draining are identical to single-material scheduling. Groups are
    sized to the pool, so the wall time per task ≈ the slowest single material —
    comfortably under the Celery time limits, and paper-generation tasks still
    interleave between groups on the solo worker."""
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections
    from . import enrichment

    ids = [m for m in (material_ids or []) if m]
    if not ids:
        return {"materials": 0}

    def _one(mid):
        try:
            return _enrich_one_and_record(mid, run_id=run_id, force=force)
        except Exception as e:   # a broken material must not sink its group-mates
            print(f"[enrich_group] material {mid} crashed: {e}")
            return {"material_id": mid, "ok": False, "stopped": False}
        finally:
            # Each pool thread opened its own DB connection — release it, or a long
            # backfill leaks one connection per thread per task.
            for conn in connections.all():
                conn.close()

    workers = min(len(ids), max(1, enrichment.enrich_concurrency()))
    if workers == 1:
        results = [_enrich_one_and_record(ids[0], run_id=run_id, force=force)]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one, ids))

    return {"materials": len(ids),
            "ok": sum(1 for r in results if r.get("ok")),
            "stopped": sum(1 for r in results if r.get("stopped"))}


def _finalize_enrichment_run(run):
    """Flip a run to its terminal status once every queued task has reported in
    (done + failed + drained >= total). 'stopping' with real drains ends 'stopped';
    'stopping' where nothing actually drained (stop clicked as the last task finished)
    ends like a normal completion. Concurrent tasks may both call this — the flip is
    idempotent (same terminal value)."""
    if run.status not in ('running', 'stopping'):
        return
    if run.done_groups + run.failed_groups + run.drained_groups < run.total_groups:
        return
    if run.status == 'stopping' and run.drained_groups:
        run.status = 'stopped'
    else:
        run.status = 'failed' if (run.failed_groups and not run.done_groups) else 'done'
    run.save(update_fields=['status', 'updated_at'])


@shared_task(bind=True)
def classify_all_chapters_task(self, force=False, user_id=None):
    """Backfill chapter-kind classification (ChapterInfo — ONE kind per chapter) across
    the whole store WITHOUT re-reading chunks through the LLM: each chapter is judged
    from its name + stored enrichment summary + one sample chunk, batched ~30 chapters
    per call and parallelized over the enrichment call gate. Idempotent — already
    classified chapters are skipped unless force=True. New uploads classify themselves
    inside enrich_material; this task exists for the corpus enriched before the feature."""
    from concurrent.futures import ThreadPoolExecutor
    from django.contrib.auth.models import User
    from .models import MaterialChunk, ChapterInfo, UsageEvent
    from . import enrichment

    keys = list(
        MaterialChunk.objects.filter(kind='body', chapter_links__isnull=False)
        .values_list('class_name', 'subject', 'chapter_links__unit').distinct())
    done = set() if force else {
        (c, s, u) for c, s, u in
        ChapterInfo.objects.exclude(kind='').values_list('class_name', 'subject', 'unit')}

    entries = []
    for cls, subj, unit in keys:
        # Kinds only exist for language subjects — Maths/Science chapters stay unbadged.
        if not unit or (cls, subj, unit) in done or not enrichment.is_language_subject(subj):
            continue
        seed = (MaterialChunk.objects
                .filter(class_name=cls, subject=subj, kind='body',
                        chapter_links__unit=unit, garbled=False)
                .order_by('material_id', 'chunk_index').first())
        summary = (MaterialChunk.objects
                   .filter(class_name=cls, subject=subj, kind='summary',
                           chapter_links__unit=unit)
                   .values_list('content', flat=True).first()) or ''
        entries.append({
            'class_name': cls, 'subject': subj, 'unit': unit, 'display': unit,
            'material_title': (seed.title if seed else '') or '',
            'summary': summary,
            'sample': ((seed.content_clean or seed.content) if seed else '') or '',
        })
    if not entries:
        print("[classify_chapters] nothing to classify")
        return {'classified': 0, 'chapters': 0}

    # Parallelize across batches; classify_chapter_kinds itself does no DB work, so the
    # threads need no connection management. The enrichment call gate caps total
    # concurrent LLM calls process-wide.
    sublists = [entries[i:i + enrichment.CLASSIFY_BATCH]
                for i in range(0, len(entries), enrichment.CLASSIFY_BATCH)]
    workers = min(len(sublists), max(1, enrichment.enrich_concurrency()))
    total_in = total_out = 0
    kind_map = {}
    if workers == 1:
        results = [enrichment.classify_chapter_kinds(sl) for sl in sublists]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(enrichment.classify_chapter_kinds, sublists))
    for km, tin, tout in results:
        kind_map.update(km)
        total_in += tin
        total_out += tout

    enrichment.upsert_chapter_kinds(kind_map)

    if total_in or total_out:
        cost = enrichment.calculate_cost(total_in, total_out)
        user = User.objects.filter(id=user_id).first() if user_id else None
        if user:
            try:
                UsageEvent.record(user=user, school=None, kind='enrichment',
                                  input_tokens=total_in, output_tokens=total_out, cost=cost or 0)
            except Exception as e:
                print(f"[classify_chapters] usage event failed: {e}")

    print(f"[classify_chapters] classified {len(kind_map)}/{len(entries)} chapters "
          f"({total_in + total_out} tokens)")
    return {'classified': len(kind_map), 'chapters': len(entries),
            'input_tokens': total_in, 'output_tokens': total_out}


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

# 'generating' silent past this is dead — the Celery hard time limit is 25 min, so a
# live task cannot go 30 min without finishing (every status change bumps updated_at).
STALE_GENERATING_SECONDS = 30 * 60
# 'queued' + dispatched whose task never started within the broker's redelivery window
# (Redis visibility timeout, 1 h) — the message is gone (broker restart, queue wipe).
STALE_DISPATCHED_SECONDS = 65 * 60


def reap_stale_papers(user_id):
    """Auto-fail this user's DEAD generations so a ghost row can never hold the per-user
    serial slot forever (a 'queued'+dispatched paper whose Celery task evaporated in a
    worker/Redis restart used to wedge every later paper as eternally 'waiting').
    A 'queued' paper without a task_id is only waiting in line — never reaped."""
    from django.utils import timezone
    now = timezone.now()
    reaped = []
    for p in QuestionPaper.objects.filter(created_by_id=user_id,
                                          status__in=['queued', 'generating']):
        if p.status == 'queued' and not p.task_id:
            continue
        window = STALE_GENERATING_SECONDS if p.status == 'generating' else STALE_DISPATCHED_SECONDS
        if (now - p.updated_at).total_seconds() > window:
            p.status = 'failed'
            p.status_detail = ('Generation was lost in a worker/broker restart — auto-failed '
                               'to free your queue slot. Use Retry to run it again.')
            p.save(update_fields=['status', 'status_detail', 'updated_at'])
            reaped.append(p.id)
    if reaped:
        print(f"[reap_stale_papers] auto-failed stale paper(s) {reaped} for user {user_id}")
    return reaped


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
    reap_stale_papers(user_id)   # a dead generation must not block the promotion forever
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


def _resolve_blueprint(blueprint_id, paper):
    """Resolve the `blueprint_id` the generate form sent into an ExamBlueprint, or None.

    The form sends prefixed ids ("exam_12") because the same field historically also offered
    BlueprintTemplates; only the `exam_` form addresses a real per-pattern unit plan. Anything
    else — a template id, a stale id, a blueprint for a different pattern — must degrade to
    "generate without a blueprint" rather than fail the paper, because the paper's structure
    comes from the pattern and is perfectly generatable without one.
    """
    raw = str(blueprint_id or '').strip()
    if not raw:
        return None
    if raw.startswith('exam_'):
        raw = raw[len('exam_'):]
    if not raw.isdigit():
        print(f"[Task] blueprint_id {blueprint_id!r} is not an exam blueprint — ignoring")
        return None

    blueprint = ExamBlueprint.objects.filter(id=int(raw), is_active=True).first()
    if blueprint is None:
        print(f"[Task] blueprint {raw} not found — generating without one")
        return None
    if not blueprint.all_units():
        print(f"[Task] blueprint {raw} has an empty unit map — generating without one")
        return None
    # A blueprint is a plan for ONE pattern's question numbers. Applied to a different pattern
    # its qnums address different questions, so it would assign units to the wrong ones.
    if blueprint.pattern_id and paper.pattern_id and blueprint.pattern_id != paper.pattern_id:
        print(f"[Task] blueprint {raw} belongs to pattern {blueprint.pattern_id}, "
              f"paper uses pattern {paper.pattern_id} — ignoring (question numbers would not line up)")
        return None
    return blueprint


def _available_units(paper):
    """Units that actually have uploaded material for this paper's class+subject — used only to
    warn about blueprint units that will generate ungrounded."""
    from .models import Material
    class_num = str(paper.class_name or '').split('-')[0]
    if not class_num or not paper.subject:
        return []
    return list(
        Material.objects
        .filter(class_name__istartswith=class_num, subject__iexact=paper.subject)
        .values_list('unit', flat=True).distinct())


@shared_task(bind=True)
def generate_paper_task(self, paper_id, blueprint_id=None, model_source='local', additional_context=""):
    # Ghost-message guard: with acks_late, a task can be redelivered long after its paper
    # was deleted, cancelled or auto-failed (reap_stale_papers). Never resurrect those —
    # only 'queued' (fresh dispatch/retry) and 'generating' (worker died mid-run) may run.
    paper = QuestionPaper.objects.filter(id=paper_id).first()
    if paper is None:
        print(f"[generate_paper_task] paper {paper_id} no longer exists — skipping")
        return {"paper_id": paper_id, "skipped": True}
    if paper.status not in ('queued', 'generating'):
        print(f"[generate_paper_task] paper {paper_id} is '{paper.status}' — not resurrecting a closed paper")
        return {"paper_id": paper_id, "skipped": True}
    paper.status = "generating"
    paper.task_id = self.request.id  # Store the actual task ID
    paper.status_detail = ""         # clear any prior failure reason / warning
    paper.save()

    # Per-paper LLM tally, so the running totals on every [Mantle] line and the closing
    # by-model / by-key breakdown describe THIS paper and not everything this worker has done.
    _t_task = time.time()
    mantle_client.reset_run_stats()
    print(f"[Task] ===== generate_paper_task paper={paper_id} task={self.request.id} =====")
    print(f"[Task] class={paper.class_name} subject={paper.subject} "
          f"difficulty={paper.difficulty} chapters={len(paper.chapters or [])} "
          f"pattern={getattr(paper.pattern, 'id', None)} model_source={model_source}")
    print(f"[Task] {mantle_client.models_summary()}")
    print(f"[Task] {mantle_client.keys_summary()}")

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

        # ── Blueprint: the teacher's per-question unit plan for this pattern ──────────
        # `blueprint_id` used to be accepted here and then dropped on the floor — the argument
        # was threaded all the way from the generate form and never read, so attaching a
        # blueprint did nothing at all. It now resolves to an ExamBlueprint whose unit_map
        # overrides the automatic chapter allocation per printed question
        # (section_generator.apply_unit_map).
        unit_map = None
        gen_chapters = list(paper.chapters or [])
        if blueprint_id:
            blueprint = _resolve_blueprint(blueprint_id, paper)
            if blueprint is not None:
                unit_map = blueprint
                bp_units = blueprint.all_units()
                # UNION, not replace: a unit the blueprint pins must be retrievable or its
                # questions get no context, and a chapter the teacher ticked must not vanish
                # just because the blueprint does not mention it.
                added = [u for u in bp_units if u not in gen_chapters]
                gen_chapters += added
                print(f"[Task] blueprint={blueprint.id} '{blueprint.name or blueprint}' "
                      f"units={len(bp_units)}"
                      + (f" (+{len(added)} added to chapters: {', '.join(added)})" if added else ""))
                # A pinned unit with no uploaded material is a real misconfiguration: the
                # question will be written from the model's own knowledge with no textbook
                # grounding. Name it rather than let the paper come back subtly wrong.
                known = set(_available_units(paper))
                if known:
                    missing = [u for u in bp_units if u not in known]
                    if missing:
                        print(f"[Task] WARNING blueprint units with NO uploaded material: "
                              f"{', '.join(missing)} — those questions will be ungrounded")

        # Source mix (percent of questions the model composes itself). The request's meta wins
        # — a regenerate can change it — with the paper's stored setting as the fallback.
        try:
            creative_ratio = int(extra_meta.get('creative_ratio', paper.creative_ratio) or 0)
        except (TypeError, ValueError):
            creative_ratio = paper.creative_ratio or 0

        file_path, summary, total_cost, input_tokens, output_tokens = generator.generate_paper(
            class_name=class_name,
            subject=paper.subject,
            chapters=gen_chapters,
            difficulty=paper.difficulty,
            pattern=pattern_obj,
            section=section,
            model_source=model_source,
            additional_context=additional_context,
            school_id=school_id,
            unit_map=unit_map,
            creative_ratio=creative_ratio,
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

        print(f"[Task] DONE paper={paper_id} in {time.time() - _t_task:.0f}s — "
              f"cost={total_cost:.4f}INR in={input_tokens} out={output_tokens} "
              f"file={'yes' if paper.file.name else 'MISSING'}")
        for _line in mantle_client.run_stats_lines():
            print(f"[Task] {_line}")
        if notes:
            for _n in notes:
                print(f"[Task] note: {_n}")

        # Count AI images in this paper so we can attribute them to the school below.
        try:
            from .paper_audit import count_paper_images
            img_count = count_paper_images(paper.paper_data or {})
        except Exception:
            img_count = 0

        # Update school cumulative usage (atomic — persists even after paper is deleted)
        school = None
        try:
            school = paper.created_by.profile.school
            if school:
                School.objects.filter(pk=school.pk).update(
                    total_papers_generated=F('total_papers_generated') + 1,
                    total_tokens_used=F('total_tokens_used') + input_tokens + output_tokens,
                    total_cost_accumulated=F('total_cost_accumulated') + (total_cost or 0),
                    total_images_generated=F('total_images_generated') + img_count,
                )
                print(f"[Task] Updated school '{school.name}' cumulative stats (+{img_count} images)")
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

        # Log the error and let the task fail once. The LLM breakdown goes out here too — a
        # failed paper is exactly when you need to know which model and which key were involved
        # and how far the run got before it died.
        print(f"[Task Failed] Paper ID {paper_id} after {time.time() - _t_task:.0f}s: {str(e)}")
        for _line in mantle_client.run_stats_lines():
            print(f"[Task Failed] {_line}")
        import traceback as _tb
        print(_tb.format_exc())
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

    # 'cbse_official' ONLY, deliberately: this task re-derives a pattern from the CBSE site with
    # the LLM, which would replace a `cbse_sqp` question-by-question replica of the official sample
    # paper with a looser reconstruction. Those are maintained by `manage.py import_sqp_patterns`
    # from the PDFs in sqp/ instead.
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
