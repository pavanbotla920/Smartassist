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

from .models import Notification, UserProfile

logger = logging.getLogger(__name__)


def get_farmer_status_message(new_status, farmer_message=''):
    return (
        farmer_message.strip()
        or f'Your application status is now {new_status}. '
        'Please check your application dashboard for further details.'
    )


def notify(user, subject, message, email_to=None, application=None):
    """Store an in-app notification and attempt email delivery.

    The notification is always stored. Email delivery is best-effort:
    failures are persisted but never interrupt the application workflow.
    """
    notification = Notification.objects.create(
        user=user,
        application=application,
        notification_type='email',
        subject=subject,
        message=message,
    )

    # Preserve temporary attributes for existing callers.
    notification.email_sent = False

    recipient = (email_to or user.email or '').strip()

    email_notifications_enabled = UserProfile.objects.filter(
        user=user,
    ).values_list('email_notifications', flat=True).first()
    if email_notifications_enabled is False:
        notification.is_sent = False
        notification.email_error = 'Email notifications are disabled in your settings.'
        notification.save(update_fields=['is_sent', 'email_error'])
        logger.info(
            'Notification %s stored in-app only: email notifications disabled.',
            notification.pk,
        )
        return notification

    if not recipient:
        error = 'No email address on file.'

        notification.is_sent = False
        notification.email_error = error
        notification.save(update_fields=['is_sent', 'email_error'])

        logger.info(
            'Notification %s stored in-app only: no email address on file.',
            notification.pk,
        )
        return notification

    try:
        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )

        notification.is_sent = bool(sent_count)
        notification.email_sent = bool(sent_count)

        if not notification.is_sent:
            notification.email_error = 'Email backend did not report a successful delivery.'

    except Exception as exc:
        notification.is_sent = False
        notification.email_sent = False
        notification.email_error = str(exc) or type(exc).__name__

        logger.exception(
            'Failed to email notification %s to %s',
            notification.pk,
            recipient,
        )

    else:
        if notification.is_sent:
            logger.info(
                'Emailed notification %s to %s',
                notification.pk,
                recipient,
            )

    notification.save(update_fields=['is_sent', 'email_error'])

    return notification


def notify_application_status(application, new_status, farmer_message=''):
    """Tell the applicant that their application status changed.

    Prefers the registered account address, falling back to the address typed
    on the application when the account address is missing.
    """
    scheme_name = (
        application.scheme.scheme_name if application.scheme else 'General Assistance'
    )
    subject = f'Application Status Updated: {new_status}'
    message = get_farmer_status_message(new_status, farmer_message)

    lines = [
        f'Hello {application.name},',
        '',
        f'Your application for {scheme_name} has been updated to: {new_status}.',
        '',
        'Message from SmartAssist Team:',
        message,
    ]
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
        email_to=application.user.email or application.email,
        application=application,
    )
