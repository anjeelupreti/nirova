"""REST API endpoints for the Nurse Workspace (§96) and Nursing Bedside Care (§28)."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.permissions import HasPermission, get_authorization
from apps.inpatient.models import (
    AdministrationStatus,
    Admission,
    Bed,
    CodeStatusChoice,
    MedicationAdministration,
    NurseAssignment,
    NurseRole,
    NursingHandover,
    NursingTask,
    ShiftChoice,
    TaskCategory,
    TaskStatus,
    Ward,
)
from apps.inpatient.nursing_services import (
    acknowledge_handover,
    administer_medication,
    assign_nurse,
    complete_nursing_task,
    create_nursing_task,
    create_sbar_handover,
    get_nurse_workspace_summary,
    get_patient_emar,
    record_bedside_round,
)
from apps.organization.models import Facility
from apps.prescriptions.models import PrescriptionLine
from apps.rbac.permissions import Scope


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class NurseAssignmentSerializer(serializers.ModelSerializer):
    ward = UUIDRelatedField(read_only=True)
    admission = UUIDRelatedField(read_only=True)
    bed = UUIDRelatedField(read_only=True)
    bed_code = serializers.CharField(source="bed.code", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    patient_name = serializers.CharField(source="admission.patient.full_name", read_only=True)

    class Meta:
        model = NurseAssignment
        fields = (
            "uuid",
            "ward",
            "ward_name",
            "admission",
            "patient_name",
            "bed",
            "bed_code",
            "nurse_id",
            "nurse_name",
            "assigned_date",
            "shift",
            "role",
            "is_active",
            "notes",
            "assigned_by_name",
        )
        read_only_fields = fields


class AssignNurseInputSerializer(serializers.Serializer):
    ward = serializers.UUIDField()
    admission = serializers.UUIDField(required=False, allow_null=True)
    bed = serializers.UUIDField(required=False, allow_null=True)
    nurse_id = serializers.UUIDField()
    nurse_name = serializers.CharField(max_length=255)
    assigned_date = serializers.DateField(required=False, default=timezone.localdate)
    shift = serializers.CharField(max_length=16, default=ShiftChoice.MORNING)
    role = serializers.CharField(max_length=16, default=NurseRole.PRIMARY)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class BedsideRoundInputSerializer(serializers.Serializer):
    admission = serializers.UUIDField()
    temperature_c = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    pulse_bpm = serializers.IntegerField(required=False, allow_null=True)
    respiratory_rate = serializers.IntegerField(required=False, allow_null=True)
    systolic_bp = serializers.IntegerField(required=False, allow_null=True)
    diastolic_bp = serializers.IntegerField(required=False, allow_null=True)
    spo2_percent = serializers.IntegerField(required=False, allow_null=True)
    on_room_air = serializers.BooleanField(required=False, default=True)
    oxygen_flow_lpm = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    blood_glucose_mmol = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    pain_score = serializers.IntegerField(required=False, allow_null=True)
    gcs_total = serializers.IntegerField(required=False, allow_null=True)
    intake_ml = serializers.IntegerField(required=False, default=0)
    output_ml = serializers.IntegerField(required=False, default=0)
    shift = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    observations = serializers.CharField(required=False, allow_blank=True, default="")
    interventions = serializers.CharField(required=False, allow_blank=True, default="")
    escalated = serializers.BooleanField(required=False, default=False)
    escalation_reason = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")


class AdministerMedicationInputSerializer(serializers.Serializer):
    prescription_line = serializers.UUIDField()
    admission = serializers.UUIDField()
    status = serializers.CharField(max_length=16, default=AdministrationStatus.GIVEN)
    dose_given = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    route = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    scheduled_time = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")
    injection_site = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    witness_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")


class NursingHandoverSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)
    ward = UUIDRelatedField(read_only=True)
    patient_name = serializers.CharField(source="admission.patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="admission.patient.mrn", read_only=True)
    bed_code = serializers.CharField(source="admission.current_bed.code", read_only=True)

    class Meta:
        model = NursingHandover
        fields = (
            "uuid",
            "admission",
            "ward",
            "patient_name",
            "patient_mrn",
            "bed_code",
            "shift_date",
            "shift",
            "outgoing_nurse_name",
            "code_status",
            "situation",
            "background",
            "assessment",
            "recommendation",
            "is_acknowledged",
            "incoming_nurse_name",
            "acknowledged_at",
            "created_at",
        )
        read_only_fields = (
            "uuid",
            "outgoing_nurse_name",
            "is_acknowledged",
            "incoming_nurse_name",
            "acknowledged_at",
            "created_at",
        )


class CreateHandoverSerializer(serializers.Serializer):
    admission = serializers.UUIDField()
    situation = serializers.CharField()
    assessment = serializers.CharField()
    recommendation = serializers.CharField()
    background = serializers.CharField(required=False, allow_blank=True, default="")
    shift = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    shift_date = serializers.DateField(required=False, default=timezone.localdate)
    code_status = serializers.CharField(max_length=16, default=CodeStatusChoice.FULL_CODE)


class NursingTaskSerializer(serializers.ModelSerializer):
    admission = UUIDRelatedField(read_only=True)
    ward = UUIDRelatedField(read_only=True)
    patient_name = serializers.CharField(source="admission.patient.full_name", read_only=True)
    bed_code = serializers.CharField(source="admission.current_bed.code", read_only=True)

    class Meta:
        model = NursingTask
        fields = (
            "uuid",
            "admission",
            "ward",
            "patient_name",
            "bed_code",
            "title",
            "category",
            "shift",
            "due_at",
            "status",
            "completed_at",
            "completed_by_name",
            "notes",
            "created_at",
        )
        read_only_fields = ("uuid", "completed_at", "completed_by_name", "created_at")


class CreateTaskSerializer(serializers.Serializer):
    admission = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=20, default=TaskCategory.GENERAL)
    shift = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class NurseWorkspaceSummaryView(APIView):
    """Aggregate live census, NEWS2 alerts, medications due and tasks for the nurse."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        facility_uuid = request.query_params.get("facility")
        if facility_uuid:
            facility = get_object_or_404(Facility, uuid=facility_uuid)
        else:
            facility = Facility.objects.filter(status="active").first() or Facility.objects.first()

        ward_uuid = request.query_params.get("ward")
        date_str = request.query_params.get("date")
        target_date = None
        if date_str:
            try:
                target_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        shift = request.query_params.get("shift")
        scope = request.query_params.get("scope", "mine")

        summary = get_nurse_workspace_summary(
            actor=request.user,
            facility=facility,
            ward_id=ward_uuid,
            target_date=target_date,
            target_shift=shift,
            scope=scope,
        )
        return Response(summary)


