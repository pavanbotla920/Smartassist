"""Outbound notifications for SmartAssist.

Design notes
------------
Email is queued explicitly from the views, never from ``Model.save()``.
Delivery is performed by a management command or worker, so requests never
wait for SMTP.

``notify()`` never raises: a mail failure is logged and must not roll back the
status change or turn the admin's action into a 500.
"""
import logging

from django.core.mail import send_mail  # Backward-compatible test/import surface.

from .models import Notification, UserProfile

logger = logging.getLogger(__name__)


def get_farmer_status_message(new_status, farmer_message=''):
    return (
        farmer_message.strip()
        or f'Your application status is now {new_status}. '
        'Please check your application dashboard for further details.'
    )


def notify(user, subject, message, email_to=None, application=None):
    """Store an in-app notification and queue email delivery."""
    notification = Notification.objects.create(
        user=user,
        application=application,
        notification_type='email',
        subject=subject,
        message=message,
        email_recipient=(email_to or user.email or '').strip(),
        is_legacy_notification=False,
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
        notification.last_error = notification.email_error
        notification.delivery_status = 'failed'
        notification.is_permanent_failure = True
        notification.save(update_fields=[
            'is_sent', 'email_error', 'last_error', 'delivery_status',
            'is_permanent_failure',
        ])
        logger.info(
            'Notification %s stored in-app only: email notifications disabled.',
            notification.pk,
        )
        return notification

    if not recipient:
        error = 'No email address on file.'

        notification.is_sent = False
        notification.email_error = error
        notification.last_error = error
        notification.delivery_status = 'failed'
        notification.is_permanent_failure = True
        notification.save(update_fields=[
            'is_sent', 'email_error', 'last_error', 'delivery_status',
            'is_permanent_failure',
        ])

        logger.info(
            'Notification %s stored in-app only: no email address on file.',
            notification.pk,
        )
        return notification

    notification.delivery_status = 'pending'
    notification.is_sent = False
    notification.save(update_fields=['is_sent', 'delivery_status'])
    logger.info('Notification %s queued for delivery.', notification.pk)

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
