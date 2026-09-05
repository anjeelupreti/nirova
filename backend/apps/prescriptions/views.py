import logging
"""Prescription endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.patients.services import record_patient_access

from apps.common.filters import uuid_filterset
from apps.common.permissions import narrow_to_relationship, HasPermission, get_authorization
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
    awaiting_dispensing,
    present,
    preview_prescription,
    revise_prescription,
)
from apps.rbac.permissions import Scope


logger = logging.getLogger("nirova.prescriptions")


class PrescriptionViewSet(viewsets.ModelViewSet):
    """Write, revise and read prescriptions.

    There is no update or delete. A signed prescription is a clinical and
    legal record: it is revised into a new version or its lines are
    discontinued, never edited away.
    """

    serializer_class = PrescriptionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Prescription, relations=['facility'], fields=['status', 'prescriber_id']
    )
    ordering_fields = ["prescribed_at"]
    http_method_names = ["get", "post", "head", "options"]

    def retrieve(self, request, *args, **kwargs):
        """Log the read.

        ACCESS_DESIGN.md: where access cannot be narrowed, it must be
        recorded. Patient retrieval has always written an access record;
        prescriptions did not -- and what somebody is being treated for is
        usually legible from what they have been prescribed.
        """
        instance = self.get_object()
        if instance.patient_id:
            record_patient_access(
                instance.patient,
                reason=f"Prescription {instance.reference}",
            )

        # Somebody who can dispense has opened this by reference, which means
        # a patient is standing at their counter holding it. Recorded as a
        # fact rather than inferred, so the prescription stays on that
        # counter's worklist instead of vanishing the moment they navigate
        # away -- and so `_presented` can make it a care relationship.
        #
        # Best-effort: failing to note the presentation must not stop the
        # pharmacist reading the prescription in front of them.
        authorization = get_authorization(request)
        facility = _facility_of(request)
        if (
            authorization is not None
            and facility is not None
            and authorization.has("prescription.dispense", Scope.OWN)
        ):
            try:
                present(instance, facility, actor=request.user)
            except Exception:
                logger.exception(
                    "could not record presentation of %s", instance.reference,
                )
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=["get"], url_path="awaiting")
    def awaiting(self, request):
        """What is waiting to be dispensed at this counter.

        The question a pharmacist actually asks, and the one that had no answer
        while `Prescription.facility` was the only link -- that records where a
        prescription was *written*, and a patient may take it anywhere. This
        reads the presentations instead: prescriptions handed over here and not
        yet dispensed.
        """
        facility = _facility_of(request)
        if facility is None:
            return Response(
                {"detail": "Name a facility to see what is waiting there.",
                 "results": []},
            )
        return Response({
            "facility": facility.code,
            "results": awaiting_dispensing(facility),
        })

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

        # Browsing narrows to the relationship; retrieving by reference
        # does not. A patient presenting a prescription number has supplied
        # both the relationship and the consent, and a pharmacy that cannot
        # enumerate the group's prescriptions can still open the one in front
        # of them. Inert until the organization turns the switch on.
        if self.action == "list":
            queryset = narrow_to_relationship(queryset, self.request)
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

    permission_classes = [IsAuthenticated, HasPermission.of("patient.read", scope=Scope.OWN)]

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


def _facility_of(request):
    """The facility a request is acting at, from the tenant context.

    `X-Facility` is resolved by the tenancy middleware into the context
    variable, not onto the request object -- so `request.facility` is always
    `None` and the first version of the presentation code silently never
    fired. The header is a UUID; this turns it back into the row.
    """
    from apps.organization.models import Facility
    from apps.tenancy.context import get_current_facility_id

    facility_id = get_current_facility_id()
    if not facility_id:
        return None
    return Facility.objects.filter(uuid=facility_id).first()
