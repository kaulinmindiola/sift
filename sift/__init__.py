"""Sift: large CSV imports into a multi-tenant catalog."""

from sift.celery import app as celery_app

__all__ = ("celery_app",)
