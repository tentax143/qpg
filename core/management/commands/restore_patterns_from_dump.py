"""
Management command: python manage.py restore_patterns_from_dump

Restores ExamPatterns that exist in a Django dumpdata fixture but no longer exist in the database.

Why not just `manage.py loaddata datadump.json`? Because loaddata writes EVERY object in the
fixture, keyed by primary key — so it would also overwrite every pattern that still exists with its
state as of the dump. On this project that would silently revert the ten SQP replicas back to the
hand-written aggregates they replaced, and undo any edit a teacher made since. A snapshot is not a
backup of the present.

This command only ever INSERTS rows whose primary key is absent from the database. It never
updates or deletes anything, so it is safe to run against live data.

    python manage.py restore_patterns_from_dump --list
    python manage.py restore_patterns_from_dump --restore
    python manage.py restore_patterns_from_dump --restore --only 339 342
"""

import io
import json
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import ExamPattern


# auto_now_add / auto_now overwrite whatever we assign, so the original timestamps have to be
# written back with a queryset .update(), which bypasses the field defaults.
_TIMESTAMPS = ("created_at", "updated_at")


def _username(value):
    """dumpdata writes a FK either as a pk or, with --natural-foreign, as ['username']."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


class Command(BaseCommand):
    help = "Re-insert ExamPatterns present in a dumpdata fixture but missing from the database."

    def add_arguments(self, parser):
        parser.add_argument("--dump", default="datadump.json",
                            help="Path to the dumpdata JSON (default: datadump.json).")
        parser.add_argument("--list", action="store_true",
                            help="Show what is missing and exit (the default if --restore is absent).")
        parser.add_argument("--restore", action="store_true",
                            help="Actually insert the missing patterns.")
        parser.add_argument("--only", nargs="+", type=int, metavar="ID",
                            help="Restore just these pattern ids.")

    def handle(self, *args, **opts):
        path = opts["dump"]
        if not os.path.exists(path):
            raise CommandError(f"No such dump: {path}")

        with io.open(path, encoding="utf-8", errors="replace") as fh:
            records = json.load(fh)

        dumped = {o["pk"]: o["fields"] for o in records
                  if o.get("model") == "core.exampattern"}
        # Map the dump's user pks to usernames so a creator can be re-linked to the live account.
        dump_users = {o["pk"]: o["fields"].get("username") for o in records
                      if o.get("model") == "auth.user"}

        live = set(ExamPattern.objects.values_list("id", flat=True))
        missing = sorted(set(dumped) - live)
        if opts["only"]:
            wanted = set(opts["only"])
            skipped = wanted - set(missing)
            for pk in sorted(skipped):
                self.stdout.write(self.style.WARNING(
                    f"  #{pk} is not missing (or not in the dump) — skipping"))
            missing = [pk for pk in missing if pk in wanted]

        self.stdout.write(f"dump: {len(dumped)} pattern(s)   live: {len(live)}   "
                          f"missing: {len(missing)}")
        if not missing:
            self.stdout.write(self.style.SUCCESS("Nothing to restore."))
            return

        for pk in missing:
            f = dumped[pk]
            creator = _username(f.get("created_by")) or dump_users.get(f.get("created_by"))
            self.stdout.write(
                f"  #{pk:4d} {f.get('created_at', '')[:10]}  {f.get('pattern_source')}  "
                f"Class {f.get('class_name')} {f.get('subject')} · {f.get('total_marks')}M · "
                f"{f.get('name')!r}  by {creator}")

        if not opts["restore"]:
            self.stdout.write("\nRe-run with --restore to insert these. "
                              "Existing patterns are never touched.")
            return

        restored, failed = 0, 0
        for pk in missing:
            f = dumped[pk]
            username = _username(f.get("created_by")) or dump_users.get(f.get("created_by"))
            owner = User.objects.filter(username=username).first() if username else None
            if username and owner is None:
                # Restoring with no creator would put the pattern straight back into the
                # invisible-to-everyone state that fix_orphan_patterns exists to repair.
                self.stdout.write(self.style.ERROR(
                    f"  #{pk}: creator '{username}' no longer exists — skipping. Recreate that "
                    f"user first, or restore it and then run fix_orphan_patterns."))
                failed += 1
                continue

            try:
                with transaction.atomic():
                    pattern = ExamPattern(
                        id=pk,
                        name=f.get("name") or "Restored pattern",
                        description=f.get("description") or "",
                        subject=f.get("subject") or "",
                        class_name=f.get("class_name") or "",
                        sections=f.get("sections") or [],
                        total_marks=f.get("total_marks") or 0,
                        total_questions=f.get("total_questions") or 0,
                        pattern_source=f.get("pattern_source") or "manual",
                        ai_prompt=f.get("ai_prompt") or "",
                        status=f.get("status") or "done",
                        task_id=f.get("task_id"),
                        sqp_year=f.get("sqp_year") or "",
                        created_by=owner,
                    )
                    pattern.save(force_insert=True)
                    stamps = {k: f[k] for k in _TIMESTAMPS if f.get(k)}
                    if stamps:
                        ExamPattern.objects.filter(pk=pk).update(**stamps)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  #{pk}: {type(exc).__name__}: {exc}"))
                failed += 1
                continue

            self.stdout.write(self.style.SUCCESS(
                f"  RESTORED #{pk} {f.get('name')!r} -> {owner.username if owner else 'no creator'}"))
            restored += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. restored={restored} failed={failed}. No existing pattern was modified."))
