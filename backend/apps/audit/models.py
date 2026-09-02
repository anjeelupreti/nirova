"""The audit log and version history, held in the tenant's own database.

Keeping the audit trail inside the tenant database rather than centrally is
deliberate: the log records who read which patient's file, which is itself
patient-identifiable. Centralising it would recreate, in one shared table,
exactly the exposure that database-per-tenant exists to prevent.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel


class AuditAction(models.TextChoices):
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Failed login"
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    VIEW = "view", "View"
    VIEW_SENSITIVE = "view_sensitive", "View sensitive record"
    EXPORT = "export", "Export"
    PRINT = "print", "Print"
    DOWNLOAD = "download", "Download"
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    SUBMIT = "submit", "Submit"
    CANCEL = "cancel", "Cancel"
    REFUND = "refund", "Refund"
    STOCK_ADJUST = "stock_adjust", "Stock adjustment"
    PRESCRIPTION_CHANGE = "prescription_change", "Prescription change"
    PATIENT_MERGE = "patient_merge", "Patient merge"
    PAYROLL_CHANGE = "payroll_change", "Payroll change"
    PERMISSION_CHANGE = "permission_change", "Permission change"
    CONFIG_CHANGE = "config_change", "Configuration change"
    FACILITY_CHANGE = "facility_change", "Facility change"
    SUPPORT_ACCESS = "support_access", "Platform support access"


class AuditSeverity(models.TextChoices):
    INFO = "info", "Informational"
    NOTABLE = "notable", "Notable"
    SENSITIVE = "sensitive", "Sensitive"
    CRITICAL = "critical", "Critical"


class AuditEvent(UUIDModel, TimeStampedModel):
    """One recorded action. Append-only: never updated, never deleted.

    There is intentionally no `save()` guard against modification -- a guard
    in application code would be theatre, since anything able to bypass the
    ORM bypasses the guard too. Immutability is enforced at the database
    level by granting the application role INSERT and SELECT on this table
    and nothing else. See docs/security/audit-immutability.md.
    """

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=32, choices=AuditAction.choices, db_index=True)
    severity = models.CharField(
        max_length=16, choices=AuditSeverity.choices, default=AuditSeverity.INFO
    )

    # -- who --------------------------------------------------------------
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_email = models.CharField(max_length=254, blank=True)
    actor_role = models.CharField(max_length=128, blank=True)
    #: Set when a platform support agent acted inside a customer's data. The
    #: distinction between "the customer did this" and "we did this on their
    #: behalf" is the first question asked when something goes wrong.
    is_platform_actor = models.BooleanField(default=False)
    on_behalf_of_id = models.UUIDField(null=True, blank=True)

    # -- where ------------------------------------------------------------
    facility_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    facility_code = models.CharField(max_length=32, blank=True)
    department_id = models.BigIntegerField(null=True, blank=True)

    # -- what -------------------------------------------------------------
    entity_type = models.CharField(max_length=128, blank=True, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True, db_index=True)
    entity_label = models.CharField(
        max_length=255, blank=True,
        help_text="Human-readable at the time of the event, since the record "
                  "may since have been renamed or deleted.",
    )

    #: Changed fields only, not whole rows. Storing full before/after copies
    #: of clinical records would duplicate the medical record into the audit
    #: log, multiplying the data at risk for no investigative gain.
    changes = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # -- context ----------------------------------------------------------
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    session_id = models.CharField(max_length=64, blank=True)
    device_id = models.CharField(max_length=128, blank=True)
    request_id = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Correlates every event produced by one request.",
    )
    http_method = models.CharField(max_length=8, blank=True)
    http_path = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "audit_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "-occurred_at"]),
            models.Index(fields=["actor_id", "-occurred_at"]),
            models.Index(fields=["action", "-occurred_at"]),
            models.Index(fields=["severity", "-occurred_at"]),
        ]

    def __str__(self):
        return f"{self.action} {self.entity_type}#{self.entity_id} by {self.actor_email}"


class EntityVersion(UUIDModel, TimeStampedModel):
    """A point-in-time snapshot of a record that must never be lost.

    Applied to prescriptions, invoices, clinical notes, compensation and
    configuration: the things where "what did it say before it was changed?"
    is a question with clinical, financial or legal weight. Ordinary records
    rely on the audit log's field-level diffs instead.
    """

    entity_type = models.CharField(max_length=128, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField()

    snapshot = models.JSONField()
    changed_fields = models.JSONField(default=list, blank=True)

    changed_by_id = models.UUIDField(null=True, blank=True)
    changed_by_email = models.CharField(max_length=254, blank=True)
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    change_reason = models.TextField(blank=True)
    audit_event_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "entity_version"
        ordering = ["entity_type", "entity_id", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_id", "version"],
                name="uniq_entity_version",
            )
        ]
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "-version"]),
        ]

    def __str__(self):
        return f"{self.entity_type}#{self.entity_id} v{self.version}"
