from django.apps import AppConfig


class WorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workspace"
    label = "workspace"
    verbose_name = "My workspace"

    def ready(self):
        from apps.workspace.sources import load

        load()
