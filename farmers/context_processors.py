from django.conf import settings
from .models import Notification


def site_languages(request):
    return {
        "LANGUAGES": settings.LANGUAGES,
    }


def notification_status(request):
    unread_count = 0
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).count()
    return {
        'unread_notification_count': unread_count,
    }
