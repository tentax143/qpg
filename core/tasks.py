from celery import shared_task
from .models import QuestionPaper, ExamPattern, School
from . import generator, embeddings
from django.core.files import File
from django.conf import settings
from django.db.models import F
import os

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
        pattern_data = generate_pattern_via_api(
            teacher_input=pattern.ai_prompt,
            class_name=pattern.class_name,
            subject=pattern.subject,
            exam_name=pattern.name,
        )
        pattern.sections       = pattern_data.get('sections', [])
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
def ingest_material_task(self, class_name, subject, materials, material_type="textbook", provider="local", school_id=None):
    """Ingest PDFs into ChromaDB. Textbooks go to shared + school store; private materials go to school store only."""
    try:
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
        return {"count": len(materials), "provider": provider, "school_id": school_id}
    except Exception as exc:
        print(f"[ingest_material_task] Error: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True)
def copy_shared_vectorstore_task(self, school_id):
    """Copy shared textbook vector store and Material records to a school."""
    from .models import Material, School
    school = School.objects.get(id=school_id)

    # 1. Copy ChromaDB vector data from shared → school's store
    count = embeddings.copy_shared_to_school(school_id)
    print(f"[copy_shared_vectorstore_task] Copied {count} vector store dirs to school {school_id}")

    # 2. Create Material records for shared textbooks not yet assigned to this school
    shared_textbooks = Material.objects.filter(type='textbook').exclude(school=school)
    created = 0
    for mat in shared_textbooks:
        already_exists = Material.objects.filter(
            school=school,
            class_name=mat.class_name,
            subject=mat.subject,
            unit=mat.unit,
            title=mat.title,
        ).exists()
        if not already_exists:
            Material.objects.create(
                school=school,
                class_name=mat.class_name,
                subject=mat.subject,
                unit=mat.unit,
                title=mat.title,
                file=mat.file.name,
                type='textbook',
                uploaded_by=None,
                metadata=mat.metadata or {},
            )
            created += 1
    print(f"[copy_shared_vectorstore_task] Created {created} Material records for school {school_id}")
    return {'vector_dirs_copied': count, 'materials_created': created}


@shared_task(bind=True)
def generate_paper_task(self, paper_id, blueprint_id=None, model_source='local', additional_context=""):
    paper = QuestionPaper.objects.get(id=paper_id)
    paper.status = "generating"
    paper.task_id = self.request.id  # Store the actual task ID
    paper.save()

    try:
        # Extract section from class_name if present (e.g., "11-A" -> section="A")
        class_name = paper.class_name
        section = None
        if "-" in class_name:
            class_name, section = class_name.split("-", 1)
        
        # Resolve school for vector store routing
        school_id = None
        try:
            school_id = paper.created_by.profile.school.id
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
        # Construct full path and save using File object to ensure proper extension
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                filename = os.path.basename(file_path)
                paper.file.save(filename, File(f), save=False)

        paper.cost = total_cost
        paper.input_tokens = input_tokens
        paper.output_tokens = output_tokens
        paper.status = "done"
        # Persist the raw generated JSON so we can re-render later without calling the LLM
        try:
            import json as _json
            with open("temp_clean.json", "r", encoding="utf-8") as _f:
                paper.paper_data = _json.load(_f)
        except Exception as _e:
            print(f"[Task] Could not save paper_data: {_e}")
        paper.save()

        # Update school cumulative usage (atomic — persists even after paper is deleted)
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

        return summary
        
    except Exception as e:
        # Mark the paper as failed (no auto-retry)
        paper.status = "failed"
        paper.save()

        # Log the error and let the task fail once
        print(f"[Task Failed] Paper ID {paper_id}: {str(e)}")
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
