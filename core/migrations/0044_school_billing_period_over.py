from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_materialchunk_content_clean'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='billing_period_over',
            field=models.BooleanField(default=False),
        ),
    ]
