from django.apps import AppConfig


class EntitlementsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.entitlements"
    label = "entitlements"

    def ready(self):
        """Anything that changes what a customer is entitled to forgets the gate.

        The module gate remembers an organization's modules for half a minute
        so it does not re-resolve on every request (the query-budget guard
        caught that immediately). A cache nobody invalidates is worse than the
        queries: a support agent who grants a module, or a sale that moves a
        customer up a plan, would watch the system disagree with itself for
        thirty seconds — and a plan edit that *removes* a module would keep
        serving it. So every write that can change the answer clears it here,
        rather than at the call sites, where the next one added would forget.
        """
        from django.db.models.signals import post_delete, post_save

        from apps.catalog.models import PlanFeature, PlanLimit, PlanModule
        from apps.entitlements.gate import forget
        from apps.entitlements.models import EntitlementGrant, EntitlementOverride
        from apps.subscriptions.models import Subscription, SubscriptionAddOn

        def forget_one(sender, instance, **kwargs):
            organization = getattr(instance, "organization", None)
            slug = getattr(organization, "slug", "")
            forget(slug)

        def forget_all(sender, instance, **kwargs):
            # A plan is shared: changing it changes everybody on it.
            forget()

        for model in (EntitlementGrant, EntitlementOverride, Subscription):
            post_save.connect(forget_one, sender=model, weak=False)
            post_delete.connect(forget_one, sender=model, weak=False)

        for model in (PlanModule, PlanFeature, PlanLimit, SubscriptionAddOn):
            post_save.connect(forget_all, sender=model, weak=False)
            post_delete.connect(forget_all, sender=model, weak=False)
