"""Sending notifications beyond the screen, off the request path.

The event has already happened by the time anybody is told about it, so an
email server that is slow or an SMS gateway that is down must not slow a ward
round or fail the transaction that recorded the observation. The task retries
with a backoff and gives up loudly; `deliver` itself is idempotent, so a retry
after a partial success does not send anything twice.
"""

import logging

from celery import shared_task

logger = logging.getLogger("nirova.notifications")


@shared_task(
    name="notifications.deliver",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def deliver_notification(organization_slug: str, notification_uuid: str,
                         force: bool = False) -> dict:
    """Deliver one notification, in one tenant's database."""
    from apps.notifications.delivery import deliver
    from apps.notifications.models import Notification
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Organization

    organization = Organization.objects.filter(slug=organization_slug).first()
    if organization is None:
        logger.error("cannot deliver %s: no organization %s",
                     notification_uuid, organization_slug)
        return {}

    with tenant_context(context_for_organization(organization)):
        notification = Notification.objects.filter(uuid=notification_uuid).first()
        if notification is None:
            # Raised and rolled back, or expired. Nothing to do and nothing
            # wrong: the transaction that would have kept it did not commit.
            return {}
        return deliver(notification, force=force)


@shared_task(name="notifications.remind_patients")
def remind_patients() -> dict:
    """The evening-before appointment reminder, for every live tenant.

    A clinic loses a fifth of its outpatient slots to people who forgot. This
    runs once a day; `send_to_patient` is keyed on the appointment reference,
    so running it twice — a retry, a second scheduler — still tells somebody
    once.
    """
    from apps.notifications.patient_outreach import remind_tomorrows_appointments
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Organization, OrganizationStatus

    running = [OrganizationStatus.ACTIVE, OrganizationStatus.TRIAL,
               OrganizationStatus.PAST_DUE]
    summary = {}
    for organization in Organization.objects.filter(status__in=running):
        try:
            with tenant_context(context_for_organization(organization)):
                counts = remind_tomorrows_appointments()
        except Exception:  # noqa: BLE001 — one tenant must not stop the rest
            logger.exception("patient reminders failed for %s", organization.slug)
            continue
        try:
            with tenant_context(context_for_organization(organization)):
                # The same sweep, for the loop nobody was closing: tomorrow's
                # follow-ups, and the ones that lapsed in the last week.
                from apps.scheduling.followups import recall_due

                recalls = recall_due()
        except Exception:  # noqa: BLE001 -- one tenant must not stop the rest
            logger.exception("follow-up recalls failed for %s", organization.slug)
            recalls = {}
        if any(counts.values()) or any(recalls.values()):
            summary[organization.slug] = {**counts, **{f"recall_{k}": v for k, v in recalls.items()}}
    return summary
