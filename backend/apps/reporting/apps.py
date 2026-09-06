from django.apps import AppConfig


class ReportingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reporting"
    label = "reporting"
    verbose_name = "Reporting"

    def ready(self):
        # Registering here rather than at import time: the registry reaches
        # into a dozen service modules, and doing that while apps are still
        # loading makes the app registry order load-bearing.
        from apps.reporting.registry import load

        load()
