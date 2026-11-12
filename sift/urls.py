"""Root URL configuration."""

from django.contrib import admin
from django.urls import path

from sift.common import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live", health.live, name="health-live"),
]
