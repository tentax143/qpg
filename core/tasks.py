from celery import shared_task
from .models import QuestionPaper
from . import generator
from django.core.files import File
from django.conf import settings
import os

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
        file_path, summary, total_cost = generator.generate_paper(
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
                # Extract just the filename from the path
                filename = os.path.basename(file_path)
                paper.file.save(filename, File(f), save=False)
        
        paper.cost = total_cost
        paper.status = "done"
        paper.save()
        return summary
        
    except Exception as e:
        # Mark the paper as failed (no auto-retry)
        paper.status = "failed"
        paper.save()
        
        # Log the error and let the task fail once
        print(f"[Task Failed] Paper ID {paper_id}: {str(e)}")
        raise
