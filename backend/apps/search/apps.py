from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.search"
    label = "search"
    verbose_name = "Global search"

    def ready(self):
        # Same reason as the report registry: the sources reach into a dozen
        # model modules, and importing those while the app registry is still
        # loading makes load order load-bearing.
        from apps.search.sources import load

        load()
