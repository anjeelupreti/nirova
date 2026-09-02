"""Serializers for people.

Salary is the one field on this module that is not simply "sensitive" but
actively dangerous to leak: an HR list endpoint that includes pay would put
every colleague's salary in front of anyone who can view the team. So
contract terms live on their own serializer behind their own permission, and
the employee serializers never carry them.
"""

from rest_framework import serializers

# UUIDRelatedField: foreign keys are published as the related object's uuid.
# With a database per tenant, `id` 42 is a different row in every tenant --
# see apps/common/fields.py.
from apps.common.fields import UUIDRelatedField
from apps.hr.models import (
    Credential,
    Employee,
    EmployeeDocument,
    EmploymentContract,
    EmploymentEvent,
    Experience,
    Position,
    Skill,
)


class PositionSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    reports_to = UUIDRelatedField(read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True
    )
    filled = serializers.IntegerField(read_only=True)
    vacancies = serializers.IntegerField(read_only=True)

    class Meta:
        model = Position
        fields = (
            "uuid", "code", "title", "title_nepali", "facility",
            "facility_name", "department", "department_name", "grade",
            "reports_to", "budgeted_headcount", "filled", "vacancies",
            "job_description", "is_clinical", "is_provider",
            "requires_licence", "is_active",
        )
        read_only_fields = ("uuid", "filled", "vacancies", "facility_name",
                            "department_name")


class CredentialSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True, allow_null=True)
    blocks_practice = serializers.BooleanField(read_only=True)

    class Meta:
        model = Credential
        fields = (
            "uuid", "employee", "credential_type", "name", "issuing_body",
            "reference_number", "issued_on", "expires_on", "is_expired",
            "days_to_expiry", "blocks_practice", "verification_status",
            "verified_by_name", "verified_at", "verification_notes",
            "document_url", "notes",
        )
        read_only_fields = (
            "uuid", "employee", "is_expired", "days_to_expiry",
            "blocks_practice", "verification_status", "verified_by_name",
            "verified_at", "verification_notes",
        )


class ExperienceSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    months = serializers.IntegerField(read_only=True)
    years = serializers.DecimalField(
        max_digits=5, decimal_places=1, read_only=True
    )

    class Meta:
        model = Experience
        fields = (
            "uuid", "employee", "organization_name", "job_title", "department",
            "started_on", "ended_on", "months", "years", "responsibilities",
            "reference_name", "reference_contact", "is_verified",
            "document_url",
        )
        read_only_fields = ("uuid", "employee", "months", "years",
                            "is_verified")


class SkillSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)

    class Meta:
        model = Skill
        fields = (
            "uuid", "employee", "name", "level", "assessed_on",
            "assessed_by_name", "notes",
        )
        read_only_fields = ("uuid", "employee", "assessed_by_name")


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = EmployeeDocument
        fields = (
            "uuid", "employee", "document_type", "title", "file_url",
            "file_name", "content_type", "size_bytes", "expires_on",
            "is_expired", "is_mandatory", "notes",
        )
        read_only_fields = ("uuid", "employee", "is_expired")


class EmploymentEventSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    summary = serializers.CharField(read_only=True)

    class Meta:
        model = EmploymentEvent
        fields = (
            "uuid", "employee", "event_type", "effective_on", "summary",
            "from_position", "to_position", "from_facility", "to_facility",
            "from_department", "to_department", "from_employment_type",
            "to_employment_type", "reason", "approved_by_name", "notes",
            "created_at",
        )
        read_only_fields = fields


class EmploymentContractSerializer(serializers.ModelSerializer):
    """Pay. Served only to holders of `salary.read`."""

    employee = UUIDRelatedField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True, allow_null=True)
    gross_monthly = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = EmploymentContract
        fields = (
            "uuid", "employee", "reference", "employment_type", "starts_on",
            "ends_on", "is_expired", "days_to_expiry", "notice_period_days",
            "basic_salary", "rate_basis", "allowances", "gross_monthly",
            "working_hours_per_week", "status", "signed_on", "document_url",
            "notes",
        )
        read_only_fields = ("uuid", "employee", "is_expired", "days_to_expiry",
                            "gross_monthly")


class EmployeeListSerializer(serializers.ModelSerializer):
    """The directory row. Deliberately narrow.

    No salary, no citizenship number, no home address — a colleague looking
    somebody up needs a name, a job and a phone extension, and a list endpoint
    that carried the rest would leak it to every holder of `employee.read`.
    """

    position = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(
        source="position.title", read_only=True, default=""
    )
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=""
    )
    is_working = serializers.BooleanField(read_only=True)
    is_provider = serializers.BooleanField(read_only=True)

    class Meta:
        model = Employee
        fields = (
            "uuid", "employee_code", "full_name", "first_name", "last_name",
            "position", "position_title", "facility", "facility_name",
            "department", "department_name", "employment_type", "status",
            "is_working", "is_provider", "joined_on", "phone", "work_email",
            "photo_url",
        )
        read_only_fields = fields


