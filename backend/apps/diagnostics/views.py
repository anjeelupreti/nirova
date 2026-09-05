"""Diagnostics endpoints: ordering, the worklist, results and alerts."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.diagnostics.models import (
    AlertStatus,
    CriticalValueAlert,
    DiagnosticOrder,
    DiagnosticResult,
    TestDefinition,
)
from apps.diagnostics.serializers import (
    AcknowledgeCriticalSerializer,
    AmendResultSerializer,
    CollectSpecimenSerializer,
    CriticalValueAlertSerializer,
    DiagnosticOrderDetailSerializer,
    DiagnosticOrderListSerializer,
    EnterResultsSerializer,
    NotifyCriticalSerializer,
    PlaceOrderSerializer,
    RejectSpecimenSerializer,
    TestDefinitionSerializer,
)
from apps.diagnostics.services import (
    acknowledge_critical,
    amend_result,
    collect_specimen,
    enter_results,
    notify_critical,
    patient_results,
    place_order,
    receive_specimen,
    reject_specimen,
    turnaround_report,
    verify_order,
    worklist,
)
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.patients.services import record_patient_access
from apps.rbac.permissions import Scope


class TestDefinitionViewSet(viewsets.ModelViewSet):
    """The catalogue of orderable investigations."""

    serializer_class = TestDefinitionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        TestDefinition, relations=['department'], fields=['modality', 'is_active', 'is_panel']
    )
    search_fields = ["code", "name", "short_name"]
    ordering_fields = ["modality", "name"]

    def get_queryset(self):
        queryset = TestDefinition.objects.prefetch_related(
            "reference_ranges", "components"
        )
        # Panel members are noise in an ordering list: a clinician orders the
        # liver function test, not its bilirubin component.
        if self.request.query_params.get("orderable") == "true":
            queryset = queryset.filter(parent__isnull=True, is_active=True)
        return queryset.order_by("modality", "display_order", "name")


class DiagnosticOrderViewSet(viewsets.ModelViewSet):
    """Order investigations and move them through the workflow.

    Each transition is its own action rather than a status field a client can
    set. Collection allocates an accession number; verification enforces a
    second pair of eyes. Neither is safe as a PATCH.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        DiagnosticOrder, relations=['facility'], fields=['status', 'modality', 'priority']
    )
    ordering_fields = ["ordered_at", "due_at"]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "list":
            return DiagnosticOrderListSerializer
        return DiagnosticOrderDetailSerializer

    def get_queryset(self):
        queryset = DiagnosticOrder.objects.select_related(
            "patient", "facility", "test", "encounter"
        )
        params = self.request.query_params

        if self.action == "retrieve":
            queryset = queryset.prefetch_related("results", "critical_alerts")
        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])
        if params.get("encounter"):
            queryset = queryset.filter(encounter__uuid=params["encounter"])
        if params.get("accession"):
            queryset = queryset.filter(accession_number=params["accession"])

        authorization = get_authorization(self.request)
        if authorization is not None:
            allowed = authorization.accessible_facility_ids("encounter.read")
            if allowed is not None:
                queryset = queryset.filter(facility_id__in=allowed)

        return queryset.order_by("-ordered_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = place_order(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            test=get_object_or_404(TestDefinition, uuid=data["test_uuid"]),
            actor=request.user,
            encounter=(
                Encounter.objects.filter(uuid=data["encounter_uuid"]).first()
                if data.get("encounter_uuid")
                else None
            ),
            priority=data["priority"],
            clinical_indication=data.get("clinical_indication", ""),
            clinical_notes=data.get("clinical_notes", ""),
        )
        return Response(
            DiagnosticOrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="collect")
    def collect(self, request, uuid=None):
        """Record collection and allocate the specimen barcode."""
        serializer = CollectSpecimenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = collect_specimen(
            self.get_object(),
            actor=request.user,
            specimen_type=serializer.validated_data.get("specimen_type", ""),
        )
        return Response(DiagnosticOrderDetailSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="receive")
    def receive(self, request, uuid=None):
        order = receive_specimen(self.get_object(), actor=request.user)
        return Response(DiagnosticOrderDetailSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, uuid=None):
        serializer = RejectSpecimenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = reject_specimen(
            self.get_object(),
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(DiagnosticOrderDetailSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="results")
    def results(self, request, uuid=None):
        """Enter values. Critical results raise an alert immediately."""
        serializer = EnterResultsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        enter_results(
            self.get_object(),
            [dict(entry) for entry in serializer.validated_data["results"]],
            actor=request.user,
        )
        order = self.get_queryset().prefetch_related(
            "results", "critical_alerts"
        ).get(uuid=uuid)
        return Response(
            DiagnosticOrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, uuid=None):
        """Verify and release.

        Refused if the caller entered the results — that is what verification
        is for, and the service layer enforces it.
        """
        order = verify_order(self.get_object(), actor=request.user)
        order = self.get_queryset().prefetch_related(
            "results", "critical_alerts"
        ).get(pk=order.pk)
        return Response(DiagnosticOrderDetailSerializer(order).data)


class AmendResultView(APIView):
    """Correct a verified result by superseding it."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.create")]

    def post(self, request, uuid):
        original = get_object_or_404(DiagnosticResult, uuid=uuid)
        serializer = AmendResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.diagnostics.serializers import DiagnosticResultSerializer

        amendment = amend_result(
            original,
            value=serializer.validated_data["value"],
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(
            DiagnosticResultSerializer(amendment).data,
            status=status.HTTP_201_CREATED,
        )


class WorklistView(APIView):
    """What the department has to do, in the order it should be picked up.

    STAT first, then urgent, then oldest — not arrival order, which is what a
    plain list would give and is the wrong answer whenever anyone is sick.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        orders = worklist(
            facility,
            modality=request.query_params.get("modality", ""),
            status=request.query_params.get("status", ""),
        )
        return Response(
            {
                "facility": facility.name,
                "generated_at": timezone.now().isoformat(),
                "count": len(orders),
                "overdue": sum(1 for order in orders if order.is_overdue),
                "orders": DiagnosticOrderListSerializer(orders, many=True).data,
            }
        )


class CriticalAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """Critical values awaiting communication or acknowledgement."""

    serializer_class = CriticalValueAlertSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_fields = ["status", "flag"]

    def get_queryset(self):
        queryset = CriticalValueAlert.objects.select_related(
            "patient", "order", "result"
        )
        if self.request.query_params.get("open") == "true":
            queryset = queryset.filter(status=AlertStatus.PENDING)
        return queryset.order_by("-raised_at")

    @action(detail=True, methods=["post"], url_path="notify")
    def notify(self, request, uuid=None):
        """Record that a named person was told."""
        serializer = NotifyCriticalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = notify_critical(
            self.get_object(),
            person=serializer.validated_data["person"],
            via=serializer.validated_data.get("via", "telephone"),
            actor=request.user,
        )
        return Response(CriticalValueAlertSerializer(alert).data)

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, uuid=None):
        serializer = AcknowledgeCriticalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = acknowledge_critical(
            self.get_object(),
            action_taken=serializer.validated_data["action_taken"],
            actor=request.user,
        )
        return Response(CriticalValueAlertSerializer(alert).data)


class PatientResultsView(APIView):
    """A patient's released results, newest first."""

    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]

    def get(self, request, uuid):
        patient = get_object_or_404(Patient, uuid=uuid)
        record_patient_access(patient, reason="Diagnostic results")
        return Response(
            {
                "patient_mrn": patient.mrn,
                "orders": patient_results(patient),
            }
        )


class TurnaroundReportView(APIView):
    """Turnaround performance, split by where the delay occurs."""

    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(turnaround_report(facility))
