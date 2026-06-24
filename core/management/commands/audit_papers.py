"""
Validate that each assembled question paper's marks add up to its pattern total.

Sums the per-question marks (an OR / internal-choice pair counts ONCE) section by
section and compares to the ExamPattern. Reports the exact section and cause for
any mismatch — missing questions, wrong per-question marks, missing/extra section.

Usage
-----
    python manage.py audit_papers                 # audit all completed papers
    python manage.py audit_papers --id 63          # a single paper
    python manage.py audit_papers --bad-only       # only show papers that fail
"""

from django.core.management.base import BaseCommand

from core.models import QuestionPaper
from core.paper_audit import audit_paper_marks, audit_chapter_coverage


class Command(BaseCommand):
    help = "Audit assembled papers' marks against their pattern (OR-choice aware)."

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, default=None, help="Audit only this paper id.")
        parser.add_argument("--bad-only", action="store_true", help="Only print papers that fail the audit.")

    def handle(self, *args, **opts):
        qs = QuestionPaper.objects.filter(status="done").order_by("id")
        if opts["id"]:
            qs = QuestionPaper.objects.filter(id=opts["id"])

        total, passed, failed, skipped = 0, 0, 0, 0
        for paper in qs:
            if not paper.pattern:
                skipped += 1
                continue
            if not paper.paper_data:
                skipped += 1
                continue
            total += 1
            res = audit_paper_marks(paper.paper_data, paper.pattern)
            cov = audit_chapter_coverage(paper.paper_data)
            if res["ok"] and cov["ok"]:
                passed += 1
                if not opts["bad_only"]:
                    cov_note = (f", chapters {cov['covered']}/{cov['planned']}"
                                if cov["has_plan"] else "")
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ Paper {paper.id} ({paper.class_name} {paper.subject}): "
                        f"{res['actual_total']:g}/{res['expected_total']} marks{cov_note} — OK"))
                continue

            failed += 1
            self.stdout.write(self.style.ERROR(
                f"✗ Paper {paper.id} ({paper.class_name} {paper.subject}) "
                f"pattern='{paper.pattern.name}': "
                f"{res['actual_total']:g}/{res['expected_total']} marks"))
            for issue in res["issues"]:
                self.stdout.write(f"      • {issue}")
            # Per-section table for context.
            for row in res["sections"]:
                mark = "ok" if row["ok"] else "‼"
                self.stdout.write(
                    f"        [{mark}] {row['name']}: "
                    f"{row['actual_q']}/{row['expected_q']}q  "
                    f"{row['actual_marks']:g}/{row['expected_marks']}m")
            if cov["has_plan"] and not cov["ok"]:
                self.stdout.write(f"      • Chapter coverage {cov['covered']}/{cov['planned']} chapters "
                                  f"({cov.get('slot_covered', 0)}/{cov.get('slot_planned', 0)} section-slots) "
                                  f"— no question anywhere for: {', '.join(cov['missed'][:12])}")

        self.stdout.write("\n" + "-" * 60)
        self.stdout.write(f"Audited: {total}   Passed: {passed}   "
                          f"Failed: {failed}   Skipped (no pattern/data): {skipped}")
