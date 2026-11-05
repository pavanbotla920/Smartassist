from django.db import migrations


def reconcile_legacy_notifications(apps, schema_editor):
    Notification = apps.get_model("farmers", "Notification")

    common_updates = {
        "email_recipient": "",
        "retry_count": 0,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "delivered_at": None,
    }

    Notification.objects.filter(is_legacy_notification=True, is_sent=True).update(
        delivery_status="sent",
        is_permanent_failure=False,
        **common_updates,
    )
    Notification.objects.filter(is_legacy_notification=True, is_sent=False).update(
        delivery_status="failed",
        is_permanent_failure=True,
        **common_updates,
    )


def prevent_unsafe_reverse(apps, schema_editor):
    raise RuntimeError(
        "Reversing 0015 would discard notification reconciliation state. "
        "Restore a verified pre-migration database backup instead."
    )


class Migration(migrations.Migration):

    atomic = True

    dependencies = [
        ("farmers", "0014_notification_delivery_queue"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_legacy_notifications,
            prevent_unsafe_reverse,
        ),
    ]
