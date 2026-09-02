"""Build a working demo tenant, exercising the real code paths.

Nothing here writes a facility directly. Every facility is opened by raising
a change request and approving it, because that is the only sanctioned path
-- and a seed script that bypassed it would be seeding a state the
application cannot itself produce.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Plan
from apps.entitlements.services import facility_quota_summary
from apps.identity.models import Membership, MembershipStatus, User
from apps.provisioning.models import (
    ApprovalLevel,
    ChangeRequestPolicy,
    ChangeRequestType,
    DecisionType,
)
from apps.provisioning.services import decide, submit_request
from apps.rbac.services import assign_role
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

DEMO_PASSWORD = "NirovaDemo!2026"


class Command(BaseCommand):
    help = "Create a demo organization with a provisioned database and facilities."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")
        parser.add_argument("--plan", default="professional")

    def handle(self, *args, **options):
        slug = options["slug"]
        plan_code = options["plan"]

        platform_user = self._platform_staff()
        organization = self._organization(slug)
        self._subscription(organization, plan_code)
        self._policy(organization)

        self.stdout.write("Provisioning tenant database...")
        provision_organization(organization, verbosity=0)

        owner = self._owner(organization, slug)
        requester = self._requester(organization, slug)

        counter_staff = self._counter_staff(organization, slug)
        self._assign_roles(organization, owner, requester, counter_staff)
        self._open_facilities(organization, requester, owner, platform_user)
        self._assign_counter_roles(organization, counter_staff)
        self._report(organization)

    # -- control plane ---------------------------------------------------

    def _platform_staff(self):
        user, created = User.objects.get_or_create(
            email="platform@nirova.test",
            defaults={
                "full_name": "Nirova Platform Operations",
                "is_platform_staff": True,
                "is_staff": True,
                "is_superuser": True,
                "support_access_enabled": True,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(f"  platform staff: {user.email}")
        return user

    @transaction.atomic
    def _organization(self, slug):
        organization, created = Organization.objects.get_or_create(
            slug=slug,
            defaults={
                "legal_name": "Manakamana Health Services Pvt. Ltd.",
                "display_name": "Manakamana Health",
                "business_type": BusinessType.POLYCLINIC,
                "status": OrganizationStatus.PENDING,
                "pan_number": "301234567",
                "vat_number": "601234567",
                "primary_email": "admin@manakamana.test",
                "primary_phone": "+977-1-4567890",
                "province": "Bagmati",
                "district": "Kathmandu",
                "municipality": "Kathmandu Metropolitan City",
                "ward": "10",
                "street_address": "Kamalpokhari",
                "primary_color": "#0f766e",
            },
        )
        self.stdout.write(
            f"  organization: {organization.slug} "
            f"({'created' if created else 'existing'})"
        )
        return organization

    def _subscription(self, organization, plan_code):
        plan = Plan.objects.filter(code=plan_code).first()
        if plan is None:
            self.stdout.write(
                self.style.ERROR(
                    f"No plan '{plan_code}'. Run `manage.py seed_catalog` first."
                )
            )
            raise SystemExit(1)

        subscription, created = Subscription.objects.get_or_create(
            organization=organization,
            plan=plan,
            defaults={
                "status": SubscriptionStatus.ACTIVE,
                "contracted_price": plan.base_price,
                "currency": plan.currency,
                "billing_interval": plan.billing_interval,
                "started_at": timezone.now(),
                "current_period_start": timezone.now(),
                "current_period_end": timezone.now() + timedelta(days=30),
            },
        )
        if created:
            SubscriptionEvent.objects.create(
                subscription=subscription,
                event_type=SubscriptionEventType.ACTIVATED,
                to_plan=plan,
                mrr_before=Decimal("0"),
                mrr_after=plan.base_price,
                reason="Demo seed",
            )
        self.stdout.write(f"  subscription: {plan.code} ({subscription.status})")
        return subscription

    def _policy(self, organization):
        """Give this customer a policy that shows both routes in action.

        Self-service is off, so even an in-quota request goes to their own
        administrator -- which is how most customers should start.
        """
        ChangeRequestPolicy.objects.update_or_create(
            organization=organization,
            defaults={
                "allow_self_service_within_quota": False,
                "require_org_approval_for_open": True,
                "require_org_approval_for_close": True,
                "require_platform_approval_for_close": False,
                "churn_window_days": 90,
                "churn_threshold": 2,
                "enforce_segregation_of_duties": True,
                "require_justification": True,
                "min_justification_length": 40,
            },
        )
        ChangeRequestPolicy.objects.get_or_create(
            organization=None,
            defaults={"allow_self_service_within_quota": True},
        )

    def _user(self, email, full_name, organization, is_owner, slug):
        user, created = User.objects.get_or_create(
            email=email, defaults={"full_name": full_name}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()

        Membership.objects.update_or_create(
            user=user,
            organization=organization,
            defaults={
                "status": MembershipStatus.ACTIVE,
                "is_default": True,
                "is_organization_owner": is_owner,
                "joined_at": timezone.now(),
            },
        )
        self.stdout.write(f"  user: {email}")
        return user

    def _owner(self, organization, slug):
        return self._user(
            f"owner@{slug}.test", "Sunita Shrestha", organization, True, slug
        )

    def _requester(self, organization, slug):
        return self._user(
            f"manager@{slug}.test", "Bikash Thapa", organization, False, slug
        )

    def _counter_staff(self, organization, slug):
        """The two people a retail counter needs, and why they are two.

        Every control at a till is a maker-checker pair: sell/void, request a
        return/approve it, count the drawer/sign the count off. One user
        holding both halves makes all three checks vacuous, so the demo tenant
        ships with the pair separated.
        """
        cashier = self._user(
            f"counter@{slug}.test", "Rita Gurung", organization, False, slug
        )
        pharmacy_manager = self._user(
            f"pharmacy@{slug}.test", "Anil Maharjan", organization, False, slug
        )
        return cashier, pharmacy_manager

    # -- tenant ----------------------------------------------------------

    def _assign_roles(self, organization, owner, requester, counter_staff):
        context = context_for_organization(organization)
        with tenant_context(context):
            assign_role(owner, "organization_admin", scope="organization",
                        reason="Demo seed")
            # Estate planning is organization-wide; a facility-scoped role
            # could not raise the request for the first facility.
            assign_role(requester, "operations_manager", scope="organization",
                        reason="Demo seed")
        self.stdout.write("  roles assigned")

    def _assign_counter_roles(self, organization, counter_staff):
        """Bind the counter roles to an actual facility.

        Must run *after* the facilities are open. A facility-scoped assignment
        with no facility on it resolves to no facility at all -- the scope
        filter is doing exactly what it should, and the user sees an empty
        estate. It looks like a permissions bug and is really an ordering one.
        """
        cashier, pharmacy_manager = counter_staff
        with tenant_context(context_for_organization(organization)):
            from apps.organization.models import Facility as TenantFacility

            facility = (
                TenantFacility.objects.filter(facility_type="pharmacy").first()
                or TenantFacility.objects.filter(facility_type="clinic").first()
            )
            if facility is None:
                self.stdout.write("  no facility yet — counter roles skipped")
                return
            # Facility scope for both: a counter is a place, and nothing about
            # either job needs sight of another branch's takings.
            assign_role(cashier, "pharmacy_counter", scope="facility",
                        facility=facility, reason="Demo seed")
            assign_role(pharmacy_manager, "pharmacy_manager", scope="facility",
                        facility=facility, reason="Demo seed")
        self.stdout.write(f"  counter roles bound to {facility.code}")

    def _open_facilities(self, organization, requester, approver, platform_user):
        """Open facilities through the request workflow, including one refusal."""
        wanted = [
            ("clinic", "MKC-KTM", "Manakamana Clinic, Kathmandu"),
            ("pharmacy", "MKP-KTM", "Manakamana Pharmacy, Kathmandu"),
            ("laboratory", "MKL-KTM", "Manakamana Diagnostics, Kathmandu"),
            # Professional does not include the hospital module, so this one
            # is expected to escalate to the platform rather than proceed.
            ("hospital", "MKH-BKT", "Manakamana Hospital, Bhaktapur"),
        ]

        # Re-running the seed must be safe. The facility service correctly
        # refuses a duplicate code -- that is the uniqueness rule doing its
        # job -- so the seed skips what already exists rather than the rule
        # being relaxed to accommodate a demo script.
        from apps.organization.models import Facility as TenantFacility

        with tenant_context(context_for_organization(organization)):
            existing = set(
                TenantFacility.objects.values_list("code", flat=True)
            )

        for facility_type, code, name in wanted:
            if code in existing:
                self.stdout.write(f"  {code} already open — skipped")
                continue
            request = submit_request(
                organization=organization,
                request_type=ChangeRequestType.OPEN_FACILITY,
                facility_type=facility_type,
                requested_by=requester,
                payload={
                    "code": code,
                    "name": name,
                    "province": "Bagmati",
                    "district": "Kathmandu",
                    "municipality": "Kathmandu Metropolitan City",
                    "phone": "+977-1-4567890",
                },
                justification=(
                    f"Opening {name} to serve patients in the catchment area; "
                    "premises secured and staffing plan approved by the board."
                ),
            )
            self.stdout.write(
                f"  {request.reference}: {facility_type} -> {request.status} "
                f"(level={request.approval_level})"
            )

            if request.status == "org_review":
                decided = decide(
                    request,
                    actor=approver,
                    decision=DecisionType.APPROVE,
                    level=ApprovalLevel.ORGANIZATION,
                    comment="Approved by the board on 2026-08-28.",
                )
                self.stdout.write(
                    self.style.SUCCESS(f"    approved -> {decided.status}")
                )
            elif request.status == "platform_review":
                for reason in request.escalation_reasons:
                    self.stdout.write(
                        self.style.WARNING(f"    escalated: {reason['message']}")
                    )

    def _report(self, organization):
        summary = facility_quota_summary(organization)
        overall = summary.pop("_overall")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Facility capacity"))
        self.stdout.write(
            f"  overall: {overall['used']} / "
            f"{'unlimited' if overall['unlimited'] else overall['limit']}"
        )
        for facility_type, row in sorted(summary.items()):
            if not row["module_entitled"] and not row["used"]:
                continue
            limit = "unlimited" if row["unlimited"] else row["limit"]
            self.stdout.write(
                f"  {facility_type:<18} {row['used']} / {limit}"
                + ("" if row["module_entitled"] else "   (module not entitled)")
            )
        self.stdout.write("")
        self.stdout.write(f"Sign in with any demo account, password: {DEMO_PASSWORD}")
