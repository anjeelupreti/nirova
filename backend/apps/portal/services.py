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
