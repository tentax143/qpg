"""Rename the SQP-derived board patterns to drop the class from their name.

`import_sqp_patterns` originally stored these as "CBSE Board Biology Class 12", matching the name
`seed_cbse_patterns` used so it would upgrade that row in place. But the structure a sample paper
defines is reusable for ANY class and subject — `ExamPatternViewSet.templates` now offers these to
every class — so carrying "Class 12" in the name told a Class 10 Biology teacher this pattern was
not for them, which is the opposite of true.

The extracted sections are unchanged and correct; only the name (and the description's phrasing)
needs to move. Doing it as a migration rather than re-running the importer avoids ~10 LLM calls and
guarantees every deploy lands on the same names.

SQP-derived rows are identified by the presence of `question_slots` in their sections: that is the
per-question structure the importer produces, and precisely what the hand-written
`core/data/cbse_patterns.py` seeds do NOT have. So a re-seeded aggregate-only row is left alone.
"""

from django.db import migrations


def _is_slot_authored(sections):
    return isinstance(sections, list) and any(
        isinstance(s, dict) and s.get("question_slots") for s in sections)


def rename_forward(apps, schema_editor):
    ExamPattern = apps.get_model("core", "ExamPattern")

    for pattern in ExamPattern.objects.filter(pattern_source="cbse_official"):
        if not _is_slot_authored(pattern.sections):
            continue
        new_name = f"CBSE Sample Paper — {pattern.subject}"
        if pattern.name == new_name:
            continue
        # Never collide with an existing row — leave the duplicate for a human to resolve rather
        # than creating two identically-named templates in the picker.
        if ExamPattern.objects.filter(name=new_name, pattern_source="cbse_official") \
                              .exclude(pk=pattern.pk).exists():
            continue
        pattern.name = new_name
        # The source class stays in the description as provenance; it just stops being a label.
        if pattern.description and " Class " in pattern.description:
            pattern.description = pattern.description.replace(
                f"{pattern.subject} Class ", f"{pattern.subject}, from the Class ")
        pattern.save(update_fields=["name", "description"])


def rename_backward(apps, schema_editor):
    """Deliberately a no-op.

    The old names embedded a class this model no longer tracks per pattern, and reversing would
    have to guess it back. Nothing depends on the old names — patterns are referenced by id — so
    leaving them renamed on a rollback is safe.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0051_examblueprint_name_examblueprint_pattern_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
