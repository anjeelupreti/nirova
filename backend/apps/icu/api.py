"""Intensive care endpoints.

`encounter.read` sees the board and a patient's chart. Charting — observations,
fluids, infusions, ventilation, lines — needs `encounter.create`, which every
ICU nurse has. Ending a stay and setting a ceiling of care need
`encounter.create` too, but both write an audit record naming the actor,
because they are the two decisions somebody will be asked about afterwards.

Three things this API deliberately does not offer.

**No endpoint edits an observation, a fluid entry or a rate.** The chart is
evidence. A wrong fluid entry is corrected by reversing it, and a wrong rate by
charting the right one — both leave the original visible, which is the point.

**No endpoint deletes an alert.** An alert that can be made to disappear is an
alert nobody has to explain.

**No endpoint sets a SOFA total directly.** It is computed, with its components
and its gaps, or it does not exist.
"""

from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# UUIDRelatedField: related objects are published by UUID, never by integer
# PK. With a database per tenant, `bed: 42` means a different bed in every
# customer's database.
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.icu.models import (
    FASTHUG_ITEMS,
    Alert,
    FluidEntry,
    IcuOutcome,
    IcuStay,
    Infusion,
    InvasiveDevice,
    Observation,
    Round,
    VentilationRecord,
    icu_day_of,
)
from apps.icu.services import (
    acknowledge_alert,
    admit_to_icu,
    alert_summary,
    change_rate,
    chart_observation,
    chart_ventilation,
    cumulative_balance,
    device_days,
    discharge_from_icu,
    fasthug_compliance,
    fluid_balance,
    infusion_state,
    insert_device,
    overdue_devices,
    record_fluid,
    record_round,
    remove_device,
    reverse_fluid,
    score_sofa,
    set_ceiling_of_care,
    set_threshold,
    severity_trend,
    start_infusion,
    step_down_blockers,
    stop_infusion,
    thresholds_for,
    trend,
    unit_board,
    unit_summary,
    validate_observation,
    ventilator_days,
)
from apps.inpatient.models import Admission, Bed, Ward
from apps.organization.models import Facility
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ObservationSerializer(serializers.ModelSerializer):
    gcs_total = serializers.IntegerField(read_only=True)
    map_value = serializers.IntegerField(read_only=True)
    is_validated = serializers.BooleanField(read_only=True)

    class Meta:
        model = Observation
        fields = [
            "uuid", "recorded_at", "source", "device_identifier",
            "validated_by_name", "validated_at", "is_validated",
            "heart_rate", "systolic", "diastolic", "mean_arterial_pressure",
            "map_value", "respiratory_rate", "spo2", "temperature",
            "gcs_eye", "gcs_verbal", "gcs_motor", "gcs_verbal_not_testable",
            "gcs_total", "pupil_left_mm", "pupil_right_mm", "pupils_reactive",
            "rass", "pain_score", "blood_glucose", "lactate", "notes",
        ]
        read_only_fields = fields


class FluidEntrySerializer(serializers.ModelSerializer):
    signed_ml = serializers.IntegerField(read_only=True)
    is_reversed = serializers.SerializerMethodField()

    class Meta:
        model = FluidEntry
        fields = [
            "uuid", "recorded_at", "direction", "route", "volume_ml",
            "signed_ml", "description", "recorded_by_name", "is_reversed",
        ]
        read_only_fields = fields

    def get_is_reversed(self, obj) -> bool:
        return hasattr(obj, "reversed_by")


class InfusionRateSerializer(serializers.Serializer):
    rate = serializers.DecimalField(max_digits=8, decimal_places=3)
    changed_at = serializers.DateTimeField()
    reason = serializers.CharField()
    changed_by_name = serializers.CharField()


class InfusionSerializer(serializers.ModelSerializer):
    rates = InfusionRateSerializer(many=True, read_only=True)

    class Meta:
        model = Infusion
        fields = [
            "uuid", "drug_name", "concentration", "rate_unit", "route",
            "is_titratable", "target", "maximum_rate", "status", "started_at",
            "stopped_at", "stop_reason", "prescribed_by_name", "notes",
            "rates",
        ]
        read_only_fields = fields


