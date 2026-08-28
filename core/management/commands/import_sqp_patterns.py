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

Patterns are written as `cbse_sqp` / `created_by=None`, i.e. premade templates every school
can clone. The name carries NO class ("CBSE Sample Paper — Biology"): the structure is offered
to every class and subject, and labelling it Class 12 told a Class 10 teacher it was not for
them. A rerun looks the row up by its older names too, so it is renamed in place rather than
duplicated. Re-running `seed_cbse_patterns` restores the aggregate-only version under its own name.

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


# CBSE publishes ONE sample paper per subject per stage, and schools use that structure across
# the whole stage — the Class 10 paper models classes 1-10, the Class 12 paper models 11-12. So a
# folder is imported as a BAND, not as a single class: a Class 6 English teacher gets the Class 10
# English SQP, which is the paper their syllabus is built towards.
#
# `subjects` is an allow-list on purpose. sqp_downloads/ carries 29 folders per stage including
# Dance, Painting and Music Carnatic; importing all of them would bury the subjects schools
# actually set behind two dozen they never will.
SQP_BANDS = {
    "class_10": {
        "classes": (1, 10),
        "subjects": {
            "Mathematics Standard":          "Mathematics Standard",
            "Mathematics Basic":             "Mathematics Basic",
            "Science":                       "Science",
            "Social Science":                "Social Science",
            "English Language & Literature": "English Language & Literature",
            # No Computer Science here on purpose: CBSE publishes no Class 10 Computer Science
            # sample paper (the class-10 subject is Computer Applications, code 165), and the
            # scraper left the SCIENCE paper in that folder. header_subject_matches would now
            # catch it, but listing a subject that cannot exist just prints a SKIP every run.
        },
    },
    "class_12": {
        "classes": (11, 12),
        "subjects": {
            "Accountancy":       "Accountancy",
            "Biology":           "Biology",
            "Business Studies":  "Business Studies",
            "Chemistry":         "Chemistry",
            "Computer Science":  "Computer Science",
            "Economics":         "Economics",
            "English Core":      "English Core",
            "Geography":         "Geography",
            "History":           "History",
            "Mathematics":       "Mathematics",
            "Physics":           "Physics",
            "Political Science": "Political Science",
        },
    },
}

# Legacy flat layout (sqp/<Subject>-SQP.pdf), kept so `--dir sqp` still works.
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


# Words in a paper's title line that carry no identity.
_TITLE_NOISE = {"AND", "THE", "OF", "CODE", "NO", "NOS", "SAMPLE", "QUESTION", "PAPER", "CLASS"}


def header_subject_matches(text, subject):
    """Does the subject printed on the paper agree with the folder it was filed under?

    sqp_downloads/ is produced by a scraper, and a scraper that cannot find a paper can leave the
    wrong one in place: class_10/Computer Science/SQP.pdf is in fact the SCIENCE paper (code 086) —
    CBSE publishes no Class 10 Computer Science SQP. Importing it produced a "Computer Science"
    pattern whose sections were Biology and Physics, which no teacher would ever spot from the
    pattern list.

    Matched on WORDS rather than a substring so punctuation and connectives do not matter:
    "MATHEMATICS (BASIC )" satisfies "Mathematics Basic", "ENGLISH LANGUAGE AND LITERATURE"
    satisfies "English Language & Literature" — while "SCIENCE" alone fails "Computer Science",
    because the distinguishing word is absent.
    """
    def words(value):
        cleaned = re.sub(r"[^A-Z0-9 ]+", " ", str(value or "").upper())
        return {w for w in cleaned.split() if w and w not in _TITLE_NOISE}

    return words(subject) <= words(text[:1200])


