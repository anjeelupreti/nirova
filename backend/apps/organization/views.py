"""The organization-facing API: facilities, capacity and change requests."""

from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.entitlements.resolver import resolve_entitlements
from apps.entitlements.services import facility_quota_summary
from apps.organization.models import Department, Facility
from apps.organization.serializers import (
    ChangeRequestDecisionInputSerializer,
    DepartmentSerializer,
    FacilityChangePreviewSerializer,
    FacilityChangeRequestCreateSerializer,
    FacilityChangeRequestSerializer,
    FacilityDetailSerializer,
    FacilitySerializer,
)
from apps.provisioning.models import (
    ApprovalLevel,
    ChangeRequestStatus,
    DecisionType,
    FacilityChangeRequest,
)
from apps.provisioning.services import decide, evaluate_request, submit_request
from apps.rbac.permissions import Scope


class DepartmentViewSet(viewsets.ModelViewSet):
    """Departments, which had no endpoint at all.

    `DepartmentSerializer` has existed since the organization app was written
    and was only ever used *nested* inside a facility, so departments could be
    read and never created: no route, no service, no management command. A new
    facility's departments could only be put there by a seed or by somebody
    with a Django shell.

    That matters more than it sounds. A department is what `apply_scope_filter`
    narrows a department-scoped grant to, what clinical work is attributed to,
    and what a ward and a position both hang off. A facility without them is a
    facility nothing can be routed inside.

    **Departments are not facilities.** A facility exists only by executing an
    approved change request, because opening one is a licensing matter. Adding
    a physiotherapy department inside a hospital that already exists is not,
    and `department.manage` -- which the catalogue has carried all along, held
    by the facility manager, the operations manager and the organization
    administrator -- is the authority for it.
    """

    serializer_class = DepartmentSerializer
    permission_classes = [
        IsAuthenticated,
        # Read at `own`: a doctor holds `department.read` at *department* scope
        # and was refused by the facility default, which is the same mismatch
        # log 219 found across eleven sidebar entries. Everybody who works in a
        # department may see the list of them; changing one is separate.
        HasPermission.of(
            "department.read", scope=Scope.OWN, write="department.manage",
        ),
    ]
    lookup_field = "uuid"
    # Matched on the facility's uuid, not its integer pk. `filterset_fields`
    # would have expected the pk -- which is a different row in every tenant
    # and is never published -- so `?facility=<uuid>` answered 400.
    filterset_class = uuid_filterset(
        Department, relations=["facility"], fields=["kind", "is_active"],
    )
    search_fields = ["code", "name"]
    ordering_fields = ["display_order", "name", "code"]

    def get_queryset(self):
        return (
            Department.objects.select_related("facility")
            .prefetch_related("units")
            .order_by("facility__name", "display_order", "name")
        )

    def perform_create(self, serializer):
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        serializer.save(updated_by_id=self.request.user.uuid)


