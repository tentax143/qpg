from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_school_total_images_generated'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='disable_image_generation',
            field=models.BooleanField(default=False),
        ),
    ]
