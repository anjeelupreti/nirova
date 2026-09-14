"""Scheduled work for the organization."""

import logging

from celery import shared_task

logger = logging.getLogger("nirova.organization")


@shared_task(name="organization.snapshot_day")
def snapshot_day() -> dict:
    """Keep each live tenant's figures for today, so tomorrow can compare.

    Beds occupied and money owed are levels: the records say what is true now,
    and by tomorrow nothing says what was true tonight. This is what does.
    """
    from apps.entitlements.resolver import resolve_entitlements
    from apps.organization.today import take_snapshot
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Organization, OrganizationStatus

    running = [OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL, OrganizationStatus.PAST_DUE]
    summary = {}
    for organization in Organization.objects.filter(status__in=running):
        try:
            entitlements = resolve_entitlements(organization)
            with tenant_context(context_for_organization(organization)):
                summary[organization.slug] = take_snapshot(entitlements)
        except Exception:  # noqa: BLE001 -- one tenant must not stop the rest
            logger.exception("daily snapshot failed for %s", organization.slug)
    return summary
