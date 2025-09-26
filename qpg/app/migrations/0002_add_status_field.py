# Generated manually to add status field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='questionpaper',
            name='status',
            field=models.CharField(
                choices=[
                    ('generated', 'Generated'),
                    ('processing', 'Processing'),
                    ('failed', 'Failed')
                ],
                default='generated',
                max_length=20
            ),
        ),
    ]
