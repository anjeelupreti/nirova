"""Writing audit events, and the request context they are stamped with."""

import logging

# uuid: generates the per-request correlation id when the caller did not
# supply an X-Request-ID, so every event from one request can be tied together.
import uuid

# ContextVar: holds the request-scoped audit facts. Same reasoning as the
# tenant context -- thread locals leak across async boundaries, which under
# ASGI would stamp one user's identity onto another user's audit events.
from contextvars import ContextVar

# dataclass / field: AuditContext is a plain value object. `field` supplies
# the default_factory for request_id, since a mutable/computed default cannot
# be a bare class attribute.
from dataclasses import dataclass, field

# AuditAction: the action vocabulary, also keyed by SEVERITY_BY_ACTION below.
# AuditEvent: the append-only log row.
# AuditSeverity: how loudly an event should be treated downstream.
# EntityVersion: full snapshots for records whose history must survive edits.
from apps.audit.models import AuditAction, AuditEvent, AuditSeverity, EntityVersion

logger = logging.getLogger("nirova.audit")

#: Fields never written into an audit diff, whatever model they appear on.
REDACTED_FIELDS = frozenset(
    {
        "password", "mfa_secret", "db_password", "token", "refresh_token",
        "access_token", "secret", "api_key", "private_key", "signature",
    }
)

#: Actions that are always recorded at sensitive severity or above.
SEVERITY_BY_ACTION = {
    AuditAction.VIEW_SENSITIVE: AuditSeverity.SENSITIVE,
    AuditAction.EXPORT: AuditSeverity.SENSITIVE,
    AuditAction.DOWNLOAD: AuditSeverity.SENSITIVE,
    AuditAction.PATIENT_MERGE: AuditSeverity.CRITICAL,
    AuditAction.PRESCRIPTION_CHANGE: AuditSeverity.CRITICAL,
    AuditAction.PERMISSION_CHANGE: AuditSeverity.CRITICAL,
    AuditAction.PAYROLL_CHANGE: AuditSeverity.CRITICAL,
    AuditAction.REFUND: AuditSeverity.CRITICAL,
    AuditAction.STOCK_ADJUST: AuditSeverity.NOTABLE,
    AuditAction.FACILITY_CHANGE: AuditSeverity.CRITICAL,
    AuditAction.SUPPORT_ACCESS: AuditSeverity.CRITICAL,
    AuditAction.CONFIG_CHANGE: AuditSeverity.NOTABLE,
    AuditAction.LOGIN_FAILED: AuditSeverity.NOTABLE,
}


@dataclass
class AuditContext:
    """Request-scoped facts every event in that request inherits."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    actor_id: object = None
    actor_email: str = ""
    actor_role: str = ""
    is_platform_actor: bool = False
    on_behalf_of_id: object = None
    ip_address: object = None
    user_agent: str = ""
    session_id: str = ""
    device_id: str = ""
    http_method: str = ""
    http_path: str = ""
    facility_id: object = None
    facility_code: str = ""


_current_audit: ContextVar[AuditContext | None] = ContextVar(
    "nirova_audit_context", default=None
)


def set_audit_context(context: AuditContext | None):
    return _current_audit.set(context)


def reset_audit_context(token) -> None:
    _current_audit.reset(token)


def get_audit_context() -> AuditContext:
    return _current_audit.get() or AuditContext()


def redact(data: dict) -> dict:
    """Strip secrets from a payload before it is persisted."""
    cleaned = {}
    for key, value in (data or {}).items():
        if key.lower() in REDACTED_FIELDS:
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


def diff_instance(before: dict, after: dict) -> dict:
    """Field-level changes, secrets redacted.

    Only changed fields are kept. An update that touched one field should
    not write a copy of the whole record into the log.
    """
    changes = {}
    for key, new_value in (after or {}).items():
        old_value = (before or {}).get(key)
        if old_value == new_value:
            continue
        if key.lower() in REDACTED_FIELDS:
            changes[key] = {"before": "[redacted]", "after": "[redacted]"}
        else:
            changes[key] = {"before": old_value, "after": new_value}
    return changes


def record(
    action: str,
    entity_type: str = "",
    entity_id="",
    entity_label: str = "",
    changes: dict | None = None,
    reason: str = "",
    severity: str | None = None,
    metadata: dict | None = None,
    context: AuditContext | None = None,
) -> AuditEvent | None:
    """Write one audit event against the active tenant database.

    Never raises. An audit write that fails must not take a clinical action
    down with it -- a nurse recording vitals should not be blocked because
    the log is unavailable. Failures are logged loudly for the platform team
    instead, and the health check surfaces them.
    """
    context = context or get_audit_context()
    severity = severity or SEVERITY_BY_ACTION.get(action, AuditSeverity.INFO)

    try:
        return AuditEvent.objects.create(
            action=action,
            severity=severity,
            actor_id=context.actor_id,
            actor_email=context.actor_email,
            actor_role=context.actor_role,
            is_platform_actor=context.is_platform_actor,
            on_behalf_of_id=context.on_behalf_of_id,
            facility_id=context.facility_id,
            facility_code=context.facility_code,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else "",
            entity_label=entity_label[:255],
            changes=redact(changes or {}),
            reason=reason,
            metadata=redact(metadata or {}),
            ip_address=context.ip_address,
            user_agent=context.user_agent[:512],
            session_id=context.session_id,
            device_id=context.device_id,
            request_id=context.request_id,
            http_method=context.http_method,
            http_path=context.http_path[:512],
        )
    except Exception:
        logger.exception(
            "AUDIT WRITE FAILED action=%s entity=%s#%s actor=%s",
            action, entity_type, entity_id, context.actor_email,
        )
        return None


def record_version(
    entity_type: str,
    entity_id,
    snapshot: dict,
    changed_fields: list | None = None,
    reason: str = "",
    audit_event: AuditEvent | None = None,
    context: AuditContext | None = None,
) -> EntityVersion | None:
    """Snapshot a record whose history must survive later edits."""
    context = context or get_audit_context()
    try:
        last_version = (
            EntityVersion.objects.filter(
                entity_type=entity_type, entity_id=str(entity_id)
            )
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        return EntityVersion.objects.create(
            entity_type=entity_type,
            entity_id=str(entity_id),
            version=(last_version or 0) + 1,
            snapshot=redact(snapshot),
            changed_fields=changed_fields or [],
            changed_by_id=context.actor_id,
            changed_by_email=context.actor_email,
            change_reason=reason,
            audit_event_uuid=audit_event.uuid if audit_event else None,
        )
    except Exception:
        logger.exception(
            "VERSION WRITE FAILED entity=%s#%s", entity_type, entity_id
        )
        return None
