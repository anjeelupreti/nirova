"""The organization-facing API: facilities, capacity and change requests."""

from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.permissions import HasPermission, get_authorization
from apps.entitlements.resolver import resolve_entitlements
from apps.entitlements.services import facility_quota_summary
from apps.organization.models import Facility
from apps.organization.serializers import (
    ChangeRequestDecisionInputSerializer,
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

    @action(detail=False, methods=["get"], url_path="capacity")
    def capacity(self, request):
        """Per-type facility capacity: what is used, what is left, and why.

        Rendered before the user starts a request, so limits are visible in
        advance rather than discovered on submission.
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
