"""Serializers for prescriptions."""

from rest_framework import serializers

# UUIDRelatedField: foreign keys are published as the related object's
# uuid, never as the internal integer id. With a database per tenant,
# id 42 is a different row in every tenant -- see apps/common/fields.py.
from apps.common.fields import UUIDRelatedField

from apps.prescriptions.models import (
    DoseRoute,
    Frequency,
    Prescription,
    PrescriptionLine,
)


class PrescriptionLineSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    sig = serializers.CharField(read_only=True)

    class Meta:
        model = PrescriptionLine
        fields = (
            "uuid", "product_uuid", "generic_name", "brand_name", "strength",
            "dosage_form", "display_name", "dose", "route", "frequency",
            "duration_days", "is_prn", "prn_indication", "max_doses_per_day",
            "instructions", "quantity", "quantity_unit", "sig", "start_date",
            "end_date", "status", "discontinued_at", "discontinuation_reason",
            "allow_substitution", "warnings", "display_order",
        )
        read_only_fields = (
            "uuid", "display_name", "sig", "warnings", "discontinued_at",
        )


class PrescriptionLineInputSerializer(serializers.Serializer):
    """One medicine as the prescriber enters it.

    `generic_name` is required and `brand_name` is not, which is the right way
    round: prescribing generically is the norm, and a brand is an optional
    refinement rather than the identity of the drug.
    """

    product_uuid = serializers.UUIDField(required=False, allow_null=True)
    generic_name = serializers.CharField(max_length=255)
    brand_name = serializers.CharField(required=False, allow_blank=True, default="")
    strength = serializers.CharField(required=False, allow_blank=True, default="")
    dosage_form = serializers.CharField(required=False, allow_blank=True, default="")

    dose = serializers.CharField(max_length=64)
    route = serializers.ChoiceField(choices=DoseRoute.choices, default=DoseRoute.ORAL)
    frequency = serializers.ChoiceField(choices=Frequency.choices, default=Frequency.BD)
    duration_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=365
    )

    is_prn = serializers.BooleanField(required=False, default=False)
    prn_indication = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    max_doses_per_day = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )

    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    quantity_unit = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    allow_substitution = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if attrs.get("is_prn") and not attrs.get("prn_indication"):
            raise serializers.ValidationError(
                {
                    "prn_indication":
                        "An as-required medicine must say what it is required for."
                }
            )
        # A course with neither a duration nor an end date has no stopping
        # point, which is how patients end up on antibiotics for months.
        if not attrs.get("is_prn") and not attrs.get("duration_days") and not attrs.get(
            "end_date"
        ):
            raise serializers.ValidationError(
                {
                    "duration_days":
                        "Give a duration or an end date, or mark the medicine "
                        "as required (PRN)."
                }
            )
        return attrs


class PrescriptionSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    lines = PrescriptionLineSerializer(many=True, read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    encounter_reference = serializers.CharField(
        source="encounter.reference", read_only=True, default=None
    )
    supersedes_reference = serializers.CharField(
        source="supersedes.reference", read_only=True, default=None
    )
    is_dispensable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Prescription
        fields = (
            "uuid", "reference", "patient", "patient_mrn", "patient_name",
            "encounter_reference", "facility_name", "prescriber_name",
            "prescriber_registration", "status", "prescribed_at",
            "valid_until", "version", "supersedes_reference",
            "revision_reason", "safety_checks", "has_overridden_warning",
            "override_reason", "is_signed", "signed_at", "is_dispensable",
            "notes", "patient_instructions", "lines",
        )
        read_only_fields = fields


class PrescriptionCreateSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    encounter_uuid = serializers.UUIDField(required=False, allow_null=True)
    lines = PrescriptionLineInputSerializer(many=True, min_length=1)
    prescriber_name = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    prescriber_registration = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    patient_instructions = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    valid_days = serializers.IntegerField(required=False, default=30, min_value=1)
    #: Required when the safety checks raise a high or critical warning. The
    #: server enforces this; the field is optional here so the first attempt
    #: can come back with the warnings to show.
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    sign = serializers.BooleanField(required=False, default=True)


class PrescriptionPreviewSerializer(serializers.Serializer):
    """Ask what warnings a prescription would raise. Writes nothing."""

    patient_uuid = serializers.UUIDField()
    lines = PrescriptionLineInputSerializer(many=True, min_length=1)


class PrescriptionReviseSerializer(serializers.Serializer):
    lines = PrescriptionLineInputSerializer(many=True, min_length=1)
    reason = serializers.CharField(min_length=5)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class DiscontinueLineSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)
