"""Scheduled billing work."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="billing.reconcile_online_payments")
def reconcile_online_payments() -> dict:
    """Ask eSewa and Khalti about every attempt still open, in every tenant.

    For the payer who paid and closed the tab before being sent back: without
    this their money sits with the provider and the bill still says unpaid
    until they ring the hospital. Every ten minutes, attempts older than two
    minutes, for up to a week; after two hours unfinished, one is given up.
    """
    from apps.billing.online import reconcile
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Organization, OrganizationStatus

    summary = {}
    running = [OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL, OrganizationStatus.PAST_DUE]
    for organization in Organization.objects.filter(status__in=running):
        try:
            with tenant_context(context_for_organization(organization)):
                counts = reconcile()
        except Exception:  # noqa: BLE001 -- one tenant's failure must not stop the rest
            logger.exception("Reconciling online payments failed for %s", organization.slug)
            continue
        if counts["checked"]:
            summary[organization.slug] = counts
    return summary
