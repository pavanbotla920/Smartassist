"""Outbound notifications for SmartAssist.

Design notes
------------
Email is sent explicitly from the views, never from ``Model.save()``. Sending
inside ``save()`` fires on fixtures, ``loaddata`` and migrations, hides network
I/O inside a database write, and makes the test suite try to reach the real SMTP
server. Keeping it explicit makes the behaviour obvious and testable.

``notify()`` never raises: a mail failure is logged and must not roll back the
status change or turn the admin's action into a 500.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

logger = logging.getLogger(__name__)


def notify(user, subject, message, email_to=None):
    """Store an in-app Notification and attempt to email the recipient.

    The in-app record is always created; the email is best-effort. Prefers
    ``email_to`` and falls back to the address on the account. Returns the
    Notification instance.
    """
    notification = Notification.objects.create(
        user=user,
        notification_type='email',
        subject=subject,
        message=message,
    )

    # Transient result flags so callers can report the outcome to the user.
    notification.email_sent = False
    notification.email_error = None

    recipient = (email_to or user.email or '').strip()
    if not recipient:
        notification.email_error = 'No email address on file.'
        logger.info(
            'Notification %s stored in-app only: no email address on file.',
            notification.pk,
        )
        return notification

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:
        notification.email_error = str(exc) or type(exc).__name__
        logger.exception(
            'Failed to email notification %s to %s', notification.pk, recipient,
        )
    else:
        notification.email_sent = True
        logger.info('Emailed notification %s to %s', notification.pk, recipient)

    return notification


def notify_application_status(application, new_status, notes=''):
    """Tell the applicant that their application status changed.

    Prefers the address typed on the application, falling back to the address on
    the account.
    """
    scheme_name = (
        application.scheme.scheme_name if application.scheme else 'General Assistance'
    )
    subject = f'Application Status Updated: {new_status}'

    lines = [
        f'Hello {application.name},',
        '',
        f'Your application for {scheme_name} has been updated to: {new_status}.',
    ]
    if notes:
        lines += ['', f'Notes from our team: {notes}']
    lines += [
        '',
        f'Application reference: {application.application_number or application.id}',
        '',
        'You can track your application at any time on the SmartAssist portal.',
        '',
        'Thank you,',
        'SmartAssist Team',
    ]

    return notify(
        application.user,
        subject,
        '\n'.join(lines),
        email_to=application.email,
    )