def subject_for(path):
    """Canonical subject name for an SQP file, from its stem ('BusinessStudies-SQP.pdf')."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[-_\s]*sqp$", "", stem, flags=re.IGNORECASE)
    return SUBJECT_BY_STEM.get(re.sub(r"[^a-z]", "", stem.lower()))


def band_for_class(n):
    """Which stage band a published paper for class `n` models. CBSE's own split: the secondary
    paper (class 10) is what classes 1-10 work towards, the senior-secondary one (12) covers 11-12."""
    return (1, 10) if int(n) <= 10 else (11, 12)


def band_label(class_min, class_max):
    if not class_min or not class_max:
        return ""
    return f"Class {class_min}" if class_min == class_max else f"Classes {class_min}-{class_max}"


def sqp_pattern_name(subject, sqp_year="", class_min=None, class_max=None):
    """The stored name of a subject's SQP pattern, carrying the BAND of classes it serves.

    Not the single class the paper was published for: CBSE issues one sample paper per subject per
    stage and schools work towards it across the stage, so the Class 10 English paper is the model
    for classes 1-10. Naming it "Class 10" told a Class 6 teacher it was not for them. Naming it
    nothing at all (the previous attempt) claimed it served Class 12 too, which is equally wrong —
    hence the band.

    The band is part of the NAME because the same subject exists in both stages: English 1-10 and
    English Core 11-12 are different papers and must be distinguishable in a picker.
    """
    band = band_label(class_min, class_max)
    suffix = " (" + ", ".join(x for x in (band, sqp_year) if x) + ")" if (band or sqp_year) else ""
    return f"CBSE Sample Paper — {subject}" + suffix


def legacy_pattern_names(subject, class_name):
    """Names this pattern has been stored under before, newest first.

    Looked up when the current name finds nothing, so re-running the importer RENAMES the existing
    row in place instead of leaving a stale duplicate beside it in the picker.
    """
    return [
        f"CBSE Sample Paper — {subject}",                        # class-less naming
        f"CBSE Sample Paper — {subject} Class {class_name}",     # first import naming
        f"CBSE Board {subject} Class {class_name}",                # seed_cbse_patterns naming
    ]


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
            help="Root folder (default: <project>/sqp_downloads). Understands both the "
                 "class_N/<Subject>/SQP.pdf tree and a flat folder of PDFs.")
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

    def _discover(self, root, only):
        """Resolve the folder into [(pdf_path, subject, band_or_None)] plus notes about gaps.

        Two layouts are supported. The tree layout `class_N/<Subject>/SQP.pdf` is the real source
        (sqp_downloads/) and carries the band in the folder name. A flat folder of PDFs (the older
        sqp/) has no band, so it is resolved later from the class printed on each paper.
        """
        entries = set(os.listdir(root))
        band_dirs = [d for d in SQP_BANDS if d in entries and os.path.isdir(os.path.join(root, d))]

        jobs, missing = [], []
        if band_dirs:
            for band_dir in sorted(band_dirs):
                cfg = SQP_BANDS[band_dir]
                for folder, subject in sorted(cfg["subjects"].items()):
                    pdf = os.path.join(root, band_dir, folder, "SQP.pdf")
                    if not os.path.exists(pdf):
                        missing.append(f"{band_dir}/{folder}/SQP.pdf — not downloaded, skipping")
                        continue
                    jobs.append((pdf, subject, cfg["classes"]))
        else:
            for f in sorted(entries):
                if not f.lower().endswith(".pdf"):
                    continue
                subject = subject_for(f)
                if not subject:
                    missing.append(f"{f} — unknown subject, add its stem to SUBJECT_BY_STEM")
                    continue
                jobs.append((os.path.join(root, f), subject, None))

        if only:
            wanted = [w.lower().replace(" ", "") for w in only]
            jobs = [j for j in jobs
                    if any(w in j[1].lower().replace(" ", "")
                           or w in j[0].lower().replace(" ", "").replace("\\", "/")
                           for w in wanted)]
        return jobs, missing

    def handle(self, *args, **opts):
        # Imported lazily: this command is the only place that needs the PDF/LLM stack, and a
        # missing optional dep should not break `manage.py help`.
        from core.material_intel import extract_pages_text
        from core.tasks import build_validated_sections
        from api.ai_service import extract_pattern_from_sqp_via_api

        sqp_dir = opts["dir"] or os.path.join(settings.BASE_DIR, "sqp_downloads")
        if not os.path.isdir(sqp_dir):
            raise CommandError(f"No such folder: {sqp_dir}")

        jobs, missing = self._discover(sqp_dir, opts["only"])
        for note in missing:
            self.stdout.write(self.style.WARNING(f"  MISSING  {note}"))
        if not jobs:
            raise CommandError(f"No matching sample papers under {sqp_dir}")

        if opts["json_out"]:
            os.makedirs(opts["json_out"], exist_ok=True)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Importing {len(jobs)} sample paper(s) from {sqp_dir}"))

        created = updated = skipped = failed = 0
        for path, subject, band in jobs:
            fname = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
            self.stdout.write(f"\n  {fname}")

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

            if not header_subject_matches(text, subject):
                printed = " ".join(text[:200].split())
                self.stdout.write(self.style.ERROR(
                    f"    SKIP  this PDF is not a {subject} paper — its header reads: "
                    f"{printed[:110]}"))
                self.stdout.write(
                    "          The download for this subject is wrong or the paper does not "
                    "exist; re-download it or drop the subject from SQP_BANDS.")
                skipped += 1
                continue

            # The folder says which band this paper models; a flat --dir has no folder to say so,
            # in which case fall back to the class printed on the paper itself.
            class_min, class_max = band or band_for_class(class_name)

            declared_marks = detect_max_marks(text)
            self.stdout.write(
                f"    {subject} · from the Class {class_name} paper · serves "
                f"{band_label(class_min, class_max)} · {len(text):,} chars"
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
                    f"{subject.replace(' ', '')}-{class_min}to{class_max}.json")
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump({"sections": sections, "total_marks": total_marks,
                               "total_questions": total_questions}, fh,
                              indent=2, ensure_ascii=False)
                self.stdout.write(f"    json -> {out}")

            if opts["dry_run"]:
                self.stdout.write(self.style.WARNING("    DRY-RUN  not saved"))
                continue

            name = sqp_pattern_name(subject, opts["sqp_year"] if opts["as_new"] else "",
                                    class_min, class_max)
            fields = dict(
                name=name,
                class_min=class_min,
                class_max=class_max,
                description=(
                    f"Official CBSE {opts['sqp_year']} sample question paper structure for "
                    f"{subject}, taken from the Class {class_name} paper ({fname}). Reproduces "
                    f"it question by question: {len(sections)} sections, {total_questions} "
                    f"questions, {total_marks} marks. Serves "
                    f"{band_label(class_min, class_max).lower()}."),
                subject=subject,
                class_name=class_name,
                sections=sections,
                total_marks=total_marks,
                total_questions=total_questions,
                pattern_source="cbse_sqp",
                sqp_year=opts["sqp_year"],
                status="done",
                created_by=None,      # premade template — clone-only, visible to every school
            )

            # Both sources are searched: rows imported before `cbse_sqp` existed are still
            # stored as `cbse_official`, and must be adopted rather than duplicated.
            SOURCES = ("cbse_sqp", "cbse_official")
            existing = ExamPattern.objects.filter(
                name=name, pattern_source__in=SOURCES).first()
            renamed_from = None
            if existing is None and not opts["as_new"]:
                for old_name in legacy_pattern_names(subject, class_name):
                    candidate = ExamPattern.objects.filter(
                        name=old_name, pattern_source__in=SOURCES).first()
                    if candidate is None:
                        continue
                    # A band-less legacy name is AMBIGUOUS when a subject exists in both stages —
                    # Computer Science has a class-10 and a class-12 paper. Only adopt the old row
                    # if the paper it came from sits in the band being imported now, otherwise the
                    # 1-10 import would rename the 11-12 row and the 11-12 import would then
                    # create a duplicate beside it.
                    src = str(candidate.class_name or '').split('-')[0].strip()
                    if src.isdigit() and not (class_min <= int(src) <= class_max):
                        continue
                    existing, renamed_from = candidate, old_name
                    break

            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                note = f"  (renamed from '{renamed_from}')" if renamed_from else ""
                self.stdout.write(self.style.SUCCESS(f"    UPDATE  #{existing.id}  {name}{note}"))
                updated += 1
            else:
                obj = ExamPattern.objects.create(**fields)
                self.stdout.write(self.style.SUCCESS(f"    CREATE  #{obj.id}  {name}"))
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. created={created} updated={updated} skipped={skipped} failed={failed}"))
