"""Inviting, registering, signing in, and deciding what a patient may see.

The rules this layer keeps, all of which are about the difference between a
staff reader and a patient one.

**Registration needs an invitation.** Not an MRN and a date of birth: both are
printed on every document the patient carries, and accepting them would make
the portal an enumeration attack with a login at the end.

**Authentication answers the same way whether or not the account exists.**
A login form that says "no such account" is a tool for finding out who is a
patient at this hospital.

**Results are released, and critical ones are held.** The portal shows only
what the laboratory released, and holds a critical result for a day so a
clinician can ring first. The hold is stated, not silent: the patient is told
a result is ready and that somebody will be in touch, because a gap they do
not know about is worse than a delay they do.

**Proxy access is checked at query time.** Never cached, never resolved at
login: consent withdrawn at ten o'clock must stop working at ten o'clock, not
at the next sign-in.

**A proxy's reads are logged, a patient's own are not.** Logging a patient
reading their own record produces noise nobody can search; logging a proxy's
is the only way to answer who looked.
"""

import logging
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
# escape: every value in a generated document is free text somebody typed,
# and the patient application renders that HTML same-origin.
from django.utils.html import escape

from apps.audit.models import AuditAction
# record: creating a portal account and granting proxy access are the two
# actions that let a new person read a medical record. Both are asked about
# afterwards.
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.portal.models import (
    ABNORMAL_HOLD_HOURS,
    CRITICAL_HOLD_HOURS,
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    SESSION_HOURS,
    AccountStatus,
    MessageDirection,
    PortalAccessLog,
    PortalAccount,
    PortalInvitation,
    PortalMessage,
    PortalSession,
    ProxyAccess,
    ProxyRelationship,
    PatientCorrectionField,
    PatientCorrectionRequest,
    PatientCorrectionStatus,
    account_for_login,
)
# tenant_atomic_method: writes that must land together open on the tenant
# connection — the router refuses to guess, so a bare `transaction.atomic`
# would protect nothing. Note that `authenticate` deliberately does *not* use
# it; see its docstring.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.portal")

#: How long an invitation is worth anything.
INVITATION_DAYS = 14

#: Wrong codes before an invitation is dead.
#:
#: Eight digits is ample against a person and nothing against a script. Five
#: guesses and the patient asks the desk for another code, which costs seconds
#: — against an attack that would otherwise cost minutes.
MAX_INVITATION_ATTEMPTS = 5


class PortalError(DomainError):
    """The portal will not do that."""


class AuthenticationFailed(PortalError):
    """Wrong credentials, a locked account, or no account at all.

    One exception for all three on purpose: distinguishing them tells an
    attacker which identifiers exist.
    """

    message = "Those details do not match an account."


def _hash(value: str) -> str:
    return make_password(value)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@tenant_atomic_method
def invite(patient, actor, delivered_by: str = "", delivered_to: str = "") -> tuple:
    """Issue a one-time registration code, and return it once.

    Returned once and stored hashed. An invitation list readable by anybody
    with database access would otherwise be a list of working credentials for
    other people's medical records.

    Any earlier unused invitation is revoked, so a patient never holds two
    live codes — the second of which they would have forgotten they had.
    """
    if hasattr(patient, "portal_account") and (
        patient.portal_account.status == AccountStatus.ACTIVE
    ):
        raise PortalError(
            f"{patient.full_name} already has a portal account. Reset the "
            "password rather than issuing a new invitation."
        )

    PortalInvitation.objects.filter(
        patient=patient, used_at__isnull=True, revoked_at__isnull=True,
    ).update(
        revoked_at=timezone.now(),
        revoked_reason="Superseded by a new invitation.",
    )

    # Digits, because it is read aloud across a desk and typed on a phone.
    # Eight of them, which is a hundred million and rate-limited by lockout.
    code = f"{secrets.randbelow(10 ** 8):08d}"
    invitation = PortalInvitation.objects.create(
        patient=patient,
        code_hash=_hash(code),
        code_hint=code[:2] + "······",
        issued_by_id=getattr(actor, "uuid", None),
        issued_by_name=getattr(actor, "full_name", "") or "",
        expires_at=timezone.now() + timedelta(days=INVITATION_DAYS),
        delivered_by=delivered_by,
        delivered_to=delivered_to,
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="portal.PortalInvitation",
        entity_id=invitation.uuid,
        entity_label=f"Portal invitation for {patient.full_name}",
        metadata={"delivered_by": delivered_by, "to": delivered_to},
    )
    return invitation, code


def register(patient, code: str, login_identifier: str, password: str,
             email: str = "") -> PortalAccount:
    """Create the account, consuming the invitation.

    The code is checked against this patient's live invitations only. Without
    that, a code guessed for one patient would open an account on whichever
    record the attacker named — so the patient is named by the MRN on their
    card and the code comes from the desk, and neither alone is enough.

    Not atomic, for the reason `authenticate` is not: a wrong code increments
    the invitation's attempt counter, and a counter written inside the
    transaction that then raises never advances. The account creation below is
    wrapped separately.
    """
    if len(password) < 8:
        raise PortalError(
            "A portal password must be at least eight characters. This "
            "account reads a medical record."
        )
    if not login_identifier.strip():
        raise PortalError("A login needs a phone number or an email address.")

    # The code is checked *before* the identifier collision, deliberately.
    # The other way round — which is how this was first written — answers
    # "does this phone number have an account here?" to anybody who asks,
    # with no code at all. That is the same disclosure the sign-in path takes
    # care to avoid, arriving through the registration form instead.
    live = [
        row for row in PortalInvitation.objects.filter(patient=patient)
        if row.is_usable
    ]
    invitation = next((row for row in live if row.check_code(code)), None)

    if invitation is None:
        # Count the guess against every live invitation for this patient, and
        # kill any that have been tried too often. Written here, outside any
        # transaction, precisely so that the refusal below cannot undo it.
        for row in live:
            row.failed_attempts += 1
            if row.failed_attempts >= MAX_INVITATION_ATTEMPTS:
                row.revoked_at = timezone.now()
                row.revoked_reason = (
                    f"{row.failed_attempts} wrong codes tried."
                )
                logger.warning(
                    "Portal invitation for patient %s revoked after repeated "
                    "wrong codes", patient.mrn,
                )
            row.save(update_fields=[
                "failed_attempts", "revoked_at", "revoked_reason",
                "updated_at",
            ])
        raise PortalError(
            "That code is not valid for this patient, or it has expired. Ask "
            "at the desk for a new one.",
        )

    # Only now, having proved they hold the desk's code for this patient.
    existing = account_for_login(login_identifier)
    if existing is not None and existing.patient_id != patient.id:
        raise PortalError(
            "That phone number or email is already used by another account."
        )

    return _create_account(
        patient, invitation, login_identifier, password, email,
    )


