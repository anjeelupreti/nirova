"""Emergency endpoints.

`encounter.read` gets the board — everybody working a shift needs to see who
is waiting and how long. Registering an arrival, triaging and dispositioning
all need `encounter.create`, which is what a triage nurse holds.

One deliberate absence: there is no endpoint that edits a triage assessment or
a resuscitation entry. Both are appended and never amended, because a record
that can be edited after the fact is a record a coroner discounts.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.emergency.models import (
    Arrival,
    CriticalAlert,
    ResuscitationEvent,
    TriageAssessment,
)
from apps.emergency.services import (
    activate_alert,
    arrive,
    board,
    department_summary,
    dispose,
    identify,
    log_resus,
    mark_seen,
    pathway_performance,
    record_intervention,
    resuscitation_record,
    stand_down,
    triage,
)
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class TriageAssessmentSerializer(serializers.ModelSerializer):
    arrival = UUIDRelatedField(read_only=True)
    is_deterioration = serializers.BooleanField(read_only=True)

    class Meta:
        model = TriageAssessment
        fields = (
            "uuid", "arrival", "assessed_at", "category", "previous_category",
            "is_deterioration", "assessed_by_name", "reason", "pulse",
            "systolic", "diastolic", "respiratory_rate", "temperature_c",
            "spo2", "gcs", "pain_score", "notes",
        )
        read_only_fields = fields


class CriticalAlertSerializer(serializers.ModelSerializer):
    arrival = UUIDRelatedField(read_only=True)
    target_minutes = serializers.IntegerField(read_only=True)
    recognition_minutes = serializers.IntegerField(read_only=True)
    door_to_intervention_minutes = serializers.IntegerField(
        read_only=True, allow_null=True
    )
    met_target = serializers.BooleanField(read_only=True, allow_null=True)

    class Meta:
        model = CriticalAlert
        fields = (
            "uuid", "arrival", "pathway", "activated_at",
            "activated_by_name", "target_minutes", "recognition_minutes",
            "intervention", "intervention_at",
            "door_to_intervention_minutes", "met_target", "stood_down_at",
            "stood_down_reason", "notes",
        )
        read_only_fields = fields


class ResuscitationEventSerializer(serializers.ModelSerializer):
    arrival = UUIDRelatedField(read_only=True)

    class Meta:
        model = ResuscitationEvent
        fields = (
            "uuid", "arrival", "occurred_at", "event_type", "detail", "drug",
            "dose", "route", "joules", "rhythm", "recorded_by_name",
        )
        read_only_fields = fields


class ArrivalListSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    waiting_minutes = serializers.IntegerField(read_only=True)
    target_minutes = serializers.IntegerField(read_only=True, allow_null=True)
    minutes_to_breach = serializers.IntegerField(read_only=True, allow_null=True)
    is_breaching = serializers.BooleanField(read_only=True)
    total_minutes = serializers.IntegerField(read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Arrival
        fields = (
            "uuid", "reference", "patient", "patient_name", "patient_mrn",
            "facility", "arrived_at", "arrival_mode", "presenting_complaint",
            "is_unidentified", "arrived_unidentified",
            "provisional_description", "triage_category", "triaged_at",
            "first_seen_at", "seen_by_name", "waiting_minutes",
            "target_minutes", "minutes_to_breach", "is_breaching",
            "total_minutes", "disposition", "disposition_at", "is_open",
            "is_mlc",
        )
        read_only_fields = fields


class ArrivalDetailSerializer(ArrivalListSerializer):
    encounter = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    assessments = TriageAssessmentSerializer(many=True, read_only=True)
    alerts = CriticalAlertSerializer(many=True, read_only=True)
    minutes_unidentified = serializers.IntegerField(
        read_only=True, allow_null=True
    )

    class Meta(ArrivalListSerializer.Meta):
        fields = ArrivalListSerializer.Meta.fields + (
            "encounter", "department", "ambulance_reference", "brought_by",
            "brought_by_phone", "identified_at", "minutes_unidentified",
            "disposition_notes", "admission_reference", "referred_to",
            "mlc_number", "police_informed_at", "notes", "assessments",
            "alerts",
        )
        read_only_fields = fields


# -- write ------------------------------------------------------------------


class ArriveSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    presenting_complaint = serializers.CharField(max_length=512)
    #: Omit for somebody nobody can name. That is the normal path for an
    #: ambulance arrival, and it must be the easy one.
    patient = serializers.UUIDField(required=False, allow_null=True)
    department = serializers.UUIDField(required=False, allow_null=True)
    arrival_mode = serializers.CharField(max_length=20, default="walk_in")
    unidentified_description = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    apparent_gender = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )
    is_mlc = serializers.BooleanField(required=False, default=False)
    ambulance_reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    brought_by = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    brought_by_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )


class TriageSerializer(serializers.Serializer):
    category = serializers.IntegerField(min_value=1, max_value=5)
    reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )
    pulse = serializers.IntegerField(required=False, allow_null=True)
    systolic = serializers.IntegerField(required=False, allow_null=True)
    diastolic = serializers.IntegerField(required=False, allow_null=True)
    respiratory_rate = serializers.IntegerField(required=False, allow_null=True)
    temperature_c = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True
    )
    spo2 = serializers.IntegerField(required=False, allow_null=True)
    gcs = serializers.IntegerField(
        required=False, allow_null=True, min_value=3, max_value=15
    )
    pain_score = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=10
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class IdentifySerializer(serializers.Serializer):
    #: Either an existing record to merge into, or a name.
    existing_patient = serializers.UUIDField(required=False, allow_null=True)
    first_name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    last_name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )

    def validate(self, data):
        if not data.get("existing_patient") and not (
            data.get("first_name", "").strip()
            and data.get("last_name", "").strip()
        ):
            raise serializers.ValidationError(
                "Give a name, or the existing record they belong to."
            )
        return data


class AlertSerializer(serializers.Serializer):
    pathway = serializers.CharField(max_length=20)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class InterventionSerializer(serializers.Serializer):
    intervention = serializers.CharField(max_length=255)
    at = serializers.DateTimeField(required=False)


class StandDownSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class ResusSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=24)
    detail = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )
    drug = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    dose = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    route = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    joules = serializers.IntegerField(required=False, allow_null=True)
    rhythm = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    at = serializers.DateTimeField(required=False)


class DisposeSerializer(serializers.Serializer):
    disposition = serializers.CharField(max_length=16)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    admission_reference = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    referred_to = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class ArrivalViewSet(viewsets.ReadOnlyModelViewSet):
    """Emergency attendances."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Arrival, relations=["facility", "patient", "department"],
        fields=[
            "disposition", "triage_category", "arrival_mode", "is_mlc",
            "is_unidentified", "arrived_unidentified",
        ],
    )
    search_fields = [
        "reference", "patient__mrn", "patient__first_name",
        "patient__last_name", "presenting_complaint",
    ]
    ordering_fields = ["arrived_at", "triage_category"]

    def get_serializer_class(self):
        if self.action == "list":
            return ArrivalListSerializer
        return ArrivalDetailSerializer

    def get_queryset(self):
        queryset = Arrival.objects.select_related(
            "patient", "facility", "department", "encounter"
        )
        if self.action != "list":
            queryset = queryset.prefetch_related("assessments", "alerts")
        if self.request.query_params.get("open") == "true":
            queryset = queryset.filter(disposition="pending")
        return queryset.order_by("-arrived_at")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ArriveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        arrival = arrive(
            organization=request.organization,
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            presenting_complaint=data["presenting_complaint"],
            actor=request.user,
            patient=(
                get_object_or_404(Patient, uuid=data["patient"])
                if data.get("patient") else None
            ),
            department=(
                get_object_or_404(Department, uuid=data["department"])
                if data.get("department") else None
            ),
            arrival_mode=data.get("arrival_mode", "walk_in"),
            unidentified_description=data.get("unidentified_description", ""),
            apparent_gender=data.get("apparent_gender", ""),
            is_mlc=data.get("is_mlc", False),
            ambulance_reference=data.get("ambulance_reference", ""),
            brought_by=data.get("brought_by", ""),
            brought_by_phone=data.get("brought_by_phone", ""),
        )
        return Response(
            ArrivalDetailSerializer(arrival).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="triage")
    def triage(self, request, reference=None):
        """Assess, or re-assess. Always appends."""
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = TriageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        category = data.pop("category")
        reason = data.pop("reason", "")
        assessment = triage(
            self.get_object(), category, actor=request.user, reason=reason,
            **data,
        )
        return Response(
            TriageAssessmentSerializer(assessment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="seen")
    def seen(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        arrival = mark_seen(self.get_object(), actor=request.user)
        return Response(ArrivalDetailSerializer(arrival).data)

    @action(detail=True, methods=["post"], url_path="identify")
    def identify(self, request, reference=None):
        """Put a name to an unidentified arrival."""
        get_authorization(request).require("patient.update", Scope.FACILITY)
        serializer = IdentifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        arrival = identify(
            self.get_object(),
            actor=request.user,
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            existing_patient=(
                get_object_or_404(Patient, uuid=data["existing_patient"])
                if data.get("existing_patient") else None
            ),
            phone=data.get("phone", ""),
        )
        return Response(ArrivalDetailSerializer(arrival).data)

    @action(detail=True, methods=["get", "post"], url_path="alerts")
    def alerts(self, request, reference=None):
        arrival = self.get_object()
        if request.method == "GET":
            return Response(
                CriticalAlertSerializer(arrival.alerts.all(), many=True).data
            )
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = AlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = activate_alert(
            arrival,
            pathway=serializer.validated_data["pathway"],
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(
            CriticalAlertSerializer(alert).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="resuscitation")
    def resuscitation(self, request, reference=None):
        arrival = self.get_object()
        if request.method == "GET":
            return Response(resuscitation_record(arrival))
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ResusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        entry = log_resus(
            arrival,
            event_type=data.pop("event_type"),
            actor=request.user,
            detail=data.pop("detail", ""),
            at=data.pop("at", None),
            **data,
        )
        return Response(
            ResuscitationEventSerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="dispose")
    def dispose(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = DisposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        arrival = dispose(
            self.get_object(),
            disposition=data["disposition"],
            actor=request.user,
            notes=data.get("notes", ""),
            admission_reference=data.get("admission_reference", ""),
            referred_to=data.get("referred_to", ""),
        )
        return Response(ArrivalDetailSerializer(arrival).data)


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CriticalAlertSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        CriticalAlert, relations=["arrival"], fields=["pathway"]
    )

    def get_queryset(self):
        return CriticalAlert.objects.select_related("arrival").order_by(
            "-activated_at"
        )

    @action(detail=True, methods=["post"], url_path="intervention")
    def intervention(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = InterventionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = record_intervention(
            self.get_object(),
            actor=request.user,
            intervention=serializer.validated_data["intervention"],
            at=serializer.validated_data.get("at"),
        )
        return Response(CriticalAlertSerializer(alert).data)

    @action(detail=True, methods=["post"], url_path="stand-down")
    def stand_down(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = StandDownSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = stand_down(
            self.get_object(),
            actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(CriticalAlertSerializer(alert).data)


class BoardView(APIView):
    """Everyone in the department, sickest and longest-waiting first."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(board(facility))


class DepartmentSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        since = request.query_params.get("since")
        return Response(
            {
                "summary": department_summary(facility, since=since),
                "pathways": pathway_performance(facility, since=since),
            }
        )
