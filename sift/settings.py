"""Django settings for Sift.

Every value comes from the environment (FR-SEC-1). A local ``.env`` file is
loaded first for native development on the host; variables already present in
the process environment (compose, CI) always win. Secrets have no default, so
the process refuses to start without them.
"""

from pathlib import Path

from sift.common.config import ImportSettings
from sift.common.env import env_bool, env_int, env_list, env_str, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent

load_env_file(BASE_DIR / ".env")

# --- Core -------------------------------------------------------------------

SECRET_KEY = env_str("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "sift.common",
    "sift.accounts",
    "sift.catalog",
    "sift.imports",
    "sift.storage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sift.urls"
ASGI_APPLICATION = "sift.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env_str("DB_HOST", "localhost"),
        "PORT": env_int("DB_PORT", 5432),
        "NAME": env_str("DB_NAME", "sift"),
        "USER": env_str("DB_USER", "sift"),
        "PASSWORD": env_str("DB_PASSWORD"),
        "CONN_MAX_AGE": 0,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization and static files ---------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Redis and Celery (D1, ADR-007) -----------------------------------------

REDIS_URL = env_str("REDIS_URL", "redis://localhost:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_DEFAULT_QUEUE = "imports"
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
# A message is acknowledged only after the task finishes, and a task whose
# worker dies is returned to the queue; the run_token claim makes redelivery safe.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# --- Object storage ---------------------------------------------------------

S3_ENDPOINT = env_str("S3_ENDPOINT", "http://localhost:9000")
S3_PUBLIC_ENDPOINT = env_str("S3_PUBLIC_ENDPOINT", S3_ENDPOINT)
S3_ACCESS_KEY = env_str("S3_ACCESS_KEY")
S3_SECRET_KEY = env_str("S3_SECRET_KEY")
S3_BUCKET = env_str("S3_BUCKET", "sift")
S3_REGION = env_str("S3_REGION", "us-east-1")

# --- Imports ----------------------------------------------------------------

IMPORT_SETTINGS = ImportSettings.from_env()

# --- Logging (structlog JSON arrives in F1) ---------------------------------

LOG_LEVEL = env_str("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
