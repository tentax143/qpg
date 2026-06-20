from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("core", "0018_school_shared_vectorstore_material_school")]
    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="allowed_subject",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