class FacilityViewSet(viewsets.ReadOnlyModelViewSet):
    """Facilities are read-only here.

    There is no create, update or delete endpoint, and that is the point: a
    facility comes into existence only by executing an approved change
    request. Leaving a POST here would be a second, unchecked door into the
    same state.
    """

    serializer_class = FacilitySerializer
    permission_classes = [IsAuthenticated, HasPermission.of("facility.read")]
    lookup_field = "uuid"
    filterset_fields = ["facility_type", "status"]
    search_fields = ["name", "code", "district", "municipality"]
    ordering_fields = ["name", "code", "opened_on"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return FacilityDetailSerializer
        return FacilitySerializer

    def get_queryset(self):
        queryset = (
            Facility.objects.all()
            .annotate(department_count=Count("departments"))
            .order_by("name")
        )

        # Scope narrows the list rather than refusing it: a department-scoped
        # user sees their own facility, not an error page.
        authorization = get_authorization(self.request)
        if authorization is not None:
            allowed = authorization.accessible_facility_ids("facility.read")
            if allowed is not None:
                queryset = queryset.filter(id__in=allowed)
        return queryset

    @action(
        detail=False, methods=["get"], url_path="capacity",
        permission_classes=[
            IsAuthenticated,
            HasPermission.of("subscription.read", scope=Scope.ORGANIZATION),
        ],
    )
    def capacity(self, request):
        """Per-type facility capacity: what is used, what is left, and why.

        Rendered before the user starts a request, so limits are visible in
        advance rather than discovered on submission.

        **`subscription.read`, not the viewset's `facility.read`.** This is
        commercial information -- what the hospital's plan allows and how much
        of it is spent -- and it inherited a permission every clinician holds
        for the entirely different purpose of knowing which facilities exist.
        Every doctor in the hospital could read the subscription's limits.

        The same shape as `report.read` gating the general ledger (log 271):
        one permission answering two questions, and the answer that lets more
        people in is the one that wins.
        """
        organization = request.organization
        entitlements = resolve_entitlements(organization)
        summary = facility_quota_summary(organization, entitlements=entitlements)
        return Response(
            {
                "plan": entitlements.plan_code,
                "subscription_status": entitlements.subscription_status,
                "is_entitled": entitlements.is_entitled,
                "overall": summary.pop("_overall"),
                "by_type": summary,
            }
        )


class FacilityChangeRequestViewSet(viewsets.ModelViewSet):
    """Raise, review and decide facility change requests."""

    serializer_class = FacilityChangeRequestSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("facility.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "request_type", "facility_type"]
    ordering_fields = ["created_at", "submitted_at", "status"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            FacilityChangeRequest.objects.filter(
                organization=self.request.organization
            )
            .select_related("organization")
            .prefetch_related("decisions")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("facility.request_change", Scope.FACILITY)

        serializer = FacilityChangeRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        change_request = submit_request(
            organization=request.organization,
            request_type=data["request_type"],
            facility_type=data["facility_type"],
            requested_by=request.user,
            payload=data.get("payload") or {},
            justification=data.get("justification", ""),
            target_facility_uuid=data.get("target_facility_uuid"),
            requested_effective_date=data.get("requested_effective_date"),
        )

        record(
            AuditAction.FACILITY_CHANGE,
            entity_type="provisioning.FacilityChangeRequest",
            entity_id=change_request.reference,
            entity_label=f"{change_request.get_request_type_display()} "
                         f"({change_request.facility_type})",
            reason=change_request.justification,
            metadata={
                "approval_level": change_request.approval_level,
                "status": change_request.status,
                "within_entitlement": not change_request.requires_capacity_purchase,
            },
        )

        return Response(
            FacilityChangeRequestSerializer(change_request).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """What would happen if this were submitted? Changes nothing."""
        serializer = FacilityChangePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        evaluation = evaluate_request(
            request.organization,
            data["request_type"],
            data["facility_type"],
            data.get("target_facility_uuid"),
        )
        return Response(evaluation)

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        """Approve, reject or send back a request, at organization level.

        Platform-level decisions are made from the platform console, not
        here -- a customer cannot approve their own capacity increase.
        """
        change_request = self.get_object()
        authorization = get_authorization(request)
        authorization.require("facility.approve_change", Scope.ORGANIZATION)

        if change_request.status == ChangeRequestStatus.PLATFORM_REVIEW:
            return Response(
                {
                    "error": {
                        "code": "platform_decision_required",
                        "message": (
                            "This request is awaiting a decision from the "
                            "platform, because it goes beyond the current "
                            "subscription."
                        ),
                        "detail": {"reference": change_request.reference},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = ChangeRequestDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated = decide(
            change_request,
            actor=request.user,
            decision=data["decision"],
            level=ApprovalLevel.ORGANIZATION,
            comment=data["comment"],
            conditions=data.get("conditions"),
        )

        record(
            AuditAction.APPROVE if data["decision"] == DecisionType.APPROVE
            else AuditAction.REJECT,
            entity_type="provisioning.FacilityChangeRequest",
            entity_id=updated.reference,
            entity_label=updated.get_request_type_display(),
            reason=data["comment"],
            metadata={"resulting_status": updated.status},
        )

        # Re-fetch before serializing. `change_request` came from a queryset
        # with prefetch_related("decisions"), and that cache was populated
        # before this decision existed -- serializing it directly would hand
        # the client a response missing the very decision they just made.
        updated = self.get_queryset().get(pk=updated.pk)
        return Response(FacilityChangeRequestSerializer(updated).data)


class EntitlementView(APIView):
    """What this organization's subscription currently allows."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        entitlements = resolve_entitlements(request.organization)
        return Response(entitlements.as_dict())


class PlanView(APIView):
    """The plan, the modules in it, the modules that exist, and the limits.

    Answers the question a customer asks when a screen is missing: *is this
    something the product cannot do, or something we did not buy?* Those are
    very different answers and the product owes the honest one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.entitlements.services import plan_summary

        return Response(plan_summary(request.organization))
