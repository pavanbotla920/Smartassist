from django.db import migrations


def normalize_legacy_pending_status(apps, schema_editor):
    ApplicationRequest = apps.get_model('farmers', 'ApplicationRequest')
    ApplicationRequest.objects.filter(status='Pending').update(status='Submitted')


class Migration(migrations.Migration):

    dependencies = [
        ('farmers', '0008_update_rkvy_official_website'),
    ]

    operations = [
        migrations.RunPython(
            normalize_legacy_pending_status,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
