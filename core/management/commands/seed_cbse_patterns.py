"""
Management command: python manage.py seed_cbse_patterns

Seeds official CBSE 2025-26 board exam patterns from core/data/cbse_patterns.py
into the ExamPattern table with pattern_source='cbse_official'.

Safe to re-run: existing cbse_official patterns are UPDATED in place (refreshing the
description, sections, marks and sqp_year) rather than duplicated. Use --force to delete
and re-create all from scratch.
"""

import re as _re

from django.core.management.base import BaseCommand
from core.models import ExamPattern
from core.data.cbse_patterns import PATTERNS, PATTERNS_MIDDLE_SCHOOL, EXAM_TYPES


def _infer_sub_count(sub: dict) -> int:
    """Best-effort number of questions a sub-block represents (for template display)."""
    # "attempt": "3 of 4" → generate the larger provided set (4).
    attempt = str(sub.get("attempt", ""))
    m = _re.findall(r"\d+", attempt)
    if len(m) >= 2:
        return int(m[-1])
    # "q": "Q3-Q7" / "Q13-Q15" → inclusive range count.
    q = str(sub.get("q", ""))
    nums = _re.findall(r"\d+", q)
    if len(nums) >= 2:
        return max(1, int(nums[-1]) - int(nums[0]) + 1)
    return 1


def _infer_qtype_label(text: str) -> str:
    """Map a descriptive sub-question type to a coarse question-type label."""
    t = (text or "").lower()
    if "mcq" in t or "multiple choice" in t or "objective" in t:
        return "MCQ"
    if "long answer" in t or " la " in t or "(la" in t:
        return "LA"
    if "very short" in t or "vsa" in t:
        return "VSA"
    if "extract" in t:
        return "Extract"
    if "passage" in t or "reading" in t or "comprehension" in t or "unseen" in t:
        return "Reading"
    if any(k in t for k in ("letter", "essay", "paragraph", "article", "report", "notice", "writing", "lekhan", "nibandh")):
        return "Writing"
    if any(k in t for k in ("grammar", "gap", "editing", "omission", "reorder", "sandhi", "samaas", "vyakaran")):
        return "Grammar"
    if "short answer" in t or " sa " in t or "(sa" in t:
        return "SA"
    return "SA"


def _subsections_from_sub(subs_raw: list):
    """Build (subsections, total_question_count) from a section's `sub` list."""
    subsections, q_total = [], 0
    for sub in subs_raw:
        label = sub.get("type") or sub.get("q") or ""
        sm = sub.get("marks", 0) or 0
        cnt = _infer_sub_count(sub)
        q_total += cnt
        mpq = round(sm / cnt, 2) if cnt else sm
        extras = [x for x in [
            sub.get("types"),
            (f"Choice: {sub['choice']}" if sub.get("choice") else None),
            (f"Attempt {sub['attempt']}" if sub.get("attempt") else None),
            (sub.get("sub") if isinstance(sub.get("sub"), str) else None),
        ] if x]
        subsections.append({
            "name": (sub.get("q") or label or "Q")[:60],
            "marks": sm,
            "questions_count": cnt,
            "marks_per_question": mpq,
            "question_types": [_infer_qtype_label(label)],
            "instructions": extras,
        })
    return subsections, q_total


def _sections_from_pattern(pattern: dict) -> list:
    """Convert cbse_patterns.py dict structure into ExamPattern.sections format."""
    sections_raw = pattern.get("sections", [])
    result = []

    for s in sections_raw:
        name = s.get("name", "")

        # Compound subject format: sections keyed by subject (Biology, Chemistry, etc.)
        if "subject" in s:
            result.append({
                "name": name,
                "subject": s["subject"],
                "title": s["subject"],
                "marks": s.get("total", 0),
                "questions": s.get("count", 0),
                "internal_choice": s.get("internal_choice", False),
                "choices": s.get("choices", 0),
                "hots": s.get("hots", 0),
                "cbq": s.get("cbq", 0),
                "notes": s.get("notes", ""),
                "question_types": s.get("question_types", []),
            })
            continue

        # Sub-block format (language papers: English Lang & Lit, Hindi, English Core, Sanskrit).
        # The detail lives in `sub` — build real subsections so the section isn't blank, and
        # keep `sub`/`total` so the create-pattern text view renders the breakdown too.
        if isinstance(s.get("sub"), list) and s["sub"]:
            total = s.get("total", 0)
            subsections, q_total = _subsections_from_sub(s["sub"])
            clean_title = name.split("—", 1)[-1].strip() if "—" in name else name
            result.append({
                "name": name,
                "title": clean_title,
                "type": clean_title,             # create-pattern text view shows "Section A — <title>"
                "total": total,
                "marks": total,
                "questions": q_total,
                "questions_count": q_total,
                "sub": s["sub"],                 # raw — create-pattern text view renders this
                "subsections": subsections,      # structured — generation + pattern-detail page
                "internal_choice": any(su.get("choice") for su in s["sub"]),
                "notes": s.get("notes", ""),
            })
            continue

        # Traditional format: sections keyed by question type (MCQ, VSA, SA, etc.)
        q_type = s.get("type", "")
        provided = s.get("count") or 0
        attempt = s.get("attempt")
        # Use provided count for generation; fall back to attempt if count absent
        count = provided or attempt or 0
        marks_each = s.get("marks_each")
        total = s.get("total") or (
            count * marks_each if isinstance(marks_each, (int, float)) else 0
        )
        choice = s.get("internal_choice", False)
        notes = s.get("notes", "") or s.get("choices", "")

        result.append({
            "name": name,
            "title": q_type,
            "type": q_type,
            "total": total,
            "marks": total,
            "questions": count,       # total questions printed in paper
            "attempt": attempt,       # MO-01: students attempt this many (None if N/A)
            "marks_each": marks_each,
            "internal_choice": choice,
            "notes": notes,
        })

    return result


class Command(BaseCommand):
    help = "Seed official CBSE 2025-26 exam patterns into ExamPattern table"

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
        updated_count = 0

        all_patterns = list(PATTERNS.items()) + list(PATTERNS_MIDDLE_SCHOOL.items())

        for subject_name, pattern in all_patterns:
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
                    f"Official CBSE 2025-26 board exam pattern for {subject_name} Class {cls}. "
                    f"Theory: {theory_marks}M"
                    + (f" + Practical: {practical_marks}M" if practical_marks else "")
                    + f". Duration: {duration} min."
                )
                fields = dict(
                    description=description,
                    subject=subject_name,
                    class_name=cls,
                    sections=sections,
                    total_marks=theory_marks,
                    total_questions=total_questions,
                    pattern_source="cbse_official",
                    sqp_year="2025-26",
                    created_by=None,
                )

                # Update in place if it already exists (refreshes year/sections), else create.
                existing = ExamPattern.objects.filter(name=name, pattern_source="cbse_official").first()
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.save()
                    self.stdout.write(f"  UPDATE {name}  ({len(sections)} sections)")
                    updated_count += 1
                else:
                    ExamPattern.objects.create(name=name, **fields)
                    self.stdout.write(self.style.SUCCESS(f"  CREATE {name}  ({len(sections)} sections, {theory_marks}M theory)"))
                    created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created: {created_count}  Updated: {updated_count}"
            )
        )
