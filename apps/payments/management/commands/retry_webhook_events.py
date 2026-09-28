import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.payments.models import WebhookEvent, WebhookEventStatus
from apps.payments.webhooks import process_event

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Reprocess webhook events that failed (or were stored but never processed). "
        "Intended to run periodically, e.g. from cron."
    )

    def add_arguments(self, parser):
        parser.add_argument("--max-attempts", type=int, default=5)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--stale-after-seconds",
            type=int,
            default=300,
            help="RECEIVED events older than this are treated as abandoned and retried.",
        )

    def handle(self, *args, max_attempts: int, limit: int, stale_after_seconds: int, **options):
        stale_before = timezone.now() - timedelta(seconds=stale_after_seconds)
        candidates = (
            WebhookEvent.objects.filter(
                Q(status=WebhookEventStatus.FAILED)
                | Q(status=WebhookEventStatus.RECEIVED, created_at__lt=stale_before),
                attempts__lt=max_attempts,
            )
            .order_by("created_at")
            .values_list("pk", flat=True)[:limit]
        )

        succeeded = still_failing = 0
        for event_pk in list(candidates):
            try:
                process_event(event_pk)
            except Exception:  # one bad event must not stop the batch; details are on the row
                still_failing += 1
                logger.warning("webhook.retry_failed", extra={"event_pk": str(event_pk)})
            else:
                succeeded += 1

        self.stdout.write(
            f"Retried {succeeded + still_failing} event(s): {succeeded} ok, "
            f"{still_failing} still failing."
        )
