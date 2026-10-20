from django.conf import settings


def site_languages(request):
    return {
        "LANGUAGES": settings.LANGUAGES,
    }
