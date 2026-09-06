from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notification centre"

    def ready(self):
        # Registered here rather than at import time: the reminders reach into
        # seven model modules, and doing that while the app registry is still
        # loading makes load order load-bearing.
        from apps.notifications.reminders import load

        load()
