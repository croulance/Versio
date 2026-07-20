import os
from pathlib import Path

from .logging import LOGGING  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "auth-dev-secret-change-in-prod")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.supplier_auth",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "versio.urls_auth"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "versio"),
        "USER": os.environ.get("DB_USER", "versio"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "versio"),
        "HOST": os.environ.get("DB_HOST", "db"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles_auth"
# WhiteNoise serves /static/ directly from this gunicorn process -- no nginx
# or CDN in front of any of the three services. WHITENOISE_USE_FINDERS lets
# it serve straight from each app's own static/ (including django.contrib.admin's
# built-in CSS/JS) in dev, with no collectstatic step needed; STORAGES switches
# to the collected, hashed, compressed STATIC_ROOT once DEBUG is off.
WHITENOISE_USE_FINDERS = DEBUG
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

# Opaque, DB-backed supplier session token (apps.supplier_auth.models.SupplierAuthToken)
SUPPLIER_TOKEN_TTL_DAYS = int(os.environ.get("SUPPLIER_TOKEN_TTL_DAYS", "15"))

# Cache-aside layer over AuthService.introspect() — the only DB round trip this
# service can avoid, since it's called on every dashboard request. Short TTL:
# this is a performance layer, not a source of truth (AuthService.refresh()
# actively invalidates the rotated-out token's entry, so staleness is bounded
# by this TTL only when a token is never rotated, not after rotation).
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AUTH_INTROSPECTION_CACHE_TTL = int(os.environ.get("AUTH_INTROSPECTION_CACHE_TTL", "10"))
