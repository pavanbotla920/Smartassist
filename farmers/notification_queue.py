"""Reliable, bounded processing for queued email notifications."""

from __future__ import annotations

import os
import re
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.core.mail import BadHeaderError
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Notification


DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_SECONDS = 60
DEFAULT_RETRY_MAX_SECONDS = 3600


def _positive_int_setting(name, default):
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def max_retries():
    return _positive_int_setting("SMARTASSIST_EMAIL_MAX_RETRIES", DEFAULT_MAX_RETRIES)


def _retry_delay(retry_count):
    base = _positive_int_setting(
        "SMARTASSIST_EMAIL_RETRY_BASE_SECONDS",
        DEFAULT_RETRY_BASE_SECONDS,
    )
    maximum = _positive_int_setting(
        "SMARTASSIST_EMAIL_RETRY_MAX_SECONDS",
        DEFAULT_RETRY_MAX_SECONDS,
    )
    return min(maximum, base * (2 ** max(0, retry_count - 1)))


def _safe_error(error):
    message = str(error).strip() or type(error).__name__
    message = re.sub(r"(?i)(password|passwd|secret|token)=?[^\s,;]+", r"\1=[redacted]", message)
    if len(message) > 500:
        message = message[:497] + "..."
    return message


def _is_permanent_failure(error):
    return isinstance(
        error,
        (
            BadHeaderError,
            ValueError,
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
        ),
    )


def _eligible_notifications(now):
    return Notification.objects.filter(
        notification_type="email",
        delivery_status__in=("pending", "failed"),
        is_sent=False,
        is_permanent_failure=False,
        retry_count__lt=max_retries(),
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))


def process_notification(notification_id, *, now=None, dry_run=False):
    """Attempt one eligible notification while preventing duplicate sends."""
    now = now or timezone.now()
    with transaction.atomic():
        notification = (
            Notification.objects.select_for_update()
            .select_related("user")
            .get(pk=notification_id)
        )
        if (
            notification.notification_type != "email"
            or notification.is_sent
            or notification.delivery_status == "sent"
            or notification.is_permanent_failure
            or notification.retry_count >= max_retries()
            or (
                notification.next_attempt_at is not None
                and notification.next_attempt_at > now
            )
        ):
            return "skipped"

        if dry_run:
            return "eligible"

        recipient = notification.email_recipient.strip()
        if not recipient:
            error = "No email address on file."
            notification.delivery_status = "failed"
            notification.is_sent = False
            notification.is_permanent_failure = True
            notification.email_error = error
            notification.last_error = error
            notification.last_attempt_at = now
            notification.save(
                update_fields=[
                    "delivery_status",
                    "is_sent",
                    "is_permanent_failure",
                    "email_error",
                    "last_error",
                    "last_attempt_at",
                ]
            )
            return "permanent_failure"
        try:
            validate_email(recipient)
        except ValidationError:
            error = "Invalid recipient email address."
            notification.delivery_status = "failed"
            notification.is_sent = False
            notification.is_permanent_failure = True
            notification.email_error = error
            notification.last_error = error
            notification.last_attempt_at = now
            notification.save(
                update_fields=[
                    "delivery_status",
                    "is_sent",
                    "is_permanent_failure",
                    "email_error",
                    "last_error",
                    "last_attempt_at",
                ]
            )
            return "permanent_failure"

        notification.last_attempt_at = now
        notification.save(update_fields=["last_attempt_at"])
        try:
            sent_count = mail.send_mail(
                subject=notification.subject or "",
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
            if not sent_count:
                raise RuntimeError("Email backend did not report a successful delivery.")
        except Exception as exc:
            retry_count = notification.retry_count + 1
            permanent = _is_permanent_failure(exc) or retry_count >= max_retries()
            error = _safe_error(exc)
            notification.retry_count = retry_count
            notification.delivery_status = "failed"
            notification.is_sent = False
            notification.is_permanent_failure = permanent
            notification.email_error = error
            notification.last_error = error
            notification.next_attempt_at = (
                None
                if permanent
                else now + timedelta(seconds=_retry_delay(retry_count))
            )
            notification.save(
                update_fields=[
                    "retry_count",
                    "delivery_status",
                    "is_sent",
                    "is_permanent_failure",
                    "email_error",
                    "last_error",
                    "next_attempt_at",
                    "last_attempt_at",
                ]
            )
            return "permanent_failure" if permanent else "failed"

        notification.delivery_status = "sent"
        notification.is_sent = True
        notification.email_error = ""
        notification.last_error = ""
        notification.next_attempt_at = None
        notification.delivered_at = now
        notification.save(
            update_fields=[
                "delivery_status",
                "is_sent",
                "email_error",
                "last_error",
                "next_attempt_at",
                "delivered_at",
                "last_attempt_at",
            ]
        )
        return "sent"


def process_pending_notifications(*, limit=100, now=None, dry_run=False):
    """Process currently eligible notifications once, returning status counts."""
    now = now or timezone.now()
    notification_ids = list(
        _eligible_notifications(now).order_by("sent_at", "pk").values_list(
            "pk",
            flat=True,
        )[: max(0, limit)]
    )
    results = {"eligible": 0, "sent": 0, "failed": 0, "permanent_failure": 0, "skipped": 0}
    for notification_id in notification_ids:
        result = process_notification(
            notification_id,
            now=now,
            dry_run=dry_run,
        )
        results[result] += 1
    return results