class VentilationSerializer(serializers.ModelSerializer):
    pf_ratio = serializers.DecimalField(
        max_digits=8, decimal_places=0, read_only=True
    )
    driving_pressure = serializers.DecimalField(
        max_digits=5, decimal_places=1, read_only=True
    )

    class Meta:
        model = VentilationRecord
        fields = [
            "uuid", "recorded_at", "mode", "is_invasive", "set_rate",
            "set_tidal_volume", "peep", "pressure_support", "fio2",
            "measured_rate", "expired_tidal_volume", "peak_pressure",
            "plateau_pressure", "minute_volume", "etco2", "pao2", "paco2",
            "ph", "pf_ratio", "driving_pressure", "source", "notes",
        ]
        read_only_fields = fields


class DeviceSerializer(serializers.ModelSerializer):
    days_in_situ = serializers.DecimalField(
        max_digits=6, decimal_places=1, read_only=True
    )

    class Meta:
        model = InvasiveDevice
        fields = [
            "uuid", "device_type", "site", "size", "inserted_at",
            "inserted_by_name", "inserted_in_emergency", "removed_at",
            "removal_reason", "was_infected", "next_change_due",
            "days_in_situ", "notes",
        ]
        read_only_fields = fields


class AlertSerializer(serializers.ModelSerializer):
    is_acknowledged = serializers.BooleanField(read_only=True)
    minutes_to_acknowledge = serializers.IntegerField(read_only=True)

    class Meta:
        model = Alert
        fields = [
            "uuid", "raised_at", "severity", "parameter", "value",
            "threshold", "message", "from_unvalidated_device",
            "acknowledged_at", "acknowledged_by_name", "action_taken",
            "is_acknowledged", "minutes_to_acknowledge",
        ]
        read_only_fields = fields


class RoundSerializer(serializers.ModelSerializer):
    missed_items = serializers.ListField(read_only=True)
    negative_items = serializers.ListField(read_only=True)

    class Meta:
        model = Round
        fields = [
            "uuid", "round_at", "icu_day", "consultant_name", "assessment",
            "plan", "fasthug", "fasthug_reasons", "missed_items",
            "negative_items", "is_ready_for_sedation_hold",
            "is_ready_for_weaning_trial", "is_ready_for_step_down",
            "step_down_blockers", "family_updated", "family_update_notes",
        ]
        read_only_fields = fields


class StaySummarySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    admission = serializers.CharField(source="admission.reference", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    bed_code = serializers.CharField(source="bed.code", read_only=True, default="")
    hours = serializers.DecimalField(
        max_digits=8, decimal_places=1, read_only=True
    )
    icu_day = serializers.SerializerMethodField()

    class Meta:
        model = IcuStay
        fields = [
            "uuid", "patient_name", "patient_mrn", "admission", "ward_name",
            "bed_code", "admitted_at", "discharged_at", "hours", "icu_day",
            "route", "reason", "primary_diagnosis", "consultant_name",
            "outcome", "apache_ii", "is_for_resuscitation", "weight_kg",
        ]
        read_only_fields = fields

    def get_icu_day(self, obj) -> int:
        return icu_day_of(obj)


class StayDetailSerializer(StaySummarySerializer):
    observations = serializers.SerializerMethodField()
    infusions = serializers.SerializerMethodField()
    ventilation = serializers.SerializerMethodField()
    devices = DeviceSerializer(many=True, read_only=True)
    alerts = serializers.SerializerMethodField()
    rounds = RoundSerializer(many=True, read_only=True)
    balance = serializers.SerializerMethodField()
    ventilator = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField()
    sofa = serializers.SerializerMethodField()

    class Meta(StaySummarySerializer.Meta):
        fields = StaySummarySerializer.Meta.fields + [
            "height_cm", "ceiling_of_care", "ceiling_set_by", "ceiling_set_at",
            "outcome_notes", "notes", "observations", "infusions",
            "ventilation", "devices", "alerts", "rounds", "balance",
            "ventilator", "blockers", "sofa",
        ]
        read_only_fields = fields

    def get_observations(self, obj):
        # The last twenty-four charted sets. A chart is read backwards from
        # now; sending the whole stay would be megabytes by day four.
        return ObservationSerializer(
            obj.observations.order_by("-recorded_at")[:24], many=True,
        ).data

    def get_infusions(self, obj):
        return infusion_state(obj)

    def get_ventilation(self, obj):
        return VentilationSerializer(
            obj.ventilation.order_by("-recorded_at")[:12], many=True,
        ).data

    def get_alerts(self, obj):
        return AlertSerializer(
            obj.alerts.order_by("-raised_at")[:30], many=True,
        ).data

    def get_balance(self, obj):
        return fluid_balance(obj)

    def get_ventilator(self, obj):
        return ventilator_days(obj)

    def get_blockers(self, obj):
        return step_down_blockers(obj)

    def get_sofa(self, obj):
        return severity_trend(obj)


# -- inputs -----------------------------------------------------------------


class AdmitSerializer(serializers.Serializer):
    admission = serializers.UUIDField()
    ward = serializers.UUIDField()
    bed = serializers.UUIDField()
    reason = serializers.CharField(max_length=512)
    route = serializers.CharField(max_length=16, required=False, default="ward")
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
    )
    height_cm = serializers.IntegerField(required=False, allow_null=True)


