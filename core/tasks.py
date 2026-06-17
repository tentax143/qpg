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
def ingest_material_task(self, class_name, subject, materials, material_type="textbook", provider="local"):
    """Ingest PDFs into ChromaDB. provider: 'local' (Ollama) or 'openrouter'."""
    try:
        chunks = embeddings.ingest_bulk(class_name, subject, materials, material_type=material_type, provider=provider)
        print(f"[ingest_material_task] Done — {chunks} chunks for {class_name}/{subject} via {provider}")
        return {"chunks": chunks, "count": len(materials), "provider": provider}
    except Exception as exc:
        print(f"[ingest_material_task] Error: {exc}")
        raise self.retry(exc=exc)


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
        
        # If blueprint_id is provided, we'll use it in the generator
        # For now, the generator will auto-resolve blueprints
        file_path, summary, total_cost, input_tokens, output_tokens = generator.generate_paper(
            class_name=class_name,
            subject=paper.subject,
            chapters=paper.chapters,
            difficulty=paper.difficulty,
            pattern=paper.pattern,
            section=section,
            model_source=model_source,
            additional_context=additional_context
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