class EmployeeDetailSerializer(serializers.ModelSerializer):
    position = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    reports_to = UUIDRelatedField(read_only=True)

    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(
        source="position.title", read_only=True, default=""
    )
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=""
    )
    manager_name = serializers.CharField(
        source="reports_to.full_name", read_only=True, default=""
    )
    is_working = serializers.BooleanField(read_only=True)
    is_provider = serializers.BooleanField(read_only=True)
    on_probation = serializers.BooleanField(read_only=True)
    probation_overdue = serializers.BooleanField(read_only=True)
    years_of_service = serializers.DecimalField(
        max_digits=5, decimal_places=1, read_only=True
    )

    credentials = CredentialSerializer(many=True, read_only=True)
    experience = ExperienceSerializer(many=True, read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    documents = EmployeeDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Employee
        fields = (
            "uuid", "employee_code", "full_name", "first_name", "middle_name",
            "last_name", "name_nepali", "date_of_birth", "gender",
            "citizenship_number", "pan_number", "blood_group", "photo_url",
            "phone", "personal_email", "address", "province", "district",
            "municipality", "emergency_contact_name", "emergency_contact_phone",
            "emergency_contact_relation", "position", "position_title",
            "facility", "facility_name", "department", "department_name",
            "reports_to", "manager_name", "employment_type", "status",
            "is_working", "is_provider", "on_probation", "probation_overdue",
            "joined_on", "probation_ends_on", "confirmed_on", "separated_on",
            "separation_reason", "years_of_service", "user_id", "work_email",
            "bank_name", "bank_account_number", "bank_branch", "notes",
            "credentials", "experience", "skills", "documents",
        )
        read_only_fields = (
            "uuid", "employee_code", "full_name", "is_working", "is_provider",
            "on_probation", "probation_overdue", "years_of_service",
            "separated_on", "separation_reason", "confirmed_on",
            "credentials", "experience", "skills", "documents",
        )


# ---------------------------------------------------------------------------
# Write serializers
# ---------------------------------------------------------------------------


class HireSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    position = serializers.UUIDField(required=False, allow_null=True)
    department = serializers.UUIDField(required=False, allow_null=True)
    reports_to = serializers.UUIDField(required=False, allow_null=True)
    employment_type = serializers.CharField(
        max_length=16, required=False, allow_blank=True
    )
    joined_on = serializers.DateField(required=False)
    probation_days = serializers.IntegerField(required=False, default=0)
    employee_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True
    )
    user_id = serializers.UUIDField(required=False, allow_null=True)

    phone = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                  default="")
    personal_email = serializers.EmailField(required=False, allow_blank=True,
                                            default="")
    work_email = serializers.EmailField(required=False, allow_blank=True,
                                        default="")
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=16, required=False,
                                   allow_blank=True, default="")
    citizenship_number = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )


class TransferSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)
    facility = serializers.UUIDField(required=False, allow_null=True)
    department = serializers.UUIDField(required=False, allow_null=True)
    position = serializers.UUIDField(required=False, allow_null=True)
    reports_to = serializers.UUIDField(required=False, allow_null=True)
    effective_on = serializers.DateField(required=False)
    #: Optional. Left out, the service derives it from what actually changed,
    #: which stops a promotion being filed as a transfer.
    event_type = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )

    def validate(self, data):
        if not any(
            data.get(key)
            for key in ("facility", "department", "position", "reports_to")
        ):
            raise serializers.ValidationError(
                "Say what is changing: facility, department, position or manager."
            )
        return data


class SeparateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)
    event_type = serializers.ChoiceField(
        choices=["resignation", "termination", "retirement"],
        default="resignation",
    )
    last_working_day = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class SuspendSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class VerifyCredentialSerializer(serializers.Serializer):
    passed = serializers.BooleanField(default=True)
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )

    def validate(self, data):
        if not data["passed"] and not data.get("notes", "").strip():
            raise serializers.ValidationError(
                {"notes": "A failed verification must say what was wrong."}
            )
        return data


class IssueContractSerializer(serializers.Serializer):
    starts_on = serializers.DateField()
    basic_salary = serializers.DecimalField(max_digits=12, decimal_places=2)
    employment_type = serializers.CharField(
        max_length=16, required=False, allow_blank=True
    )
    ends_on = serializers.DateField(required=False, allow_null=True)
    rate_basis = serializers.CharField(max_length=16, required=False,
                                       default="monthly")
    allowances = serializers.DictField(required=False, default=dict)
    notice_period_days = serializers.IntegerField(required=False, default=30)
    working_hours_per_week = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=48
    )
    reference = serializers.CharField(max_length=32, required=False,
                                      allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
