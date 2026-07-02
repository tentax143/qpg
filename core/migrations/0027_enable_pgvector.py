from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Enable the pgvector extension (CREATE EXTENSION IF NOT EXISTS vector).

    Only enables the extension — no vector columns / tables are created yet. CreateExtension is
    a no-op on non-PostgreSQL backends, so a SQLite fallback (POSTGRES_DB unset) still migrates.
    pgvector is a 'trusted' extension, so the app's non-superuser role can create it as long as
    it has CREATE on the database.
    """

    dependencies = [
        ("core", "0026_backfill_usage_events"),
    ]

    operations = [
        CreateExtension("vector"),
    ]
