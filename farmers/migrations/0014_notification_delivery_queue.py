from django.db import migrations, models


def mark_existing_notifications_as_legacy(apps, schema_editor):
    Notification = apps.get_model("farmers", "Notification")
    Notification.objects.update(is_legacy_notification=True)


class Migration(migrations.Migration):

    atomic = True

    dependencies = [
        ("farmers", "0013_userprofile_farmer_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="email_recipient",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="notification",
            name="is_permanent_failure",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="notification",
            name="last_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="notification",
            name="next_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notification",
            name="is_legacy_notification",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(
            mark_existing_notifications_as_legacy,
            migrations.RunPython.noop,
        ),
    ]
