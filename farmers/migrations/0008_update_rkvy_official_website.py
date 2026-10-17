from django.db import migrations


OFFICIAL_MINISTRY_URL = 'https://agriwelfare.gov.in/en/Major'


def update_rkvy_website(apps, schema_editor):
    Scheme = apps.get_model('farmers', 'Scheme')
    Scheme.objects.filter(scheme_name='Rashtriya Krishi Vikas Yojana').update(
        official_website=OFFICIAL_MINISTRY_URL,
        apply_link=OFFICIAL_MINISTRY_URL,
    )


def restore_rkvy_website(apps, schema_editor):
    Scheme = apps.get_model('farmers', 'Scheme')
    Scheme.objects.filter(scheme_name='Rashtriya Krishi Vikas Yojana').update(
        official_website='https://www.rkvy.nic.in',
        apply_link='https://www.rkvy.nic.in',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('farmers', '0007_correct_pmmsy_portal'),
    ]

    operations = [
        migrations.RunPython(update_rkvy_website, restore_rkvy_website),
    ]
