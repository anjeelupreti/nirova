"""Theatre endpoints.

`encounter.read` sees the list — everybody working a session needs to know
what is running. Booking, staffing and running a case need `encounter.create`.
Forcing a double-booking needs `theatre.override`, which exists separately so
it can be given to a coordinator and audited on every use.

There is no endpoint that edits a completed checklist phase or deletes a
consumption row. Both are deliberate: the checklist is evidence, and a
consumption that never happened is a stock discrepancy somebody should
investigate rather than erase.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.dates import as_date
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.encounters.models import Encounter
from apps.hr.models import Employee
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.pharmacy.models import Batch, Product
from apps.rbac.permissions import Scope
from apps.theatre.models import (
    CHECKLIST_ITEMS,
    AnaesthesiaRecord,
    CaseConsumption,
    RecoveryRecord,
    SafetyChecklist,
    SurgicalCase,
    TeamMember,
    Theatre,
)
from apps.theatre.services import (
    approve_case,
    assign,
    cancel_case,
    case_cost,
    checklist_state,
    complete_checklist,
    consume,
    day_list,
    implant_registry,
    mark,
    request_case,
    safety_audit,
    schedule,
    skip_checklist,
    team_gaps,
    utilisation,
)

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class TheatreSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    stock_location = UUIDRelatedField(read_only=True)

    class Meta:
        model = Theatre
        fields = (
            "uuid", "code", "name", "theatre_type", "facility", "department",
            "stock_location", "floor", "turnaround_minutes",
            "session_starts_at", "session_ends_at", "has_laminar_flow",
            "has_image_intensifier", "has_microscope", "is_active", "notes",
        )
        read_only_fields = ("uuid",)


class TeamMemberSerializer(serializers.ModelSerializer):
    case = UUIDRelatedField(read_only=True)
    employee = UUIDRelatedField(read_only=True)

    class Meta:
        model = TeamMember
        fields = (
            "uuid", "case", "employee", "role", "name",
            "registration_number", "scrubbed_in_at", "scrubbed_out_at",
            "notes",
        )
        read_only_fields = fields


class ChecklistSerializer(serializers.ModelSerializer):
    case = UUIDRelatedField(read_only=True)
    is_complete = serializers.BooleanField(read_only=True)
    unanswered = serializers.ListField(read_only=True)
    negative_answers = serializers.ListField(read_only=True)

    class Meta:
        model = SafetyChecklist
        fields = (
            "uuid", "case", "phase", "completed_at", "completed_by_name",
            "responses", "concerns", "was_skipped", "skip_reason",
            "is_complete", "unanswered", "negative_answers",
        )
        read_only_fields = fields


class ConsumptionSerializer(serializers.ModelSerializer):
    case = UUIDRelatedField(read_only=True)
    product = UUIDRelatedField(read_only=True)
    batch = UUIDRelatedField(read_only=True)

    class Meta:
        model = CaseConsumption
        fields = (
            "uuid", "case", "kind", "product", "batch", "description",
            "batch_number", "serial_number", "manufacturer", "expires_on",
            "quantity", "unit_cost", "total_cost", "charge_uuid",
            "implanted_site", "recorded_by_name", "notes",
        )
        read_only_fields = fields


class AnaesthesiaSerializer(serializers.ModelSerializer):
    case = UUIDRelatedField(read_only=True)
    total_input_ml = serializers.IntegerField(read_only=True)

    class Meta:
        model = AnaesthesiaRecord
        fields = (
            "uuid", "case", "anaesthesia_type", "airway",
            "intubation_attempts", "was_difficult_airway",
            "difficult_airway_detail", "crystalloid_ml", "colloid_ml",
            "blood_ml", "total_input_ml", "urine_output_ml",
            "lowest_systolic", "lowest_spo2", "adverse_events",
            "reversal_given", "post_op_analgesia", "anaesthetist_name",
            "notes",
        )
        read_only_fields = ("uuid", "case", "total_input_ml")


class RecoverySerializer(serializers.ModelSerializer):
    case = UUIDRelatedField(read_only=True)
    minutes_in_recovery = serializers.IntegerField(
        read_only=True, allow_null=True
    )

    class Meta:
        model = RecoveryRecord
        fields = (
            "uuid", "case", "arrived_at", "discharged_at",
            "minutes_in_recovery", "aldrete_score", "pain_score",
            "had_nausea", "had_shivering", "complications", "discharged_to",
            "nurse_name", "notes",
        )
        read_only_fields = ("uuid", "case", "minutes_in_recovery")


class CaseListSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    theatre = UUIDRelatedField(read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    theatre_code = serializers.CharField(
        source="theatre.code", read_only=True, default=""
    )
    theatre_minutes = serializers.IntegerField(read_only=True, allow_null=True)
    operating_minutes = serializers.IntegerField(read_only=True, allow_null=True)
    start_delay_minutes = serializers.IntegerField(
        read_only=True, allow_null=True
    )
    overran_minutes = serializers.IntegerField(read_only=True, allow_null=True)
    is_live = serializers.BooleanField(read_only=True)
    was_avoidable_cancellation = serializers.BooleanField(read_only=True)

    class Meta:
        model = SurgicalCase
        fields = (
            "uuid", "reference", "patient", "patient_name", "patient_mrn",
            "facility", "theatre", "theatre_code", "planned_procedure",
            "performed_procedure", "laterality", "urgency", "asa_grade",
            "status", "is_live", "is_day_case", "scheduled_start",
            "scheduled_end", "planned_minutes", "wheels_in_at",
            "incision_at", "closure_at", "wheels_out_at", "theatre_minutes",
            "operating_minutes", "start_delay_minutes", "overran_minutes",
            "cancellation_reason", "was_avoidable_cancellation",
        )
        read_only_fields = fields


class CaseDetailSerializer(CaseListSerializer):
    encounter = UUIDRelatedField(read_only=True)
    anaesthesia_minutes = serializers.IntegerField(
        read_only=True, allow_null=True
    )
    team = TeamMemberSerializer(many=True, read_only=True)
    checklists = ChecklistSerializer(many=True, read_only=True)
    consumption = ConsumptionSerializer(many=True, read_only=True)

    class Meta(CaseListSerializer.Meta):
        fields = CaseListSerializer.Meta.fields + (
            "encounter", "procedure_code", "indication", "requested_at",
            "requested_by_name", "approved_at", "approved_by_name",
            "sent_for_at", "anaesthesia_start_at", "recovery_out_at",
            "anaesthesia_minutes", "cancelled_at", "cancellation_notes",
            "findings", "complications", "blood_loss_ml", "specimen_sent",
            "specimen_detail", "post_op_instructions", "notes",
            "team", "checklists", "consumption",
        )
        read_only_fields = fields


# -- write ------------------------------------------------------------------


class RequestCaseSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    facility = serializers.UUIDField()
    planned_procedure = serializers.CharField(max_length=512)
    encounter = serializers.UUIDField(required=False, allow_null=True)
    urgency = serializers.CharField(max_length=16, default="elective")
    planned_minutes = serializers.IntegerField(default=60, min_value=5)
    laterality = serializers.CharField(max_length=12, default="na")
    asa_grade = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=6
    )
    procedure_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    indication = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    is_day_case = serializers.BooleanField(required=False, default=False)


class ScheduleSerializer(serializers.Serializer):
    theatre = serializers.UUIDField()
    start = serializers.DateTimeField()
    minutes = serializers.IntegerField(required=False, allow_null=True)
    #: Double-booking. Needs `theatre.override` and a reason.
    force = serializers.BooleanField(required=False, default=False)
    force_reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


class AssignSerializer(serializers.Serializer):
    employee = serializers.UUIDField()
    role = serializers.CharField(max_length=20)
    allow_unregistered = serializers.BooleanField(required=False, default=False)


class MarkSerializer(serializers.Serializer):
    step = serializers.CharField(max_length=24)
    at = serializers.DateTimeField(required=False)


class ChecklistInputSerializer(serializers.Serializer):
    phase = serializers.CharField(max_length=16)
    responses = serializers.DictField(required=False, default=dict)
    concerns = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    at = serializers.DateTimeField(required=False)
    #: When true, the phase is recorded as skipped and `reason` is required.
    skip = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )

    def validate(self, data):
        if data.get("skip") and not data.get("reason", "").strip():
            raise serializers.ValidationError(
                {"reason": "Skipping a safety checklist phase must say why."}
            )
        return data


class ConsumeSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255)
    kind = serializers.CharField(max_length=16, default="consumable")
    product = serializers.UUIDField(required=False, allow_null=True)
    batch = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, default=1
    )
    serial_number = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    unit_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    service_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    implanted_site = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=24)
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )
    postpone = serializers.BooleanField(required=False, default=False)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class TheatreViewSet(viewsets.ModelViewSet):
    serializer_class = TheatreSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Theatre, relations=["facility", "department"],
        fields=["theatre_type", "is_active"],
    )

    def get_queryset(self):
        return Theatre.objects.select_related("facility").order_by("code")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "department.manage", Scope.FACILITY
        )
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["get"], url_path="list")
    def day(self, request, uuid=None):
        """One room's list for one day, with the idle gaps between cases."""
        return Response(
            day_list(self.get_object(),
                     on_date=as_date(request.query_params.get("date"), "date"))
        )

    @action(detail=True, methods=["get"], url_path="utilisation")
    def utilisation(self, request, uuid=None):
        return Response(
            utilisation(
                self.get_object(),
                since=request.query_params.get("since"),
                until=request.query_params.get("until"),
            )
        )


class SurgicalCaseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        SurgicalCase, relations=["facility", "theatre", "patient"],
        fields=["status", "urgency", "cancellation_reason", "is_day_case"],
    )
    search_fields = [
        "reference", "planned_procedure", "patient__mrn",
        "patient__first_name", "patient__last_name",
    ]
    ordering_fields = ["scheduled_start", "requested_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return CaseListSerializer
        return CaseDetailSerializer

    def get_queryset(self):
        queryset = SurgicalCase.objects.select_related(
            "patient", "facility", "theatre"
        )
        if self.action != "list":
            queryset = queryset.prefetch_related(
                "team", "checklists", "consumption"
            )
        if self.request.query_params.get("waiting") == "true":
            # The waiting list: approved, no slot.
            queryset = queryset.filter(
                status="approved", scheduled_start__isnull=True
            )
        return queryset.order_by("-scheduled_start", "-requested_at")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = RequestCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        case = request_case(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient"]),
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            planned_procedure=data["planned_procedure"],
            actor=request.user,
            encounter=(
                get_object_or_404(Encounter, uuid=data["encounter"])
                if data.get("encounter") else None
            ),
            urgency=data.get("urgency", "elective"),
            planned_minutes=data.get("planned_minutes", 60),
            laterality=data.get("laterality", "na"),
            asa_grade=data.get("asa_grade"),
            procedure_code=data.get("procedure_code", ""),
            indication=data.get("indication", ""),
            is_day_case=data.get("is_day_case", False),
        )
        return Response(
            CaseDetailSerializer(case).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        case = approve_case(
            self.get_object(), actor=request.user,
            notes=request.data.get("notes", ""),
        )
        return Response(CaseDetailSerializer(case).data)

    @action(detail=True, methods=["post"], url_path="schedule")
    def schedule(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.OWN)
        serializer = ScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("force"):
            # Double-booking a theatre is its own authority. It is a real
            # decision an emergency sometimes requires, and one a theatre
            # committee asks about afterwards.
            authorization.require("theatre.override", Scope.FACILITY)

        case = schedule(
            self.get_object(),
            theatre=get_object_or_404(Theatre, uuid=data["theatre"]),
            start=data["start"],
            actor=request.user,
            minutes=data.get("minutes"),
            force=data.get("force", False),
            force_reason=data.get("force_reason", ""),
        )
        return Response(CaseDetailSerializer(case).data)

    @action(detail=True, methods=["get", "post"], url_path="team")
    def team(self, request, reference=None):
        case = self.get_object()
        if request.method == "GET":
            return Response(
                {
                    "team": TeamMemberSerializer(
                        case.team.all(), many=True
                    ).data,
                    "gaps": team_gaps(case),
                }
            )
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = assign(
            case,
            employee=get_object_or_404(Employee, uuid=data["employee"]),
            role=data["role"],
            actor=request.user,
            allow_unregistered=data.get("allow_unregistered", False),
        )
        return Response(
            TeamMemberSerializer(member).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="checklist")
    def checklist(self, request, reference=None):
        case = self.get_object()
        if request.method == "GET":
            return Response(
                {
                    "state": checklist_state(case),
                    #: The template, so a client renders the items rather than
                    #: hard-coding them. A checklist whose contents live in a
                    #: React component cannot be audited.
                    "items": CHECKLIST_ITEMS,
                }
            )
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ChecklistInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("skip"):
            row = skip_checklist(
                case, data["phase"], actor=request.user,
                reason=data["reason"],
            )
        else:
            row = complete_checklist(
                case, data["phase"], actor=request.user,
                responses=data.get("responses") or {},
                concerns=data.get("concerns", ""),
                at=data.get("at"),
            )
        return Response(ChecklistSerializer(row).data)

    @action(detail=True, methods=["post"], url_path="mark")
    def mark(self, request, reference=None):
        """Record one of the case's timings."""
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = MarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        case = mark(
            self.get_object(),
            step=serializer.validated_data["step"],
            actor=request.user,
            at=serializer.validated_data.get("at"),
        )
        return Response(CaseDetailSerializer(case).data)

    @action(detail=True, methods=["get", "post"], url_path="consumption")
    def consumption(self, request, reference=None):
        case = self.get_object()
        if request.method == "GET":
            return Response(case_cost(case))
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ConsumeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = consume(
            request.organization, case,
            description=data["description"],
            actor=request.user,
            kind=data.get("kind", "consumable"),
            product=(
                get_object_or_404(Product, uuid=data["product"])
                if data.get("product") else None
            ),
            batch=(
                get_object_or_404(Batch, uuid=data["batch"])
                if data.get("batch") else None
            ),
            quantity=data.get("quantity", 1),
            serial_number=data.get("serial_number", ""),
            unit_cost=data.get("unit_cost"),
            service_code=data.get("service_code", ""),
            implanted_site=data.get("implanted_site", ""),
            notes=data.get("notes", ""),
        )
        return Response(
            ConsumptionSerializer(row).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, reference=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        case = cancel_case(
            self.get_object(), actor=request.user,
            reason=data["reason"],
            notes=data.get("notes", ""),
            postpone=data.get("postpone", False),
        )
        return Response(CaseDetailSerializer(case).data)

    @action(detail=True, methods=["get", "post"], url_path="anaesthesia")
    def anaesthesia(self, request, reference=None):
        case = self.get_object()
        row = getattr(case, "anaesthesia", None)
        if request.method == "GET":
            return Response(
                AnaesthesiaSerializer(row).data if row else {}
            )
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = AnaesthesiaSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(case=case, created_by_id=request.user.uuid)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="recovery")
    def recovery(self, request, reference=None):
        case = self.get_object()
        row = getattr(case, "recovery", None)
        if request.method == "GET":
            return Response(RecoverySerializer(row).data if row else {})
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = RecoverySerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(case=case, created_by_id=request.user.uuid)
        return Response(serializer.data)


class ImplantRegistryView(APIView):
    """Which patients hold an implant from a product or batch.

    The reason serial numbers are stored. Called on the morning a manufacturer
    issues a recall, and the answer has to be names and phone numbers.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        product = request.query_params.get("product")
        batch = request.query_params.get("batch")
        return Response(
            implant_registry(
                product=(
                    get_object_or_404(Product, uuid=product) if product else None
                ),
                batch=(
                    get_object_or_404(Batch, uuid=batch) if batch else None
                ),
            )
        )


class SafetyAuditView(APIView):
    """How reliably the checklist is actually being done."""

    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(
            safety_audit(facility, since=request.query_params.get("since"))
        )
