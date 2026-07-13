# Generated migration for SystemNotification schools field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_systemnotification'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemnotification',
            name='schools',
            field=models.ManyToManyField(blank=True, related_name='notifications', to='core.school'),
        ),
    ]
