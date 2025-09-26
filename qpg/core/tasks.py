from celery import shared_task
from .models import QuestionPaper
from . import generator

@shared_task(bind=True)
def generate_paper_task(self, paper_id, blueprint_id=None):
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
        file_path, summary = generator.generate_paper(
            class_name=class_name,
            subject=paper.subject,
            chapters=paper.chapters,
            difficulty=paper.difficulty,
            pattern=paper.pattern,
            section=section
        )

        paper.file.name = file_path
        paper.status = "done"
        paper.save()
        return summary
        
    except Exception as e:
        # Mark the paper as failed
        paper.status = "failed"
        paper.save()
        
        # Log the error
        print(f"[Task Failed] Paper ID {paper_id}: {str(e)}")
        
        # Re-raise the exception so Celery knows the task failed
        raise self.retry(exc=e, countdown=60, max_retries=3)
