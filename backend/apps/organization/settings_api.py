"""Reading and changing a tenant's own settings.

`config.read` to look, `config.update` to change. Both codes have been in the
catalogue and held by four roles since the RBAC app was written, and until now
**neither was checked by anything**, because there was no endpoint to check
them on.

Two verbs and no more. There is deliberately no create and no delete: the set
of settings is declared in `settings_registry`, so there is nothing to create,
and clearing one is expressed as resetting it to its default rather than as
removing a row -- which is the same act and reads better in an audit log.
"""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
# DomainError is a 400 in the standard envelope; PermissionDeniedError a 403.
# There is no `ValidationError` in this project's exception module -- DRF's own
# is handled separately by `api_exception_handler` and does not carry the
# `detail` dict these refusals want.
from apps.common.exceptions import DomainError, PermissionDeniedError
from apps.common.permissions import HasPermission
from apps.organization.config import config_value, set_config_value
from apps.organization.models import ConfigScope, ConfigSetting, Facility
from apps.organization.settings_registry import BY_CODE, SETTINGS, coerce
from apps.rbac.permissions import Scope


class SettingValueSerializer(serializers.Serializer):
    value = serializers.JSONField()
    facility_uuid = serializers.UUIDField(required=False, allow_null=True)


def _facility(uuid):
    if not uuid:
        return None
    facility = Facility.objects.filter(uuid=uuid).first()
    if facility is None:
        raise PermissionDeniedError("No such facility.")
    return facility


def _describe(setting, facility=None) -> dict:
    """One setting, its current value, and whether that value is its own.

    `is_set` matters more than it looks. "13.00" tells a reader nothing about
    whether somebody chose it or whether it is simply what everybody gets, and
    those are different facts when you are deciding whether to change it.
    """
    current = config_value(
        setting.namespace, setting.key, default=setting.default,
        facility=facility,
    )
    explicit = ConfigSetting.objects.filter(
        namespace=setting.namespace, key=setting.key,
    )
    at_organization = explicit.filter(scope=ConfigScope.ORGANIZATION).first()
    at_facility = (
        explicit.filter(scope=ConfigScope.FACILITY, facility=facility).first()
        if facility is not None
        else None
    )

    return {
        "namespace": setting.namespace,
        "key": setting.key,
        "code": setting.code,
        "label": setting.label,
        "description": setting.description,
        "kind": setting.kind,
        "choices": [
            {"value": value, "label": label} for value, label in setting.choices
        ],
        "default": setting.default,
        "value": current,
        "per_facility": setting.per_facility,
        "caution": setting.caution,
        "is_set": bool(at_organization or at_facility),
        "set_at": (
            "facility" if at_facility else
            "organization" if at_organization else ""
        ),
        # A locked organization value is why a facility's own row is being
        # ignored. Without this the screen shows a value that does not match
        # what was saved and looks broken.
        "is_locked": bool(at_organization and at_organization.is_locked),
    }


class SettingsView(APIView):
    """Every setting this tenant may change, with what it is set to now."""

    permission_classes = [
        IsAuthenticated,
        HasPermission.of("config.read", scope=Scope.OWN, write="config.update"),
    ]

    def get(self, request):
        facility = _facility(request.query_params.get("facility"))
        return Response({
            "facility": str(facility.uuid) if facility else None,
            "settings": [_describe(s, facility=facility) for s in SETTINGS],
        })

    def put(self, request):
        """Set one value. `PUT` rather than `POST`: this replaces a value at a
        known address rather than creating something new."""
        code = request.data.get("code") or ""
        setting = BY_CODE.get(code)
        if setting is None:
            raise DomainError(
                f"'{code}' is not a setting this system has.",
                detail={"known": sorted(BY_CODE)},
            )

        form = SettingValueSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        facility = _facility(form.validated_data.get("facility_uuid"))

        if facility is not None and not setting.per_facility:
            raise DomainError(
                f"{setting.label} is set for the whole organization, not per "
                "facility.",
            )

        try:
            value = coerce(setting, form.validated_data["value"])
        except ValueError as exc:
            raise DomainError(str(exc)) from exc

        before = config_value(
            setting.namespace, setting.key, default=setting.default,
            facility=facility,
        )
        set_config_value(
            setting.namespace, setting.key, value,
            scope=ConfigScope.FACILITY if facility else ConfigScope.ORGANIZATION,
            facility=facility,
            description=setting.label,
        )

        # Recorded as a change with both sides. "Somebody turned privacy on"
        # is not enough a year later; "it was off and became on, on this date,
        # by this person" is what an auditor is asking for.
        record(
            AuditAction.UPDATE,
            entity_type="organization.ConfigSetting",
            entity_id=setting.code,
            entity_label=setting.label,
            changes={setting.code: {"from": before, "to": value}},
            metadata={"facility": str(facility.uuid) if facility else ""},
        )
        return Response(_describe(setting, facility=facility))

    def delete(self, request):
        """Put a setting back to its default.

        Deleting the row rather than writing the default value, so that
        `is_set` becomes false again and the screen can distinguish "we chose
        the default" from "we never chose". A tenant that later changes its
        mind about what the default should be then follows it.
        """
        code = request.data.get("code") or request.query_params.get("code") or ""
        setting = BY_CODE.get(code)
        if setting is None:
            raise DomainError(f"'{code}' is not a setting this system has.")

        facility = _facility(
            request.data.get("facility_uuid")
            or request.query_params.get("facility")
        )
        rows = ConfigSetting.objects.filter(
            namespace=setting.namespace, key=setting.key,
        )
        rows = (
            rows.filter(scope=ConfigScope.FACILITY, facility=facility)
            if facility is not None
            else rows.filter(scope=ConfigScope.ORGANIZATION)
        )
        locked = rows.filter(is_locked=True).exists()
        if locked:
            raise PermissionDeniedError(
                f"{setting.label} is locked and cannot be reset here.",
            )
        # `ConfigSetting` is soft-deleted, and its manager's `delete()`
        # returns a plain count rather than Django's `(count, per_model)`
        # tuple. Soft deletion is the right behaviour here: the row stays,
        # stamped, so "we turned this off in March" remains answerable --
        # and `ConfigSetting.objects` excludes it, so resolution correctly
        # falls back to the default.
        removed = rows.delete()

        # The delete bypasses `set_config_value`, which is what clears the
        # locale memo -- so it is cleared here. Without this the old value
        # keeps being served for the rest of the request that reset it.
        from apps.organization.locale import clear_cache

        clear_cache()

        record(
            AuditAction.DELETE,
            entity_type="organization.ConfigSetting",
            entity_id=setting.code,
            entity_label=f"{setting.label} reset to default",
            metadata={"rows": removed},
        )
        return Response(
            _describe(setting, facility=facility),
            status=status.HTTP_200_OK,
        )
