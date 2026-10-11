from django.db import migrations


def update_pmmsy_portal(apps, schema_editor):
    Scheme = apps.get_model('farmers', 'Scheme')
    schemes = Scheme.objects.filter(
        official_website__icontains='pmmsy.dac.gov.in'
    ) | Scheme.objects.filter(
        apply_link__icontains='pmmsy.dac.gov.in'
    )

    for scheme in schemes.iterator():
        updates = {}
        for field in ('official_website', 'apply_link'):
            value = getattr(scheme, field)
            if value and 'pmmsy.dac.gov.in' in value.lower():
                updates[field] = value.replace('pmmsy.dac.gov.in', 'pmmsy.dof.gov.in')
        if updates:
            Scheme.objects.filter(pk=scheme.pk).update(**updates)


def restore_legacy_pmmsy_portal(apps, schema_editor):
    Scheme = apps.get_model('farmers', 'Scheme')
    schemes = Scheme.objects.filter(
        official_website__icontains='pmmsy.dof.gov.in'
    ) | Scheme.objects.filter(
        apply_link__icontains='pmmsy.dof.gov.in'
    )

    for scheme in schemes.iterator():
        updates = {}
        for field in ('official_website', 'apply_link'):
            value = getattr(scheme, field)
            if value and 'pmmsy.dof.gov.in' in value.lower():
                updates[field] = value.replace('pmmsy.dof.gov.in', 'pmmsy.dac.gov.in')
        if updates:
            Scheme.objects.filter(pk=scheme.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('farmers', '0006_remove_notification_created_at_and_more'),
    ]

    operations = [
        migrations.RunPython(update_pmmsy_portal, restore_legacy_pmmsy_portal),
    ]
