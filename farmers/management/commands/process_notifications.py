from django.core.management.base import BaseCommand, CommandError

from farmers.notification_queue import process_pending_notifications


class Command(BaseCommand):
    help = "Process eligible queued email notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of notifications to inspect (default: 100).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report eligible notifications without sending email.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        results = process_pending_notifications(
            limit=limit,
            dry_run=options["dry_run"],
        )
        mode = "eligible" if options["dry_run"] else "processed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: "
                + ", ".join(
                    f"{key}={value}" for key, value in results.items()
                )
            )
        )
