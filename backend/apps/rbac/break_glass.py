"""Emergency access: granted instantly, reviewed afterwards, ended by time.

Step 3 of `PHASE2_PLAN.md`, built **before** enforcement so that the first
clinician refused by the relationship check is not also the one discovering
there is no way through.

The shape, and why each part of it is here.

**It refuses nobody.** An unconscious patient arrives and nobody has a care
relationship with them. A doctor is telephoned about a ward they have never
worked on. Any control that can stop those is a control that will one day kill
somebody, so this one does not stop anybody -- it records them.

**It demands a sentence, not a category.** "Emergency" is the one thing every
override has in common, so it distinguishes nothing and reviews to nothing. The
minimum length is crude and deliberate: it exists to make the useless answer
inconvenient, not to validate prose.

**It ends by time, not by intention.** Nobody has to remember to close it, and
the person who took it cannot extend it. Four hours is roughly one crisis; a
clinician who still needs the record after that is no longer in an emergency
and will have a real relationship by then.

**The review is the control; the grant is only the mechanism.** Every grant
raises a `CRITICAL` notification -- a category the notification centre refuses
to let anybody silence by preference -- and stays on a queue until a human
signs it off. This is the part most likely to be dropped later for looking like
paperwork, and dropping it would leave an override with no control attached.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.audit.models import AuditAction, AuditSeverity
# record: this is the most sensitive thing a clinician can do to a record they
# have no relationship with. "Who opened this, and what did they say?" is the
# first question of any privacy investigation.
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify
from apps.rbac.models import (
    BREAK_GLASS_HOURS,
    MINIMUM_REASON_LENGTH,
    BreakGlassGrant,
    BreakGlassOutcome,
)
from apps.rbac.services import holders_of

logger = logging.getLogger("nirova.rbac")


class BreakGlassError(DomainError):
    code = "break_glass_error"


def live_grant(user_id, patient) -> BreakGlassGrant | None:
    """An unexpired grant for this person and this patient, if there is one."""
    if user_id is None or patient is None:
        return None
    return (
        BreakGlassGrant.objects.filter(
            user_id=user_id,
            patient_uuid=getattr(patient, "uuid", patient),
            expires_at__gt=timezone.now(),
        )
        .order_by("-granted_at")
        .first()
    )


def break_glass(user, patient, reason: str, facility=None) -> BreakGlassGrant:
    """Open a record there is no relationship with. Never refuses on authority.

    The only refusals here are about the *reason* -- an unusable reason makes
    the review queue unusable, and the queue is the whole control.
    """
    reason = (reason or "").strip()
    if len(reason) < MINIMUM_REASON_LENGTH:
        raise BreakGlassError(
            "Say what the emergency is, in a sentence somebody can review "
            "later. A word like 'emergency' is true of every override and "
            "tells a reviewer nothing.",
            detail={"minimum_characters": MINIMUM_REASON_LENGTH},
        )
    if user is None or getattr(user, "uuid", None) is None:
        raise BreakGlassError("Emergency access needs a signed-in user.")

    existing = live_grant(user.uuid, patient)
    if existing is not None:
        # Already inside the window. Extending it silently would let somebody
        # hold a record open indefinitely by re-asking, so the original expiry
        # stands and the reuse is counted instead.
        return existing

    now = timezone.now()
    grant = BreakGlassGrant.objects.create(
        patient_uuid=patient.uuid,
        patient_label=f"{patient.full_name} ({patient.mrn})",
        user_id=user.uuid,
        user_label=getattr(user, "full_name", "") or user.email,
        reason=reason,
        granted_at=now,
        expires_at=now + timedelta(hours=BREAK_GLASS_HOURS),
    )

    record(
        AuditAction.VIEW_SENSITIVE,
        entity_type="patients.Patient",
        entity_id=patient.uuid,
        entity_label=grant.patient_label,
        reason=reason,
        severity=AuditSeverity.CRITICAL,
        metadata={
            "break_glass": str(grant.uuid),
            "expires_at": grant.expires_at.isoformat(),
        },
    )

    # Best-effort by design: failing to tell the privacy officer must not stop
    # a clinician reaching a record in an emergency. The audit event above is
    # the durable record; this is the one that reaches a person today.
    reviewers = holders_of("privacy.review", exclude_user_id=user.uuid)
    notify(
        source="privacy",
        event="break_glass",
        category=NotificationCategory.CRITICAL,
        title=(
            f"{grant.user_label} opened {patient.full_name}'s record "
            "without a care relationship"
        ),
        body=reason,
        link="/privacy",
        recipients=reviewers,
        subject_type="rbac.BreakGlassGrant",
        subject_uuid=grant.uuid,
        facility=facility,
        actor_name=grant.user_label,
        dedupe_key=f"break_glass:{grant.uuid}",
    )
    if not reviewers:
        # Worth a loud line: a grant nobody was told about is a control with
        # nothing on the other end, and it usually means the role holding
        # `privacy.review` has not been assigned to anybody.
        logger.warning(
            "break-glass by %s on %s reached no reviewer: nobody holds "
            "privacy.review",
            grant.user_label,
            grant.patient_label,
        )
    return grant


def note_use(grant: BreakGlassGrant) -> BreakGlassGrant:
    """Count a read made under this grant.

    A grant taken and never used is a different fact from one used forty
    times, and only the second is worth a conversation. Kept as a count rather
    than a row per read -- the audit log already holds the reads.
    """
    BreakGlassGrant.objects.filter(pk=grant.pk).update(
        use_count=grant.use_count + 1, last_used_at=timezone.now(),
    )
    return grant


def review(
    grant: BreakGlassGrant, actor, outcome: str, notes: str = "",
) -> BreakGlassGrant:
    """Sign a grant off. This is the control the whole thing exists for."""
    if (
        outcome not in BreakGlassOutcome.values
        or outcome == BreakGlassOutcome.PENDING
    ):
        raise BreakGlassError(
            "A review has to reach a conclusion.",
            detail={
                "outcomes": [
                    value for value in BreakGlassOutcome.values
                    if value != BreakGlassOutcome.PENDING
                ]
            },
        )
    if outcome != BreakGlassOutcome.APPROPRIATE and not notes.strip():
        raise BreakGlassError(
            "Say why this one is being queried or escalated. The clinician "
            "will be asked about it, and 'the system flagged it' is not "
            "something anybody can answer."
        )
    if grant.is_reviewed:
        raise BreakGlassError(
            f"Already reviewed on {grant.reviewed_at:%d %b %Y} by "
            f"{grant.reviewed_by_name or 'somebody'}."
        )
    if getattr(actor, "uuid", None) == grant.user_id:
        # The point of the queue is that somebody else looks. Reviewing your
        # own override is the same act as not being reviewed at all.
        raise BreakGlassError("You cannot review your own emergency access.")

    grant.outcome = outcome
    grant.reviewed_by_id = getattr(actor, "uuid", None)
    grant.reviewed_by_name = getattr(actor, "full_name", "") or ""
    grant.reviewed_at = timezone.now()
    grant.review_notes = notes.strip()
    grant.save(update_fields=[
        "outcome", "reviewed_by_id", "reviewed_by_name", "reviewed_at",
        "review_notes", "updated_at",
    ])

    record(
        AuditAction.UPDATE,
        entity_type="rbac.BreakGlassGrant",
        entity_id=grant.uuid,
        entity_label=f"Emergency access reviewed: {grant.outcome}",
        reason=notes.strip(),
        severity=AuditSeverity.NOTABLE,
    )
    return grant


def revoke(grant: BreakGlassGrant, actor, reason: str) -> BreakGlassGrant:
    """End a live grant now, rather than waiting for it to expire.

    Added because reviewing an override that is still running and being able to
    do nothing about it is a strange position to put a privacy officer in. Four
    hours is short, but "short" is not the same as "nothing I can do".

    Ends it by moving the expiry to now, which is the same mechanism as normal
    expiry rather than a second one -- there is no `is_revoked` flag to keep in
    step with `expires_at`, and nothing else has to learn a new way for a grant
    to be over. The constraint still holds, because now is always after the
    moment it was granted.

    The clinician is told. Somebody whose access disappears mid-shift with no
    explanation will assume the system is broken and work around it.
    """
    if not reason.strip():
        raise BreakGlassError("Say why the access is being ended.")
    if not grant.is_live:
        raise BreakGlassError("That access has already expired.")

    grant.expires_at = timezone.now()
    grant.save(update_fields=["expires_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="rbac.BreakGlassGrant",
        entity_id=grant.uuid,
        entity_label=f"Emergency access ended early: {grant.patient_label}",
        reason=reason.strip(),
        severity=AuditSeverity.SENSITIVE,
    )
    notify(
        source="privacy",
        event="break_glass_revoked",
        category=NotificationCategory.WARNING,
        title="Your emergency access has been ended",
        body=f"{grant.patient_label}. {reason.strip()}",
        link="/privacy",
        recipients=[{
            "id": grant.user_id,
            "name": grant.user_label,
            "reason": "You opened this record under emergency access",
        }],
        subject_type="rbac.BreakGlassGrant",
        subject_uuid=grant.uuid,
        actor_name=getattr(actor, "full_name", "") or "",
        dedupe_key=f"break_glass_revoked:{grant.uuid}",
    )
    return grant


def queue(days: int = 90) -> dict:
    """What is waiting for a reviewer, and how the queue is behaving.

    Reports the unreviewed count beside the total rather than on its own,
    because "eleven waiting" means one thing against twelve and another
    against four hundred.
    """
    since = timezone.now() - timedelta(days=days)
    grants = BreakGlassGrant.objects.filter(granted_at__gte=since)
    pending = grants.filter(outcome=BreakGlassOutcome.PENDING)
    return {
        "window_days": days,
        "total": grants.count(),
        "pending": pending.count(),
        "live": grants.filter(expires_at__gt=timezone.now()).count(),
        # A grant taken and never used usually means somebody clicked through
        # a warning rather than needing the record.
        "never_used": grants.filter(use_count=0).count(),
        "by_outcome": {
            outcome: grants.filter(outcome=outcome).count()
            for outcome, _ in BreakGlassOutcome.choices
        },
        "grants": list(
            pending.order_by("granted_at").values(
                "uuid", "patient_label", "user_label", "reason",
                "granted_at", "expires_at", "use_count",
            )[:100]
        ),
    }
