from django.core.management.base import BaseCommand
from core.models import ExamBlueprint, BlueprintTemplate

class Command(BaseCommand):
    help = 'Check existing blueprints in database'

    def handle(self, *args, **options):
        self.stdout.write("=" * 50)
        self.stdout.write("CHECKING BLUEPRINTS IN DATABASE")
        self.stdout.write("=" * 50)

        # Check BlueprintTemplates
        templates = BlueprintTemplate.objects.all()
        self.stdout.write(f"\nBlueprint Templates: {templates.count()}")
        for template in templates:
            self.stdout.write(f"  - ID: {template.id}")
            self.stdout.write(f"    Name: {template.name}")
            self.stdout.write(f"    Class: {template.class_name}")
            self.stdout.write(f"    Subject: {template.subject}")
            self.stdout.write(f"    Is Default: {template.is_default}")
            self.stdout.write(f"    Is Active: {template.is_active}")
            self.stdout.write("")

        # Check ExamBlueprints
        blueprints = ExamBlueprint.objects.all()
        self.stdout.write(f"\nExam Blueprints: {blueprints.count()}")
        for blueprint in blueprints:
            self.stdout.write(f"  - ID: {blueprint.id}")
            self.stdout.write(f"    Class: {blueprint.class_name}")
            self.stdout.write(f"    Subject: {blueprint.subject}")
            self.stdout.write(f"    Section: {blueprint.section}")
            self.stdout.write(f"    Is Active: {blueprint.is_active}")
            self.stdout.write("")

        # Check what the system is looking for
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("TESTING BLUEPRINT RESOLUTION FOR '1 English'")
        self.stdout.write("=" * 50)

        class_name = "1"
        subject = "English"

        # Check exact matches
        self.stdout.write(f"\nLooking for class_name='{class_name}' and subject='{subject}':")

        # Check templates
        matching_templates = BlueprintTemplate.objects.filter(
            class_name=class_name,
            subject__iexact=subject,
            is_active=True
        )
        self.stdout.write(f"  Matching templates: {matching_templates.count()}")

        # Check blueprints
        matching_blueprints = ExamBlueprint.objects.filter(
            class_name=class_name,
            subject__iexact=subject,
            is_active=True
        )
        self.stdout.write(f"  Matching blueprints: {matching_blueprints.count()}")

        # Check with normalized subject
        self.stdout.write(f"\nLooking for class_name='{class_name}' and subject='English Core':")
        matching_templates_core = BlueprintTemplate.objects.filter(
            class_name=class_name,
            subject__iexact="English Core",
            is_active=True
        )
        self.stdout.write(f"  Matching templates: {matching_templates_core.count()}")

        matching_blueprints_core = ExamBlueprint.objects.filter(
            class_name=class_name,
            subject__iexact="English Core",
            is_active=True
        )
        self.stdout.write(f"  Matching blueprints: {matching_blueprints_core.count()}")

        self.stdout.write(self.style.SUCCESS('\nDone!'))