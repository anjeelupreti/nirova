"""Serializers for the patient master."""

from rest_framework import serializers

from apps.patients.models import (
    IdentifierType,
    Patient,
    PatientAllergy,
    PatientCondition,
    PatientIdentifier,
)


class PatientIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientIdentifier
        fields = (
            "uuid", "identifier_type", "value", "issued_by", "issued_on",
            "expires_on", "is_verified", "verified_at", "document_url",
        )
        read_only_fields = ("uuid", "verified_at")


class PatientAllergySerializer(serializers.ModelSerializer):
    blocks_prescribing = serializers.BooleanField(read_only=True)

    class Meta:
        model = PatientAllergy
        fields = (
            "uuid", "substance", "substance_code", "category", "reaction",
            "severity", "status", "onset_date", "notes", "blocks_prescribing",
        )
        read_only_fields = ("uuid", "blocks_prescribing")


class PatientConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientCondition
        fields = (
            "uuid", "name", "icd10_code", "category", "status",
            "onset_date", "resolved_date", "notes",
        )
        read_only_fields = ("uuid",)


class PatientListSerializer(serializers.ModelSerializer):
    """The lean shape for search results and lists.

    Deliberately excludes allergies, conditions and identifiers: a list of
    fifty patients should not carry fifty patients' clinical detail across the
    wire, and most of it would not be rendered.
    """

    full_name = serializers.CharField(read_only=True)
    age_years = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = (
            "uuid", "mrn", "full_name", "gender", "age_years", "date_of_birth",
            "phone", "district", "municipality", "category", "status",
            "registered_on", "blood_group",
        )
        read_only_fields = fields


class PatientDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age_years = serializers.IntegerField(read_only=True)
    is_minor = serializers.BooleanField(read_only=True)
    is_merged = serializers.BooleanField(read_only=True)
    identifiers = PatientIdentifierSerializer(many=True, read_only=True)
    allergies = PatientAllergySerializer(many=True, read_only=True)
    conditions = PatientConditionSerializer(many=True, read_only=True)
    merged_into_mrn = serializers.CharField(
        source="merged_into.mrn", read_only=True, default=None
    )

    class Meta:
        model = Patient
        fields = (
            "uuid", "mrn", "first_name", "middle_name", "last_name",
            "full_name", "full_name_nepali", "gender", "date_of_birth",
            "is_dob_estimated", "stated_age_years", "stated_age_months",
            "age_years", "is_minor", "marital_status", "blood_group",
            "occupation", "nationality", "ethnicity", "religion",
            "preferred_language", "phone", "alternate_phone", "email",
            "province", "district", "municipality", "ward", "tole",
            "temporary_address", "guardian_name", "guardian_relationship",
            "guardian_phone", "is_guardian_required",
            "relationship_to_family_head", "category", "corporate_account",
            "insurance_policy_number", "registered_on", "referred_by",
            "status", "date_of_death", "alerts", "notes",
            "consent_sms", "consent_email", "consent_marketing",
            "is_merged", "merged_into_mrn", "photo_url",
            "identifiers", "allergies", "conditions",
        )
        read_only_fields = (
            "uuid", "mrn", "registered_on", "status", "is_merged",
            "merged_into_mrn", "full_name", "age_years", "is_minor",
        )


class IdentifierInputSerializer(serializers.Serializer):
    identifier_type = serializers.ChoiceField(choices=IdentifierType.choices)
    value = serializers.CharField(max_length=128)


class PatientRegistrationSerializer(serializers.Serializer):
    """What registration accepts.

    Only a name and a gender are strictly required. That is deliberate: an
    unconscious patient brought in by a stranger has no phone number, no
    address and no documents, and the system must not be the reason they
    cannot be registered and treated.
    """

    first_name = serializers.CharField(max_length=128)
    middle_name = serializers.CharField(max_length=128, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=128)
    full_name_nepali = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    gender = serializers.CharField(max_length=16)

    date_of_birth = serializers.DateField(required=False, allow_null=True)
    is_dob_estimated = serializers.BooleanField(required=False, default=False)
    stated_age_years = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=130
    )
    stated_age_months = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=11
    )

    marital_status = serializers.CharField(required=False, allow_blank=True)
    blood_group = serializers.CharField(required=False, allow_blank=True)
    occupation = serializers.CharField(required=False, allow_blank=True)
    nationality = serializers.CharField(required=False, allow_blank=True)
    preferred_language = serializers.CharField(required=False, allow_blank=True)

    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    alternate_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True
    )
    email = serializers.EmailField(required=False, allow_blank=True)

    province = serializers.CharField(required=False, allow_blank=True)
    district = serializers.CharField(required=False, allow_blank=True)
    municipality = serializers.CharField(required=False, allow_blank=True)
    ward = serializers.CharField(required=False, allow_blank=True)
    tole = serializers.CharField(required=False, allow_blank=True)

    guardian_name = serializers.CharField(required=False, allow_blank=True)
    guardian_relationship = serializers.CharField(required=False, allow_blank=True)
    guardian_phone = serializers.CharField(required=False, allow_blank=True)

    category = serializers.CharField(required=False, allow_blank=True)
    referred_by = serializers.CharField(required=False, allow_blank=True)
    alerts = serializers.CharField(required=False, allow_blank=True)

    consent_sms = serializers.BooleanField(required=False, default=True)

    identifiers = IdentifierInputSerializer(many=True, required=False, default=list)
    facility_uuid = serializers.UUIDField(required=False, allow_null=True)
    #: Register anyway, having reviewed the duplicate candidates.
    force = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        # Age is needed for dosing and for triage. Either form is acceptable,
        # but having neither makes the record clinically weak, so it is
        # refused at the point where someone can still ask the patient.
        if not attrs.get("date_of_birth") and attrs.get("stated_age_years") is None:
            raise serializers.ValidationError(
                {
                    "date_of_birth":
                        "Give a date of birth, or an approximate age in years."
                }
            )
        return attrs


class PatientMergeSerializer(serializers.Serializer):
    duplicate_uuid = serializers.UUIDField()
    reason = serializers.CharField(min_length=10)
    matched_on = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
