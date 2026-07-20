import os
from pathlib import Path

from .logging import LOGGING  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dashboard-dev-secret-change-in-prod")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "django.contrib.sessions",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.dashboard.middleware.SupplierAuthMiddleware",
    "apps.dashboard.middleware.UpstreamErrorMiddleware",
]

ROOT_URLCONF = "versio.urls_dashboard"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

# No database — all data comes from the transformation API
DATABASES = {}

# Sessions stored in a signed cookie — no DB or cache required
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_NAME = "versio_dashboard"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = (
    15 * 24 * 3600
)  # 15 days, matches SUPPLIER_TOKEN_TTL_DAYS on the auth service

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles_dashboard"
# WhiteNoise serves /static/ directly from this gunicorn process -- no nginx
# or CDN in front of any of the three services. WHITENOISE_USE_FINDERS lets
# it serve straight from each app's own static/ in dev, with no collectstatic
# step needed; STORAGES switches to the collected, hashed, compressed
# STATIC_ROOT once DEBUG is off. STATIC_ROOT is its own directory (not the
# "staticfiles" name base.py/api also uses) since ./src is bind-mounted into
# every container -- two services collecting into the same path would let
# one silently clobber the other's output.
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

TRANSFORMATION_API_URL = os.environ.get("TRANSFORMATION_API_URL", "http://api:8000")
AUTH_API_URL = os.environ.get("AUTH_API_URL", "http://auth:8002")

# The supplier's session token is opaque (DB-backed, verified via the auth
# service's /auth/me/ on every request) — the dashboard never decodes it
# locally and never stores a secret to do so.
SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS = int(
    os.environ.get("SUPPLIER_TOKEN_REFRESH_THRESHOLD_HOURS", "24")
)

# Shared secret used to authenticate the dashboard backend itself (not the
# supplier) when it proxies requests to the transformation API. The supplier's
# own token never leaves the dashboard.
INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "change-me-in-prod")
