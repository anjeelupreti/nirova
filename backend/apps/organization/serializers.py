"""Serializers for the organization-facing API."""

from rest_framework import serializers

from apps.organization.models import Department, Facility, Unit
from apps.provisioning.models import (
    ChangeRequestDecision,
    ChangeRequestType,
    FacilityChangeRequest,
)
from apps.tenancy.models import FacilityType


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ("uuid", "code", "name", "description", "capacity", "is_active")


class DepartmentSerializer(serializers.ModelSerializer):
    units = UnitSerializer(many=True, read_only=True)

    class Meta:
        model = Department
        fields = (
            "uuid", "code", "name", "kind", "cost_centre_code",
            "is_revenue_generating", "is_active", "display_order", "units",
        )


class FacilitySerializer(serializers.ModelSerializer):
    department_count = serializers.IntegerField(read_only=True)
    is_operational = serializers.BooleanField(read_only=True)

    class Meta:
        model = Facility
        fields = (
            "uuid", "code", "name", "short_name", "facility_type", "status",
            "is_operational", "province", "district", "municipality", "ward",
            "street_address", "phone", "email", "pan_number", "license_number",
            "license_expires_on", "is_24x7", "operating_hours", "opened_on",
            "closed_on", "origin_reference", "department_count",
        )
        read_only_fields = ("uuid", "status", "origin_reference", "opened_on",
                            "closed_on")


class FacilityDetailSerializer(FacilitySerializer):
    departments = DepartmentSerializer(many=True, read_only=True)

    class Meta(FacilitySerializer.Meta):
        fields = FacilitySerializer.Meta.fields + ("departments",)


class ChangeRequestDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangeRequestDecision
        fields = (
            "uuid", "level", "decision", "decided_by_email", "decided_at",
            "comment", "conditions", "granted_addon_code",
            "granted_addon_quantity", "granted_entitlement_delta",
        )
        read_only_fields = fields


class FacilityChangeRequestSerializer(serializers.ModelSerializer):
    decisions = ChangeRequestDecisionSerializer(many=True, read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    age_in_days = serializers.IntegerField(read_only=True)
    organization_slug = serializers.CharField(
        source="organization.slug", read_only=True
    )
    organization_name = serializers.CharField(
        source="organization.display_name", read_only=True
    )

    class Meta:
        model = FacilityChangeRequest
        fields = (
            "uuid", "reference", "organization_slug", "organization_name",
            "request_type", "status", "approval_level", "facility_type",
            "target_facility_uuid", "proposed_name", "proposed_code",
            "payload", "requested_effective_date", "justification",
            "quota_evaluation", "requires_capacity_purchase",
            "proposed_addon_code", "proposed_addon_quantity",
            "escalation_reasons", "churn_signal", "requested_by_email",
            "submitted_at", "decided_at", "executed_at", "execution_error",
            "resulting_facility_uuid", "is_open", "age_in_days", "decisions",
            "created_at",
        )
        read_only_fields = fields


class FacilityChangeRequestCreateSerializer(serializers.Serializer):
    """What a requester submits.

    `approval_level` is absent by design -- routing is derived from the
    entitlement position and policy, never chosen by whoever is asking.
    """

    request_type = serializers.ChoiceField(choices=ChangeRequestType.choices)
    facility_type = serializers.ChoiceField(choices=FacilityType.choices)
    target_facility_uuid = serializers.UUIDField(required=False, allow_null=True)
    justification = serializers.CharField(allow_blank=True, default="")
    requested_effective_date = serializers.DateField(required=False, allow_null=True)
    payload = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        request_type = attrs["request_type"]
        if request_type == ChangeRequestType.OPEN_FACILITY:
            payload = attrs.get("payload") or {}
            missing = [f for f in ("name", "code") if not payload.get(f)]
            if missing:
                raise serializers.ValidationError(
                    {"payload": f"Opening a facility requires: {', '.join(missing)}."}
                )
        elif not attrs.get("target_facility_uuid"):
            raise serializers.ValidationError(
                {
                    "target_facility_uuid":
                        "This request type must identify an existing facility."
                }
            )
        return attrs


class AddOnGrantSerializer(serializers.Serializer):
    code = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class ChangeRequestDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=["approve", "reject", "request_info", "escalate", "withdraw"]
    )
    comment = serializers.CharField(allow_blank=True, default="")
    conditions = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    granted_addon_code = serializers.CharField(allow_blank=True, default="")
    granted_addon_quantity = serializers.IntegerField(min_value=0, default=0)
    #: Several add-ons at once, e.g. a module plus a facility slot. Opening a
    #: hospital on a plan without the hospital module needs both.
    granted_addons = serializers.ListField(
        child=AddOnGrantSerializer(), required=False, default=list
    )
    granted_entitlement_delta = serializers.IntegerField(
        required=False, allow_null=True
    )


class FacilityChangePreviewSerializer(serializers.Serializer):
    """Ask what would happen, without asking for it to happen."""

    request_type = serializers.ChoiceField(
        choices=ChangeRequestType.choices,
        default=ChangeRequestType.OPEN_FACILITY,
    )
    facility_type = serializers.ChoiceField(choices=FacilityType.choices)
    target_facility_uuid = serializers.UUIDField(required=False, allow_null=True)
