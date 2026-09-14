from django.apps import AppConfig


class TerminologyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.terminology"
    label = "terminology"
    verbose_name = "Clinical vocabulary"