@tenant_atomic_method
def _create_account(patient, invitation, login_identifier: str,
                    password: str, email: str) -> PortalAccount:
    """The account and the invitation's consumption, written together.

    These two must land as one: an account created against an invitation that
    is still marked unused would let the same code be used twice.
    """
    account, _ = PortalAccount.objects.get_or_create(
        patient=patient,
        defaults={"login_identifier": login_identifier.strip()},
    )
    account.login_identifier = login_identifier.strip()
    account.email = email
    account.set_password(password)
    account.status = AccountStatus.ACTIVE
    account.registered_at = timezone.now()
    account.failed_attempts = 0
    account.locked_until = None
    account.save()

    invitation.used_at = timezone.now()
    invitation.save(update_fields=["used_at", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="portal.PortalAccount",
        entity_id=account.uuid,
        entity_label=f"Portal account for {patient.full_name}",
    )
    return account


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def authenticate(identifier: str, password: str, device: str = "",
                 ip=None) -> tuple:
    """Check the credentials and issue a session.

    Every failure raises the same exception with the same message. A form that
    distinguishes "no such account" from "wrong password" is a tool for
    finding out who is a patient at this hospital, and that is a disclosure on
    its own before anybody guesses a password.

    Deliberately **not** wrapped in `tenant_atomic_method`. The first version
    was, and the seed caught what that meant: the failed-attempt counter was
    incremented and saved, and the `AuthenticationFailed` raised on the next
    line rolled the save back. The counter never advanced, the account never
    locked, and the brute-force protection did nothing at all — while looking,
    in the code, exactly as though it worked.

    The same shape as the blood bank's cold-chain discard: a control that
    *records* something and then *refuses* cannot do the recording inside the
    transaction the refusal aborts.
    """
    account = account_for_login(identifier)

    if account is None:
        # Still spend the time hashing, so the response time does not answer
        # the question the message refuses to.
        make_password(password)
        raise AuthenticationFailed()

    if account.is_locked:
        raise AuthenticationFailed(
            "Too many attempts. Try again in a few minutes."
        )
    if account.status != AccountStatus.ACTIVE:
        raise AuthenticationFailed()

    if not account.check_password(password):
        account.failed_attempts += 1
        if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
            account.locked_until = timezone.now() + timedelta(
                minutes=LOCKOUT_MINUTES
            )
            account.failed_attempts = 0
            logger.warning(
                "Portal account %s locked after repeated failures",
                account.login_identifier,
            )
        account.save(update_fields=[
            "failed_attempts", "locked_until", "updated_at",
        ])
        raise AuthenticationFailed()

    account.failed_attempts = 0
    account.locked_until = None
    account.last_login_at = timezone.now()
    account.save(update_fields=[
        "failed_attempts", "locked_until", "last_login_at", "updated_at",
    ])

    # Two writes rather than one transaction: a sign-in timestamp with no
    # session behind it is harmless, and wrapping them would put the failure
    # path above back inside a transaction its own exception aborts.
    token = secrets.token_urlsafe(32)
    session = PortalSession.objects.create(
        account=account,
        token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(hours=SESSION_HOURS),
        device_label=device[:128],
        ip_address=ip,
    )
    return account, session, token


def session_for(token: str):
    """The live session a token belongs to, or nothing.

    Linear over live sessions because the hash is salted and cannot be looked
    up directly. Live sessions per tenant are few; if that ever stops being
    true the fix is a keyed prefix, not an unsalted hash.
    """
    if not token:
        return None
    for session in PortalSession.objects.filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).select_related("account__patient"):
        if check_password(token, session.token_hash):
            session.last_seen_at = timezone.now()
            session.save(update_fields=["last_seen_at"])
            return session
    return None


@tenant_atomic_method
def revoke_session(session: PortalSession, reason: str = "") -> PortalSession:
    """End one signed-in device, for real.

    Sessions are rows precisely so this works. "Log out everywhere" that
    invalidates nothing is the commonest lie in a consumer account screen, and
    on a medical record it matters.
    """
    session.revoked_at = timezone.now()
    session.revoked_reason = reason or "Signed out"
    session.save(update_fields=[
        "revoked_at", "revoked_reason", "updated_at",
    ])
    return session


