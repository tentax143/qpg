from django.db import migrations


DEFAULT_PLANS = [
    {'name': 'free',   'display_name': 'Free',        'monthly_paper_limit': 5,   'teacher_limit': 2,   'price_inr': 0},
    {'name': 'basic',  'display_name': 'Basic',       'monthly_paper_limit': 30,  'teacher_limit': 5,   'price_inr': 999},
    {'name': 'pro',    'display_name': 'Pro',         'monthly_paper_limit': 100, 'teacher_limit': 15,  'price_inr': 2499},
    {'name': 'school', 'display_name': 'School',      'monthly_paper_limit': -1,  'teacher_limit': -1,  'price_inr': 5999},
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('core', 'Plan')
    for p in DEFAULT_PLANS:
        Plan.objects.get_or_create(name=p['name'], defaults=p)


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model('core', 'Plan')
    Plan.objects.filter(name__in=[p['name'] for p in DEFAULT_PLANS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_plan_school_plan_fields'),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
