"""Serializers for diagnostics."""

from rest_framework import serializers

from apps.diagnostics.models import (
    CriticalValueAlert,
    DiagnosticModality,
    DiagnosticOrder,
    DiagnosticResult,
    OrderPriority,
    ReferenceRange,
    SpecimenType,
    TestDefinition,
)


class ReferenceRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceRange
        fields = (
            "uuid", "applies_to_sex", "min_age_years", "max_age_years",
            "normal_low", "normal_high", "critical_low", "critical_high",
            "normal_value", "note",
        )
        read_only_fields = ("uuid",)


class TestDefinitionSerializer(serializers.ModelSerializer):
    reference_ranges = ReferenceRangeSerializer(many=True, read_only=True)
    needs_specimen = serializers.BooleanField(read_only=True)
    component_codes = serializers.SerializerMethodField()

    class Meta:
        model = TestDefinition
        fields = (
            "uuid", "code", "name", "short_name", "modality", "department",
            "is_panel", "parent", "component_codes", "result_data_type",
            "unit", "allowed_values", "decimal_places", "specimen_type",
            "needs_specimen", "collection_instructions",
            "patient_preparation", "turnaround_minutes", "is_outsourced",
            "outsource_partner", "service_uuid", "is_active",
            "reference_ranges",
        )
        read_only_fields = ("uuid", "needs_specimen", "component_codes")

    def get_component_codes(self, obj) -> list:
        return list(obj.components.values_list("code", flat=True))


class DiagnosticResultSerializer(serializers.ModelSerializer):
    display_value = serializers.CharField(read_only=True)
    is_abnormal = serializers.BooleanField(read_only=True)
    is_critical = serializers.BooleanField(read_only=True)
    was_amended = serializers.SerializerMethodField()

    class Meta:
        model = DiagnosticResult
        fields = (
            "uuid", "analyte_code", "analyte_name", "numeric_value",
            "text_value", "coded_value", "display_value", "unit",
            "reference_text", "flag", "is_abnormal", "is_critical",
            "entered_by_name", "entered_at", "is_verified", "verified_at",
            "was_amended", "amendment_reason", "is_superseded",
            "instrument", "method", "notes", "display_order",
        )
        read_only_fields = fields

    def get_was_amended(self, obj) -> bool:
        return obj.supersedes_id is not None


class CriticalValueAlertSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    analyte = serializers.CharField(source="result.analyte_name", read_only=True)
    minutes_outstanding = serializers.IntegerField(read_only=True)

    class Meta:
        model = CriticalValueAlert
        fields = (
            "uuid", "patient_mrn", "patient_name", "order_reference",
            "analyte", "value", "flag", "threshold", "status", "raised_at",
            "notified_person", "notified_via", "notified_at",
            "acknowledged_at", "action_taken", "minutes_outstanding",
        )
        read_only_fields = fields


class DiagnosticOrderListSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    turnaround_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = DiagnosticOrder
        fields = (
            "uuid", "reference", "patient", "patient_mrn", "patient_name",
            "test_code", "test_name", "modality", "priority", "status",
            "clinical_indication", "ordered_by_name", "ordered_at", "due_at",
            "accession_number", "collected_at", "released_at",
            "is_open", "is_overdue", "turnaround_minutes",
        )
        read_only_fields = fields


class DiagnosticOrderDetailSerializer(DiagnosticOrderListSerializer):
    results = serializers.SerializerMethodField()
    critical_alerts = CriticalValueAlertSerializer(many=True, read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    encounter_reference = serializers.CharField(
        source="encounter.reference", read_only=True, default=None
    )
    collection_to_result_minutes = serializers.IntegerField(read_only=True)

    class Meta(DiagnosticOrderListSerializer.Meta):
        fields = DiagnosticOrderListSerializer.Meta.fields + (
            "facility_name", "encounter_reference", "clinical_notes",
            "specimen_type", "collected_by_name", "received_at",
            "rejection_reason", "resulted_at", "verified_by_name",
            "verified_at", "collection_to_result_minutes",
            "results", "critical_alerts",
        )
        read_only_fields = fields

    def get_results(self, obj) -> list:
        """Current results only. Superseded rows stay in the audit trail.

        A clinician reading a chart wants the value that stands; the
        amendment history is reachable but is not the headline.
        """
        current = obj.results.filter(is_superseded=False).order_by(
            "display_order", "analyte_name"
        )
        return DiagnosticResultSerializer(current, many=True).data


class PlaceOrderSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    test_uuid = serializers.UUIDField()
    encounter_uuid = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(
        choices=OrderPriority.choices, default=OrderPriority.ROUTINE
    )
    clinical_indication = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    clinical_notes = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        # Mirrors the service-layer rule so the client gets a field error
        # rather than a generic domain error. The service still enforces it —
        # this is convenience, not the guard.
        if attrs["priority"] != OrderPriority.ROUTINE and not attrs.get(
            "clinical_indication", ""
        ).strip():
            raise serializers.ValidationError(
                {
                    "clinical_indication":
                        "An urgent or STAT request must say what is being "
                        "looked for."
                }
            )
        return attrs


class CollectSpecimenSerializer(serializers.Serializer):
    specimen_type = serializers.ChoiceField(
        choices=SpecimenType.choices, required=False, allow_blank=True, default=""
    )


class RejectSpecimenSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class ResultEntrySerializer(serializers.Serializer):
    #: Omitted for a single test; required for each analyte of a panel.
    analyte_code = serializers.CharField(required=False, allow_blank=True)
    value = serializers.CharField()
    unit = serializers.CharField(required=False, allow_blank=True, default="")
    instrument = serializers.CharField(required=False, allow_blank=True, default="")
    method = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class EnterResultsSerializer(serializers.Serializer):
    results = ResultEntrySerializer(many=True, min_length=1)


class AmendResultSerializer(serializers.Serializer):
    value = serializers.CharField()
    reason = serializers.CharField(min_length=5)


class NotifyCriticalSerializer(serializers.Serializer):
    person = serializers.CharField(min_length=2)
    via = serializers.CharField(required=False, allow_blank=True, default="telephone")


class AcknowledgeCriticalSerializer(serializers.Serializer):
    action_taken = serializers.CharField(min_length=5)


class WorklistQuerySerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    modality = serializers.ChoiceField(
        choices=DiagnosticModality.choices, required=False, allow_blank=True
    )
    status = serializers.CharField(required=False, allow_blank=True)
