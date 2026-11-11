"""Celery application shared by the worker and beat processes.

Configuration lives in Django settings under the ``CELERY_`` prefix.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sift.settings")

app = Celery("sift")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
