"""Serializers for the platform owner console."""

from rest_framework import serializers

from apps.catalog.models import Plan, PlanLimit
from apps.subscriptions.models import Subscription, SubscriptionAddOn
from apps.tenancy.models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    facility_count = serializers.IntegerField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    database_status = serializers.CharField(
        source="database.status", read_only=True, default=None
    )
    database_alias = serializers.CharField(
        source="database.alias", read_only=True, default=None
    )

    class Meta:
        model = Organization
        fields = (
            "uuid", "slug", "legal_name", "display_name", "business_type",
            "status", "pan_number", "vat_number", "primary_email",
            "primary_phone", "province", "district", "municipality",
            "trial_ends_at", "activated_at", "suspended_at",
            "onboarding_completed_at", "created_at",
            "facility_count", "member_count",
            "database_status", "database_alias",
        )
        read_only_fields = fields


class PlanLimitSerializer(serializers.ModelSerializer):
    is_unlimited = serializers.SerializerMethodField()

    class Meta:
        model = PlanLimit
        fields = ("key", "value", "is_unlimited", "enforcement",
                  "overage_unit_price", "warn_at_percent")

    def get_is_unlimited(self, obj) -> bool:
        return obj.value is None


class PlanSerializer(serializers.ModelSerializer):
    limits = PlanLimitSerializer(many=True, read_only=True)
    modules = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = (
            "uuid", "code", "name", "tagline", "description", "base_price",
            "currency", "billing_interval", "setup_fee", "trial_days",
            "grace_days", "is_public", "is_active", "version",
            "limits", "modules", "features",
        )

    def get_modules(self, obj) -> list:
        return [
            {
                "code": pm.module.code,
                "name": pm.module.name,
                "is_included": pm.is_included,
                "additional_price": pm.additional_price,
            }
            for pm in obj.plan_modules.all()
        ]

    def get_features(self, obj) -> list:
        return [
            {"code": pf.feature.code, "name": pf.feature.name,
             "is_enabled": pf.is_enabled}
            for pf in obj.plan_features.all()
        ]


class SubscriptionAddOnSerializer(serializers.ModelSerializer):
    addon_code = serializers.CharField(source="addon.code", read_only=True)
    addon_name = serializers.CharField(source="addon.name", read_only=True)
    target_key = serializers.CharField(source="addon.target_key", read_only=True)
    increment = serializers.IntegerField(source="addon.increment", read_only=True)

    class Meta:
        model = SubscriptionAddOn
        fields = (
            "uuid", "addon_code", "addon_name", "target_key", "increment",
            "quantity", "unit_price", "effective_from", "effective_to",
            "is_active", "source_reference",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    organization_slug = serializers.CharField(
        source="organization.slug", read_only=True
    )
    organization_name = serializers.CharField(
        source="organization.display_name", read_only=True
    )
    plan_code = serializers.CharField(source="plan.code", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    addons = SubscriptionAddOnSerializer(many=True, read_only=True)
    is_entitled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "uuid", "organization_slug", "organization_name", "plan_code",
            "plan_name", "status", "is_entitled", "billing_interval",
            "currency", "contracted_price", "discount_percent", "started_at",
            "trial_ends_at", "current_period_start", "current_period_end",
            "grace_ends_at", "cancel_at_period_end", "auto_renew", "addons",
        )
        read_only_fields = fields
