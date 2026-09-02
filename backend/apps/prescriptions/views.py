"""Prescription endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.prescriptions.models import Prescription, PrescriptionLine
from apps.prescriptions.serializers import (
    DiscontinueLineSerializer,
    PrescriptionCreateSerializer,
    PrescriptionPreviewSerializer,
    PrescriptionReviseSerializer,
    PrescriptionSerializer,
)
from apps.prescriptions.services import (
    active_medications,
    create_prescription,
    discontinue_line,
    preview_prescription,
    revise_prescription,
)
from apps.rbac.permissions import Scope


class PrescriptionViewSet(viewsets.ModelViewSet):
    """Write, revise and read prescriptions.

    There is no update or delete. A signed prescription is a clinical and
    legal record: it is revised into a new version or its lines are
    discontinued, never edited away.
    """

    serializer_class = PrescriptionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]
    lookup_field = "uuid"
    filterset_fields = ["status", "facility", "prescriber_id"]
    ordering_fields = ["prescribed_at"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Prescription.objects.select_related(
            "patient", "facility", "encounter", "supersedes"
        ).prefetch_related("lines")

        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])
        if params.get("encounter"):
            queryset = queryset.filter(encounter__uuid=params["encounter"])
        # Superseded versions are hidden unless asked for. They are history,
        # and a prescriber scanning a patient's list wants what is current.
        if params.get("include_superseded") != "true":
            queryset = queryset.exclude(status="superseded")

        return queryset.order_by("-prescribed_at")

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """What warnings would this prescription raise? Writes nothing.

        Called as the prescriber builds the list, so an allergy surfaces while
        they can still change their mind rather than as a rejection after they
        commit.
        """
        serializer = PrescriptionPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = get_object_or_404(Patient, uuid=data["patient_uuid"])
        return Response(preview_prescription(patient, data["lines"]))

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("prescription.create", Scope.FACILITY)

        serializer = PrescriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # OverrideRequired carries 409 plus the warnings, and is rendered by
        # the standard exception handler. The client shows them and retries
        # with an override_reason.
        prescription = create_prescription(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            lines=[dict(line) for line in data["lines"]],
            actor=request.user,
            encounter=(
                Encounter.objects.filter(uuid=data["encounter_uuid"]).first()
                if data.get("encounter_uuid")
                else None
            ),
            prescriber_name=data.get("prescriber_name", ""),
            prescriber_registration=data.get("prescriber_registration", ""),
            notes=data.get("notes", ""),
            patient_instructions=data.get("patient_instructions", ""),
            valid_days=data.get("valid_days", 30),
            override_reason=data.get("override_reason", ""),
            sign=data.get("sign", True),
        )
        prescription = self.get_queryset().get(pk=prescription.pk)
        return Response(
            PrescriptionSerializer(prescription).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="revise")
    def revise(self, request, uuid=None):
        """Supersede this prescription with a corrected version."""
        authorization = get_authorization(request)
        authorization.require("prescription.create", Scope.FACILITY)

        serializer = PrescriptionReviseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        revision = revise_prescription(
            self.get_object(),
            lines=[dict(line) for line in data["lines"]],
            reason=data["reason"],
            actor=request.user,
            override_reason=data.get("override_reason", ""),
        )
        revision = self.get_queryset().get(pk=revision.pk)
        return Response(
            PrescriptionSerializer(revision).data, status=status.HTTP_201_CREATED
        )


class DiscontinueLineView(APIView):
    """Stop one medicine without disturbing the rest of the prescription."""

    permission_classes = [IsAuthenticated, HasPermission.of("prescription.create")]

    def post(self, request, uuid):
        line = get_object_or_404(PrescriptionLine, uuid=uuid)
        serializer = DiscontinueLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        line = discontinue_line(
            line, reason=serializer.validated_data["reason"], actor=request.user
        )
        from apps.prescriptions.serializers import PrescriptionLineSerializer

        return Response(PrescriptionLineSerializer(line).data)


class ActiveMedicationsView(APIView):
    """Everything a patient is currently taking, across all prescriptions.

    A patient on five drugs may well have them on three separate scripts, so
    this is assembled across prescriptions rather than shown per script. It
    is the list a clinician checks before adding anything new.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]

    def get(self, request, uuid):
        patient = get_object_or_404(Patient, uuid=uuid)
        medications = active_medications(patient)
        return Response(
            {
                "patient_mrn": patient.mrn,
                "count": len(medications),
                "needs_review": [m for m in medications if m["is_overdue_review"]],
                "medications": medications,
            }
        )
