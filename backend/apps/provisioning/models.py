"""Facility change requests: opening, closing and converting business units.

Adding or removing a hospital, clinic or pharmacy is not an ordinary CRUD
operation. It changes what the customer pays, what their staff can do, and
what the platform has to support. Left as a plain "New Facility" button it
also becomes a way to churn capacity -- open a branch for a week, close it,
open another -- which makes both billing and capacity planning fiction.

So every such change is a *request* that carries a justification, is
evaluated against the plan at submission time, and is decided by someone
with the authority to decide it. Approval executes the change; nothing else
does. The result is a record of not just what the estate looks like, but why
it looks that way.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.tenancy.models import FacilityType, Organization


class ChangeRequestType(models.TextChoices):
    OPEN_FACILITY = "open_facility", "Open a facility"
    CLOSE_FACILITY = "close_facility", "Close a facility"
    REOPEN_FACILITY = "reopen_facility", "Re-open a closed facility"
    SUSPEND_FACILITY = "suspend_facility", "Suspend a facility"
    RESUME_FACILITY = "resume_facility", "Resume a suspended facility"
    CONVERT_TYPE = "convert_type", "Change a facility's type"
    TRANSFER_FACILITY = "transfer_facility", "Move a facility to another organization"


#: Requests that consume capacity and therefore need a quota evaluation.
CAPACITY_CONSUMING = {
    ChangeRequestType.OPEN_FACILITY,
    ChangeRequestType.REOPEN_FACILITY,
    ChangeRequestType.CONVERT_TYPE,
}

#: Requests that remove operational capability and are hard to undo cleanly.
DESTRUCTIVE = {
    ChangeRequestType.CLOSE_FACILITY,
    ChangeRequestType.TRANSFER_FACILITY,
}


class ChangeRequestStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    ORG_REVIEW = "org_review", "Awaiting organization approval"
    PLATFORM_REVIEW = "platform_review", "Awaiting platform approval"
    INFO_REQUESTED = "info_requested", "More information requested"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    SCHEDULED = "scheduled", "Approved, scheduled for a future date"
    EXECUTED = "executed", "Executed"
    FAILED = "failed", "Execution failed"
    EXPIRED = "expired", "Expired without a decision"


OPEN_STATUSES = {
    ChangeRequestStatus.SUBMITTED,
    ChangeRequestStatus.ORG_REVIEW,
    ChangeRequestStatus.PLATFORM_REVIEW,
    ChangeRequestStatus.INFO_REQUESTED,
}


class ApprovalLevel(models.TextChoices):
    """Who has to say yes.

    The level is *derived* from the request, not chosen by the requester:
    a change that fits inside what the customer already pays for is theirs
    to make; one that changes the commercial relationship is not.
    """

    AUTOMATIC = "automatic", "No approval needed"
    ORGANIZATION = "organization", "Organization administrator"
    PLATFORM = "platform", "Platform staff"
    BOTH = "both", "Organization, then platform"


class ChangeRequestPolicy(BaseModel):
    """How facility changes are routed, per organization.

    A default row (organization = NULL) sets platform-wide behaviour;
    per-organization rows override it. A hospital group with a mature
    internal governance process can be given self-service inside their
    entitlement, while a customer who has churned three pharmacies in a
    quarter can be moved to platform review without changing any code.
    """

    organization = models.OneToOneField(
        Organization,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="change_request_policy",
        help_text="NULL for the platform-wide default policy.",
    )

    #: When a request fits inside the entitlement, may the organization just
    #: do it? Requires the self_service_facility_creation feature as well.
    allow_self_service_within_quota = models.BooleanField(default=True)
    #: Opening within quota still needs an org admin's approval.
    require_org_approval_for_open = models.BooleanField(default=True)
    #: Closing is destructive, so it is approved separately by default.
    require_org_approval_for_close = models.BooleanField(default=True)
    #: Closures also go to the platform. Off by default -- a customer closing
    #: their own branch is their business, unless churn says otherwise.
    require_platform_approval_for_close = models.BooleanField(default=False)

    #: Days after a facility is closed during which opening another of the
    #: same type is treated as churn and escalated to platform review. Stops
    #: capacity being cycled to dodge the limit, without blocking a genuine
    #: relocation -- which a human reviewer can see for what it is.
    churn_window_days = models.PositiveSmallIntegerField(default=90)
    #: Closures of one type within the window before churn review kicks in.
    churn_threshold = models.PositiveSmallIntegerField(default=2)

    #: Requests with no decision after this many days are marked expired, so
    #: the queue reflects live decisions rather than accumulating forever.
    auto_expire_days = models.PositiveSmallIntegerField(default=30)
    #: A request may not be approved by the person who raised it.
    enforce_segregation_of_duties = models.BooleanField(default=True)
    require_justification = models.BooleanField(default=True)
    min_justification_length = models.PositiveSmallIntegerField(default=40)

    class Meta:
        db_table = "cp_change_request_policy"

    def __str__(self):
        if self.organization_id is None:
            return "Platform default policy"
        return f"Policy for {self.organization.slug}"

    @classmethod
    def for_organization(cls, organization) -> "ChangeRequestPolicy":
        """The organization's policy, falling back to the platform default.

        Returns an unsaved default instance when neither exists, so the
        system has sane behaviour on a fresh install rather than crashing.
        """
        policy = cls.objects.filter(organization=organization).first()
        if policy:
            return policy
        default = cls.objects.filter(organization__isnull=True).first()
        return default or cls()


class FacilityChangeRequest(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="facility_change_requests"
    )
    reference = models.CharField(
        max_length=32, unique=True, help_text="Human-quotable, e.g. FCR-2026-0041."
    )
    request_type = models.CharField(
        max_length=32, choices=ChangeRequestType.choices, db_index=True
    )
    status = models.CharField(
        max_length=24,
        choices=ChangeRequestStatus.choices,
        default=ChangeRequestStatus.DRAFT,
        db_index=True,
    )
    approval_level = models.CharField(
        max_length=16, choices=ApprovalLevel.choices, default=ApprovalLevel.ORGANIZATION
    )

    # -- what is being asked for ----------------------------------------

    facility_type = models.CharField(max_length=32, choices=FacilityType.choices)
    #: Set for changes to an existing facility; empty when opening a new one.
    target_facility_uuid = models.UUIDField(null=True, blank=True)
    proposed_name = models.CharField(max_length=255, blank=True)
    proposed_code = models.CharField(max_length=32, blank=True)
    #: Full payload used to build the facility on approval. Held rather than
    #: applied, so a rejected request leaves nothing behind.
    payload = models.JSONField(default=dict, blank=True)

    requested_effective_date = models.DateField(null=True, blank=True)
    justification = models.TextField(blank=True)

    # -- what it would cost / cost them ---------------------------------

    #: The quota decisions computed at submission. Kept verbatim so a
    #: reviewer sees the position as it stood when the request was raised,
    #: not as it stands when they happen to open it.
    quota_evaluation = models.JSONField(default=dict, blank=True)
    requires_capacity_purchase = models.BooleanField(default=False)
    #: Add-on that would have to be attached for this to fit.
    proposed_addon_code = models.CharField(max_length=64, blank=True)
    proposed_addon_quantity = models.PositiveIntegerField(default=0)
    estimated_price_delta = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    #: Why this needed a human: over quota, module missing, churn pattern,
    #: destructive. Drives what the reviewer is asked to weigh up.
    escalation_reasons = models.JSONField(default=list, blank=True)
    churn_signal = models.JSONField(default=dict, blank=True)

    # -- lifecycle -------------------------------------------------------

    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_email = models.CharField(max_length=254, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    executed_at = models.DateTimeField(null=True, blank=True)
    execution_error = models.TextField(blank=True)
    #: The facility that ended up being created or changed.
    resulting_facility_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "cp_facility_change_request"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "approval_level"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.get_request_type_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_decided(self) -> bool:
        return self.status in {
            ChangeRequestStatus.APPROVED,
            ChangeRequestStatus.REJECTED,
            ChangeRequestStatus.SCHEDULED,
            ChangeRequestStatus.EXECUTED,
        }

    @property
    def age_in_days(self) -> int:
        start = self.submitted_at or self.created_at
        return (timezone.now() - start).days

    def next_approver_level(self) -> str | None:
        """Which approval is outstanding, if any."""
        if self.status == ChangeRequestStatus.ORG_REVIEW:
            return ApprovalLevel.ORGANIZATION
        if self.status == ChangeRequestStatus.PLATFORM_REVIEW:
            return ApprovalLevel.PLATFORM
        return None


class DecisionType(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    REQUEST_INFO = "request_info", "Request more information"
    ESCALATE = "escalate", "Escalate"
    WITHDRAW = "withdraw", "Withdraw"


class ChangeRequestDecision(BaseModel):
    """One person's verdict on a request. Append-only.

    A request may collect several: an org admin approving, then platform
    staff approving the capacity purchase. Keeping each as its own row is
    what allows "who approved the fourth pharmacy?" to be answered years
    later, which is the entire point of routing this through approvals.
    """

    request = models.ForeignKey(
        FacilityChangeRequest, on_delete=models.CASCADE, related_name="decisions"
    )
    level = models.CharField(max_length=16, choices=ApprovalLevel.choices)
    decision = models.CharField(max_length=16, choices=DecisionType.choices)

    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_email = models.CharField(max_length=254, blank=True)
    decided_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True)

    #: Conditions attached to an approval, e.g. "approved on condition the
    #: Butwal branch closes first".
    conditions = models.JSONField(default=list, blank=True)
    #: Entitlement changes the approver authorised alongside the decision.
    granted_addon_code = models.CharField(max_length=64, blank=True)
    granted_addon_quantity = models.PositiveIntegerField(default=0)
    granted_entitlement_delta = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "cp_change_request_decision"
        ordering = ["decided_at"]

    def __str__(self):
        return f"{self.request.reference}: {self.get_decision_display()}"


class ChangeRequestComment(BaseModel):
    """Discussion on a request, so the reasoning is not lost in email."""

    request = models.ForeignKey(
        FacilityChangeRequest, on_delete=models.CASCADE, related_name="comments"
    )
    author_id = models.UUIDField(null=True, blank=True)
    author_email = models.CharField(max_length=254, blank=True)
    body = models.TextField()
    #: Internal notes are visible to platform staff only.
    is_internal = models.BooleanField(default=False)

    class Meta:
        db_table = "cp_change_request_comment"
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.request.reference}"