@tenant_atomic_method
def revoke_all_sessions(account: PortalAccount, reason: str = "") -> int:
    return PortalSession.objects.filter(
        account=account, revoked_at__isnull=True,
    ).update(
        revoked_at=timezone.now(),
        revoked_reason=reason or "Signed out everywhere",
        updated_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Proxy access
# ---------------------------------------------------------------------------


@tenant_atomic_method
def grant_proxy(
    account: PortalAccount,
    patient,
    relationship: str,
    actor,
    consent_evidence: str = "",
    expires_at=None,
    can_see_results: bool = False,
    can_see_invoices: bool = True,
    can_book_appointments: bool = True,
) -> ProxyAccess:
    """Let one account see another patient's record.

    Consent evidence is required. A grant nobody can point at when it is
    questioned is one that will be revoked in a hurry along with several that
    were legitimate.
    """
    if relationship not in ProxyRelationship.values:
        raise PortalError(
            f"'{relationship}' is not a recognised relationship. Use one of: "
            f"{', '.join(ProxyRelationship.values)}."
        )
    if account.patient_id == patient.id:
        raise PortalError(
            "That is the account holder's own record; they already see it."
        )
    if not consent_evidence.strip():
        raise PortalError(
            "Granting access to somebody else's record must record how "
            "consent was obtained."
        )

    existing = ProxyAccess.objects.filter(
        account=account, patient=patient, revoked_at__isnull=True,
    ).first()
    if existing is not None:
        raise PortalError(
            f"That account already has access to {patient.full_name}'s "
            "record. Revoke it before granting different terms.",
        )

    grant = ProxyAccess.objects.create(
        account=account,
        patient=patient,
        relationship=relationship,
        can_see_results=can_see_results,
        can_see_invoices=can_see_invoices,
        can_book_appointments=can_book_appointments,
        granted_by_name=getattr(actor, "full_name", "") or "",
        consent_evidence=consent_evidence,
        expires_at=expires_at,
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="portal.ProxyAccess",
        entity_id=grant.uuid,
        entity_label=(
            f"{account.patient.full_name} may see "
            f"{patient.full_name}'s record"
        ),
        reason=consent_evidence,
        metadata={"relationship": relationship,
                  "results": can_see_results},
    )
    return grant


@tenant_atomic_method
def revoke_proxy(grant: ProxyAccess, actor, reason: str) -> ProxyAccess:
    """Withdraw it, effective immediately.

    Immediately because access is checked at query time rather than resolved
    at sign-in: consent withdrawn at ten o'clock stops working at ten
    o'clock, not at the proxy's next login.
    """
    if not reason.strip():
        raise PortalError("Revoking access must say why.")
    if grant.revoked_at is not None:
        raise PortalError("That access was already withdrawn.")

    grant.revoked_at = timezone.now()
    grant.revoked_by_name = getattr(actor, "full_name", "") or ""
    grant.revoked_reason = reason
    grant.save(update_fields=[
        "revoked_at", "revoked_by_name", "revoked_reason", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="portal.ProxyAccess",
        entity_id=grant.uuid,
        entity_label=f"Access to {grant.patient.full_name} withdrawn",
        reason=reason,
    )
    return grant


def accessible_patients(account: PortalAccount) -> list:
    """Whose records this account may open, right now.

    Recomputed on every call. Never cached on the session, because a cached
    permission is one that keeps working after it is withdrawn.
    """
    rows = [{
        "patient": account.patient,
        "relationship": "self",
        "via_proxy": False,
        "can_see_results": True,
        "can_see_invoices": True,
        "can_book_appointments": True,
    }]
    for grant in account.proxies.select_related("patient"):
        if not grant.is_live:
            continue
        rows.append({
            "patient": grant.patient,
            "relationship": grant.relationship,
            "via_proxy": True,
            "can_see_results": grant.can_see_results,
            "can_see_invoices": grant.can_see_invoices,
            "can_book_appointments": grant.can_book_appointments,
        })
    return rows


def access_for(account: PortalAccount, patient) -> dict:
    """This account's permissions over one patient, or nothing at all."""
    for row in accessible_patients(account):
        if row["patient"].id == patient.id:
            return row
    raise PortalError(
        "That record is not available to this account.",
        code="not_permitted",
    )


@tenant_atomic_method
def note_access(account: PortalAccount, patient, resource: str,
                detail: str = "", ip=None) -> None:
    """Log a proxy's read. A patient's own reads are not logged.

    Logging every time somebody opens their own record produces a table
    nobody can search and a signal nobody can find. For a proxy it is the
    only way to answer the question that eventually gets asked.
    """
    if account.patient_id == patient.id:
        return
    PortalAccessLog.objects.create(
        account=account,
        patient=patient,
        resource=resource,
        detail=detail[:255],
        via_proxy=True,
        ip_address=ip,
    )


# ---------------------------------------------------------------------------
# What may be shown
# ---------------------------------------------------------------------------


def result_visibility(order) -> dict:
    """Whether a diagnostic result may be shown, and what to say if not.

    Three answers, not two. A result can be visible, withheld-and-announced,
    or not there yet — and the middle one is the point. A critical potassium
    read from a phone at eleven at night, with nobody to ask, is a harm the
    system caused; so it is held for a day while somebody rings.

    Held is not hidden. The patient is told a result is ready and that a
    clinician will be in touch, because a gap they do not know about is worse
    than a delay they do, and because an indefinite hold is a result they
    never learn about at all.
    """
    released_at = getattr(order, "released_at", None)
    if released_at is None:
        return {
            "visible": False,
            "announce": False,
            "reason": "Not yet released by the laboratory.",
        }

    rows = list(order.results.all()) if hasattr(order, "results") else []
    critical = any(getattr(row, "is_critical", False) for row in rows)
    abnormal = any(getattr(row, "is_abnormal", False) for row in rows)

    hold_hours = (
        CRITICAL_HOLD_HOURS if critical
        else ABNORMAL_HOLD_HOURS if abnormal
        else 0
    )
    if hold_hours == 0:
        return {"visible": True, "announce": True, "reason": ""}

    available_at = released_at + timedelta(hours=hold_hours)
    if timezone.now() >= available_at:
        return {"visible": True, "announce": True, "reason": ""}

    return {
        "visible": False,
        "announce": True,
        "available_at": available_at,
        "reason": (
            "This result needs a clinician to talk you through it. Somebody "
            "will contact you; it will appear here "
            f"{'tomorrow' if critical else 'shortly'} if they have not."
        ),
    }


def results_for(patient, include_held: bool = True) -> list:
    """The patient's diagnostic orders, with what may be shown of each."""
    orders = patient.diagnostic_orders.prefetch_related("results").order_by(
        "-ordered_at"
    )[:100]

    rows = []
    for order in orders:
        visibility = result_visibility(order)
        if not visibility["visible"] and not visibility["announce"]:
            continue
        if not visibility["visible"] and not include_held:
            continue
        rows.append({
            "reference": order.reference,
            "test": order.test_name,
            "ordered_at": order.ordered_at,
            "status": order.status,
            "visible": visibility["visible"],
            "message": visibility.get("reason", ""),
            "available_at": visibility.get("available_at"),
            "results": [
                {
                    "analyte": getattr(row, "analyte_name", "")
                    or getattr(row, "name", ""),
                    "value": getattr(row, "value", ""),
                    "unit": getattr(row, "unit", ""),
                    "reference_range": getattr(row, "reference_range", ""),
                    "abnormal": getattr(row, "is_abnormal", False),
                }
                for row in order.results.all()
            ] if visibility["visible"] else [],
        })
    return rows


def appointments_for(patient, upcoming_only: bool = False) -> list:
    rows = list(patient.appointments.order_by("-scheduled_for")[:60])
    if upcoming_only:
        rows = [row for row in rows if row.scheduled_for >= timezone.now()]
    return [
        {
            "reference": row.reference,
            "when": row.scheduled_for,
            "minutes": row.duration_minutes,
            "status": row.status,
            "provider": row.provider_name,
            "facility": row.facility.name if row.facility_id else "",
            "reason": row.reason,
            "upcoming": row.scheduled_for >= timezone.now(),
        }
        for row in rows
    ]


def invoices_for(patient) -> dict:
    """What the patient owes, and what they have paid.

    Only issued documents. A draft invoice is a working note inside the
    hospital, and showing one to a patient invites an argument about a number
    nobody has agreed yet.
    """
    from decimal import Decimal

    from apps.billing.models import Invoice, InvoiceStatus

    rows = list(
        Invoice.objects.filter(patient=patient)
        .exclude(status=InvoiceStatus.DRAFT)
        .order_by("-issued_at")[:60]
    )

    outstanding = sum(
        (row.total - row.amount_paid for row in rows if not row.is_credit_note),
        Decimal("0.00"),
    )
    return {
        "outstanding": outstanding,
        "invoices": [
            {
                "number": row.number,
                "issued_on": row.issued_at.date() if row.issued_at else None,
                "total": row.total,
                "paid": row.amount_paid,
                "balance": row.balance_due,
                "status": row.status,
                "is_credit_note": row.is_credit_note,
            }
            for row in rows
        ],
    }


def prescriptions_for(patient) -> list:
    rows = patient.prescriptions.prefetch_related("lines").order_by(
        "-created_at"
    )[:30]
    return [
        {
            "reference": getattr(row, "reference", ""),
            "prescribed_on": row.created_at.date(),
            "prescriber": getattr(row, "prescriber_name", ""),
            "status": getattr(row, "status", ""),
            "lines": [
                {
                    "drug": line.generic_name,
                    "brand": getattr(line, "brand_name", ""),
                    "dose": line.dose,
                    "frequency": line.frequency,
                    "duration_days": line.duration_days,
                    "instructions": getattr(line, "instructions", ""),
                }
                for line in row.lines.all()
            ],
        }
        for row in rows
    ]


def referrals_for(patient) -> list:
    """Where the patient has been referred, and whether an answer came back.

    Shown to the patient because they are the one person who always knows
    whether they attended, and the commonest way a referral is discovered to
    have gone nowhere is the patient asking.
    """
    if not hasattr(patient, "referrals"):
        return []
    return [
        {
            "reference": row.reference,
            "specialty": row.specialty,
            "status": row.status,
            "created_on": row.created_on,
            "seen_at": row.seen_at,
            "answered": row.responded_at is not None,
        }
        for row in patient.referrals.order_by("-created_on")[:20]
    ]


def home(account: PortalAccount, patient=None) -> dict:
    """What the portal shows first.

    Held results are counted separately from visible ones, so that the first
    screen can say a result is ready and being discussed rather than showing
    a list with an unexplained gap in it.
    """
    patient = patient or account.patient
    permissions = access_for(account, patient)

    results = results_for(patient) if permissions["can_see_results"] else []
    held = [row for row in results if not row["visible"]]
    appointments = appointments_for(patient)
    upcoming = [row for row in appointments if row["upcoming"]]
    money = invoices_for(patient) if permissions["can_see_invoices"] else {
        "outstanding": 0, "invoices": [],
    }

    return {
        "patient": patient.full_name,
        "mrn": patient.mrn,
        "via_proxy": permissions["via_proxy"],
        "relationship": permissions["relationship"],
        "next_appointment": upcoming[-1] if upcoming else None,
        "upcoming_appointments": len(upcoming),
        "results_ready": len([row for row in results if row["visible"]]),
        "results_being_discussed": len(held),
        "outstanding": money["outstanding"],
        "unread_messages": PortalMessage.objects.filter(
            patient=patient,
            direction=MessageDirection.TO_PATIENT,
            read_at__isnull=True,
        ).count(),
        "can_see_results": permissions["can_see_results"],
        "can_see_invoices": permissions["can_see_invoices"],
        "can_book_appointments": permissions["can_book_appointments"],
    }


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@tenant_atomic_method
def send_message(account: PortalAccount, patient, subject: str, body: str,
                 ) -> PortalMessage:
    """A message from the patient to the practice.

    Not a clinical channel, and the portal says so beside the box. A patient
    who describes chest pain here and waits is a foreseeable harm, and a
    system that accepts the message without saying that has invited it.
    """
    access_for(account, patient)
    if not subject.strip() or not body.strip():
        raise PortalError("A message needs a subject and something to say.")

    return PortalMessage.objects.create(
        patient=patient,
        account=account,
        direction=MessageDirection.FROM_PATIENT,
        subject=subject[:255],
        body=body,
        sender_name=account.patient.full_name,
    )


@tenant_atomic_method
def reply_to_message(message: PortalMessage, body: str, actor,
                     subject: str = "") -> PortalMessage:
    """Staff answering. Marks the original answered, which read does not."""
    if not body.strip():
        raise PortalError("A reply needs something in it.")

    reply = PortalMessage.objects.create(
        patient=message.patient,
        direction=MessageDirection.TO_PATIENT,
        subject=(subject or f"Re: {message.subject}")[:255],
        body=body,
        sender_name=getattr(actor, "full_name", "") or "",
    )
    message.answered_at = timezone.now()
    message.answered_by_name = getattr(actor, "full_name", "") or ""
    message.save(update_fields=[
        "answered_at", "answered_by_name", "updated_at",
    ])
    return reply


def messages_for(patient, account: PortalAccount = None) -> list:
    rows = patient.portal_messages.order_by("-sent_at")[:50]
    return [
        {
            "uuid": str(row.uuid),
            "direction": row.direction,
            "subject": row.subject,
            "body": row.body,
            "sent_at": row.sent_at,
            "sender": row.sender_name,
            "read": row.read_at is not None,
            "answered": row.is_answered,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Oversight
# ---------------------------------------------------------------------------


def adoption(facility=None) -> dict:
    """How much of the patient list actually uses the portal.

    Invitations issued against accounts registered is the number that says
    whether the desk is offering it or quietly skipping it, and it is
    invisible if only active accounts are counted.
    """
    from apps.patients.models import Patient

    patients = Patient.objects.filter(merged_into__isnull=True).count()
    invited = PortalInvitation.objects.values("patient_id").distinct().count()
    accounts = PortalAccount.objects.count()
    active = PortalAccount.objects.filter(status=AccountStatus.ACTIVE).count()
    used_recently = PortalAccount.objects.filter(
        last_login_at__gte=timezone.now() - timedelta(days=90),
    ).count()

    return {
        "patients": patients,
        "invited": invited,
        "accounts": accounts,
        "active": active,
        "used_in_90_days": used_recently,
        "invitation_to_account_percent": (
            round(accounts * 100 / invited, 1) if invited else None
        ),
        "coverage_percent": (
            round(active * 100 / patients, 1) if patients else None
        ),
        "expired_unused_invitations": PortalInvitation.objects.filter(
            used_at__isnull=True, revoked_at__isnull=True,
            expires_at__lt=timezone.now(),
        ).count(),
        "locked_accounts": PortalAccount.objects.filter(
            locked_until__gt=timezone.now(),
        ).count(),
        "live_proxy_grants": sum(
            1 for grant in ProxyAccess.objects.all() if grant.is_live
        ),
    }


def proxy_review(days: int = 365) -> list:
    """Proxy grants that nobody has looked at in a long time.

    Consent given once and never revisited is the mechanism by which an
    estranged relative keeps reading somebody's results for years. The list
    exists so that somebody can be asked.
    """
    cutoff = timezone.now() - timedelta(days=days)
    rows = []
    for grant in ProxyAccess.objects.select_related(
        "account__patient", "patient",
    ):
        if not grant.is_live:
            continue
        if grant.granted_at > cutoff:
            continue
        last = grant.account.access_log.filter(
            patient=grant.patient,
        ).order_by("-looked_at").first()
        rows.append({
            "grant": str(grant.uuid),
            "proxy": grant.account.patient.full_name,
            "patient": grant.patient.full_name,
            "relationship": grant.relationship,
            "granted_at": grant.granted_at,
            "days_old": (timezone.now() - grant.granted_at).days,
            "expires_at": grant.expires_at,
            "can_see_results": grant.can_see_results,
            "consent_evidence": grant.consent_evidence,
            "last_looked": last.looked_at if last else None,
        })
    return sorted(rows, key=lambda row: -row["days_old"])


# ---------------------------------------------------------------------------
# Patient Demographic Corrections
# ---------------------------------------------------------------------------


def patient_profile_for(patient, account: PortalAccount) -> dict:
    """The patient's current demographic profile, along with pending proposals."""
    access_for(account, patient)
    pending_qs = PatientCorrectionRequest.objects.filter(
        patient=patient, status=PatientCorrectionStatus.PENDING,
    ).order_by("-requested_at")
    recent_qs = PatientCorrectionRequest.objects.filter(
        patient=patient,
    ).exclude(status=PatientCorrectionStatus.PENDING).order_by("-requested_at")[:10]

    return {
        "uuid": str(patient.uuid),
        "mrn": patient.mrn,
        "full_name": patient.full_name,
        "phone": patient.phone,
        "alternate_phone": patient.alternate_phone,
        "email": patient.email,
        "gender": patient.gender,
        "date_of_birth": patient.date_of_birth,
        "stated_age_years": patient.stated_age_years,
        "temporary_address": patient.temporary_address,
        "tole": patient.tole,
        "municipality": patient.municipality,
        "district": patient.district,
        "province": patient.province,
        "guardian_name": patient.guardian_name,
        "guardian_phone": patient.guardian_phone,
        "guardian_relationship": patient.guardian_relationship,
        "pending_corrections": [
            {
                "uuid": str(req.uuid),
                "field_name": req.field_name,
                "field_label": req.get_field_name_display(),
                "old_value": req.old_value,
                "proposed_value": req.proposed_value,
                "reason": req.reason,
                "status": req.status,
                "requested_at": req.requested_at,
            }
            for req in pending_qs
        ],
        "recent_corrections": [
            {
                "uuid": str(req.uuid),
                "field_name": req.field_name,
                "field_label": req.get_field_name_display(),
                "old_value": req.old_value,
                "proposed_value": req.proposed_value,
                "reason": req.reason,
                "status": req.status,
                "requested_at": req.requested_at,
                "decided_at": req.decided_at,
                "decided_by_name": req.decided_by_name,
                "decision_notes": req.decision_notes,
            }
            for req in recent_qs
        ],
    }


@tenant_atomic_method
def request_patient_correction(
    account: PortalAccount,
    patient,
    field_name: str,
    proposed_value: str,
    reason: str,
) -> PatientCorrectionRequest:
    """Submit a proposed correction to demographic or contact information."""
    access_for(account, patient)
    if field_name not in PatientCorrectionField.values:
        raise PortalError(
            f"Field '{field_name}' cannot be modified via self-service.",
            code="invalid_field",
        )

    proposed_value = proposed_value.strip()
    reason = reason.strip()
    if not proposed_value:
        raise PortalError("Proposed value cannot be empty.", code="empty_value")
    if not reason:
        raise PortalError(
            "Please provide a reason for the correction so desk staff can verify.",
            code="missing_reason",
        )

    existing_pending = PatientCorrectionRequest.objects.filter(
        patient=patient,
        field_name=field_name,
        status=PatientCorrectionStatus.PENDING,
    ).exists()
    if existing_pending:
        raise PortalError(
            f"A correction request for '{field_name}' is already pending review.",
            code="already_pending",
        )

    old_value = str(getattr(patient, field_name, "") or "")
    if old_value.strip() == proposed_value:
        raise PortalError(
            "The proposed value is identical to the current recorded value.",
            code="no_change",
        )

    correction = PatientCorrectionRequest.objects.create(
        patient=patient,
        account=account,
        field_name=field_name,
        old_value=old_value,
        proposed_value=proposed_value,
        reason=reason,
        status=PatientCorrectionStatus.PENDING,
        created_by_id=account.uuid,
    )

    record(
        AuditAction.CREATE,
        entity_type="portal.PatientCorrectionRequest",
        entity_id=correction.uuid,
        entity_label=f"Correction proposed for {patient.full_name} ({field_name})",
        reason=reason,
        metadata={"old_value": old_value, "proposed_value": proposed_value},
    )
    return correction


@tenant_atomic_method
def decide_patient_correction(
    correction: PatientCorrectionRequest,
    actor,
    approved: bool,
    decision_notes: str = "",
) -> PatientCorrectionRequest:
    """Approve or reject a patient correction proposal. Updates Patient model on approval."""
    if not correction.is_pending:
        raise PortalError(
            "This correction proposal has already been decided.",
            code="already_decided",
        )

    decision_notes = decision_notes.strip()
    if not approved and not decision_notes:
        raise PortalError(
            "A decision note is required when rejecting a correction proposal.",
            code="missing_rejection_reason",
        )

    correction.status = (
        PatientCorrectionStatus.APPROVED
        if approved
        else PatientCorrectionStatus.REJECTED
    )
    correction.decided_at = timezone.now()
    correction.decided_by_id = getattr(actor, "uuid", None)
    correction.decided_by_name = getattr(actor, "full_name", "") or str(actor)
    correction.decision_notes = decision_notes
    correction.save(update_fields=[
        "status", "decided_at", "decided_by_id", "decided_by_name",
        "decision_notes", "updated_at",
    ])

    if approved:
        patient = correction.patient
        setattr(patient, correction.field_name, correction.proposed_value)
        patient.save(update_fields=[correction.field_name, "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="portal.PatientCorrectionRequest",
        entity_id=correction.uuid,
        entity_label=f"Correction for {correction.patient.full_name} ({correction.field_name}) {correction.status}",
        reason=decision_notes,
        metadata={
            "approved": approved,
            "applied_field": correction.field_name,
            "applied_value": correction.proposed_value if approved else None,
        },
    )
    return correction


@tenant_atomic_method
def cancel_patient_correction(
    correction: PatientCorrectionRequest,
    account: PortalAccount,
) -> PatientCorrectionRequest:
    """Cancel a pending correction request by the patient account."""
    if not correction.is_pending:
        raise PortalError(
            "Only pending correction proposals can be cancelled.",
            code="not_pending",
        )
    if correction.account_id != account.id:
        raise PortalError(
            "You can only cancel your own correction proposals.",
            code="not_permitted",
        )

    correction.status = PatientCorrectionStatus.CANCELLED
    correction.decided_at = timezone.now()
    correction.decided_by_name = account.patient.full_name
    correction.decision_notes = "Cancelled by patient"
    correction.save(update_fields=[
        "status", "decided_at", "decided_by_name", "decision_notes", "updated_at",
    ])
    return correction


# ---------------------------------------------------------------------------
# Document Export Generator
# ---------------------------------------------------------------------------


def _esc(value) -> str:
    """HTML-escape a value on its way into a generated document.

    Every value in these documents is free text somebody typed -- a patient's
    name at reception, an analyte from the laboratory, a prescriber's
    instructions. None of it is trusted markup, and the patient application
    renders the result same-origin, so an unescaped `<script>` in any of them
    would run where the portal token is kept.
    """
    return escape("" if value is None else str(value))


def generate_patient_document(
    account: PortalAccount,
    patient,
    doc_type: str,
    reference: str,
) -> dict:
    """Generate a clean, printable document for lab results, prescriptions, or invoices."""
    access = access_for(account, patient)
    reference = reference.strip()

    if doc_type == "result":
        if not access["can_see_results"]:
            raise PortalError(
                "This account is not authorized to view or print diagnostic results.",
                code="not_permitted",
            )
        from apps.diagnostics.models import DiagnosticOrder

        order = DiagnosticOrder.objects.filter(
            patient=patient, reference=reference,
        ).prefetch_related("results").first()
        if order is None:
            raise PortalError(
                f"Diagnostic order '{reference}' not found for this patient.",
                code="not_found",
            )
        vis = result_visibility(order)
        if not vis["visible"]:
            raise PortalError(
                vis.get("reason", "This result is not yet available for document release."),
                code="result_held",
            )

        facility_name = _esc(getattr(order.facility, "name", "Nirova Medical Center"))
        order_date = order.ordered_at.strftime("%d %b %Y %H:%M")
        release_date = (
            order.released_at.strftime("%d %b %Y %H:%M")
            if order.released_at
            else "Released"
        )

        rows_html = ""
        for r in order.results.all():
            abnormal_badge = (
                '<span style="color: #dc2626; font-weight: 700;">[HIGH/ABNORMAL]</span>'
                if getattr(r, "is_abnormal", False)
                else ""
            )
            name = _esc(getattr(r, "analyte_name", "") or getattr(r, "name", "Analyte"))
            val = _esc(getattr(r, "value", ""))
            unit = _esc(getattr(r, "unit", ""))
            ref_range = _esc(getattr(r, "reference_range", "") or "Normal")
            rows_html += f"""
            <tr>
                <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 500;">{name}</td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-family: monospace; font-size: 1.05em;"><strong>{val}</strong> {abnormal_badge}</td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; color: #64748b;">{unit}</td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; color: #475569;">{ref_range}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Diagnostic Report - {_esc(order.reference)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; margin: 0; padding: 32px 20px; background: #f8fafc; }}
  .page {{ max-width: 800px; margin: 0 auto; background: #ffffff; padding: 40px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f172a; padding-bottom: 20px; margin-bottom: 24px; }}
  .hosp-title {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; color: #0f172a; }}
  .hosp-sub {{ font-size: 13px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .report-badge {{ background: #f1f5f9; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; color: #334155; text-align: right; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 28px; background: #f8fafc; padding: 18px; border-radius: 6px; border: 1px solid #edf2f7; font-size: 14px; }}
  .grid-label {{ color: #64748b; font-size: 12px; text-transform: uppercase; }}
  .grid-val {{ font-weight: 600; color: #0f172a; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 32px; font-size: 14px; text-align: left; }}
  th {{ background: #f1f5f9; padding: 12px 14px; font-size: 12px; font-weight: 700; text-transform: uppercase; color: #475569; border-bottom: 2px solid #cbd5e1; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: flex-end; font-size: 12px; color: #64748b; }}
  .sig-line {{ border-top: 1px solid #94a3b8; width: 220px; text-align: center; padding-top: 8px; font-size: 12px; color: #334155; font-weight: 600; }}
  .print-bar {{ max-width: 800px; margin: 0 auto 16px auto; display: flex; justify-content: space-between; align-items: center; }}
  .btn-print {{ background: #0284c7; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; }}
  .btn-print:hover {{ background: #0369a1; }}
  @media print {{
    body {{ background: white; padding: 0; }}
    .page {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
    .no-print {{ display: none !important; }}
    @page {{ margin: 1.5cm; }}
  }}
</style>
</head>
<body>
<div class="print-bar no-print">
  <span style="font-size: 13px; color: #64748b;">Nirova Health Records &bull; Official Diagnostic Release</span>
  <button class="btn-print" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="page">
  <div class="header">
    <div>
      <div class="hosp-title">{facility_name}</div>
      <div class="hosp-sub">Laboratory & Pathology Diagnostic Report</div>
    </div>
    <div class="report-badge">
      <div>REF: {_esc(order.reference)}</div>
      <div style="font-weight: 400; color: #64748b; margin-top: 3px;">Released: {release_date}</div>
    </div>
  </div>

  <div class="grid">
    <div>
      <div class="grid-label">Patient Name</div>
      <div class="grid-val">{_esc(patient.full_name)}</div>
    </div>
    <div>
      <div class="grid-label">MRN / Hospital ID</div>
      <div class="grid-val">{_esc(patient.mrn)}</div>
    </div>
    <div>
      <div class="grid-label">Age / Gender</div>
      <div class="grid-val">{patient.stated_age_years or patient.age or '—'} Y / {_esc(patient.get_gender_display())}</div>
    </div>
    <div>
      <div class="grid-label">Specimen / Ordered Date</div>
      <div class="grid-val">{order_date}</div>
    </div>
    <div style="grid-column: span 2;">
      <div class="grid-label">Investigation Ordered</div>
      <div class="grid-val" style="font-size: 15px; color: #0369a1;">{_esc(order.test_name)}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Investigation / Analyte</th>
        <th>Observed Result</th>
        <th>Unit</th>
        <th>Reference Range</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="footer">
    <div>
      <div>Verified by Authorized Hospital Laboratory Personnel</div>
      <div style="margin-top: 4px; font-size: 11px; color: #94a3b8;">Document ID: {order.uuid} &bull; Tamper-evident electronic record</div>
    </div>
    <div class="sig-line">
      Consultant Pathologist / Lab Director
    </div>
  </div>
</div>
</body>
</html>"""
        return {"html": html, "reference": order.reference, "title": f"Diagnostic Report - {_esc(order.reference)}"}

    elif doc_type == "prescription":
        if not access["can_see_results"]:
            raise PortalError(
                "This account is not authorized to view prescriptions.",
                code="not_permitted",
            )
        from apps.prescriptions.models import Prescription

        prescription = Prescription.objects.filter(
            patient=patient, reference=reference,
        ).prefetch_related("lines").first()
        if prescription is None:
            raise PortalError(
                f"Prescription '{reference}' not found for this patient.",
                code="not_found",
            )

        prescribed_date = prescription.created_at.strftime("%d %b %Y")
        prescriber = _esc(getattr(prescription, "prescriber_name", "") or "Consultant Physician")
        lines_html = ""
        for i, line in enumerate(prescription.lines.all(), 1):
            instructions = _esc(getattr(line, "instructions", "") or "As advised")
            duration = f"{line.duration_days} days" if line.duration_days else "Course completed"
            brand = f" ({_esc(line.brand_name)})" if getattr(line, "brand_name", "") else ""
            lines_html += f"""
            <tr>
              <td style="padding: 12px 14px; border-bottom: 1px solid #e2e8f0; vertical-align: top; font-weight: 700; color: #64748b;">{i}.</td>
              <td style="padding: 12px 14px; border-bottom: 1px solid #e2e8f0; vertical-align: top;">
                <div style="font-size: 15px; font-weight: 700; color: #0f172a;">{_esc(line.generic_name)}{brand}</div>
                <div style="color: #64748b; font-size: 13px; margin-top: 3px;">Sig: {_esc(line.dose)} &bull; {_esc(line.frequency)} &bull; {duration}</div>
                <div style="color: #0369a1; font-size: 12px; margin-top: 2px;">{instructions}</div>
              </td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Outpatient Prescription - {_esc(prescription.reference)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; margin: 0; padding: 32px 20px; background: #f8fafc; }}
  .page {{ max-width: 800px; margin: 0 auto; background: #ffffff; padding: 40px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f172a; padding-bottom: 20px; margin-bottom: 24px; }}
  .hosp-title {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; color: #0f172a; }}
  .hosp-sub {{ font-size: 13px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .report-badge {{ background: #f1f5f9; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; color: #334155; text-align: right; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 28px; background: #f8fafc; padding: 18px; border-radius: 6px; border: 1px solid #edf2f7; font-size: 14px; }}
  .grid-label {{ color: #64748b; font-size: 12px; text-transform: uppercase; }}
  .grid-val {{ font-weight: 600; color: #0f172a; margin-top: 2px; }}
  .rx-symbol {{ font-size: 32px; font-weight: 900; font-family: serif; color: #0284c7; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 32px; font-size: 14px; text-align: left; }}
  .footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: flex-end; font-size: 12px; color: #64748b; }}
  .sig-line {{ border-top: 1px solid #94a3b8; width: 220px; text-align: center; padding-top: 8px; font-size: 12px; color: #334155; font-weight: 600; }}
  .print-bar {{ max-width: 800px; margin: 0 auto 16px auto; display: flex; justify-content: space-between; align-items: center; }}
  .btn-print {{ background: #0284c7; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; }}
  .btn-print:hover {{ background: #0369a1; }}
  @media print {{
    body {{ background: white; padding: 0; }}
    .page {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
    .no-print {{ display: none !important; }}
    @page {{ margin: 1.5cm; }}
  }}
</style>
</head>
<body>
<div class="print-bar no-print">
  <span style="font-size: 13px; color: #64748b;">Nirova Health Records &bull; Official Outpatient Prescription</span>
  <button class="btn-print" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="page">
  <div class="header">
    <div>
      <div class="hosp-title">Nirova Medical Center</div>
      <div class="hosp-sub">Department of Clinical Medicine &bull; Outpatient Prescription</div>
    </div>
    <div class="report-badge">
      <div>RX: {_esc(prescription.reference)}</div>
      <div style="font-weight: 400; color: #64748b; margin-top: 3px;">Date: {prescribed_date}</div>
    </div>
  </div>

  <div class="grid">
    <div>
      <div class="grid-label">Patient Name</div>
      <div class="grid-val">{_esc(patient.full_name)}</div>
    </div>
    <div>
      <div class="grid-label">MRN / Hospital ID</div>
      <div class="grid-val">{_esc(patient.mrn)}</div>
    </div>
    <div>
      <div class="grid-label">Age / Gender</div>
      <div class="grid-val">{patient.stated_age_years or patient.age or '—'} Y / {_esc(patient.get_gender_display())}</div>
    </div>
    <div>
      <div class="grid-label">Prescribing Physician</div>
      <div class="grid-val">{prescriber}</div>
    </div>
  </div>

  <div class="rx-symbol">&#8478;</div>

  <table>
    <tbody>
      {lines_html}
    </tbody>
  </table>

  <div style="background: #fffbeb; border: 1px solid #fef3c7; border-radius: 6px; padding: 12px; font-size: 12px; color: #92400e; margin-top: 24px;">
    <strong>Patient Instructions:</strong> Complete full antibiotic regimen if prescribed. Take medication with or after food unless directed otherwise. In case of unexpected allergic symptoms, contact hospital casualty immediately.
  </div>

  <div class="footer">
    <div>
      <div>Registered Clinical Prescription &bull; Nirova Healthcare OS</div>
      <div style="margin-top: 4px; font-size: 11px; color: #94a3b8;">Document ID: {prescription.uuid}</div>
    </div>
    <div class="sig-line">
      {prescriber}<br>
      <span style="font-weight: 400; font-size: 11px; color: #64748b;">Medical Council Registered Practitioner</span>
    </div>
  </div>
</div>
</body>
</html>"""
        return {"html": html, "reference": prescription.reference, "title": f"Prescription - {_esc(prescription.reference)}"}

    elif doc_type == "invoice":
        if not access["can_see_invoices"]:
            raise PortalError(
                "This account is not authorized to view or print billing invoices.",
                code="not_permitted",
            )
        from apps.billing.models import Invoice, InvoiceStatus

        invoice = Invoice.objects.filter(
            patient=patient, number=reference,
        ).exclude(status=InvoiceStatus.DRAFT).prefetch_related("lines").first()
        if invoice is None:
            raise PortalError(
                f"Invoice '{reference}' not found for this patient.",
                code="not_found",
            )

        issued_date = (
            invoice.issued_at.strftime("%d %b %Y %H:%M")
            if invoice.issued_at
            else "Issued"
        )
        lines_html = ""
        lines = list(invoice.lines.all()) if hasattr(invoice, "lines") else []
        for i, l in enumerate(lines, 1):
            desc = getattr(l, "description", "") or getattr(l, "service_name", "Hospital Service")
            qty = getattr(l, "quantity", 1)
            rate = getattr(l, "unit_price", "0.00")
            disc = getattr(l, "discount_amount", "0.00")
            tot = getattr(l, "total", "0.00")
            lines_html += f"""
            <tr>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 500;">{i}.</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0;">{desc}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; text-align: center;">{qty}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; text-align: right; font-family: monospace;">Rs {rate}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; text-align: right; font-family: monospace; color: #64748b;">Rs {disc}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 700; font-family: monospace;">Rs {tot}</td>
            </tr>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Official Billing Invoice - {invoice.number}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; margin: 0; padding: 32px 20px; background: #f8fafc; }}
  .page {{ max-width: 800px; margin: 0 auto; background: #ffffff; padding: 40px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f172a; padding-bottom: 20px; margin-bottom: 24px; }}
  .hosp-title {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; color: #0f172a; }}
  .hosp-sub {{ font-size: 13px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .report-badge {{ background: #f1f5f9; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 700; color: #334155; text-align: right; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 28px; background: #f8fafc; padding: 18px; border-radius: 6px; border: 1px solid #edf2f7; font-size: 14px; }}
  .grid-label {{ color: #64748b; font-size: 12px; text-transform: uppercase; }}
  .grid-val {{ font-weight: 600; color: #0f172a; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 14px; }}
  th {{ background: #f1f5f9; padding: 12px 14px; font-size: 12px; font-weight: 700; text-transform: uppercase; color: #475569; border-bottom: 2px solid #cbd5e1; }}
  .summary-box {{ margin-left: auto; width: 300px; margin-bottom: 30px; font-size: 14px; }}
  .summary-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed #e2e8f0; }}
  .summary-total {{ display: flex; justify-content: space-between; padding: 10px 0; border-top: 2px solid #0f172a; border-bottom: 2px solid #0f172a; font-size: 16px; font-weight: 800; margin-top: 6px; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: flex-end; font-size: 12px; color: #64748b; }}
  .sig-line {{ border-top: 1px solid #94a3b8; width: 220px; text-align: center; padding-top: 8px; font-size: 12px; color: #334155; font-weight: 600; }}
  .print-bar {{ max-width: 800px; margin: 0 auto 16px auto; display: flex; justify-content: space-between; align-items: center; }}
  .btn-print {{ background: #0284c7; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; }}
  .btn-print:hover {{ background: #0369a1; }}
  @media print {{
    body {{ background: white; padding: 0; }}
    .page {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
    .no-print {{ display: none !important; }}
    @page {{ margin: 1.5cm; }}
  }}
</style>
</head>
<body>
<div class="print-bar no-print">
  <span style="font-size: 13px; color: #64748b;">Nirova Billing System &bull; Official Tax Invoice Receipt</span>
  <button class="btn-print" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="page">
  <div class="header">
    <div>
      <div class="hosp-title">Nirova Healthcare Hospital</div>
      <div class="hosp-sub">Tax Invoice &bull; Inland Revenue Department Registered</div>
      <div style="font-size: 12px; color: #64748b; margin-top: 4px;">PAN / VAT No: 600123456 &bull; Fiscal Year: {getattr(invoice, 'fiscal_year', '2082/83')}</div>
    </div>
    <div class="report-badge">
      <div>INVOICE: {invoice.number}</div>
      <div style="font-weight: 400; color: #64748b; margin-top: 3px;">Date: {issued_date}</div>
      <div style="font-weight: 700; color: #0284c7; margin-top: 3px; text-transform: uppercase;">Status: {invoice.status}</div>
    </div>
  </div>

  <div class="grid">
    <div>
      <div class="grid-label">Billed To (Patient)</div>
      <div class="grid-val">{_esc(patient.full_name)}</div>
    </div>
    <div>
      <div class="grid-label">MRN / Patient ID</div>
      <div class="grid-val">{_esc(patient.mrn)}</div>
    </div>
    <div>
      <div class="grid-label">Contact Phone</div>
      <div class="grid-val">{patient.phone or '—'}</div>
    </div>
    <div>
      <div class="grid-label">Address</div>
      <div class="grid-val">{patient.temporary_address or patient.district or 'Nepal'}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="width: 40px;">#</th>
        <th>Description / Service Item</th>
        <th style="text-align: center; width: 60px;">Qty</th>
        <th style="text-align: right; width: 100px;">Rate</th>
        <th style="text-align: right; width: 90px;">Discount</th>
        <th style="text-align: right; width: 110px;">Total</th>
      </tr>
    </thead>
    <tbody>
      {lines_html if lines_html else '<tr><td colspan="6" style="text-align: center; padding: 20px; color: #64748b;">Hospital Consultation and Standard Care Package</td></tr>'}
    </tbody>
  </table>

  <div class="summary-box">
    <div class="summary-row">
      <span style="color: #64748b;">Invoice Total:</span>
      <span style="font-family: monospace; font-weight: 600;">Rs {invoice.total}</span>
    </div>
    <div class="summary-row">
      <span style="color: #64748b;">Amount Paid:</span>
      <span style="font-family: monospace; font-weight: 600; color: #16a34a;">Rs {invoice.amount_paid}</span>
    </div>
    <div class="summary-total">
      <span>Balance Due:</span>
      <span style="font-family: monospace; color: {'#dc2626' if invoice.balance_due > 0 else '#0f172a'};">Rs {invoice.balance_due}</span>
    </div>
  </div>

  <div class="footer">
    <div>
      <div>Thank you for choosing Nirova Healthcare.</div>
      <div style="margin-top: 4px; font-size: 11px; color: #94a3b8;">This is a computer generated statutory document.</div>
    </div>
    <div class="sig-line">
      Authorized Billing Cashier
    </div>
  </div>
</div>
</body>
</html>"""
        return {"html": html, "reference": invoice.number, "title": f"Invoice - {invoice.number}"}

    raise PortalError(f"Unsupported document type '{doc_type}'. Use 'result', 'prescription', or 'invoice'.")

