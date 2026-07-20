"""Shared LOGGING config, imported independently by base.py, auth.py, and
dashboard.py — the three services don't share a settings base, so this stays
a plain dict each one pulls in, rather than new inheritance between them."""

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Django already emits its own formatted line for a 500 — WARNING
        # avoids a second, differently-formatted copy of the same event.
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
