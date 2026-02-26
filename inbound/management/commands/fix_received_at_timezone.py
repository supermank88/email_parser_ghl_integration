"""
Management command to fix received_at timestamps in InboundEmail.

1. Naive -> aware: If received_at is naive, treat as UTC and make timezone-aware.
2. Assumed EST: If data was stored in EST/local without timezone, use
   --assume-stored-as-est to convert those values to proper UTC.

Run: python manage.py fix_received_at_timezone
     python manage.py fix_received_at_timezone --assume-stored-as-est
     python manage.py fix_received_at_timezone --dry-run
"""

from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from inbound.models import InboundEmail


class Command(BaseCommand):
    help = "Fix received_at timestamps for correct EST display."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes.',
        )
        parser.add_argument(
            '--assume-stored-as-est',
            action='store_true',
            help='Treat naive datetimes as Eastern time and convert to UTC.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        assume_est = options['assume_stored_as_est']
        if dry_run:
            self.stdout.write("DRY RUN - no changes will be saved")

        est = ZoneInfo('America/New_York')
        qs = InboundEmail.objects.filter(received_at__isnull=False)
        updated = 0

        for email in qs:
            dt = email.received_at
            if dt is None:
                continue

            new_dt = None
            if dt.tzinfo is None:
                if assume_est:
                    # Treat naive value as Eastern, convert to UTC
                    dt_est = dt.replace(tzinfo=est)
                    new_dt = dt_est.astimezone(timezone.utc)
                else:
                    # Assume naive is UTC
                    new_dt = timezone.make_aware(dt, timezone.utc)

            if new_dt is not None:
                email.received_at = new_dt
                if not dry_run:
                    email.save(update_fields=['received_at'])
                updated += 1
                self.stdout.write(
                    f"  Fixed id={email.pk} received_at={email.received_at} UTC"
                )

        if updated:
            self.stdout.write(self.style.SUCCESS(f"Updated {updated} record(s)."))
        else:
            self.stdout.write("No records needed updating.")