class DischargeSerializer(serializers.Serializer):
    outcome = serializers.CharField(max_length=20)
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="",
    )
    bed = serializers.UUIDField(required=False, allow_null=True)
    #: Overriding is possible and is recorded. A unit under pressure steps a
    #: patient down on a low dose, and a system that simply refuses gets
    #: worked around by not charting the infusion.
    override_blockers = serializers.BooleanField(required=False, default=False)


class ObservationInputSerializer(serializers.Serializer):
    recorded_at = serializers.DateTimeField(required=False)
    source = serializers.CharField(max_length=12, required=False, default="manual")
    device_identifier = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    heart_rate = serializers.IntegerField(required=False, allow_null=True)
    systolic = serializers.IntegerField(required=False, allow_null=True)
    diastolic = serializers.IntegerField(required=False, allow_null=True)
    mean_arterial_pressure = serializers.IntegerField(
        required=False, allow_null=True
    )
    respiratory_rate = serializers.IntegerField(required=False, allow_null=True)
    spo2 = serializers.IntegerField(required=False, allow_null=True)
    temperature = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    gcs_eye = serializers.IntegerField(required=False, allow_null=True)
    gcs_verbal = serializers.IntegerField(required=False, allow_null=True)
    gcs_motor = serializers.IntegerField(required=False, allow_null=True)
    gcs_verbal_not_testable = serializers.BooleanField(
        required=False, default=False
    )
    pupil_left_mm = serializers.IntegerField(required=False, allow_null=True)
    pupil_right_mm = serializers.IntegerField(required=False, allow_null=True)
    pupils_reactive = serializers.BooleanField(required=False, allow_null=True)
    rass = serializers.IntegerField(required=False, allow_null=True)
    pain_score = serializers.IntegerField(required=False, allow_null=True)
    blood_glucose = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
    )
    lactate = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
    )
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class FluidInputSerializer(serializers.Serializer):
    direction = serializers.CharField(max_length=4)
    route = serializers.CharField(max_length=16)
    volume_ml = serializers.IntegerField(min_value=1)
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    recorded_at = serializers.DateTimeField(required=False)


class InfusionInputSerializer(serializers.Serializer):
    drug_name = serializers.CharField(max_length=255)
    rate = serializers.DecimalField(max_digits=8, decimal_places=3)
    concentration = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )
    rate_unit = serializers.CharField(max_length=32, required=False, default="ml/hr")
    is_titratable = serializers.BooleanField(required=False, default=False)
    target = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    maximum_rate = serializers.DecimalField(
        max_digits=8, decimal_places=3, required=False, allow_null=True,
    )


class RateChangeSerializer(serializers.Serializer):
    rate = serializers.DecimalField(max_digits=8, decimal_places=3)
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    stop = serializers.BooleanField(required=False, default=False)


class VentilationInputSerializer(serializers.Serializer):
    mode = serializers.CharField(max_length=16)
    recorded_at = serializers.DateTimeField(required=False)
    is_invasive = serializers.BooleanField(required=False, default=True)
    set_rate = serializers.IntegerField(required=False, allow_null=True)
    set_tidal_volume = serializers.IntegerField(required=False, allow_null=True)
    peep = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    pressure_support = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    fio2 = serializers.IntegerField(required=False, allow_null=True)
    measured_rate = serializers.IntegerField(required=False, allow_null=True)
    expired_tidal_volume = serializers.IntegerField(
        required=False, allow_null=True
    )
    peak_pressure = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    plateau_pressure = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
    )
    minute_volume = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
    )
    etco2 = serializers.IntegerField(required=False, allow_null=True)
    pao2 = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
    )
    paco2 = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
    )
    ph = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False, allow_null=True,
    )
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class DeviceInputSerializer(serializers.Serializer):
    device_type = serializers.CharField(max_length=24)
    site = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )
    size = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="",
    )
    in_emergency = serializers.BooleanField(required=False, default=False)
    change_after_days = serializers.IntegerField(required=False, allow_null=True)


