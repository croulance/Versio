import os
from pathlib import Path

from .logging import LOGGING  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.transformation",
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

ROOT_URLCONF = "versio.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

CELERY_BROKER_URL = os.environ.get(
    "RABBITMQ_URL", "amqp://versio:versio@rabbitmq:5672/"
)
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_CHUNK_QUEUE = os.environ.get("CELERY_CHUNK_QUEUE", "chunks")
CELERY_MERGE_QUEUE = os.environ.get("CELERY_MERGE_QUEUE", "default")
CELERY_TASK_ROUTES = {
    "apps.transformation.tasks.transform.process_chunk": {"queue": CELERY_CHUNK_QUEUE},
}
# Without these, a worker killed mid-task (OOM, redeploy, scale-down, even a
# routine `docker compose restart worker`) loses that task silently: the
# broker acks a message on receipt by default, not on completion, so a task
# in flight when the process dies is simply gone — no exception, no
# redelivery, nothing left for retry_stuck_jobs to find.
# Safe with this codebase's RabbitMQ broker specifically: redelivery fires
# only on an actual lost connection/nack, not a visibility-timeout heuristic
# (the latter is the Redis-as-broker gotcha this doesn't have). Every task
# this enables redelivery for is already safe to run more than once:
# process_chunk via its chunk lock + its own output-existence guard,
# split_and_dispatch_chunks via deterministic chunk keys,
# merge_output via its own DONE-status guard.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET", "versio-inputs")
AWS_S3_REGION = os.environ.get("AWS_S3_REGION", "us-east-1")
AWS_S3_ENDPOINT_URL = os.environ.get(
    "AWS_S3_ENDPOINT_URL", None
)  # set to MinIO URL in dev

INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "change-me-in-prod")

# Chunk size is computed dynamically per job (utils/chunking.py) rather than
# fixed, aimed at landing near CHUNK_TARGET_COUNT chunks and clamped to
# [CHUNK_SIZE_MIN, CHUNK_SIZE_MAX]. Calibrated empirically.
CHUNK_TARGET_COUNT = int(os.environ.get("CHUNK_TARGET_COUNT", 8))
CHUNK_SIZE_MIN = int(os.environ.get("CHUNK_SIZE_MIN", 1000))
CHUNK_SIZE_MAX = int(os.environ.get("CHUNK_SIZE_MAX", 40000))
ITEM_THREAD_POOL_SIZE = int(os.environ.get("ITEM_THREAD_POOL_SIZE", 8))
IDEMPOTENCY_TTL = int(os.environ.get("IDEMPOTENCY_TTL", 86400))
# Safety-net TTL on the reservation placeholder — only matters if the
# reserving process crashes before resolving or releasing it.
IDEMPOTENCY_RESERVATION_TTL = int(os.environ.get("IDEMPOTENCY_RESERVATION_TTL", 60))
IDEMPOTENCY_WAIT_TIMEOUT = float(os.environ.get("IDEMPOTENCY_WAIT_TIMEOUT", 30))
IDEMPOTENCY_WAIT_POLL_INTERVAL = float(
    os.environ.get("IDEMPOTENCY_WAIT_POLL_INTERVAL", 0.2)
)
CHUNK_LOCK_TTL = int(os.environ.get("CHUNK_LOCK_TTL", 600))

# retry_stuck_jobs management command (run periodically via crontab/Celery beat)
STUCK_PENDING_JOB_MIN_AGE_MINUTES = int(
    os.environ.get("STUCK_PENDING_JOB_MIN_AGE_MINUTES", 15)
)
# Beyond this age, a still-PENDING job is more likely a systemic outage
# (workers down) than a one-off dispatch failure — skip and warn instead of
# auto-retrying, so the command doesn't quietly requeue into a broken worker
# pool forever.
STUCK_PENDING_JOB_MAX_AGE_MINUTES = int(
    os.environ.get("STUCK_PENDING_JOB_MAX_AGE_MINUTES", 1440)
)
# A PROCESSING job that hasn't finished in this long is more likely stuck
# (a chunk task silently lost) than genuinely still working.
# Higher than the chunk lock TTL (CHUNK_LOCK_TTL, 10min) and each chunk's own
# Celery retry budget combined, so this never fires on a job that's merely
# slow.
STUCK_PROCESSING_JOB_MIN_AGE_MINUTES = int(
    os.environ.get("STUCK_PROCESSING_JOB_MIN_AGE_MINUTES", 60)
)
# Beyond this age, treat it the same as a PENDING job past its own max age —
# stop auto-retrying and mark FAILED so it's visibly not silently retried
# forever, rather than left indistinguishable from a healthy job.
STUCK_PROCESSING_JOB_MAX_AGE_MINUTES = int(
    os.environ.get("STUCK_PROCESSING_JOB_MAX_AGE_MINUTES", 1440)
)
# A PARTIAL job whose oldest failed_chunks entry is this old hasn't been
# retried by anyone — automatically retry only its *retryable* entries;
# entries marked permanent are skipped outright, not retried and
# not escalated, since nothing about waiting longer makes a config bug
# resolve itself.
STUCK_PARTIAL_JOB_MIN_AGE_MINUTES = int(
    os.environ.get("STUCK_PARTIAL_JOB_MIN_AGE_MINUTES", 30)
)
STUCK_PARTIAL_JOB_MAX_AGE_MINUTES = int(
    os.environ.get("STUCK_PARTIAL_JOB_MAX_AGE_MINUTES", 1440)
)
TEMPLATE_CACHE_TTL = int(os.environ.get("TEMPLATE_CACHE_TTL", 300))
JOB_REPORT_CACHE_TTL = int(os.environ.get("JOB_REPORT_CACHE_TTL", 5))
JOB_REPORT_DONE_CACHE_TTL = int(os.environ.get("JOB_REPORT_DONE_CACHE_TTL", 3600))

# Source path resolution
SOURCE_PATH_SCAN_LIMIT = int(os.environ.get("SOURCE_PATH_SCAN_LIMIT", 1000))
DEFAULT_SOURCE_PATH = os.environ.get("DEFAULT_SOURCE_PATH", "data.items.item")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serves /static/ directly from this gunicorn process -- no nginx
# or CDN in front of any of the three services. WHITENOISE_USE_FINDERS lets
# it serve straight from each app's own static/ (including django.contrib.admin's
# built-in CSS/JS) in dev, with no collectstatic step needed; STORAGES switches
# to the collected, hashed, compressed STATIC_ROOT once DEBUG is off.
WHITENOISE_USE_FINDERS = DEBUG
STORAGES = {
    # Left at Django's own default -- nothing in this codebase writes through
    # Django's file storage framework (uploads are streamed straight to S3
    # via StorageInterface/S3Client, never a model FileField), but STORAGES
    # replaces the whole dict rather than merging, so "default" is spelled
    # out explicitly instead of silently dropped.
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
