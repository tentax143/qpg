"""
Management command: python manage.py import_sqp_patterns

Turns the CBSE Sample Question Papers in `sqp/` into ExamPatterns that reproduce those
papers ONE-TO-ONE — the same sections, the same question numbers, the same marks per
question, the same internal/open choices and sub-parts.

Why this exists
---------------
`seed_cbse_patterns` seeds board patterns from the hand-written summary in
`core/data/cbse_patterns.py`. Those are section-level aggregates only ("Section B: 5
questions x 2 marks"), so a generated paper matched the shape of a board paper but not its
detail, and some entries were simply wrong (Economics XII was seeded at 40 marks; the real
2025-26 SQP is 80). This command instead reads the actual sample paper and emits a
slot-authored pattern — one `question_slots` entry per printed question — which is the
structure `core/section_generator` generates against question by question.

It reuses the LIVE import path (`api.ai_service.extract_pattern_from_sqp_via_api` +
`core.tasks.build_validated_sections`), so a pattern seeded here is validated by exactly the
same rules as one a teacher imports through the UI. The extractor is under standing orders to
abstract the structure and never copy the sample's content, so generated papers replicate the
FORMAT, not the questions.

Patterns are written as `cbse_official` / `created_by=None`, i.e. premade templates every
school can clone, under the same `CBSE Board {subject} Class {class}` name the seeder uses —
so this UPGRADES the existing board pattern in place rather than adding a rival row to the
picker. Re-running `seed_cbse_patterns` restores the old aggregate-only version.

Usage
-----
    python manage.py import_sqp_patterns                    # all PDFs in sqp/
    python manage.py import_sqp_patterns --only Physics Maths
    python manage.py import_sqp_patterns --dry-run          # extract + report, write nothing
    python manage.py import_sqp_patterns --as-new           # keep the seeded pattern, add a new one
    python manage.py import_sqp_patterns --json-out out/    # also dump each pattern JSON
"""

import json
import os
import re
import time
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import ExamPattern


# Filename stem -> the canonical subject name used by the app (frontend/src/lib/subjects.js
# and the seeded DB list). Matching these EXACTLY is what lets the pattern picker and the
# `templates` endpoint find the imported pattern for a teacher's chosen subject.
SUBJECT_BY_STEM = {
    "accountancy":      "Accountancy",
    "biology":          "Biology",
    "businessstudies":  "Business Studies",
    "chemistry":        "Chemistry",
    "computerscience":  "Computer Science",
    "economics":        "Economics",
    "englishcore":      "English Core",
    "englishl":         "English Language & Literature",
    "maths":            "Mathematics",
    "mathematics":      "Mathematics",
    "physics":          "Physics",
}

# Roman/word class markers as they appear in SQP headers. Ordered longest-first: "XII" must be
# tested before "XI" and "X", or "CLASS - XII" reads as class 10.
_CLASS_TOKENS = [
    ("XII", "12"), ("XI", "11"), ("IX", "9"), ("X", "10"),
    ("12", "12"), ("11", "11"), ("10", "10"), ("9", "9"),
]

_CLASS_RE = re.compile(r"CLASS\s*[-–—:]?\s*([IVX]+|\d{1,2})\b", re.IGNORECASE)
_MAXMARKS_RE = re.compile(
    r"(?:MAX(?:IMUM)?\.?\s*MARKS|M\.?\s*M\.?)\s*[:\-–—]?\s*(\d{2,3})", re.IGNORECASE)


def detect_class(text):
    """Class level from the SQP header ('CLASS – XII (2025-26)', 'CLASS -X-'), or None.

    Read from the paper itself rather than assumed per folder: the sqp/ drop is mostly Class
    XII, but EnglishL-SQP.pdf is the Class X English Language & Literature paper, and filing
    it under Class 12 would hand teachers a pattern for the wrong board exam.
    """
    head = text[:4000].upper()
    for m in _CLASS_RE.finditer(head):
        token = m.group(1).upper()
        for marker, cls in _CLASS_TOKENS:
            if token == marker:
                return cls
    return None


def detect_max_marks(text):
    """Declared maximum marks from the header ('Maximum Marks: 70', 'MM - 80'), or None.
    Used only as a cross-check on what the extractor produced."""
    m = _MAXMARKS_RE.search(text[:4000])
    return int(m.group(1)) if m else None


