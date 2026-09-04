"""Hiring, moving, verifying and separating people.

Every function that changes someone's posting does two writes: it moves the
denormalised pointer on `Employee` **and** appends an `EmploymentEvent`. That
is the whole discipline of this module. A transfer that only updated the
department would answer "where do they work?" and permanently destroy "where
did they work in March?" — and the second question is the one that gets asked
when something has gone wrong.

The other rule worth stating up front: **a lapsed credential blocks clinical
work.** It is the same shape as the supplier drug-licence rule in
procurement, and for the same reason — the moment to catch it is before the
work happens, not in an audit afterwards.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: the append-only audit trail. Employment changes are contested more
# often than almost anything else in the system -- who approved a transfer,
# when a suspension started -- so each one leaves a row.
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.hr.models import (
    BLOCKING_CREDENTIALS,
    WORKING_STATUSES,
    ContractStatus,
    Credential,
    Employee,
    EmployeeStatus,
    EmploymentContract,
    EmploymentEvent,
    EmploymentType,
    EventType,
    Position,
    ProfileCorrectionRequest,
    ProfileCorrectionStatus,
    VerificationStatus,
)
from apps.organization.models import Department, Facility
# assert_different_actors: maker-checker. Whoever verifies a credential may
# not be the person it belongs to.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.hr")

#: How far ahead to warn about something expiring. Ninety days is long enough
#: to renew a council registration in Nepal, which is the binding constraint --
#: a shorter window would surface the problem too late to fix it.
EXPIRY_HORIZON_DAYS = 90


class HrError(DomainError):
    code = "hr_operation_failed"


class NotPractising(HrError):
    """Raised when someone may not do clinical work."""

    code = "credential_blocks_practice"
    status_code = 422


class EmployeeNotAvailable(HrError):
    code = "employee_not_available"
    status_code = 409


# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------


def next_employee_code(prefix: str = "EMP") -> str:
    """The next employee number.

    Not a statutory sequence, so a gap costs nothing and no lock is taken.
    Derived from the highest existing number rather than a counter table
    because employee records are created a handful at a time by one person in
    a browser, never concurrently at volume.
    """
    last = (
        Employee.all_objects.filter(employee_code__startswith=prefix)
        .order_by("-employee_code")
        .values_list("employee_code", flat=True)
        .first()
    )
    if not last:
        return f"{prefix}-0001"
    try:
        serial = int(last.rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        serial = Employee.all_objects.count() + 1
    return f"{prefix}-{serial:04d}"


# ---------------------------------------------------------------------------
# Hiring
# ---------------------------------------------------------------------------


@tenant_atomic_method
def hire(
    facility: Facility,
    first_name: str,
    last_name: str,
    actor=None,
    position: Position = None,
    department: Department = None,
    reports_to: Employee = None,
    employment_type: str = None,
    joined_on=None,
    probation_days: int = 0,
    employee_code: str = None,
    user_id=None,
    **details,
) -> Employee:
    """Create an employee and open their history.

    The `JOINED` event is written here rather than left implicit, so the
    timeline starts at the beginning. A history that begins at the first
    transfer has a hole in it exactly where the question "when did they
    start?" is asked.
    """
    joined_on = joined_on or timezone.localdate()
    # Probation is the honest default when one is being served: an employee
    # marked "permanent" from day one has no probation to fail.
    employment_type = employment_type or (
        EmploymentType.PROBATION if probation_days else EmploymentType.PERMANENT
    )

    if user_id and Employee.objects.filter(user_id=user_id).exists():
        raise HrError(
            "That login already belongs to another employee record.",
            detail={"user_id": str(user_id)},
        )

    employee = Employee.objects.create(
        employee_code=employee_code or next_employee_code(),
        first_name=first_name,
        last_name=last_name,
        facility=facility,
        position=position,
        department=department,
        reports_to=reports_to,
        employment_type=employment_type,
        joined_on=joined_on,
        probation_ends_on=(
            joined_on + timedelta(days=probation_days) if probation_days else None
        ),
        user_id=user_id,
        created_by_id=getattr(actor, "uuid", None),
        **details,
    )

    _event(
        employee,
        EventType.JOINED,
        effective_on=joined_on,
        actor=actor,
        to_position=str(position) if position else "",
        to_facility=facility.name,
        to_department=department.name if department else "",
        to_employment_type=employment_type,
        reason="Joined the organization.",
    )
    record(
        AuditAction.CREATE,
        entity_type="hr.Employee",
        entity_id=employee.uuid,
        entity_label=f"{employee.employee_code} — {employee.full_name}",
        metadata={"facility": facility.code, "type": employment_type},
    )
    return employee


def _event(employee: Employee, event_type: str, actor=None, **fields) -> EmploymentEvent:
    """Append one row to the employment history.

    Private because every caller should be a named operation — `transfer`,
    `promote`, `separate` — rather than arbitrary history-writing. An event
    log anyone can append to freely stops being a record of what happened.
    """
    return EmploymentEvent.objects.create(
        employee=employee,
        event_type=event_type,
        approved_by_id=getattr(actor, "uuid", None),
        approved_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
        **fields,
    )


@tenant_atomic_method
def transfer(
    employee: Employee,
    actor,
    reason: str,
    facility: Facility = None,
    department: Department = None,
    position: Position = None,
    reports_to: Employee = None,
    effective_on=None,
    event_type: str = None,
) -> Employee:
    """Move someone, and record where they came from.

    One function for transfer, promotion and departmental move because the
    mechanics are identical — snapshot the old values, write the new ones,
    append the event. Only the `event_type` differs, and getting that right
    is what makes turnover and internal-mobility reporting possible later.
    """
    if not reason.strip():
        raise HrError("A posting change must record why.")
    if employee.status == EmployeeStatus.SEPARATED:
        raise EmployeeNotAvailable(
            f"{employee.full_name} left on {employee.separated_on}.",
            detail={"separated_on": str(employee.separated_on)},
        )

    before = {
        "position": str(employee.position) if employee.position else "",
        "facility": employee.facility.name,
        "department": employee.department.name if employee.department else "",
    }

    changed = []
    if facility and facility.pk != employee.facility_id:
        employee.facility = facility
        changed.append("facility")
    if department is not None and department != employee.department:
        employee.department = department
        changed.append("department")
    if position is not None and position != employee.position:
        employee.position = position
        changed.append("position")
    if reports_to is not None and reports_to != employee.reports_to:
        if reports_to.pk == employee.pk:
            raise HrError("Somebody cannot report to themselves.")
        employee.reports_to = reports_to
        changed.append("reports_to")

    if not changed:
        raise HrError("Nothing about this posting would change.")

    employee.save(update_fields=[*changed, "updated_at"])

    # Derived rather than asked for, so the caller cannot mislabel a move.
    # The distinction drives reporting, and a promotion recorded as a
    # transfer is a promotion that never happened as far as the figures go.
    if event_type is None:
        if "position" in changed:
            event_type = EventType.PROMOTION
        elif "facility" in changed:
            event_type = EventType.TRANSFER
        elif "department" in changed:
            event_type = EventType.DEPARTMENT_CHANGE
        else:
            event_type = EventType.MANAGER_CHANGE

    _event(
        employee,
        event_type,
        effective_on=effective_on or timezone.localdate(),
        actor=actor,
        from_position=before["position"],
        to_position=str(employee.position) if employee.position else "",
        from_facility=before["facility"],
        to_facility=employee.facility.name,
        from_department=before["department"],
        to_department=employee.department.name if employee.department else "",
        reason=reason,
    )
    record(
        AuditAction.UPDATE,
        entity_type="hr.Employee",
        entity_id=employee.uuid,
        entity_label=f"{employee.employee_code} {event_type}",
        reason=reason,
        metadata={"changed": changed},
    )
    return employee


@tenant_atomic_method
def confirm(employee: Employee, actor, notes: str = "") -> Employee:
    """End probation successfully."""
    if employee.confirmed_on:
        raise HrError(
            f"{employee.full_name} was confirmed on {employee.confirmed_on}."
        )
    employee.confirmed_on = timezone.localdate()
    if employee.employment_type == "probation":
        employee.employment_type = "permanent"
    employee.save(
        update_fields=["confirmed_on", "employment_type", "updated_at"]
    )
    _event(
        employee, EventType.CONFIRMED, actor=actor,
        to_employment_type=employee.employment_type,
        reason=notes or "Probation completed.",
    )
    return employee


@tenant_atomic_method
def suspend(employee: Employee, actor, reason: str) -> Employee:
    """Stop someone working, reversibly.

    Distinct from separation because it is temporary and because the person
    remains employed — payroll, benefits and the reporting line all continue,
    while rostering and clinical work stop.
    """
    if not reason.strip():
        raise HrError("A suspension must record why.")
    if employee.status == EmployeeStatus.SEPARATED:
        raise EmployeeNotAvailable("They have already left.")

    employee.status = EmployeeStatus.SUSPENDED
    employee.save(update_fields=["status", "updated_at"])
    _event(employee, EventType.SUSPENSION, actor=actor, reason=reason)
    record(
        AuditAction.UPDATE,
        entity_type="hr.Employee",
        entity_id=employee.uuid,
        entity_label=f"{employee.employee_code} suspended",
        reason=reason,
    )
    logger.warning(
        "SUSPENSION %s by %s: %s",
        employee.employee_code, getattr(actor, "email", "?"), reason,
    )
    return employee


@tenant_atomic_method
def reinstate(employee: Employee, actor, reason: str) -> Employee:
    if employee.status != EmployeeStatus.SUSPENDED:
        raise HrError("Only a suspended employee can be reinstated.")
    employee.status = EmployeeStatus.ACTIVE
    employee.save(update_fields=["status", "updated_at"])
    _event(employee, EventType.REINSTATEMENT, actor=actor, reason=reason)
    return employee


@tenant_atomic_method
def separate(
    employee: Employee,
    actor,
    reason: str,
    event_type: str = EventType.RESIGNATION,
    last_working_day=None,
    notes: str = "",
) -> Employee:
    """End someone's employment.

    The employee record is **not** deleted and the user account is not touched
    here. Everything they did — prescriptions written, stock adjusted, refunds
    approved — still points at them, and a deleted record would orphan all of
    it. Revoking the login is a separate, deliberate act in identity.
    """
    if employee.status == EmployeeStatus.SEPARATED:
        raise HrError(f"They already left on {employee.separated_on}.")
    if not reason.strip():
        raise HrError("A separation must record why.")

    employee.status = EmployeeStatus.SEPARATED
    employee.separated_on = last_working_day or timezone.localdate()
    employee.separation_reason = reason
    employee.save(
        update_fields=[
            "status", "separated_on", "separation_reason", "updated_at",
        ]
    )

    # Contracts close with the person. Leaving one "active" against someone
    # who has gone would keep them in every payroll run.
    EmploymentContract.objects.filter(
        employee=employee, status=ContractStatus.ACTIVE
    ).update(status=ContractStatus.TERMINATED)

    _event(
        employee, event_type, actor=actor,
        effective_on=employee.separated_on,
        from_facility=employee.facility.name,
        from_department=employee.department.name if employee.department else "",
        from_position=str(employee.position) if employee.position else "",
        reason=reason,
        notes=notes,
    )
    record(
        AuditAction.UPDATE,
        entity_type="hr.Employee",
        entity_id=employee.uuid,
        entity_label=f"{employee.employee_code} separated",
        reason=reason,
        metadata={"last_working_day": str(employee.separated_on)},
    )
    return employee


# ---------------------------------------------------------------------------
# Onboarding: giving an employee a login
# ---------------------------------------------------------------------------


def provision_login(
    organization,
    employee: Employee,
    email: str,
    actor=None,
    role_code: str = None,
    scope: str = "facility",
    consumes_seat: bool = True,
):
    """Give an employee an account, and link the two.

    This is the seam between the control plane and the tenant, and it is the
    one place in the system where a write has to land in two databases. They
    cannot be one transaction -- different connections -- so the order is
    chosen for what survives a failure halfway:

    1. **User and membership first**, in the control plane. If the tenant
       write then fails, the result is a login with no employee record: the
       person can sign in and see nothing, which is inert and obvious.
    2. **The employee link second.** The reverse order would leave an employee
       record pointing at a user that does not exist, and every screen
       resolving a provider would break on it.

    Seats are checked before either. A plan limit that is only enforced at
    billing time is not a limit.
    """
    # Imported here rather than at module scope: `apps.hr` is a tenant app and
    # `apps.identity` is a control-plane one. A module-level import would tie
    # the two together for every caller, when only this function crosses.
    from apps.catalog.keys import LimitKey
    from apps.entitlements.services import check_quota
    from apps.identity.models import Membership, MembershipStatus, User

    if employee.user_id:
        raise HrError(
            f"{employee.full_name} already has a login.",
            detail={"user_id": str(employee.user_id)},
        )

    existing = User.objects.filter(email__iexact=email).first()
    if existing and Employee.objects.filter(user_id=existing.uuid).exists():
        raise HrError(
            f"{email} already belongs to another employee.",
            detail={"email": email},
        )

    if consumes_seat:
        check_quota(
            organization, LimitKey.MAX_USERS, requested=1
        ).raise_if_blocked()

    user = existing or User.objects.create_user(
        email=email, full_name=employee.full_name
    )
    Membership.objects.update_or_create(
        user=user,
        organization=organization,
        defaults={
            "status": MembershipStatus.ACTIVE,
            "is_default": True,
            "joined_at": timezone.now(),
            "employee_uuid": employee.uuid,
            "consumes_seat": consumes_seat,
            "invited_by_id": getattr(actor, "uuid", None),
        },
    )

    employee.user_id = user.uuid
    employee.work_email = user.email
    employee.save(update_fields=["user_id", "work_email", "updated_at"])

    if role_code:
        # Imported here for the same reason: rbac is a tenant app but the
        # assignment needs the user object, which is not.
        from apps.rbac.services import assign_role

        assign_role(
            user, role_code, scope=scope,
            facility=employee.facility if scope == "facility" else None,
            assigned_by=actor,
            reason=f"Onboarding {employee.employee_code}",
        )

    record(
        AuditAction.CREATE,
        entity_type="hr.Employee",
        entity_id=employee.uuid,
        entity_label=f"Login provisioned for {employee.employee_code}",
        metadata={"email": user.email, "role": role_code or ""},
    )
    return user


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@tenant_atomic_method
def issue_contract(
    employee: Employee,
    starts_on,
    basic_salary,
    actor=None,
    employment_type: str = None,
    ends_on=None,
    allowances: dict = None,
    **terms,
) -> EmploymentContract:
    """Put someone on new terms, superseding the old ones.

    Supersede rather than edit: last year's payroll must still be explicable
    against the terms that applied when it ran.
    """
    EmploymentContract.objects.filter(
        employee=employee, status=ContractStatus.ACTIVE
    ).update(status=ContractStatus.SUPERSEDED)

    contract = EmploymentContract.objects.create(
        employee=employee,
        employment_type=employment_type or employee.employment_type,
        starts_on=starts_on,
        ends_on=ends_on,
        basic_salary=Decimal(str(basic_salary)),
        allowances=allowances or {},
        created_by_id=getattr(actor, "uuid", None),
        **terms,
    )
    record(
        AuditAction.CREATE,
        entity_type="hr.EmploymentContract",
        entity_id=contract.uuid,
        entity_label=f"{employee.employee_code} from {starts_on}",
        metadata={"gross_monthly": str(contract.gross_monthly)},
    )
    return contract


def current_contract(employee: Employee) -> EmploymentContract | None:
    """The terms in force today.

    Filters on the dates rather than trusting `status`, because a contract
    that expired overnight is still marked active until something sweeps it —
    and payroll must not pay on lapsed terms just because a nightly job did
    not run.
    """
    today = timezone.localdate()
    return (
        EmploymentContract.objects.filter(
            employee=employee,
            status=ContractStatus.ACTIVE,
            starts_on__lte=today,
        )
        .filter(models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=today))
        .order_by("-starts_on")
        .first()
    )


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@tenant_atomic_method
def verify_credential(
    credential: Credential,
    actor,
    passed: bool = True,
    notes: str = "",
) -> Credential:
    """Record that somebody checked this against the issuing register.

    Segregation of duties: nobody verifies their own paperwork. That is not a
    hypothetical — self-verification is the entire mechanism by which forged
    council registrations survive in a hospital.
    """
    if credential.employee.user_id:
        assert_different_actors(
            credential.employee.user_id,
            getattr(actor, "uuid", None),
            "credential verification",
        )
    if not passed and not notes.strip():
        raise HrError("A failed verification must say what was wrong.")

    credential.verification_status = (
        VerificationStatus.VERIFIED if passed else VerificationStatus.FAILED
    )
    credential.verified_by_id = getattr(actor, "uuid", None)
    credential.verified_by_name = getattr(actor, "full_name", "") or ""
    credential.verified_at = timezone.now()
    credential.verification_notes = notes
    credential.save(
        update_fields=[
            "verification_status", "verified_by_id", "verified_by_name",
            "verified_at", "verification_notes", "updated_at",
        ]
    )

    record(
        AuditAction.APPROVE if passed else AuditAction.REJECT,
        entity_type="hr.Credential",
        entity_id=credential.uuid,
        entity_label=f"{credential.name} for {credential.employee.employee_code}",
        reason=notes,
    )
    if not passed:
        logger.warning(
            "CREDENTIAL VERIFICATION FAILED %s for %s: %s",
            credential.name, credential.employee.employee_code, notes,
        )
    return credential


def practice_blockers(employee: Employee) -> list:
    """Every reason this person may not do clinical work today.

    Returns a list rather than a boolean because a manager needs to know
    *which* thing to fix, and because there is often more than one. An empty
    list means they are clear.
    """
    blockers = []

    if employee.status == EmployeeStatus.SEPARATED:
        blockers.append({
            "code": "separated",
            "message": f"{employee.full_name} left on {employee.separated_on}.",
        })
    elif employee.status == EmployeeStatus.SUSPENDED:
        blockers.append({
            "code": "suspended",
            "message": f"{employee.full_name} is suspended.",
        })

    position = employee.position
    if position and position.requires_licence:
        registrations = [
            c for c in employee.credentials.all()
            if c.credential_type in BLOCKING_CREDENTIALS
        ]
        if not registrations:
            blockers.append({
                "code": "no_registration",
                "message": (
                    f"{position.title} requires a professional registration "
                    "and none is recorded."
                ),
            })
        else:
            # Clear if *any* registration is currently good. Someone may hold
            # both a council registration and a practising licence, and one
            # lapsed certificate among several valid ones is not a bar.
            usable = [c for c in registrations if not c.blocks_practice]
            if not usable:
                for credential in registrations:
                    blockers.append({
                        "code": (
                            "registration_expired" if credential.is_expired
                            else "registration_unverified"
                        ),
                        "message": (
                            f"{credential.name} "
                            + (
                                f"expired on {credential.expires_on}."
                                if credential.is_expired
                                else "has not been verified."
                            )
                        ),
                        "credential": str(credential.uuid),
                    })

    return blockers


def assert_may_practise(employee: Employee) -> None:
    """Raise unless this person may treat patients right now.

    Called before scheduling and before prescribing. Deliberately a hard
    refusal rather than a warning: practising on a lapsed registration is an
    offence under the councils' own rules, and a warning somebody can click
    past is not a control.
    """
    blockers = practice_blockers(employee)
    if blockers:
        raise NotPractising(
            blockers[0]["message"],
            detail={"blockers": blockers, "employee": employee.employee_code},
        )


def provider_for(user_id):
    """Resolve a bare `provider_uuid` to an employee.

    Scheduling, encounters and prescriptions all carry one of these with
    nothing behind it. This is the single place that gap is closed, so that
    a prescription can print a prescriber's name and council number, and a
    schedule can refuse a doctor whose registration has lapsed.
    """
    return Employee.for_user(user_id)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def expiring_credentials(facility=None, within_days: int = EXPIRY_HORIZON_DAYS) -> list:
    """What is about to lapse, soonest first.

    Includes what has already expired: something that lapsed last week is more
    urgent than something lapsing next month, and a report that only looked
    forward would hide the actual problem.
    """
    horizon = timezone.localdate() + timedelta(days=within_days)
    queryset = Credential.objects.filter(
        expires_on__isnull=False,
        expires_on__lte=horizon,
        employee__status__in=WORKING_STATUSES,
    ).select_related("employee", "employee__position")
    if facility is not None:
        queryset = queryset.filter(employee__facility=facility)

    return [
        {
            "credential": str(credential.uuid),
            "employee_code": credential.employee.employee_code,
            "employee_name": credential.employee.full_name,
            "position": (
                credential.employee.position.title
                if credential.employee.position else ""
            ),
            "type": credential.get_credential_type_display(),
            "name": credential.name,
            "reference_number": credential.reference_number,
            "expires_on": credential.expires_on,
            "days_to_expiry": credential.days_to_expiry,
            "is_expired": credential.is_expired,
            "blocks_practice": credential.blocks_practice,
            "verification_status": credential.verification_status,
        }
        for credential in sorted(queryset, key=lambda c: c.expires_on)
    ]


def expiring_contracts(facility=None, within_days: int = EXPIRY_HORIZON_DAYS) -> list:
    """Fixed-term contracts running out.

    A contract that lapses without anyone noticing means somebody is working
    with no terms — which is both a legal exposure and, in practice, how
    people end up unpaid.
    """
    horizon = timezone.localdate() + timedelta(days=within_days)
    queryset = EmploymentContract.objects.filter(
        status=ContractStatus.ACTIVE,
        ends_on__isnull=False,
        ends_on__lte=horizon,
        employee__status__in=WORKING_STATUSES,
    ).select_related("employee")
    if facility is not None:
        queryset = queryset.filter(employee__facility=facility)

    return [
        {
            "contract": str(contract.uuid),
            "employee_code": contract.employee.employee_code,
            "employee_name": contract.employee.full_name,
            "employment_type": contract.get_employment_type_display(),
            "ends_on": contract.ends_on,
            "days_to_expiry": contract.days_to_expiry,
            "is_expired": contract.is_expired,
            "gross_monthly": str(contract.gross_monthly),
        }
        for contract in sorted(queryset, key=lambda c: c.ends_on)
    ]


def headcount(facility=None) -> dict:
    """Who is on the books, and where the gaps are.

    Vacancies come from positions rather than from employees, because "how
    many nurses are we short?" cannot be answered by counting nurses.
    """
    employees = Employee.objects.filter(status__in=WORKING_STATUSES)
    positions = Position.objects.filter(is_active=True)
    if facility is not None:
        employees = employees.filter(facility=facility)
        positions = positions.filter(
            models.Q(facility=facility) | models.Q(facility__isnull=True)
        )

    by_type = dict(
        employees.values_list("employment_type")
        .annotate(n=models.Count("id"))
        .values_list("employment_type", "n")
    )
    by_department = list(
        employees.values("department__name")
        .annotate(count=models.Count("id"))
        .order_by("-count")
    )

    budgeted = sum(p.budgeted_headcount for p in positions)
    filled = sum(p.filled for p in positions)

    return {
        "total": employees.count(),
        "by_employment_type": by_type,
        "by_department": by_department,
        "budgeted": budgeted,
        "filled": filled,
        "vacancies": max(budgeted - filled, 0),
        "on_probation": sum(1 for e in employees if e.on_probation),
        "probation_overdue": sum(1 for e in employees if e.probation_overdue),
        "suspended": Employee.objects.filter(
            status=EmployeeStatus.SUSPENDED,
            **({"facility": facility} if facility else {}),
        ).count(),
        "vacant_positions": [
            {
                "code": position.code,
                "title": position.title,
                "budgeted": position.budgeted_headcount,
                "filled": position.filled,
                "vacancies": position.vacancies,
            }
            for position in positions
            if position.vacancies > 0
        ],
    }


def separations(facility=None, since=None) -> dict:
    """Turnover, from the event log rather than from a stored counter.

    Reasons are grouped by event type because that is the question a board
    asks — how many resigned versus how many were let go — and free text
    cannot be counted.
    """
    since = since or (timezone.localdate() - timedelta(days=365))
    events = EmploymentEvent.objects.filter(
        event_type__in=[
            EventType.RESIGNATION, EventType.TERMINATION, EventType.RETIREMENT
        ],
        effective_on__gte=since,
    ).select_related("employee")
    if facility is not None:
        events = events.filter(employee__facility=facility)

    headcount_now = Employee.objects.filter(status__in=WORKING_STATUSES)
    if facility is not None:
        headcount_now = headcount_now.filter(facility=facility)
    average = headcount_now.count() or 1

    by_type = dict(
        events.values_list("event_type")
        .annotate(n=models.Count("id"))
        .values_list("event_type", "n")
    )
    total = sum(by_type.values())
    return {
        "since": since,
        "total": total,
        "by_type": by_type,
        # Against current headcount rather than a true average over the
        # period, which needs a monthly snapshot this module does not keep
        # yet. Named honestly so nobody reads more into it than it says.
        "turnover_percent_of_current_headcount": round(
            total / average * 100, 1
        ),
    }


def team_of(manager: Employee) -> list:
    """Everyone reporting to this person, directly or below.

    Walks the tree in Python rather than with a recursive query. A hospital's
    reporting depth is single digits and its headcount is thousands, not
    millions, so the query count is small and the code stays legible; if that
    ever stops being true this is the function to replace with a CTE.
    """
    seen, queue, result = {manager.pk}, [manager], []
    while queue:
        current = queue.pop()
        for report in current.direct_reports.filter(
            status__in=WORKING_STATUSES
        ):
            if report.pk in seen:
                continue          # defends against a cycle in bad data
            seen.add(report.pk)
            result.append(report)
            queue.append(report)
    return result


ALLOWED_PROFILE_CORRECTION_FIELDS = {
    "phone",
    "personal_email",
    "address",
    "province",
    "district",
    "municipality",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relation",
    "bank_name",
    "bank_account_number",
    "bank_branch",
}


def request_profile_correction(
    employee: Employee,
    fields_payload: dict,
    reason: str,
    actor,
) -> ProfileCorrectionRequest:
    """Propose a correction to personal contact or bank details."""
    clean_payload = {
        k: str(v).strip()
        for k, v in fields_payload.items()
        if k in ALLOWED_PROFILE_CORRECTION_FIELDS and v is not None
    }
    if not clean_payload:
        raise HrError(
            "No valid profile fields provided to update.",
            code="invalid_profile_fields",
        )

    correction = ProfileCorrectionRequest.objects.create(
        employee=employee,
        requested_by_user_id=actor.uuid,
        fields_payload=clean_payload,
        reason=reason.strip(),
        status=ProfileCorrectionStatus.PENDING,
    )
    return correction


def decide_profile_correction(
    correction: ProfileCorrectionRequest,
    actor,
    approve: bool,
    notes: str = "",
) -> ProfileCorrectionRequest:
    """HR or manager decides a profile change request."""
    if correction.status != ProfileCorrectionStatus.PENDING:
        raise HrError(
            f"Request is already {correction.status}.",
            code="profile_request_not_pending",
        )

    assert_different_actors(
        correction.requested_by_user_id, actor.uuid, "profile change request"
    )

    correction.decided_by_user_id = actor.uuid
    correction.decided_by_name = (
        getattr(actor, "get_full_name", lambda: str(actor))() or str(actor)
    )
    correction.decided_at = timezone.now()
    correction.decision_notes = notes.strip()

    if approve:
        correction.status = ProfileCorrectionStatus.APPROVED
        emp = correction.employee
        for field, val in correction.fields_payload.items():
            if field in ALLOWED_PROFILE_CORRECTION_FIELDS:
                setattr(emp, field, val)
        emp.save()
    else:
        correction.status = ProfileCorrectionStatus.REJECTED

    correction.save()
    return correction


def cancel_profile_correction(
    correction: ProfileCorrectionRequest,
    actor,
) -> ProfileCorrectionRequest:
    """Requester cancels an unapproved correction request."""
    if correction.status != ProfileCorrectionStatus.PENDING:
        raise HrError(
            f"Request is already {correction.status}.",
            code="profile_request_not_pending",
        )
    correction.status = ProfileCorrectionStatus.CANCELLED
    correction.decision_notes = "Cancelled by requester."
    correction.decided_at = timezone.now()
    correction.save(update_fields=["status", "decision_notes", "decided_at"])
    return correction
