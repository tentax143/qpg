"""
Management command: python manage.py seed_cbse_patterns

Seeds official CBSE 2024-25 board exam patterns from core/data/cbse_patterns.py
into the ExamPattern table with pattern_source='cbse_official'.

Safe to re-run: existing cbse_official patterns are skipped (not duplicated).
Use --force to delete and re-create all.
"""

from django.core.management.base import BaseCommand
from core.models import ExamPattern
from core.data.cbse_patterns import PATTERNS, EXAM_TYPES


def _sections_from_pattern(pattern: dict) -> list:
    """Convert cbse_patterns.py dict structure into ExamPattern.sections format."""
    sections_raw = pattern.get("sections", [])
    result = []

    for s in sections_raw:
        name = s.get("name", "")
        q_type = s.get("type", "")
        count = s.get("count") or s.get("attempt") or 0
        marks_each = s.get("marks_each")
        total = s.get("total") or (
            count * marks_each if isinstance(marks_each, (int, float)) else 0
        )
        choice = s.get("internal_choice", False)
        notes = s.get("notes", "") or s.get("choices", "")

        result.append({
            "name": name,
            "title": q_type,
            "marks": total,
            "questions": count,
            "marks_each": marks_each,
            "internal_choice": choice,
            "notes": notes,
        })

    # Fallback: if pattern uses sub-section style (English Core, Hindi Core, etc.)
    if not result:
        for s in sections_raw:
            name = s.get("name", "")
            total = s.get("total", 0)
            subs = s.get("sub", [])
            sub_list = []
            for sub in subs:
                sub_list.append({
                    "q": sub.get("q", ""),
                    "type": sub.get("type", ""),
                    "marks": sub.get("marks", 0),
                    "notes": sub.get("notes", sub.get("types", "")),
                })
            result.append({
                "name": name,
                "title": name,
                "marks": total,
                "questions": len(subs),
                "subsections": sub_list,
                "internal_choice": False,
                "notes": "",
            })

    return result


class Command(BaseCommand):
    help = "Seed official CBSE 2024-25 exam patterns into ExamPattern table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete all existing cbse_official patterns and re-create them",
        )
        parser.add_argument(
            "--subject",
            type=str,
            default=None,
            help="Only seed pattern for this subject (e.g. Physics)",
        )

    def handle(self, *args, **options):
        force = options["force"]
        only_subject = options.get("subject")

        if force:
            deleted, _ = ExamPattern.objects.filter(pattern_source="cbse_official").delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing cbse_official patterns."))

        created_count = 0
        skipped_count = 0

        for subject_name, pattern in PATTERNS.items():
            if only_subject and subject_name.lower() != only_subject.lower():
                continue

            classes = pattern.get("classes", [])
            theory_marks = pattern.get("theory_marks", pattern.get("marks_theory", 80))
            practical_marks = pattern.get("practical_marks", 0)
            total_questions = pattern.get("total_questions", 0)
            duration = pattern.get("duration_minutes", 180)

            # Build sections list
            sections = _sections_from_pattern(pattern)
            total_sections_marks = sum(s.get("marks", 0) for s in sections)

            for cls in classes:
                name = f"CBSE Board {subject_name} Class {cls}"
                description = (
                    f"Official CBSE 2024-25 board exam pattern for {subject_name} Class {cls}. "
                    f"Theory: {theory_marks}M"
                    + (f" + Practical: {practical_marks}M" if practical_marks else "")
                    + f". Duration: {duration} min."
                )

                if not force and ExamPattern.objects.filter(
                    name=name, pattern_source="cbse_official"
                ).exists():
                    self.stdout.write(f"  SKIP  {name}")
                    skipped_count += 1
                    continue

                ExamPattern.objects.create(
                    name=name,
                    description=description,
                    subject=subject_name,
                    class_name=cls,
                    sections=sections,
                    total_marks=theory_marks,
                    total_questions=total_questions,
                    pattern_source="cbse_official",
                    created_by=None,
                )
                self.stdout.write(self.style.SUCCESS(f"  CREATE {name}  ({len(sections)} sections, {theory_marks}M theory)"))
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created: {created_count}  Skipped (already exist): {skipped_count}"
            )
        )
