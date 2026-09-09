"""Taking on a new customer.

Everything needed to provision a tenant has existed for a long time and none
of it was reachable. `provision_organization` creates the database, runs the
migrations and seeds the roles, and is idempotent and well tested — but the
only callers were `manage.py provision_tenant` and `seed_demo`. The platform
API could *read* organizations and not create one:
`OrganizationViewSet(viewsets.ReadOnlyModelViewSet)`.

So onboarding a customer required an engineer with shell access on the
production host. For a product meant to serve practices from a single room to
a chain, that caps the business at whatever one developer can hand-run, and it
puts a person with a database shell in the middle of every sale.

**This is `seed_demo` with the demonstration taken out.** That command has
been assembling a working customer end to end since the beginning — an
organization, a subscription, a change-request policy, a provisioned database,
an owner with the administrator role. It was the only thing that knew how, and
what it knew was buried in a management command nobody could call over HTTP.

**Ordering, and what survives a failure halfway.** Provisioning creates a
physical database and runs every migration against it. It takes tens of
seconds and it can fail. So the control-plane rows are written first and the
organization is left `pending` until the database is ready:

1. Organization, subscription and policy — fast, transactional, and harmless
   if provisioning never happens. An organization stuck at `pending` with no
   database is a visible, retryable state, and `provision_organization` is
   safe to run again.
2. The database. If this fails, `TenantDatabase.status` is `failed` with the
   error on it, which is the state the platform console already renders.
3. The owner's login, last, because `assign_role` writes to the tenant and
   there is no tenant to write to until step 2 has finished.

**Synchronous, and that is a decision rather than an oversight.** It runs
inside nginx's 110-second read timeout and gunicorn's 120-second worker
timeout, so it works today with no new moving parts. The state machine for
doing it in the background already exists — `Organization.status` and
`TenantDatabase.status` — so moving this to the Celery worker (which is
running and has no tasks at all) needs no change to the API's shape. Noted
here so the next person does not have to rediscover that it was considered.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Plan
from apps.common.exceptions import DomainError
from apps.identity.models import Membership, MembershipStatus, User
from apps.provisioning.models import ChangeRequestPolicy
from apps.subscriptions.models import (
    Subscription,
    SubscriptionEvent,
    SubscriptionEventType,
    SubscriptionStatus,
)
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import BusinessType, Organization, OrganizationStatus
from apps.tenancy.provisioning import provision_organization


class OnboardingError(DomainError):
    """Something about taking on this customer is not allowed."""

    default_code = "onboarding_error"


#: How long a new customer gets before the subscription must be paid for.
#: Zero means no trial: they are `active` from the first day.
DEFAULT_TRIAL_DAYS = 30


def onboard_organization(
    *,
    slug: str,
    legal_name: str,
    display_name: str,
    primary_email: str,
    plan_code: str,
    owner_email: str,
    owner_name: str,
    business_type: str = BusinessType.CLINIC,
    trial_days: int = DEFAULT_TRIAL_DAYS,
    actor=None,
    province: str = "",
    district: str = "",
    phone: str = "",
) -> dict:
    """Create a customer, give them a database, and give one person the keys.

    Returns a summary rather than a model, because the interesting answer
    spans three of them: the organization, whether its database is ready, and
    who can now sign in.

    Idempotent by slug. Re-running against an existing organization finishes
    whatever did not finish last time rather than refusing — which is what you
    want when the first attempt died halfway through a migration.
    """
    slug = (slug or "").strip().lower()
    if not slug:
        raise OnboardingError("A customer needs a slug.")

    owner_email = (owner_email or "").strip().lower()
    if not owner_email:
        raise OnboardingError("A customer needs somebody who can administer it.")

    plan = Plan.objects.filter(code=plan_code, is_active=True).first()
    if plan is None:
        raise OnboardingError(
            f"No active plan '{plan_code}'.",
            detail={"available": sorted(
                Plan.objects.filter(is_active=True).values_list("code", flat=True)
            )},
        )

    # ------------------------------------------------------------------
    # 1. The control plane
    # ------------------------------------------------------------------
    with transaction.atomic():
        organization, created = Organization.objects.get_or_create(
            slug=slug,
            defaults={
                "legal_name": legal_name,
                "display_name": display_name,
                "primary_email": primary_email,
                "business_type": business_type,
                "status": OrganizationStatus.PENDING,
                "province": province,
                "district": district,
                "primary_phone": phone,
                "trial_ends_at": (
                    timezone.now() + timedelta(days=trial_days)
                    if trial_days
                    else None
                ),
            },
        )

        subscription, subscription_created = Subscription.objects.get_or_create(
            organization=organization,
            plan=plan,
            defaults={
                "status": (
                    SubscriptionStatus.TRIALING
                    if trial_days
                    else SubscriptionStatus.ACTIVE
                ),
                "contracted_price": plan.base_price,
                "currency": plan.currency,
                "billing_interval": plan.billing_interval,
                "started_at": timezone.now(),
                "current_period_start": timezone.now(),
                "current_period_end": timezone.now() + timedelta(days=30),
            },
        )
        if subscription_created:
            SubscriptionEvent.objects.create(
                subscription=subscription,
                event_type=SubscriptionEventType.ACTIVATED,
                to_plan=plan,
                mrr_before=Decimal("0"),
                mrr_after=plan.base_price,
                reason=f"Onboarded by {getattr(actor, 'email', 'platform')}",
            )

        # Every customer starts with their own administrator approving facility
        # changes, and self-service off. That is the conservative position and
        # the one most customers should begin from; they can loosen it.
        ChangeRequestPolicy.objects.get_or_create(
            organization=organization,
            defaults={
                "allow_self_service_within_quota": False,
                "require_org_approval_for_open": True,
            },
        )

    # ------------------------------------------------------------------
    # 2. The database
    # ------------------------------------------------------------------
    # Outside the transaction above, deliberately: creating a database cannot
    # be rolled back, and holding a control-plane transaction open across tens
    # of seconds of migrations would block anything else touching these tables.
    tenant_db = provision_organization(organization, verbosity=0)

    # ------------------------------------------------------------------
    # 3. Somebody who can administer it
    # ------------------------------------------------------------------
    owner, owner_created = _owner_login(
        organization, owner_email, owner_name, actor=actor,
    )

    organization.refresh_from_db()
    return {
        "organization": organization,
        "created": created,
        "database_status": tenant_db.status,
        "owner": owner,
        "owner_created": owner_created,
        "plan": plan.code,
    }


def _owner_login(organization, email, full_name, actor=None):
    """The first administrator, with no password.

    The same rule as `invite_user`: an account exists and cannot be used until
    its owner sets a password. A platform operator typing a password for a
    customer's administrator would know a credential that is not theirs.

    `is_organization_owner` is what exempts this person from the privilege
    escalation checks in `assign_role` — there is nobody above them to check
    against, which is exactly why the role is granted here and not through the
    staff API.
    """
    from apps.rbac.services import assign_role, seed_system_roles

    with transaction.atomic():
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User.objects.create_user(
                email=email, full_name=full_name or email,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])

        Membership.objects.update_or_create(
            user=user,
            organization=organization,
            defaults={
                "status": MembershipStatus.ACTIVE,
                "is_organization_owner": True,
                "is_default": not Membership.objects.filter(user=user)
                .exclude(organization=organization)
                .exists(),
                "joined_at": timezone.now(),
                "invited_by_id": getattr(actor, "uuid", None),
                "consumes_seat": True,
            },
        )

    with tenant_context(context_for_organization(organization)):
        # `provision_organization` seeds the roles, but calling it again is a
        # no-op and makes this function safe to run against a tenant that was
        # provisioned before the role catalogue last changed.
        seed_system_roles()
        assign_role(
            user,
            "organization_admin",
            scope="organization",
            assigned_by=actor,
            reason="First administrator, created at onboarding",
            # No `assigner_authorization`: the platform operator creating a
            # customer holds no role *inside* that customer, and there is
            # nobody in an empty tenant to delegate from. This is the one path
            # that legitimately bypasses the escalation guard, and it is
            # reachable only by platform staff.
        )

    return user, created
