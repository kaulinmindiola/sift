from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "sift.common"
    label = "common"
    default_auto_field = "django.db.models.BigAutoField"