class RoundInputSerializer(serializers.Serializer):
    assessment = serializers.CharField(
        max_length=4000, required=False, allow_blank=True, default="",
    )
    plan = serializers.CharField(
        max_length=4000, required=False, allow_blank=True, default="",
    )
    fasthug = serializers.DictField(required=False, default=dict)
    fasthug_reasons = serializers.DictField(required=False, default=dict)
    sedation_hold = serializers.BooleanField(required=False, allow_null=True)
    weaning_trial = serializers.BooleanField(required=False, allow_null=True)
    step_down = serializers.BooleanField(required=False, default=False)
    blockers = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    family_updated = serializers.BooleanField(required=False, default=False)
    family_notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class SofaInputSerializer(serializers.Serializer):
    """The three laboratory components, all optional.

    Optional on purpose: a score with gaps that names them is more useful than
    no score, and far more useful than one that scores the gaps as normal.
    """

    platelets = serializers.DecimalField(
        max_digits=6, decimal_places=1, required=False, allow_null=True,
    )
    bilirubin = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True,
    )
    creatinine = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True,
    )
    urine_ml_24h = serializers.IntegerField(required=False, allow_null=True)


class ThresholdInputSerializer(serializers.Serializer):
    parameter = serializers.CharField(max_length=48)
    reason = serializers.CharField(max_length=255)
    low = serializers.DecimalField(
        max_digits=7, decimal_places=2, required=False, allow_null=True,
    )
    high = serializers.DecimalField(
        max_digits=7, decimal_places=2, required=False, allow_null=True,
    )
    critical_low = serializers.DecimalField(
        max_digits=7, decimal_places=2, required=False, allow_null=True,
    )
    critical_high = serializers.DecimalField(
        max_digits=7, decimal_places=2, required=False, allow_null=True,
    )


