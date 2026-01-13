from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import ExamBlueprint, BlueprintTemplate
import json

class Command(BaseCommand):
    help = 'Create blueprint for Class 1 English'

    def handle(self, *args, **options):
        # The blueprint structure you provided
        blueprint_data = {
            "sections": [
                {
                    "name": "A",
                    "title": "choose",
                    "marks": 11,
                    "question_types": ["MCQ", "Fill in the blanks"],
                    "subsections": []
                },
                {
                    "name": "B",
                    "title": "2 marks",
                    "marks": 8,
                    "question_types": ["Short answer"],
                    "subsections": []
                },
                {
                    "name": "C",
                    "title": "3 marks",
                    "marks": 9,
                    "question_types": ["Short answer"],
                    "subsections": []
                },
                {
                    "name": "D",
                    "title": "5 marks",
                    "marks": 10,
                    "question_types": ["Long answer"],
                    "subsections": []
                }
            ]
        }

        # First, create a blueprint template for Class 1 English
        template, created = BlueprintTemplate.objects.update_or_create(
            class_name="1",
            subject="English",
            defaults={
                "name": "Class 1 English Blueprint",
                "description": "Blueprint for Class 1 English exams",
                "blueprint": blueprint_data,
                "is_default": True,
                "is_active": True,
                "created_by": User.objects.first()  # Use the first user or None
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created new BlueprintTemplate: {template}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated existing BlueprintTemplate: {template}'))

        # Also create an ExamBlueprint
        exam_blueprint, created = ExamBlueprint.objects.update_or_create(
            class_name="1",
            subject="English",
            section=None,
            defaults={
                "code": None,
                "blueprint": blueprint_data,
                "template": template,
                "is_active": True,
                "created_by": User.objects.first()  # Use the first user or None
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created new ExamBlueprint: {exam_blueprint}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated existing ExamBlueprint: {exam_blueprint}'))

        # Also create one for "English Core" as the system maps "English" to "English Core"
        template_core, created = BlueprintTemplate.objects.update_or_create(
            class_name="1",
            subject="English Core",
            defaults={
                "name": "Class 1 English Core Blueprint",
                "description": "Blueprint for Class 1 English Core exams",
                "blueprint": blueprint_data,
                "is_default": True,
                "is_active": True,
                "created_by": User.objects.first()
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created new BlueprintTemplate for English Core: {template_core}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated existing BlueprintTemplate for English Core: {template_core}'))

        self.stdout.write(self.style.SUCCESS('\n✅ Blueprint creation completed successfully!'))