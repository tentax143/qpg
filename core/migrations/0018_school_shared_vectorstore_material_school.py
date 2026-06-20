import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_add_school_cumulative_stats"),
    ]

    operations = [
        migrations.AddField(
            model_name="school",
            name="access_shared_vector_store",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="material",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="materials",
                to="core.school",
            ),
        ),
        # Populate Material.school from uploaded_by__profile__school for existing rows
        migrations.RunSQL(
            sql="""
                UPDATE core_material
                SET school_id = (
                    SELECT school_id
                    FROM core_userprofile
                    WHERE user_id = core_material.uploaded_by_id
                    LIMIT 1
                )
                WHERE uploaded_by_id IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