class NurseAssignmentViewSet(viewsets.ModelViewSet):
    """Nurse-to-patient / bed assignments."""

    serializer_class = NurseAssignmentSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"

    def get_queryset(self):
        qs = NurseAssignment.objects.select_related("ward", "admission__patient", "bed").order_by(
            "-assigned_date", "shift", "nurse_name"
        )
        ward = self.request.query_params.get("ward")
        if ward:
            qs = qs.filter(ward__uuid=ward)
        date_param = self.request.query_params.get("date")
        if date_param:
            qs = qs.filter(assigned_date=date_param)
        shift = self.request.query_params.get("shift")
        if shift:
            qs = qs.filter(shift=shift)
        nurse_id = self.request.query_params.get("nurse_id")
        if nurse_id:
            qs = qs.filter(nurse_id=nurse_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = AssignNurseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ward = get_object_or_404(Ward, uuid=data["ward"])
        admission = None
        if data.get("admission"):
            admission = get_object_or_404(Admission, uuid=data["admission"])
        bed = None
        if data.get("bed"):
            bed = get_object_or_404(Bed, uuid=data["bed"])

        assignment = assign_nurse(
            ward=ward,
            nurse_id=data["nurse_id"],
            nurse_name=data["nurse_name"],
            assigned_date=data.get("assigned_date", timezone.localdate()),
            shift=data.get("shift", ShiftChoice.MORNING),
            admission=admission,
            bed=bed,
            role=data.get("role", NurseRole.PRIMARY),
            notes=data.get("notes", ""),
            actor=request.user,
        )
        return Response(NurseAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class BedsideRoundView(APIView):
    """Record bedside observations and vitals with real-time NEWS2 calculation."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.create")]

    def post(self, request):
        serializer = BedsideRoundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admission = get_object_or_404(Admission, uuid=data["admission"])
        res = record_bedside_round(
            admission=admission,
            actor=request.user,
            temperature_c=data.get("temperature_c"),
            pulse_bpm=data.get("pulse_bpm"),
            respiratory_rate=data.get("respiratory_rate"),
            systolic_bp=data.get("systolic_bp"),
            diastolic_bp=data.get("diastolic_bp"),
            spo2_percent=data.get("spo2_percent"),
            on_room_air=data.get("on_room_air", True),
            oxygen_flow_lpm=data.get("oxygen_flow_lpm"),
            blood_glucose_mmol=data.get("blood_glucose_mmol"),
            pain_score=data.get("pain_score"),
            gcs_total=data.get("gcs_total"),
            intake_ml=data.get("intake_ml", 0),
            output_ml=data.get("output_ml", 0),
            shift=data.get("shift", ""),
            observations=data.get("observations", ""),
            interventions=data.get("interventions", ""),
            escalated=data.get("escalated", False),
            escalation_reason=data.get("escalation_reason", ""),
            notes=data.get("notes", ""),
        )
        return Response(res, status=status.HTTP_201_CREATED)


class EmarView(APIView):
    """Electronic Medication Administration Record (eMAR) query & dose administration."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        adm_uuid = request.query_params.get("admission")
        if not adm_uuid:
            return Response({"error": "Parameter 'admission' is required."}, status=status.HTTP_400_BAD_REQUEST)
        admission = get_object_or_404(Admission, uuid=adm_uuid)
        return Response(get_patient_emar(admission))

    def post(self, request):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = AdministerMedicationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        line = get_object_or_404(PrescriptionLine, uuid=data["prescription_line"])
        admission = get_object_or_404(Admission, uuid=data["admission"])

        admin = administer_medication(
            prescription_line=line,
            admission=admission,
            actor=request.user,
            status=data.get("status", AdministrationStatus.GIVEN),
            dose_given=data.get("dose_given", ""),
            route=data.get("route", ""),
            scheduled_time=data.get("scheduled_time"),
            reason=data.get("reason", ""),
            injection_site=data.get("injection_site", ""),
            witness_name=data.get("witness_name", ""),
            notes=data.get("notes", ""),
        )
        return Response(
            {
                "uuid": str(admin.uuid),
                "medicine_name": admin.medicine_name,
                "status": admin.status,
                "dose_given": admin.dose_given,
                "route": admin.route,
                "administered_at": admin.administered_at.isoformat(),
                "administered_by_name": admin.administered_by_name,
                "reason": admin.reason,
            },
            status=status.HTTP_201_CREATED,
        )


class NursingHandoverViewSet(viewsets.ModelViewSet):
    """SBAR shift handovers between outgoing and incoming nurses."""

    serializer_class = NursingHandoverSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"

    def get_queryset(self):
        qs = NursingHandover.objects.select_related("admission__patient", "ward").order_by("-created_at")
        adm = self.request.query_params.get("admission")
        if adm:
            qs = qs.filter(admission__uuid=adm)
        ward = self.request.query_params.get("ward")
        if ward:
            qs = qs.filter(ward__uuid=ward)
        return qs

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = CreateHandoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admission = get_object_or_404(Admission, uuid=data["admission"])
        handover = create_sbar_handover(
            admission=admission,
            outgoing_nurse=request.user,
            situation=data["situation"],
            assessment=data["assessment"],
            recommendation=data["recommendation"],
            background=data.get("background", ""),
            shift=data.get("shift", ""),
            shift_date=data.get("shift_date"),
            code_status=data.get("code_status", CodeStatusChoice.FULL_CODE),
        )
        return Response(NursingHandoverSerializer(handover).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, uuid=None):
        handover = self.get_object()
        ack = acknowledge_handover(handover, incoming_nurse=request.user)
        return Response(NursingHandoverSerializer(ack).data)


class NursingTaskViewSet(viewsets.ModelViewSet):
    """Bedside duties and nursing tasks for the shift."""

    serializer_class = NursingTaskSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"

    def get_queryset(self):
        qs = NursingTask.objects.select_related("admission__patient", "ward").order_by("due_at", "-created_at")
        adm = self.request.query_params.get("admission")
        if adm:
            qs = qs.filter(admission__uuid=adm)
        ward = self.request.query_params.get("ward")
        if ward:
            qs = qs.filter(ward__uuid=ward)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = CreateTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admission = get_object_or_404(Admission, uuid=data["admission"])
        task = create_nursing_task(
            admission=admission,
            title=data["title"],
            category=data.get("category", TaskCategory.GENERAL),
            shift=data.get("shift", ""),
            due_at=data.get("due_at"),
            notes=data.get("notes", ""),
        )
        return Response(NursingTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, uuid=None):
        task = self.get_object()
        notes = request.data.get("notes", "")
        completed = complete_nursing_task(task, actor=request.user, notes=notes)
        return Response(NursingTaskSerializer(completed).data)
