"""Inpatient endpoints.

The access rules follow the ward, not the org chart. `encounter.read` gets you
the census and the bed board — a nurse coming on shift needs to know who is in
which bed. Admitting and discharging need `encounter.create`, moving a bed
needs it too, and overriding a blocked discharge needs `discharge.override`,
which is a permission of its own precisely so that it can be given to few
people and audited on all of them.
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
from apps.inpatient.models import (
    Admission,
    Bed,
    BedAssignment,
    DailyAccrual,
    DischargeClearance,
    NursingRound,
    Ward,
)
from apps.inpatient.services import (
    accrue_all,
    admit,
    available_beds,
    backfill_accruals,
    census,
    clear,
    discharge,
    discharge_blockers,
    fluid_balance,
    initiate_discharge,
    outcomes,
    record_round,
    set_bed_status,
    stay_charges,
    transfer_bed,
    ward_occupancy,
)
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class BedSerializer(serializers.ModelSerializer):
    ward = UUIDRelatedField(read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    ward_type = serializers.CharField(source="ward.ward_type", read_only=True)
    is_occupied = serializers.BooleanField(read_only=True)
    is_assignable = serializers.BooleanField(read_only=True)
    #: Who is in it, so a bed board is one request rather than one per bed.
    occupant_name = serializers.SerializerMethodField()
    occupant_admission = serializers.SerializerMethodField()

    class Meta:
        model = Bed
        fields = (
            "uuid", "ward", "ward_name", "ward_type", "code", "bay", "status",
            "status_reason", "status_changed_at", "gender_restriction",
            "has_oxygen", "has_suction", "has_monitor", "has_ventilator",
            "is_isolation", "daily_rate", "service_code", "is_active",
            "is_occupied", "is_assignable", "occupant_name",
            "occupant_admission", "notes",
        )
        read_only_fields = (
            "uuid", "is_occupied", "is_assignable", "occupant_name",
            "occupant_admission", "ward_name", "ward_type",
        )

    def get_occupant_name(self, bed) -> str:
        assignment = bed.current_assignment
        return assignment.admission.patient.full_name if assignment else ""

    def get_occupant_admission(self, bed) -> str:
        assignment = bed.current_assignment
        return assignment.admission.reference if assignment else ""


class WardSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    unit = UUIDRelatedField(read_only=True)
    bed_count = serializers.IntegerField(read_only=True)
    is_critical_care = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ward
        fields = (
            "uuid", "code", "name", "name_nepali", "ward_type", "facility",
            "department", "unit", "floor", "building", "bed_count",
            "is_critical_care", "nurse_to_patient_ratio",
            "is_gender_segregated", "allows_attendant", "visiting_hours",
            "is_active", "notes",
        )
        read_only_fields = ("uuid", "bed_count", "is_critical_care")


class BedAssignmentSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)
    bed = UUIDRelatedField(read_only=True)
    ward = UUIDRelatedField(read_only=True)
    bed_code = serializers.CharField(source="bed.code", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    is_current = serializers.BooleanField(read_only=True)
    nights = serializers.IntegerField(read_only=True)

    class Meta:
        model = BedAssignment
        fields = (
            "uuid", "admission", "bed", "bed_code", "ward", "ward_name",
            "occupied_at", "vacated_at", "is_current", "nights", "daily_rate",
            "reason", "assigned_by_name",
        )
        read_only_fields = fields


class ClearanceSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)

    class Meta:
        model = DischargeClearance
        fields = (
            "uuid", "admission", "kind", "is_cleared", "cleared_by_name",
            "cleared_at", "blocking_reason", "notes",
        )
        read_only_fields = fields


class AccrualSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)
    bed_assignment = UUIDRelatedField(read_only=True)

    class Meta:
        model = DailyAccrual
        fields = (
            "uuid", "admission", "accrual_date", "kind", "bed_assignment",
            "service_code", "description", "quantity", "unit_rate", "amount",
            "charge_uuid", "notes",
        )
        read_only_fields = fields


class NursingRoundSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)
    balance_ml = serializers.IntegerField(read_only=True)

    class Meta:
        model = NursingRound
        fields = (
            "uuid", "admission", "recorded_at", "shift", "nurse_name",
            "intake_ml", "output_ml", "balance_ml", "pain_score",
            "observations", "interventions", "escalated", "escalation_reason",
        )
        read_only_fields = fields


class AdmissionListSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    bed_code = serializers.SerializerMethodField()
    ward_name = serializers.SerializerMethodField()
    length_of_stay_days = serializers.IntegerField(read_only=True)
    is_in_house = serializers.BooleanField(read_only=True)
    is_overstaying = serializers.BooleanField(read_only=True)

    class Meta:
        model = Admission
        fields = (
            "uuid", "reference", "patient", "patient_name", "patient_mrn",
            "facility", "status", "source", "admitted_at", "discharged_at",
            "expected_discharge", "consultant_name", "admitting_diagnosis",
            "bed_code", "ward_name", "length_of_stay_days", "is_in_house",
            "is_overstaying", "is_mlc",
        )
        read_only_fields = fields

    def get_bed_code(self, admission) -> str:
        bed = admission.current_bed
        return str(bed) if bed else ""

    def get_ward_name(self, admission) -> str:
        bed = admission.current_bed
        return bed.ward.name if bed else ""


class AdmissionDetailSerializer(AdmissionListSerializer):
    encounter = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    bed_assignments = BedAssignmentSerializer(many=True, read_only=True)
    clearances = ClearanceSerializer(many=True, read_only=True)

    class Meta(AdmissionListSerializer.Meta):
        fields = AdmissionListSerializer.Meta.fields + (
            "encounter", "department", "provisional_diagnosis",
            "final_diagnosis", "attendant_name", "attendant_phone",
            "attendant_relation", "deposit_expected", "diet_plan",
            "mlc_number", "police_informed_at", "outcome_notes",
            "discharge_summary", "discharge_advice", "follow_up_on",
            "cancelled_reason", "notes", "bed_assignments", "clearances",
        )
        read_only_fields = fields


# -- write ------------------------------------------------------------------


class AdmitSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    facility = serializers.UUIDField()
    #: One of the two, or neither: an admission with no bed is `pending`,
    #: which is a real state — a patient waiting in emergency for a ward bed.
    bed = serializers.UUIDField(required=False, allow_null=True)
    ward = serializers.UUIDField(required=False, allow_null=True)
    department = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.CharField(max_length=16, default="opd")
    consultant_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    admitting_diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )
    expected_discharge = serializers.DateField(required=False, allow_null=True)
    deposit_expected = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    is_mlc = serializers.BooleanField(required=False, default=False)
    attendant_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    attendant_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    attendant_relation = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )


class TransferSerializer(serializers.Serializer):
    bed = serializers.UUIDField()
    reason = serializers.CharField(max_length=255)


class BedStatusSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=16)
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class ClearSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=16)
    cleared = serializers.BooleanField(default=True)
    reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


class DischargeSerializer(serializers.Serializer):
    outcome = serializers.CharField(max_length=24, default="discharged")
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    advice = serializers.CharField(required=False, allow_blank=True, default="")
    follow_up_on = serializers.DateField(required=False, allow_null=True)
    final_diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )
    #: Non-empty forces past a blocked discharge. Named, reasoned and audited
    #: rather than a silent bypass.
    override_reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


class RoundSerializer(serializers.Serializer):
    shift = serializers.CharField(max_length=16, required=False,
                                  allow_blank=True, default="")
    intake_ml = serializers.IntegerField(required=False, default=0)
    output_ml = serializers.IntegerField(required=False, default=0)
    pain_score = serializers.IntegerField(required=False, allow_null=True)
    observations = serializers.CharField(required=False, allow_blank=True,
                                         default="")
    interventions = serializers.CharField(required=False, allow_blank=True,
                                          default="")
    escalate = serializers.BooleanField(required=False, default=False)
    escalation_reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class WardViewSet(viewsets.ModelViewSet):
    serializer_class = WardSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Ward, relations=["facility", "department"],
        fields=["ward_type", "is_active"],
    )

    def get_queryset(self):
        return Ward.objects.select_related("facility").order_by("name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "department.manage", Scope.FACILITY
        )
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["get"], url_path="occupancy")
    def occupancy(self, request, uuid=None):
        return Response(ward_occupancy(self.get_object()))

    @action(detail=True, methods=["get"], url_path="beds")
    def beds(self, request, uuid=None):
        """The bed board for one ward, occupants included.

        One request rather than one per bed: a nurse coming on shift opens
        this and wants the whole ward at once.
        """
        beds = self.get_object().beds.filter(is_active=True).order_by("code")
        return Response(BedSerializer(beds, many=True).data)


class BedViewSet(viewsets.ModelViewSet):
    serializer_class = BedSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Bed, relations=["ward"], fields=["status", "is_active", "is_isolation"]
    )

    def get_queryset(self):
        queryset = Bed.objects.select_related("ward").order_by(
            "ward__name", "code"
        )
        if self.request.query_params.get("available") == "true":
            facility = self.request.query_params.get("facility")
            ward = self.request.query_params.get("ward")
            assignable = available_beds(
                ward=(
                    get_object_or_404(Ward, uuid=ward) if ward else None
                ),
                facility=(
                    get_object_or_404(Facility, uuid=facility)
                    if facility else None
                ),
                gender=self.request.query_params.get("gender", ""),
            )
            # Narrowed back to a queryset rather than returned as the list the
            # service produced. DRF's filter backend and paginator both reach
            # for `.model` on whatever `get_queryset` returns, so handing them
            # a list is a 500 at the first request that also filters.
            return queryset.filter(pk__in=[bed.pk for bed in assignable])
        return queryset

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "department.manage", Scope.FACILITY
        )
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, uuid=None):
        """Take a bed out of service, or put it back."""
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = BedStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bed = set_bed_status(
            self.get_object(),
            status=serializer.validated_data["status"],
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(BedSerializer(bed).data)


class AdmissionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Admission, relations=["facility", "patient", "department"],
        fields=["status", "source", "is_mlc"],
    )
    search_fields = ["reference", "patient__mrn", "patient__first_name",
                     "patient__last_name", "consultant_name"]
    ordering_fields = ["admitted_at", "discharged_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return AdmissionListSerializer
        return AdmissionDetailSerializer

    def get_queryset(self):
        queryset = Admission.objects.select_related(
            "patient", "facility", "department", "encounter"
        )
        if self.action != "list":
            queryset = queryset.prefetch_related(
                "bed_assignments__bed", "bed_assignments__ward", "clearances"
            )
        # The ward list means people who are here. Closed admissions stay in
        # the record and are asked for explicitly.
        if self.request.query_params.get("in_house") == "true":
            queryset = queryset.filter(
                status__in=["admitted", "discharge_initiated"]
            )
        return queryset.order_by("-admitted_at")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = AdmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admission = admit(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient"]),
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            actor=request.user,
            bed=(
                get_object_or_404(Bed, uuid=data["bed"])
                if data.get("bed") else None
            ),
            ward=(
                get_object_or_404(Ward, uuid=data["ward"])
                if data.get("ward") else None
            ),
            department=(
                get_object_or_404(Department, uuid=data["department"])
                if data.get("department") else None
            ),
            source=data.get("source", "opd"),
            consultant=request.user,
            consultant_name=data.get("consultant_name", ""),
            admitting_diagnosis=data.get("admitting_diagnosis", ""),
            expected_discharge=data.get("expected_discharge"),
            deposit_expected=data.get("deposit_expected", 0),
            is_mlc=data.get("is_mlc", False),
            attendant_name=data.get("attendant_name", ""),
            attendant_phone=data.get("attendant_phone", ""),
            attendant_relation=data.get("attendant_relation", ""),
        )
        return Response(
            AdmissionDetailSerializer(admission).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="transfer")
    def transfer(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer_bed(
            self.get_object(),
            bed=get_object_or_404(Bed, uuid=serializer.validated_data["bed"]),
            actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(
            AdmissionDetailSerializer(self.get_object()).data
        )

    @action(detail=True, methods=["get"], url_path="charges")
    def charges(self, request, reference=None):
        """What the stay has cost, and what is not yet billed."""
        return Response(stay_charges(self.get_object()))

    @action(detail=True, methods=["get"], url_path="accruals")
    def accruals(self, request, reference=None):
        rows = self.get_object().accruals.order_by("-accrual_date")
        return Response(AccrualSerializer(rows, many=True).data)

    @action(detail=True, methods=["post"], url_path="accrue")
    def accrue(self, request, reference=None):
        """Backfill any un-accrued day. Idempotent."""
        get_authorization(request).require("invoice.create", Scope.FACILITY)
        return Response(
            backfill_accruals(
                request.organization, self.get_object(), actor=request.user
            )
        )

    @action(detail=True, methods=["get", "post"], url_path="rounds")
    def rounds(self, request, reference=None):
        admission = self.get_object()
        if request.method == "GET":
            return Response(
                NursingRoundSerializer(
                    admission.rounds.order_by("-recorded_at"), many=True
                ).data
            )
        serializer = RoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = record_round(
            admission, actor=request.user, **serializer.validated_data
        )
        return Response(
            NursingRoundSerializer(entry).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="fluid-balance")
    def fluid(self, request, reference=None):
        hours = int(request.query_params.get("hours", 24))
        return Response(fluid_balance(self.get_object(), hours=hours))

    # -- discharge ---------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="blockers")
    def blockers(self, request, reference=None):
        """Everything standing between this patient and the door."""
        admission = self.get_object()
        return Response(
            {
                "admission": admission.reference,
                "can_discharge": not discharge_blockers(admission),
                "blockers": discharge_blockers(admission),
            }
        )

    @action(detail=True, methods=["post"], url_path="initiate-discharge")
    def start_discharge(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        admission = initiate_discharge(
            self.get_object(),
            actor=request.user,
            notes=request.data.get("notes", ""),
        )
        return Response(AdmissionDetailSerializer(admission).data)

    @action(detail=True, methods=["post"], url_path="clear")
    def clearance(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ClearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = clear(
            self.get_object(),
            kind=data["kind"],
            actor=request.user,
            cleared=data.get("cleared", True),
            reason=data.get("reason", ""),
        )
        return Response(ClearanceSerializer(row).data)

    @action(detail=True, methods=["post"], url_path="discharge")
    def do_discharge(self, request, reference=None):
        serializer = DischargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)
        if data.get("override_reason", "").strip():
            # Forcing past a blocked discharge is its own authority, so that
            # it can be given to few people and audited on all of them.
            authorization.require("discharge.override", Scope.FACILITY)

        admission = discharge(
            self.get_object(),
            actor=request.user,
            outcome=data.get("outcome", "discharged"),
            summary=data.get("summary", ""),
            advice=data.get("advice", ""),
            follow_up_on=data.get("follow_up_on"),
            final_diagnosis=data.get("final_diagnosis", ""),
            override_reason=data.get("override_reason", ""),
        )
        return Response(AdmissionDetailSerializer(admission).data)


class CensusView(APIView):
    """Who is in the hospital, and where. Computed, never stored."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(census(facility, on_date=request.query_params.get("date")))


class OutcomesView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(outcomes(facility, since=request.query_params.get("since")))


class AccrualRunView(APIView):
    """The nightly job, exposed so it can be triggered and re-triggered."""

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.create")]

    def post(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.data.get("facility")
        )
        return Response(
            accrue_all(
                request.organization, facility,
                on_date=request.data.get("date"),
                actor=request.user,
            )
        )
