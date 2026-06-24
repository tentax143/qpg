"""
Backfill UsageEvent rows from existing papers so the team-usage page shows historical
per-user tokens/cost immediately after deploy.

One event per surviving QuestionPaper that recorded tokens/cost, stamped with the paper's
own created_at (so the monthly figure is correct). Deleted papers can't be re-attributed to a
user — that usage lives only in the School cumulative counter — so per-user all-time may be
lower than the school total for historical data; it stays accurate going forward. Skips
entirely if any UsageEvent already exists, so it never double-counts on re-run.
"""
from django.db import migrations


def backfill_usage(apps, schema_editor):
    UsageEvent = apps.get_model("core", "UsageEvent")
    QuestionPaper = apps.get_model("core", "QuestionPaper")
    UserProfile = apps.get_model("core", "UserProfile")

    if UsageEvent.objects.exists():
        return  # already populated — don't double-count

    school_by_user = {p.user_id: p.school_id for p in UserProfile.objects.all()}

    events = []
    for p in QuestionPaper.objects.exclude(created_by__isnull=True):
        tok_in = p.input_tokens or 0
        tok_out = p.output_tokens or 0
        cost = p.cost or 0
        if not (tok_in or tok_out or cost):
            continue
        events.append(UsageEvent(
            user_id=p.created_by_id,
            school_id=school_by_user.get(p.created_by_id),
            paper_id=p.id,
            kind="generate",
            input_tokens=tok_in,
            output_tokens=tok_out,
            cost=cost,
            created_at=p.created_at,
        ))
    if events:
        UsageEvent.objects.bulk_create(events, batch_size=500)


def reverse(apps, schema_editor):
    UsageEvent = apps.get_model("core", "UsageEvent")
    UsageEvent.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_usageevent"),
    ]

    operations = [
        migrations.RunPython(backfill_usage, reverse),
    ]
