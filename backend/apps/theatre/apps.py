from django.apps import AppConfig


class TheatreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.theatre"
    label = "theatre"
    verbose_name = "Operating theatre"
