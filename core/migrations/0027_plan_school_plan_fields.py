from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_backfill_usage_events'),
    ]

    operations = [
        migrations.CreateModel(
            name='Plan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('display_name', models.CharField(max_length=100)),
                ('monthly_paper_limit', models.IntegerField(default=5)),
                ('teacher_limit', models.IntegerField(default=2)),
                ('price_inr', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('razorpay_plan_id', models.CharField(blank=True, max_length=100)),
            ],
            options={
                'ordering': ['price_inr'],
            },
        ),
        migrations.AddField(
            model_name='school',
            name='plan',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='schools',
                to='core.plan',
            ),
        ),
        migrations.AddField(
            model_name='school',
            name='plan_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='school',
            name='trial_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
