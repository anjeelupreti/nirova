"""Serializers for identity and membership."""

from rest_framework import serializers

from apps.identity.models import Membership, User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "uuid",
            "email",
            "full_name",
            "preferred_name",
            "display_name",
            "phone",
            "avatar_url",
            "locale",
            "timezone",
            "is_platform_staff",
            "mfa_enabled",
            "must_change_password",
            "last_active_at",
        )
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    """A membership as the context switcher needs to render it."""

    organization_slug = serializers.CharField(
        source="organization.slug", read_only=True
    )
    organization_name = serializers.CharField(
        source="organization.display_name", read_only=True
    )
    organization_uuid = serializers.UUIDField(
        source="organization.uuid", read_only=True
    )
    organization_status = serializers.CharField(
        source="organization.status", read_only=True
    )
    business_type = serializers.CharField(
        source="organization.business_type", read_only=True
    )

    class Meta:
        model = Membership
        fields = (
            "uuid",
            "organization_uuid",
            "organization_slug",
            "organization_name",
            "organization_status",
            "business_type",
            "status",
            "is_default",
            "is_organization_owner",
            "facility_uuids",
        )
        read_only_fields = fields
