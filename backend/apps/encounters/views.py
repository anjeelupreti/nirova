"""Encounter, vitals, note and diagnosis endpoints."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.filters import uuid_filterset
from apps.common.permissions import (
    narrow_to_relationship,
    HasClinicalAccess,
    HasPermission,
    get_authorization,
)
from apps.encounters.models import ClinicalNote, Encounter, OPEN_ENCOUNTER_STATUSES
from apps.encounters.serializers import (
    ClinicalNoteInputSerializer,
    ClinicalNoteSerializer,
    CloseEncounterSerializer,
    DiagnosisInputSerializer,
    DiagnosisSerializer,
    EncounterDetailSerializer,
    EncounterListSerializer,
    NoteAmendmentSerializer,
    StartEncounterSerializer,
    VitalSignsInputSerializer,
    VitalSignsSerializer,
)
from apps.encounters.services import (
    add_diagnosis,
    amend_note,
    close_encounter,
    patient_clinical_summary,
    promote_to_condition,
    record_vitals,
    start_encounter,
    write_note,
)
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.patients.services import record_patient_access
from apps.rbac.permissions import Scope
from apps.scheduling.models import Appointment, QueueToken


class EncounterViewSet(viewsets.ModelViewSet):
    """Encounters and everything recorded inside them.

    Vitals, notes and diagnoses are nested actions rather than top-level
    resources. They have no meaning apart from their encounter — a blood
    pressure with no visit attached is not a record of anything — and nesting
    keeps the permission check in one place.
    """

    # `HasClinicalAccess` adds the object-level half: `encounter.read` says
    # whether somebody may read encounters at all, and the care relationship
    # says whether they may read *this* one. Kept as two classes rather than
    # folded into one, because collapsing them is exactly how a permission
    # comes to mean "everybody at this site" -- which is what the 4 September
    # probe found.
    #
    # Inert until the organization turns `privacy.require_care_relationship`
    # on. Off by default: a single-site clinic gets nothing from this and pays
    # the complexity.
    permission_classes = [
        IsAuthenticated,
        # `Scope.OWN` as the floor, not the default `Scope.FACILITY`. The
        # queryset below already narrows by `accessible_facility_ids`, with a
        # comment saying scope narrows rather than refuses -- and the check in
        # front of it was doing the opposite. A department-scoped doctor, which
        # is what the demo's own doctor role is, could not open a single
        # encounter, and the narrowing written to handle exactly that case was
        # unreachable for them. Pre-existing; found because Phase 2 needed to
        # read an encounter as a doctor and could not.
        #
        # A permission check that demands facility scope in front of a
        # queryset that narrows to it is a scope ladder with only one rung.
        HasPermission.of("encounter.read", scope=Scope.OWN),
        HasClinicalAccess,
    ]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Encounter, relations=['facility'], fields=['status', 'encounter_type', 'provider_uuid']
    )
    ordering_fields = ["started_at", "ended_at"]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "list":
            return EncounterListSerializer
        return EncounterDetailSerializer

    def get_queryset(self):
        queryset = Encounter.objects.select_related(
            "patient", "facility", "department"
        )
        params = self.request.query_params

        if self.action == "retrieve":
            queryset = queryset.prefetch_related("vitals", "notes", "diagnoses")

        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])
        if params.get("open") == "true":
            queryset = queryset.filter(status__in=list(OPEN_ENCOUNTER_STATUSES))
        if params.get("date"):
            queryset = queryset.filter(started_at__date=params["date"])

        # Scope narrows rather than refuses, as everywhere else.
        authorization = get_authorization(self.request)
        if authorization is not None:
            allowed = authorization.accessible_facility_ids("encounter.read")
            if allowed is not None:
                queryset = queryset.filter(facility_id__in=allowed)

        # Browsing narrows to the relationship; opening one by reference
        # does not -- the object-level `HasClinicalAccess` handles that, and
        # the two answer the same question from different directions.
        if self.action == "list":
            queryset = narrow_to_relationship(queryset, self.request)
        return queryset.order_by("-started_at")

    def retrieve(self, request, *args, **kwargs):
        """Open an encounter, logging the access to the patient's record."""
        encounter = self.get_object()
        record_patient_access(
            encounter.patient, reason=f"Opened encounter {encounter.reference}"
        )
        return Response(EncounterDetailSerializer(encounter).data)

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = StartEncounterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        encounter = start_encounter(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            actor=request.user,
            encounter_type=data["encounter_type"],
            department=(
                Department.objects.filter(uuid=data["department_uuid"]).first()
                if data.get("department_uuid")
                else None
            ),
            provider_uuid=data.get("provider_uuid"),
            provider_name=data.get("provider_name", ""),
            appointment=(
                Appointment.objects.filter(uuid=data["appointment_uuid"]).first()
                if data.get("appointment_uuid")
                else None
            ),
            queue_token=(
                QueueToken.objects.filter(uuid=data["queue_token_uuid"]).first()
                if data.get("queue_token_uuid")
                else None
            ),
            chief_complaint=data.get("chief_complaint", ""),
            triage_category=data.get("triage_category"),
        )
        return Response(
            EncounterDetailSerializer(encounter).data,
            status=status.HTTP_201_CREATED,
        )

    # -- nested records --------------------------------------------------

    @action(detail=True, methods=["post"], url_path="vitals")
    def add_vitals(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = VitalSignsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vitals = record_vitals(
            self.get_object(), dict(serializer.validated_data), actor=request.user
        )
        return Response(
            VitalSignsSerializer(vitals).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="notes")
    def add_note(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = ClinicalNoteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        sign = data.pop("sign", False)

        note = write_note(self.get_object(), data, actor=request.user, sign=sign)
        return Response(
            ClinicalNoteSerializer(note).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="diagnoses")
    def add_diagnosis_action(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = DiagnosisInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        diagnosis = add_diagnosis(
            self.get_object(), dict(serializer.validated_data), actor=request.user
        )
        return Response(
            DiagnosisSerializer(diagnosis).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = CloseEncounterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        encounter = close_encounter(
            self.get_object(),
            actor=request.user,
            disposition=data["disposition"],
            disposition_notes=data.get("disposition_notes", ""),
            follow_up_date=data.get("follow_up_date"),
            follow_up_instructions=data.get("follow_up_instructions", ""),
            sign=data.get("sign", True),
        )
        encounter = self.get_queryset().prefetch_related(
            "vitals", "notes", "diagnoses"
        ).get(pk=encounter.pk)
        return Response(EncounterDetailSerializer(encounter).data)


class NoteAmendmentView(APIView):
    """Amend a signed note.

    A separate endpoint rather than a PATCH on the note, because it is not an
    edit: it creates a new record that points at the original. Making that a
    distinct action stops it being reached for casually.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.create")]

    def post(self, request, uuid):
        original = get_object_or_404(ClinicalNote, uuid=uuid)
        serializer = NoteAmendmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        data.pop("sign", None)

        amendment = amend_note(original, data, reason, actor=request.user)
        return Response(
            ClinicalNoteSerializer(amendment).data, status=status.HTTP_201_CREATED
        )


class PromoteDiagnosisView(APIView):
    """Carry a diagnosis into the patient's ongoing condition list."""

    permission_classes = [IsAuthenticated, HasPermission.of("patient.update")]

    def post(self, request, uuid):
        from apps.encounters.models import Diagnosis

        diagnosis = get_object_or_404(Diagnosis, uuid=uuid)
        condition = promote_to_condition(diagnosis, actor=request.user)
        return Response(
            {
                "condition_uuid": str(condition.uuid),
                "name": condition.name,
                "icd10_code": condition.icd10_code,
                "status": condition.status,
            },
            status=status.HTTP_201_CREATED,
        )


class ClinicalSummaryView(APIView):
    """Everything a clinician wants before they see the patient.

    Allergies first, then active conditions, then recent history — in that
    order because that is the order in which they change what the clinician
    does next.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]

    def get(self, request, uuid):
        patient = get_object_or_404(Patient, uuid=uuid)
        record_patient_access(patient, reason="Clinical summary")
        return Response(patient_clinical_summary(patient))


class MyWorklistView(APIView):
    """The signed-in clinician's open encounters.

    The doctor's landing screen: who is waiting on them right now, ordered by
    triage then arrival, so the sickest patient is at the top rather than
    whoever booked first.
    """

    # `Scope.OWN`: this view is scoped to the caller by construction -- it
    # returns *their* open encounters and nobody else's. Demanding facility
    # scope in front of it refused every department-scoped doctor their own
    # landing screen, which §96 records as built. A "my" view that requires
    # facility-wide authority is a contradiction in its own name.
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("encounter.read", scope=Scope.OWN),
    ]

    def get(self, request):
        queryset = Encounter.objects.filter(
            status__in=list(OPEN_ENCOUNTER_STATUSES)
        ).select_related("patient", "facility")

        provider = request.query_params.get("provider") or str(request.user.uuid)
        if request.query_params.get("all") != "true":
            queryset = queryset.filter(provider_uuid=provider)
        if request.query_params.get("facility"):
            queryset = queryset.filter(facility__uuid=request.query_params["facility"])

        # Triage first (1 is most urgent), then how long they have waited.
        # Nulls last, so an untriaged outpatient does not outrank a triaged
        # emergency.
        queryset = queryset.order_by(
            models_nulls_last("triage_category"), "started_at"
        )

        return Response(
            {
                "generated_at": timezone.now().isoformat(),
                "count": queryset.count(),
                "encounters": EncounterListSerializer(queryset[:100], many=True).data,
            }
        )


def models_nulls_last(field: str):
    """Order by `field` ascending with NULLs last.

    Django's `F.asc(nulls_last=True)` expresses this; wrapped in a helper so
    the intent reads clearly at the call site.
    """
    from django.db.models import F

    return F(field).asc(nulls_last=True)
