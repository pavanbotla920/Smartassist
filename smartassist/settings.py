"""
Django settings for smartassist project.
"""
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# Security
def _get_secret_key():
    secret_key = os.getenv("DJANGO_SECRET_KEY", "").strip()
    if secret_key:
        return secret_key

    environment = os.getenv("DJANGO_ENV", "development").strip().lower()
    if environment in {"production", "prod"}:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be configured in production."
        )

    return get_random_secret_key()


def _get_debug_setting():
    environment = os.getenv("DJANGO_ENV", "development").strip().lower()
    if environment in {"production", "prod"}:
        return False

    return os.getenv("DJANGO_DEBUG", "False").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _get_bool_setting(name, default=False):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def _get_nonnegative_int_setting(name, default=0):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.") from exc
    if parsed < 0:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.")
    return parsed


def _get_comma_separated_setting(name, default=None, required=False):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        if required:
            raise ImproperlyConfigured(f"{name} must be configured.")
        return list(default or [])

    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    if not values:
        raise ImproperlyConfigured(f"{name} must contain at least one value.")
    if any(value == "*" for value in values):
        raise ImproperlyConfigured(f"{name} must not contain a wildcard.")
    return values


def _get_allowed_hosts():
    environment = os.getenv("DJANGO_ENV", "development").strip().lower()
    return _get_comma_separated_setting(
        "DJANGO_ALLOWED_HOSTS",
        default=["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "testserver"],
        required=environment in {"production", "prod"},
    )


def _get_csrf_trusted_origins():
    environment = os.getenv("DJANGO_ENV", "development").strip().lower()
    origins = _get_comma_separated_setting(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        default=[],
        required=environment in {"production", "prod"},
    )
    for origin in origins:
        parsed = None
        hostname = None
        try:
            parsed = urlparse(origin)
            hostname = parsed.hostname
            parsed.port
        except ValueError:
            parsed = None
            hostname = None
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != ""
            or parsed.params
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ImproperlyConfigured(
                "DJANGO_CSRF_TRUSTED_ORIGINS must contain complete http(s) origins."
            )
    return origins


SECRET_KEY = _get_secret_key()
DEBUG = _get_debug_setting()

ALLOWED_HOSTS = _get_allowed_hosts()
CSRF_TRUSTED_ORIGINS = _get_csrf_trusted_origins()

# Applications
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "farmers",
]

# Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "smartassist.urls"

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "farmers.context_processors.site_languages",
                "farmers.context_processors.notification_status",
            ],
        },
    },
]

WSGI_APPLICATION = "smartassist.wsgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3")),
    }
}

def _get_cache_config():
    cache_url = os.getenv("DJANGO_CACHE_URL", "").strip()
    environment = os.getenv("DJANGO_ENV", "development").strip().lower()
    if not cache_url and environment in {"production", "prod"}:
        raise ImproperlyConfigured(
            "DJANGO_CACHE_URL must be configured in production."
        )
    if cache_url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": cache_url,
            }
        }
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "smartassist-local-cache",
        }
    }


CACHES = _get_cache_config()


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en"

LANGUAGES = [
    ("en", "English"),
    ("hi", "Hindi"),
    ("mr", "Marathi"),
    ("te", "Telugu"),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

USE_I18N = True

LANGUAGE_COOKIE_NAME = "django_language"
LANGUAGE_COOKIE_AGE = 365 * 24 * 60 * 60
LANGUAGE_COOKIE_PATH = "/"
LANGUAGE_COOKIE_HTTPONLY = False
LANGUAGE_SESSION_KEY = "_language"

_production_environment = os.getenv("DJANGO_ENV", "development").strip().lower() in {
    "production", "prod"
}
SECURE_SSL_REDIRECT = _get_bool_setting("DJANGO_SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = _get_nonnegative_int_setting("DJANGO_SECURE_HSTS_SECONDS")
SECURE_HSTS_INCLUDE_SUBDOMAINS = _get_bool_setting(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS"
)
SECURE_HSTS_PRELOAD = _get_bool_setting("DJANGO_SECURE_HSTS_PRELOAD")
SESSION_COOKIE_SECURE = _production_environment
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = _production_environment
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

TIME_ZONE = "Asia/Kolkata"
USE_TZ = True

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# Authentication
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Email settings
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

DEFAULT_FROM_EMAIL = (
    f"SmartAssist <{EMAIL_HOST_USER}>"
    if EMAIL_HOST_USER
    else "SmartAssist <noreply@smartassist.gov.in>"
)

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
