"""The platform owner's console API.

Everything here runs in the control plane and spans customers. None of it
touches a tenant database, which is why the SaaS console can report across
thousands of organizations without opening thousands of connections -- the
facility registry and the usage counters are already here.
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsPlatformStaff
from apps.entitlements.resolver import resolve_entitlements
from apps.entitlements.services import facility_quota_summary
from apps.organization.serializers import (
    ChangeRequestDecisionInputSerializer,
    FacilityChangeRequestSerializer,
)
from apps.platform_api.serializers import (
    OrganizationSerializer,
    PlanSerializer,
    SubscriptionSerializer,
)
from apps.provisioning.models import (
    OPEN_STATUSES,
    ApprovalLevel,
    ChangeRequestStatus,
    FacilityChangeRequest,
)
from apps.provisioning.services import decide
from apps.subscriptions.revenue import (
    entitled_but_unbilled,
    largest_customers,
    platform_mrr,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.tenancy.models import (
    FacilityRegistryEntry,
    FacilityRegistryStatus,
    Organization,
    OrganizationStatus,
    TenantDatabase,
    TenantDatabaseStatus,
)
from apps.catalog.models import Plan


class PlatformDashboardView(APIView):
    """Headline numbers for the platform owner.

    Deliberately a single endpoint returning one coherent picture. A
    dashboard assembled from a dozen calls shows a dozen different moments
    in time, which is how "our numbers don't tie up" starts.
    """

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        org_counts = dict(
            Organization.objects.values_list("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )

        facility_counts = dict(
            FacilityRegistryEntry.objects.filter(
                status__in=[
                    FacilityRegistryStatus.ACTIVE,
                    FacilityRegistryStatus.PENDING,
                ]
            )
            .values_list("facility_type")
            .annotate(count=Count("id"))
            .values_list("facility_type", "count")
        )

        # Real MRR, not a sum of contracted prices. See
        # apps/subscriptions/revenue.py: intervals are normalised, add-ons are
        # included and discounts are applied, none of which a plain Sum does.
        revenue = platform_mrr()

        pending_requests = FacilityChangeRequest.objects.filter(
            status__in=list(OPEN_STATUSES)
        )

        return Response(
            {
                "generated_at": timezone.now().isoformat(),
                "organizations": {
                    "total": Organization.objects.count(),
                    "active": org_counts.get(OrganizationStatus.ACTIVE, 0),
                    "trial": org_counts.get(OrganizationStatus.TRIAL, 0),
                    "past_due": org_counts.get(OrganizationStatus.PAST_DUE, 0),
                    "suspended": org_counts.get(OrganizationStatus.SUSPENDED, 0),
                    "cancelled": org_counts.get(OrganizationStatus.CANCELLED, 0),
                    "pending_provisioning": org_counts.get(
                        OrganizationStatus.PENDING, 0
                    ),
                },
                "facilities": {
                    "total": sum(facility_counts.values()),
                    "by_type": facility_counts,
                },
                "revenue": revenue,
                "concentration": largest_customers(limit=5),
                "entitled_but_unbilled": entitled_but_unbilled(),
                "change_requests": {
                    "open": pending_requests.count(),
                    "awaiting_platform": pending_requests.filter(
                        status=ChangeRequestStatus.PLATFORM_REVIEW
                    ).count(),
                    "awaiting_organization": pending_requests.filter(
                        status=ChangeRequestStatus.ORG_REVIEW
                    ).count(),
                },
                "infrastructure": {
                    "tenant_databases": TenantDatabase.objects.count(),
                    "ready": TenantDatabase.objects.filter(
                        status=TenantDatabaseStatus.READY
                    ).count(),
                    "failed": TenantDatabase.objects.filter(
                        status=TenantDatabaseStatus.FAILED
                    ).count(),
                },
            }
        )


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """Customers, as the platform sees them."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsPlatformStaff]
    lookup_field = "slug"
    filterset_fields = ["status", "business_type", "province"]
    search_fields = ["display_name", "legal_name", "slug", "pan_number"]
    ordering_fields = ["display_name", "created_at", "status"]

    def get_queryset(self):
        return (
            Organization.objects.all()
            .select_related("database")
            .annotate(
                # `distinct=True` on both, because two Count aggregations
                # across two different reverse relations multiply each other.
                # Without it a customer with 4 facilities and 6 members
                # reported 24 facilities -- 4 x 6 -- which is the number the
                # platform owner saw on the customer list.
                facility_count=Count(
                    "facility_registry",
                    filter=Q(
                        facility_registry__status__in=[
                            FacilityRegistryStatus.ACTIVE,
                            FacilityRegistryStatus.PENDING,
                        ]
                    ),
                    distinct=True,
                ),
                member_count=Count("memberships", distinct=True),
            )
            .order_by("display_name")
        )

    @action(detail=True, methods=["get"], url_path="entitlements")
    def entitlements(self, request, slug=None):
        """The customer's resolved entitlements, with provenance.

        Support's first question when a customer says "it won't let me open
        a branch" is *why*, and the answer is here: which plan, which
        add-ons, which grants, which overrides produced the number.
        """
        organization = self.get_object()
        resolved = resolve_entitlements(organization)
        return Response(
            {
                "entitlements": resolved.as_dict(),
                "facility_capacity": facility_quota_summary(
                    organization, entitlements=resolved
                ),
            }
        )

    @action(detail=True, methods=["get"], url_path="facilities")
    def facilities(self, request, slug=None):
        """The customer's estate, read from the registry, not their database."""
        organization = self.get_object()
        entries = FacilityRegistryEntry.objects.filter(
            organization=organization
        ).order_by("facility_type", "name")
        return Response(
            [
                {
                    "facility_uuid": str(entry.facility_uuid),
                    "code": entry.code,
                    "name": entry.name,
                    "facility_type": entry.facility_type,
                    "status": entry.status,
                    "district": entry.district,
                    "opened_at": entry.opened_at,
                    "closed_at": entry.closed_at,
                    "reopened_count": entry.reopened_count,
                    "counts_towards_quota": entry.counts_towards_quota,
                }
                for entry in entries
            ]
        )


class PlatformChangeRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """The platform's approval queue, across every customer."""

    serializer_class = FacilityChangeRequestSerializer
    permission_classes = [IsPlatformStaff]
    lookup_field = "reference"
    filterset_fields = ["status", "request_type", "facility_type", "organization__slug"]
    ordering_fields = ["created_at", "submitted_at"]

    def get_queryset(self):
        return (
            FacilityChangeRequest.objects.all()
            .select_related("organization")
            .prefetch_related("decisions")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["get"], url_path="queue")
    def queue(self, request):
        """Requests waiting on the platform, oldest first.

        Ordered by age rather than by revenue on purpose: a queue sorted by
        customer size teaches small customers that requests go unanswered.
        """
        pending = self.get_queryset().filter(
            status=ChangeRequestStatus.PLATFORM_REVIEW
        ).order_by("submitted_at")
        page = self.paginate_queryset(pending)
        serializer = self.get_serializer(page or pending, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        """Decide a request at platform level.

        The approver can attach the capacity that makes the request fit --
        either sold as an add-on, or granted as temporary headroom -- in the
        same action. Approving without doing one or the other leaves the
        request to fail its re-check at execution, which is the correct
        outcome: approval does not conjure entitlement.
        """
        change_request = self.get_object()
        serializer = ChangeRequestDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = decide(
            change_request,
            actor=request.user,
            decision=data["decision"],
            level=ApprovalLevel.PLATFORM,
            comment=data["comment"],
            conditions=data.get("conditions"),
            granted_addon_code=data.get("granted_addon_code", ""),
            granted_addon_quantity=data.get("granted_addon_quantity", 0),
            granted_addons=data.get("granted_addons") or [],
            granted_entitlement_delta=data.get("granted_entitlement_delta"),
        )
        # Re-fetch before serializing. `change_request` came from a queryset
        # with prefetch_related("decisions"), and that cache was populated
        # before this decision existed -- serializing it directly would hand
        # the client a response missing the very decision they just made.
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(FacilityChangeRequestSerializer(updated).data)


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PlanSerializer
    permission_classes = [IsPlatformStaff]
    lookup_field = "code"

    def get_queryset(self):
        return (
            Plan.objects.filter(is_active=True)
            .prefetch_related("limits", "plan_modules__module", "plan_features__feature")
            .order_by("display_order")
        )


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsPlatformStaff]
    lookup_field = "uuid"
    filterset_fields = ["status", "organization__slug"]

    def get_queryset(self):
        return (
            Subscription.objects.all()
            .select_related("organization", "plan")
            .prefetch_related("addons__addon")
            .order_by("-created_at")
        )