class CeilingSerializer(serializers.Serializer):
    ceiling = serializers.CharField(max_length=255)
    for_resuscitation = serializers.BooleanField()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class IcuStayViewSet(viewsets.ReadOnlyModelViewSet):
    """A stay, its chart, and everything charted against it.

    Read-only as a model: a stay is created by `admit` and ended by
    `discharge`, both of which do far more than write a row.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        IcuStay, relations=["facility", "ward", "patient"],
        fields=["outcome", "route"],
    )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StayDetailSerializer
        return StaySummarySerializer

    def get_queryset(self):
        return (
            IcuStay.objects.select_related(
                "patient", "admission", "ward", "bed", "facility",
            )
            .prefetch_related("devices", "rounds")
            .order_by("-admitted_at")
        )

    def _writable(self):
        get_authorization(self.request).require("encounter.create", Scope.FACILITY)

    # -- the stay ---------------------------------------------------------

    @action(detail=False, methods=["post"], url_path="admit")
    def admit(self, request):
        self._writable()
        serializer = AdmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stay = admit_to_icu(
            request.organization,
            get_object_or_404(Admission, uuid=data["admission"]),
            get_object_or_404(Ward, uuid=data["ward"]),
            get_object_or_404(Bed, uuid=data["bed"]),
            reason=data["reason"],
            actor=request.user,
            route=data.get("route", "ward"),
        )
        if data.get("weight_kg") or data.get("height_cm"):
            stay.weight_kg = data.get("weight_kg")
            stay.height_cm = data.get("height_cm")
            stay.save(update_fields=["weight_kg", "height_cm", "updated_at"])
        return Response(
            StayDetailSerializer(stay).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="discharge")
    def discharge(self, request, uuid=None):
        self._writable()
        serializer = DischargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        stay = discharge_from_icu(
            self.get_object(),
            outcome=data["outcome"],
            actor=request.user,
            notes=data.get("notes", ""),
            bed=(
                get_object_or_404(Bed, uuid=data["bed"])
                if data.get("bed") else None
            ),
            override_blockers=data.get("override_blockers", False),
        )
        return Response(StayDetailSerializer(stay).data)

    @action(detail=True, methods=["get", "post"], url_path="ceiling")
    def ceiling(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response({
                "ceiling_of_care": stay.ceiling_of_care,
                "is_for_resuscitation": stay.is_for_resuscitation,
                "set_by": stay.ceiling_set_by,
                "set_at": stay.ceiling_set_at,
            })
        self._writable()
        serializer = CeilingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stay = set_ceiling_of_care(
            stay,
            ceiling=serializer.validated_data["ceiling"],
            actor=request.user,
            for_resuscitation=serializer.validated_data["for_resuscitation"],
        )
        return Response(StayDetailSerializer(stay).data)

    @action(detail=True, methods=["get"], url_path="blockers")
    def blockers(self, request, uuid=None):
        return Response(step_down_blockers(self.get_object()))

    # -- charting ---------------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="observations")
    def observations(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response(ObservationSerializer(
                stay.observations.order_by("-recorded_at")[:100], many=True,
            ).data)
        self._writable()
        serializer = ObservationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        observation = chart_observation(
            stay,
            actor=request.user,
            at=data.pop("recorded_at", None),
            source=data.pop("source", "manual"),
            device_identifier=data.pop("device_identifier", ""),
            **{key: value for key, value in data.items() if value is not None},
        )
        return Response(
            ObservationSerializer(observation).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True, methods=["post"],
        url_path="observations/(?P<observation>[^/.]+)/validate",
    )
    def validate_reading(self, request, uuid=None, observation=None):
        """A person confirms a device reading. The row stays either way."""
        self._writable()
        row = get_object_or_404(
            Observation, uuid=observation, stay=self.get_object(),
        )
        return Response(
            ObservationSerializer(
                validate_observation(row, actor=request.user)
            ).data
        )

    @action(detail=True, methods=["get"], url_path="trend")
    def parameter_trend(self, request, uuid=None):
        parameter = request.query_params.get("parameter", "heart_rate")
        hours = int(request.query_params.get("hours", 24))
        return Response({
            "parameter": parameter,
            "hours": hours,
            "points": trend(self.get_object(), parameter, hours=hours),
        })

    # -- fluids -----------------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="fluids")
    def fluids(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            hours = int(request.query_params.get("hours", 24))
            return Response({
                "balance": fluid_balance(stay, hours=hours),
                "cumulative": cumulative_balance(stay),
                "entries": FluidEntrySerializer(
                    stay.fluid_entries.order_by("-recorded_at")[:60], many=True,
                ).data,
            })
        self._writable()
        serializer = FluidInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entry = record_fluid(
            stay,
            direction=data["direction"],
            route=data["route"],
            volume_ml=data["volume_ml"],
            actor=request.user,
            description=data.get("description", ""),
            at=data.get("recorded_at"),
        )
        return Response(
            FluidEntrySerializer(entry).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True, methods=["post"],
        url_path="fluids/(?P<entry>[^/.]+)/reverse",
    )
    def reverse_entry(self, request, uuid=None, entry=None):
        """Correct a fluid entry by reversing it — never by editing it."""
        self._writable()
        row = get_object_or_404(FluidEntry, uuid=entry, stay=self.get_object())
        return Response(
            FluidEntrySerializer(
                reverse_fluid(
                    row, actor=request.user,
                    reason=request.data.get("reason", ""),
                )
            ).data,
            status=status.HTTP_201_CREATED,
        )

    # -- infusions --------------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="infusions")
    def infusions(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response({
                "running": infusion_state(stay),
                "all": InfusionSerializer(
                    stay.infusions.prefetch_related("rates"), many=True,
                ).data,
            })
        self._writable()
        serializer = InfusionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        infusion = start_infusion(
            stay,
            drug_name=data["drug_name"],
            rate=data["rate"],
            actor=request.user,
            concentration=data.get("concentration", ""),
            rate_unit=data.get("rate_unit", "ml/hr"),
            is_titratable=data.get("is_titratable", False),
            target=data.get("target", ""),
            maximum_rate=data.get("maximum_rate"),
        )
        return Response(
            InfusionSerializer(infusion).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True, methods=["post"],
        url_path="infusions/(?P<infusion>[^/.]+)/rate",
    )
    def rate(self, request, uuid=None, infusion=None):
        """Titrate, or stop. Both append; neither edits."""
        self._writable()
        row = get_object_or_404(Infusion, uuid=infusion, stay=self.get_object())
        serializer = RateChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get("stop"):
            stop_infusion(row, actor=request.user, reason=data.get("reason", ""))
        else:
            change_rate(
                row, data["rate"], actor=request.user,
                reason=data.get("reason", ""),
            )
        row.refresh_from_db()
        return Response(InfusionSerializer(row).data)

    # -- ventilation ------------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="ventilation")
    def ventilation(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response({
                "summary": ventilator_days(stay),
                "records": VentilationSerializer(
                    stay.ventilation.order_by("-recorded_at")[:50], many=True,
                ).data,
            })
        self._writable()
        serializer = VentilationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        record = chart_ventilation(
            stay,
            mode=data.pop("mode"),
            actor=request.user,
            at=data.pop("recorded_at", None),
            **{key: value for key, value in data.items() if value is not None},
        )
        return Response(
            VentilationSerializer(record).data, status=status.HTTP_201_CREATED
        )

    # -- lines and tubes --------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="devices")
    def devices(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response({
                "devices": DeviceSerializer(
                    stay.devices.order_by("-inserted_at"), many=True,
                ).data,
                "overdue": overdue_devices(stay),
            })
        self._writable()
        serializer = DeviceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        device = insert_device(
            stay,
            device_type=data["device_type"],
            actor=request.user,
            site=data.get("site", ""),
            size=data.get("size", ""),
            in_emergency=data.get("in_emergency", False),
            change_after_days=data.get("change_after_days"),
        )
        return Response(
            DeviceSerializer(device).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True, methods=["post"],
        url_path="devices/(?P<device>[^/.]+)/remove",
    )
    def remove(self, request, uuid=None, device=None):
        self._writable()
        row = get_object_or_404(
            InvasiveDevice, uuid=device, stay=self.get_object(),
        )
        return Response(DeviceSerializer(
            remove_device(
                row, actor=request.user,
                reason=request.data.get("reason", ""),
                infected=bool(request.data.get("infected", False)),
            )
        ).data)

    # -- alerts -----------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="alerts")
    def alerts(self, request, uuid=None):
        stay = self.get_object()
        hours = int(request.query_params.get("hours", 24))
        return Response({
            "summary": alert_summary(stay, hours=hours),
            "alerts": AlertSerializer(
                stay.alerts.order_by("-raised_at")[:100], many=True,
            ).data,
            "thresholds": {
                parameter: {
                    key: (str(value) if isinstance(value, Decimal) else value)
                    for key, value in limits.items()
                }
                for parameter, limits in thresholds_for(stay).items()
            },
        })

    @action(
        detail=True, methods=["post"],
        url_path="alerts/(?P<alert>[^/.]+)/acknowledge",
    )
    def acknowledge(self, request, uuid=None, alert=None):
        self._writable()
        row = get_object_or_404(Alert, uuid=alert, stay=self.get_object())
        return Response(AlertSerializer(
            acknowledge_alert(
                row, actor=request.user,
                action=request.data.get("action", ""),
            )
        ).data)

    @action(detail=True, methods=["post"], url_path="thresholds")
    def thresholds(self, request, uuid=None):
        self._writable()
        serializer = ThresholdInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        threshold = set_threshold(
            self.get_object(),
            parameter=data.pop("parameter"),
            actor=request.user,
            reason=data.pop("reason"),
            **data,
        )
        return Response({"parameter": threshold.parameter, "set": True})

    # -- rounds and scoring -----------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="rounds")
    def rounds(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response({
                "rounds": RoundSerializer(
                    stay.rounds.order_by("-icu_day"), many=True,
                ).data,
                #: The checklist template, so the client renders the items
                #: rather than hard-coding them. A daily-goals list that lives
                #: in a React component cannot be audited.
                "items": [
                    {"key": key, "label": label} for key, label in FASTHUG_ITEMS
                ],
            })
        self._writable()
        serializer = RoundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        row = record_round(
            stay,
            actor=request.user,
            assessment=data.pop("assessment", ""),
            plan=data.pop("plan", ""),
            fasthug=data.pop("fasthug", {}),
            fasthug_reasons=data.pop("fasthug_reasons", {}),
            **data,
        )
        return Response(
            RoundSerializer(row).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="sofa")
    def sofa(self, request, uuid=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response(severity_trend(stay))
        self._writable()
        serializer = SofaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        score = score_sofa(stay, **serializer.validated_data)
        return Response({
            "icu_day": score.icu_day,
            "total": score.total,
            "components": score.components,
            "missing": score.missing_components,
            "complete": score.is_complete,
        }, status=status.HTTP_201_CREATED)


class UnitBoardView(APIView):
    """Every occupied bed in one unit, sickest and least-attended first."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        ward = get_object_or_404(Ward, uuid=request.query_params.get("ward"))
        return Response(unit_board(ward))


class UnitSummaryView(APIView):
    """Occupancy, support, outcome and readmission for a facility's units."""

    permission_classes = [IsAuthenticated, HasPermission.of("report.view")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response({
            "unit": unit_summary(facility),
            "devices": device_days(facility),
            "fasthug": fasthug_compliance(facility),
        })
