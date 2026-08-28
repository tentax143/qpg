"""
Management command: python manage.py fix_orphan_patterns

Finds and repairs patterns that have fallen out of every school's list.

`ExamPattern.created_by` is `on_delete=SET_NULL` and visibility is computed by joining through
the creator's profile (`created_by__profile__school`, see `api.views.ExamPatternViewSet`). So when
a teacher is deleted, the patterns they built survive as rows but belong to nobody:

  * no school can see them — the join matches nothing, and `created_by=user` matches nothing;
  * every school CAN clone them — a NULL creator makes them match the premade-template pool
    (`_template_queryset`), so one school's work is offered to all the others as an official
    template.

That is the mechanism behind a "our pattern disappeared" report. This command lists the affected
rows and re-homes one to a school by attributing it to that school's admin, which is the only
handle the current model gives us — ownership is derived from the creator, not stored on the
pattern.

    python manage.py fix_orphan_patterns --list
    python manage.py fix_orphan_patterns --pattern 343 --school "RAMCO VIDYA MANDIR"
    python manage.py fix_orphan_patterns --pattern 343 --user geetha

Note the side effect: the pattern will read as created by that user, because there is nowhere else
to record ownership. The durable fix is a `school` field on ExamPattern set at creation time, so
deleting a user never moves a pattern.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import ExamPattern, School


# Sources that are SUPPOSED to have no creator: the premade, clone-only templates.
PREMADE_SOURCES = ("cbse_official", "cbse_sqp", "one_mark_test")


def orphaned_patterns():
    """Patterns with no creator that are not premade templates — i.e. somebody's lost work."""
    return (ExamPattern.objects
            .filter(created_by__isnull=True)
            .exclude(pattern_source__in=PREMADE_SOURCES)
            .order_by("created_at"))


class Command(BaseCommand):
    help = "List or re-home exam patterns that no school can see (their creator was deleted)."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true",
                            help="List orphaned patterns and exit.")
        parser.add_argument("--pattern", type=int,
                            help="Id of the pattern to re-home.")
        parser.add_argument("--school", type=str,
                            help="School to give it to (name, or part of one). Its admin becomes "
                                 "the recorded creator.")
        parser.add_argument("--user", type=str,
                            help="Username to attribute it to instead of picking a school admin.")

    def handle(self, *args, **opts):
        orphans = orphaned_patterns()

        if opts["list"] or not opts["pattern"]:
            if not orphans.exists():
                self.stdout.write(self.style.SUCCESS(
                    "No orphaned patterns — every non-premade pattern has a creator."))
                return
            self.stdout.write(self.style.WARNING(
                f"{orphans.count()} pattern(s) invisible to every school "
                f"(and clonable by all of them):"))
            for p in orphans:
                self.stdout.write(
                    f"  #{p.id}  {p.created_at:%Y-%m-%d}  {p.pattern_source:13s} "
                    f"Class {p.class_name} {p.subject} · {p.total_marks}M · {p.name!r}")
            if not opts["pattern"]:
                self.stdout.write("\nRe-home one with:  --pattern <id> --school \"<school name>\"")
            return

        try:
            pattern = ExamPattern.objects.get(id=opts["pattern"])
        except ExamPattern.DoesNotExist:
            raise CommandError(f"No pattern with id {opts['pattern']}.")

        if pattern.created_by_id:
            raise CommandError(
                f"#{pattern.id} already belongs to '{pattern.created_by.username}' — it is not "
                f"orphaned, so re-homing it would take it away from them.")
        if pattern.pattern_source in PREMADE_SOURCES:
            raise CommandError(
                f"#{pattern.id} is a premade {pattern.pattern_source} template. Those are meant to "
                f"have no creator (that is what makes them clone-only for every school); giving it "
                f"one would remove it from the template pool.")

        # Resolve the new owner.
        if opts["user"]:
            try:
                owner = User.objects.get(username=opts["user"])
            except User.DoesNotExist:
                raise CommandError(f"No user named '{opts['user']}'.")
        elif opts["school"]:
            schools = list(School.objects.filter(name__icontains=opts["school"]))
            if not schools:
                raise CommandError(f"No school matching '{opts['school']}'.")
            if len(schools) > 1:
                raise CommandError(
                    "That matches more than one school: "
                    + ", ".join(f"'{s.name}'" for s in schools))
            school = schools[0]
            # Prefer the school's admin: they are the account least likely to be deleted next,
            # and the one a teacher would expect to see as the owner of a shared pattern.
            owner = (User.objects.filter(profile__school=school, profile__role="school_admin")
                     .order_by("id").first()
                     or User.objects.filter(profile__school=school).order_by("id").first())
            if owner is None:
                raise CommandError(f"'{school.name}' has no users to attribute the pattern to.")
        else:
            raise CommandError("Give either --school or --user.")

        owner_school = getattr(getattr(owner, "profile", None), "school", None)
        if owner_school is None:
            raise CommandError(
                f"'{owner.username}' has no school on their profile, so the pattern would STILL be "
                f"invisible to every school. Fix that profile first.")

        self.stdout.write(f"#{pattern.id} {pattern.name!r} "
                          f"(Class {pattern.class_name} {pattern.subject}, {pattern.total_marks}M)")
        self.stdout.write(f"  before: creator=None  ->  visible to nobody, clonable by everyone")

        pattern.created_by = owner
        pattern.save(update_fields=["created_by"])

        visible = ExamPattern.objects.filter(
            created_by__profile__school=owner_school, id=pattern.id).exists()
        from api.views import ExamPatternViewSet
        still_template = ExamPatternViewSet._template_queryset().filter(id=pattern.id).exists()

        self.stdout.write(f"  after:  creator={owner.username}  ->  visible to "
                          f"'{owner_school.name}': {visible}, still a global template: {still_template}")
        if visible and not still_template:
            self.stdout.write(self.style.SUCCESS("  Re-homed."))
        else:
            self.stdout.write(self.style.ERROR(
                "  Unexpected end state — check the owner's profile and role."))