def subject_for(path):
    """Canonical subject name for an SQP file, from its stem ('BusinessStudies-SQP.pdf')."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[-_\s]*sqp$", "", stem, flags=re.IGNORECASE)
    return SUBJECT_BY_STEM.get(re.sub(r"[^a-z]", "", stem.lower()))


def summarise(sections):
    """One line per section: name, marks, and the slot breakdown — the report a human reads
    to confirm the pattern really is a 1:1 replica of the printed paper."""
    lines = []
    for sec in sections:
        slots = [s for s in (sec.get("question_slots") or []) if isinstance(s, dict)]
        qnums = [s.get("qnum") for s in slots if isinstance(s.get("qnum"), int)]
        span = f"Q{min(qnums)}-{max(qnums)}" if qnums else "no slots"
        kinds = {}
        for s in slots:
            kinds[str(s.get("type"))] = kinds.get(str(s.get("type")), 0) + 1
        kinds_txt = ", ".join(f"{k}x{v}" for k, v in sorted(kinds.items()))
        choices = sum(1 for s in slots if s.get("choice") in ("internal", "open"))
        warn = sec.get("_structure_warnings") or []
        lines.append(
            f"    {str(sec.get('name'))[:34]:34s} {str(sec.get('marks')):>4}M  "
            f"{len(slots):>2} slots  {span:<10} {kinds_txt}"
            + (f"  [{choices} with choice]" if choices else "")
            + (f"  !! {len(warn)} warning(s)" if warn else "")
        )
    return lines


class Command(BaseCommand):
    help = "Import the CBSE sample question papers in sqp/ as one-to-one, slot-authored exam patterns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir", default=None,
            help="Folder of SQP PDFs (default: <project>/sqp).")
        parser.add_argument(
            "--only", nargs="+", default=None, metavar="NAME",
            help="Import just these files/subjects, matched loosely (e.g. --only Physics Maths).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Extract and report, but write nothing to the database.")
        parser.add_argument(
            "--as-new", action="store_true",
            help="Create a separate 'CBSE Sample Paper ...' pattern instead of upgrading the "
                 "seeded 'CBSE Board ...' one in place.")
        parser.add_argument(
            "--json-out", default=None, metavar="DIR",
            help="Also write each extracted pattern to DIR/<subject>-class<N>.json for review.")
        parser.add_argument(
            "--sqp-year", default="2025-26",
            help="Academic year stamped on the imported patterns (default: 2025-26).")

    def handle(self, *args, **opts):
        # Imported lazily: this command is the only place that needs the PDF/LLM stack, and a
        # missing optional dep should not break `manage.py help`.
        from core.material_intel import extract_pages_text
        from core.tasks import build_validated_sections
        from api.ai_service import extract_pattern_from_sqp_via_api

        sqp_dir = opts["dir"] or os.path.join(settings.BASE_DIR, "sqp")
        if not os.path.isdir(sqp_dir):
            raise CommandError(f"No such folder: {sqp_dir}")

        pdfs = sorted(
            os.path.join(sqp_dir, f) for f in os.listdir(sqp_dir)
            if f.lower().endswith(".pdf"))
        if opts["only"]:
            wanted = [w.lower().replace(" ", "") for w in opts["only"]]
            pdfs = [p for p in pdfs
                    if any(w in os.path.basename(p).lower().replace(" ", "") for w in wanted)]
        if not pdfs:
            raise CommandError(f"No matching PDFs in {sqp_dir}")

        if opts["json_out"]:
            os.makedirs(opts["json_out"], exist_ok=True)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Importing {len(pdfs)} sample paper(s) from {sqp_dir}"))

        created = updated = skipped = failed = 0
        for path in pdfs:
            fname = os.path.basename(path)
            self.stdout.write(f"\n  {fname}")

            subject = subject_for(path)
            if not subject:
                self.stdout.write(self.style.WARNING(
                    f"    SKIP  unknown subject — add its stem to SUBJECT_BY_STEM"))
                skipped += 1
                continue

            text = extract_pages_text(path)
            if len(text.strip()) < 200:
                self.stdout.write(self.style.WARNING(
                    "    SKIP  no readable text (scanned/image-only PDF)"))
                skipped += 1
                continue

            class_name = detect_class(text)
            if not class_name:
                self.stdout.write(self.style.WARNING(
                    "    SKIP  could not read the class from the paper header"))
                skipped += 1
                continue

            declared_marks = detect_max_marks(text)
            self.stdout.write(
                f"    {subject} · Class {class_name} · {len(text):,} chars"
                + (f" · header says {declared_marks}M" if declared_marks else ""))

            t0 = time.time()
            try:
                pattern_data = extract_pattern_from_sqp_via_api(
                    sqp_text=text,
                    class_name=class_name,
                    subject=subject,
                    exam_name=f"CBSE Board {subject} Class {class_name}",
                )
                sections = build_validated_sections(
                    pattern_data,
                    teacher_input=text,
                    class_name=class_name,
                    subject=subject,
                    exam_name=f"CBSE Board {subject} Class {class_name}",
                    log=lambda m: self.stdout.write(f"      {m}"),
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"    FAIL  {type(exc).__name__}: {exc}"))
                if opts["verbosity"] >= 2:
                    self.stdout.write(traceback.format_exc())
                failed += 1
                continue

            if not sections:
                self.stdout.write(self.style.ERROR("    FAIL  extractor returned no sections"))
                failed += 1
                continue

            # Slots are the source of truth: derive_aggregates_from_slots has already set each
            # section's marks from its slots, so sum THOSE rather than trusting the model's own
            # total_marks line (the one number it is most prone to miscopy).
            total_marks = sum(float(s.get("marks") or 0) for s in sections)
            total_marks = int(total_marks) if total_marks == int(total_marks) else total_marks
            total_questions = sum(
                len([q for q in (s.get("question_slots") or []) if isinstance(q, dict)])
                or int(s.get("questions_count") or 0)
                for s in sections)

            for line in summarise(sections):
                self.stdout.write(line)
            # Print the residual warnings verbatim: they are saved onto the pattern and shown
            # to teachers, so anything systematic here is a bug to fix, not noise to scroll past.
            for sec in sections:
                for w in (sec.get("_structure_warnings") or []):
                    self.stdout.write(self.style.WARNING(f"      warn: {w}"))
            self.stdout.write(
                f"    => {len(sections)} sections · {total_questions} questions · "
                f"{total_marks}M  ({time.time() - t0:.0f}s)")
            if declared_marks and total_marks != declared_marks:
                self.stdout.write(self.style.WARNING(
                    f"    !!  extracted total {total_marks}M != the paper's stated "
                    f"{declared_marks}M — review this pattern before teachers use it"))

            if opts["json_out"]:
                out = os.path.join(
                    opts["json_out"],
                    f"{subject.replace(' ', '')}-class{class_name}.json")
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump({"sections": sections, "total_marks": total_marks,
                               "total_questions": total_questions}, fh,
                              indent=2, ensure_ascii=False)
                self.stdout.write(f"    json -> {out}")

            if opts["dry_run"]:
                self.stdout.write(self.style.WARNING("    DRY-RUN  not saved"))
                continue

            name = (f"CBSE Sample Paper — {subject} Class {class_name}" if opts["as_new"]
                    else f"CBSE Board {subject} Class {class_name}")
            fields = dict(
                description=(
                    f"Official CBSE {opts['sqp_year']} sample question paper structure for "
                    f"{subject} Class {class_name}, imported from {fname}. Reproduces the sample "
                    f"paper question by question: {len(sections)} sections, {total_questions} "
                    f"questions, {total_marks} marks."),
                subject=subject,
                class_name=class_name,
                sections=sections,
                total_marks=total_marks,
                total_questions=total_questions,
                pattern_source="cbse_official",
                sqp_year=opts["sqp_year"],
                status="done",
                created_by=None,      # premade template — clone-only, visible to every school
            )

            existing = ExamPattern.objects.filter(
                name=name, pattern_source="cbse_official").first()
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                self.stdout.write(self.style.SUCCESS(f"    UPDATE  #{existing.id}  {name}"))
                updated += 1
            else:
                obj = ExamPattern.objects.create(name=name, **fields)
                self.stdout.write(self.style.SUCCESS(f"    CREATE  #{obj.id}  {name}"))
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. created={created} updated={updated} skipped={skipped} failed={failed}"))
