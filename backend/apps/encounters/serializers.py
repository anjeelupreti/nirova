"""Serializers for encounters, vitals, notes and diagnoses."""

from decimal import Decimal

from rest_framework import serializers

from apps.encounters.models import (
    ClinicalNote,
    Diagnosis,
    Encounter,
    EncounterType,
    NoteType,
    VitalSigns,
)


class VitalSignsSerializer(serializers.ModelSerializer):
    blood_pressure = serializers.CharField(read_only=True)
    bmi = serializers.FloatField(read_only=True)
    abnormal = serializers.SerializerMethodField()

    class Meta:
        model = VitalSigns
        fields = (
            "uuid", "recorded_at", "recorded_by_name", "temperature_c",
            "pulse_bpm", "respiratory_rate", "systolic_bp", "diastolic_bp",
            "blood_pressure", "spo2_percent", "on_room_air", "oxygen_flow_lpm",
            "weight_kg", "height_cm", "head_circumference_cm", "bmi",
            "blood_glucose_mmol", "pain_score", "gcs_total", "notes",
            "abnormal",
        )
        read_only_fields = (
            "uuid", "recorded_at", "recorded_by_name", "blood_pressure",
            "bmi", "abnormal",
        )

    def get_abnormal(self, obj) -> list:
        return obj.abnormal_flags()


class VitalSignsInputSerializer(serializers.Serializer):
    """Every field optional — a triage temperature is a valid set of vitals."""

    temperature_c = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
        min_value=Decimal("25"), max_value=Decimal("45"),
    )
    pulse_bpm = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=300
    )
    respiratory_rate = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=99
    )
    systolic_bp = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=300
    )
    diastolic_bp = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=250
    )
    spo2_percent = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=100
    )
    on_room_air = serializers.BooleanField(required=False, default=True)
    oxygen_flow_lpm = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True
    )
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
        min_value=Decimal("0"), max_value=Decimal("500"),
    )
    height_cm = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
        min_value=Decimal("0"), max_value=Decimal("280"),
    )
    head_circumference_cm = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True
    )
    blood_glucose_mmol = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True
    )
    pain_score = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=10
    )
    gcs_total = serializers.IntegerField(
        required=False, allow_null=True, min_value=3, max_value=15
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        # A blood pressure is a pair. One half of it is not a reading, and
        # storing it would produce a record nobody can interpret.
        systolic = attrs.get("systolic_bp")
        diastolic = attrs.get("diastolic_bp")
        if (systolic is None) != (diastolic is None):
            raise serializers.ValidationError(
                {"systolic_bp": "Record both systolic and diastolic, or neither."}
            )
        if systolic is not None and diastolic is not None and diastolic >= systolic:
            raise serializers.ValidationError(
                {"diastolic_bp": "Diastolic pressure must be below systolic."}
            )
        if not attrs.get("on_room_air", True) and not attrs.get("oxygen_flow_lpm"):
            raise serializers.ValidationError(
                {"oxygen_flow_lpm": "State the oxygen flow rate when not on air."}
            )
        return attrs


class ClinicalNoteSerializer(serializers.ModelSerializer):
    is_amendment = serializers.BooleanField(read_only=True)
    amends_uuid = serializers.UUIDField(source="amends.uuid", read_only=True,
                                        default=None)

    class Meta:
        model = ClinicalNote
        fields = (
            "uuid", "note_type", "subjective", "objective", "assessment",
            "plan", "body", "author_name", "author_role", "is_signed",
            "signed_at", "is_amendment", "amends_uuid", "amendment_reason",
            "created_at",
        )
        read_only_fields = (
            "uuid", "author_name", "is_signed", "signed_at", "is_amendment",
            "amends_uuid", "created_at",
        )


class ClinicalNoteInputSerializer(serializers.Serializer):
    note_type = serializers.ChoiceField(
        choices=NoteType.choices, default=NoteType.SOAP
    )
    subjective = serializers.CharField(required=False, allow_blank=True, default="")
    objective = serializers.CharField(required=False, allow_blank=True, default="")
    assessment = serializers.CharField(required=False, allow_blank=True, default="")
    plan = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField(required=False, allow_blank=True, default="")
    author_role = serializers.CharField(required=False, allow_blank=True, default="")
    sign = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not any(
            attrs.get(field)
            for field in ("subjective", "objective", "assessment", "plan", "body")
        ):
            raise serializers.ValidationError("A note cannot be empty.")
        return attrs


class NoteAmendmentSerializer(ClinicalNoteInputSerializer):
    reason = serializers.CharField(min_length=5)


class DiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model = Diagnosis
        fields = (
            "uuid", "name", "icd10_code", "certainty", "is_primary",
            "is_chronic", "onset_date", "notes", "diagnosed_by_name",
            "promoted_to_condition", "created_at",
        )
        read_only_fields = (
            "uuid", "diagnosed_by_name", "promoted_to_condition", "created_at",
        )


class DiagnosisInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    icd10_code = serializers.CharField(required=False, allow_blank=True, default="")
    certainty = serializers.CharField(required=False, allow_blank=True,
                                      default="working")
    is_primary = serializers.BooleanField(required=False, default=False)
    is_chronic = serializers.BooleanField(required=False, default=False)
    onset_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class EncounterListSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Encounter
        fields = (
            "uuid", "reference", "patient", "patient_mrn", "patient_name",
            "encounter_type", "status", "facility_name", "provider_name",
            "chief_complaint", "triage_category", "started_at", "ended_at",
            "duration_minutes", "is_open", "disposition", "is_signed",
        )
        read_only_fields = fields


class EncounterDetailSerializer(EncounterListSerializer):
    vitals = VitalSignsSerializer(many=True, read_only=True)
    notes = ClinicalNoteSerializer(many=True, read_only=True)
    diagnoses = DiagnosisSerializer(many=True, read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )

    class Meta(EncounterListSerializer.Meta):
        fields = EncounterListSerializer.Meta.fields + (
            "department_name", "disposition_notes", "follow_up_date",
            "follow_up_instructions", "signed_at", "vitals", "notes",
            "diagnoses",
        )
        read_only_fields = fields


class StartEncounterSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    encounter_type = serializers.ChoiceField(
        choices=EncounterType.choices, default=EncounterType.OUTPATIENT
    )
    department_uuid = serializers.UUIDField(required=False, allow_null=True)
    appointment_uuid = serializers.UUIDField(required=False, allow_null=True)
    queue_token_uuid = serializers.UUIDField(required=False, allow_null=True)
    provider_uuid = serializers.UUIDField(required=False, allow_null=True)
    provider_name = serializers.CharField(required=False, allow_blank=True, default="")
    chief_complaint = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    triage_category = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=5
    )


class CloseEncounterSerializer(serializers.Serializer):
    disposition = serializers.ChoiceField(
        choices=[
            "discharged", "admitted", "referred", "transferred",
            "observation", "absconded", "died",
        ],
        default="discharged",
    )
    disposition_notes = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    follow_up_date = serializers.DateField(required=False, allow_null=True)
    follow_up_instructions = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    sign = serializers.BooleanField(required=False, default=True)
