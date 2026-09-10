"""Resolving what a user may do, and seeding the roles a new tenant starts with."""

import logging

# dataclass / field: UserAuthorization is assembled once per request and
# passed down. A dataclass rather than a dict, so `authorization.has(...)`
# reads as intent and a typo fails loudly instead of returning None.
from dataclasses import dataclass, field

from django.utils import timezone

# PermissionDeniedError: raised by UserAuthorization.require(), the guard
# views call when a permission is missing.
# SegregationOfDutiesViolation: raised by assert_different_actors when one
# person tries to both raise and approve the same record.
from apps.common.exceptions import PermissionDeniedError, SegregationOfDutiesViolation

# AssignmentStatus: only ACTIVE assignments are resolved. Expired and revoked
# ones are retained as history, not as access.
# PermissionOverride: per-user grants and denials layered over roles.
# Role / RoleAssignment: the role definitions, and who holds them where.
from apps.rbac.models import (
    AssignmentStatus,
    PermissionOverride,
    Role,
    RoleAssignment,
)

# PERMISSION_CODES: the authoritative set. A role granting a code absent from
# it is logged and ignored -- permissions are code, roles are data (log 018).
# Scope: the scope ladder plus Scope.covers(), which decides whether a grant
# is broad enough for what is being attempted.
# conflicting_permissions: the design-time segregation-of-duties check.
from apps.rbac.permissions import (
    PERMISSION_CODES,
    Scope,
    conflicting_permissions,
)

# AuditAction / AuditSeverity / record: revoking a role is a security event
# and has to appear in the log at that severity, next to the grant it undoes.
# Imported at module scope rather than inside `revoke_role` because
# `apps.audit` is a tenant app like this one -- no control-plane seam to keep
# lazy, unlike the identity imports elsewhere in this file.
from apps.audit.models import AuditAction, AuditSeverity
from apps.audit.services import record

logger = logging.getLogger("nirova.rbac")


@dataclass
class GrantedPermission:
    """A permission the user holds, and how far it reaches."""

    code: str
    scope: str
    facility_ids: set = field(default_factory=set)
    department_ids: set = field(default_factory=set)
    unit_ids: set = field(default_factory=set)
    sources: list = field(default_factory=list)

    def covers_scope(self, required_scope: str) -> bool:
        return Scope.covers(self.scope, required_scope)


@dataclass
class UserAuthorization:
    """Everything a user may do in one organization, resolved once.

    Built per request and passed down, rather than re-queried by each check.
    A busy screen asks about a dozen permissions; resolving them separately
    would put a dozen round trips in front of every page.
    """

    user_id: str
    organization_id: str
    permissions: dict = field(default_factory=dict)
    is_organization_owner: bool = False
    facility_ids: set = field(default_factory=set)

    def has(self, code: str, scope: str = Scope.FACILITY) -> bool:
        if self.is_organization_owner:
            return True
        granted = self.permissions.get(code)
        return granted is not None and granted.covers_scope(scope)

    def has_any(self, *codes: str) -> bool:
        return any(self.has(code) for code in codes)

    def has_all(self, *codes: str) -> bool:
        return all(self.has(code) for code in codes)

    def scope_for(self, code: str) -> str | None:
        granted = self.permissions.get(code)
        if granted is None:
            return Scope.ORGANIZATION if self.is_organization_owner else None
        return granted.scope

    def require(self, code: str, scope: str = Scope.FACILITY) -> None:
        if not self.has(code, scope):
            raise PermissionDeniedError(
                f"This action requires the '{code}' permission"
                + (f" at {scope} scope." if scope else "."),
                detail={"permission": code, "required_scope": scope},
            )

    def accessible_facility_ids(self, code: str) -> set | None:
        """Facility ids a permission reaches. `None` means all of them.

        This is what turns scope into a query filter: a department-scoped
        user gets a filtered list, not an error.
        """
        if self.is_organization_owner:
            return None
        granted = self.permissions.get(code)
        if granted is None:
            return set()
        if granted.scope == Scope.ORGANIZATION:
            return None
        return granted.facility_ids

    def accessible_department_ids(self, code: str) -> set | None:
        """Departments a permission reaches. `None` means "not narrowed here".

        Mirrors `accessible_facility_ids`, and the `None` means something
        subtly different on purpose: there, `None` is "every facility". Here it
        is "this grant is not department-scoped, so do not narrow by
        department" -- a facility-scoped grant reaches every department in its
        facilities, and answering "all departments" would be true but useless
        to a caller trying to decide whether to add a filter.
        """
        if self.is_organization_owner:
            return None
        granted = self.permissions.get(code)
        if granted is None:
            return set()
        if granted.scope not in (Scope.DEPARTMENT, Scope.UNIT):
            return None
        return granted.department_ids

    def is_own_scope(self, code: str) -> bool:
        """True if the permission is held strictly at Scope.OWN (not broader)."""
        if self.is_organization_owner:
            return False
        granted = self.permissions.get(code)
        if granted is None:
            return False
        return granted.scope == Scope.OWN

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "is_organization_owner": self.is_organization_owner,
            "permissions": {
                code: {
                    "scope": grant.scope,
                    "facility_ids": sorted(str(i) for i in grant.facility_ids),
                    "sources": grant.sources,
                }
                for code, grant in self.permissions.items()
            },
        }


def _merge(authorization: UserAuthorization, code: str, scope: str, source: str,
           facility_ids=None, department_ids=None, unit_ids=None) -> None:
    """Add a grant, keeping the broadest scope when one is held twice."""
    existing = authorization.permissions.get(code)
    if existing is None:
        authorization.permissions[code] = GrantedPermission(
            code=code,
            scope=scope,
            facility_ids=set(facility_ids or ()),
            department_ids=set(department_ids or ()),
            unit_ids=set(unit_ids or ()),
            sources=[source],
        )
        return

    existing.sources.append(source)
    existing.facility_ids |= set(facility_ids or ())
    existing.department_ids |= set(department_ids or ())
    existing.unit_ids |= set(unit_ids or ())
    if Scope.covers(scope, existing.scope):
        existing.scope = scope


def resolve_authorization(user, membership) -> UserAuthorization:
    """Compute a user's authorization inside the currently active tenant.

    Must be called with the tenant context set -- roles live in the tenant
    database.
    """
    authorization = UserAuthorization(
        user_id=str(user.uuid),
        organization_id=str(membership.organization.uuid),
        is_organization_owner=membership.is_organization_owner,
    )

    assignments = (
        RoleAssignment.objects.filter(
            user_id=user.uuid, status=AssignmentStatus.ACTIVE
        )
        .select_related("role", "facility", "department", "unit")
        .prefetch_related("role__inherits_from")
    )

    for assignment in assignments:
        if not assignment.is_in_effect:
            continue

        facility_ids = set()
        if assignment.facility_id:
            facility_ids.add(assignment.facility_id)
        if assignment.department_id and assignment.department:
            facility_ids.add(assignment.department.facility_id)
        if assignment.unit_id and assignment.unit:
            facility_ids.add(assignment.unit.department.facility_id)
        authorization.facility_ids |= facility_ids

        source = f"role:{assignment.role.code}@{assignment.scope}"
        for code in assignment.role.effective_permissions():
            if code not in PERMISSION_CODES:
                logger.warning(
                    "Role %s grants unknown permission %s", assignment.role.code, code
                )
                continue
            _merge(
                authorization,
                code,
                assignment.scope,
                source,
                facility_ids=facility_ids,
                department_ids={assignment.department_id} if assignment.department_id else None,
                unit_ids={assignment.unit_id} if assignment.unit_id else None,
            )

    _apply_overrides(authorization, user)
    return authorization


def _apply_overrides(authorization: UserAuthorization, user) -> None:
    """Apply per-user grants and denials. Denials always win.

    A denial that could be out-voted by a role would be useless: the whole
    point of withholding `refund.approve` from one manager is that their role
    would otherwise grant it.
    """
    overrides = PermissionOverride.objects.filter(user_id=user.uuid).select_related(
        "facility"
    )
    denials = []
    for override in overrides:
        if not override.is_in_effect:
            continue
        if override.is_granted:
            _merge(
                authorization,
                override.permission_code,
                override.scope,
                f"override:{override.uuid}",
                facility_ids={override.facility_id} if override.facility_id else None,
            )
        else:
            denials.append(override)

    for override in denials:
        authorization.permissions.pop(override.permission_code, None)
        if authorization.is_organization_owner:
            logger.info(
                "Denial override %s applies to an organization owner; owners "
                "bypass permission checks, so it has no effect.",
                override.uuid,
            )


def check_segregation_of_duties(permission_codes) -> list:
    """Report maker-checker conflicts in a proposed permission set.

    Called when a role is saved so the conflict is caught while someone is
    looking at it, rather than discovered during an audit.
    """
    return conflicting_permissions(permission_codes)


def assert_different_actors(maker_id, checker_id, action: str) -> None:
    """The runtime half of segregation of duties."""
    if maker_id and checker_id and str(maker_id) == str(checker_id):
        raise SegregationOfDutiesViolation(
            f"The same user may not both raise and approve a {action}.",
            detail={"action": action},
        )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

#: Roles every new tenant starts with. Chosen to cover the jobs that exist in
#: a Nepali clinic, hospital or pharmacy on day one -- customers rename,
#: narrow and extend from here.
SYSTEM_ROLES = [
    {
        "code": "organization_admin",
        "name": "Organization Administrator",
        "description": "Full authority across the organization.",
        "is_superuser_role": True,
        "max_scope": Scope.ORGANIZATION,
        "permissions": sorted(PERMISSION_CODES),
        # "*" -- may delegate any role. Consistent rather than special-cased:
        # this role already holds every permission, so the strict subset rule
        # would let it grant anything regardless. Saying so explicitly means
        # `_may_delegate` has one path instead of an `is_superuser_role`
        # exception nobody would think to test.
        "grantable_roles": ["*"],
    },
    {
        "code": "operations_manager",
        "name": "Operations Manager",
        "description": (
            "Plans the estate: proposes opening, closing and converting "
            "facilities across the organization. Cannot approve their own "
            "proposals."
        ),
        "max_scope": Scope.ORGANIZATION,
        "permissions": [
            "organization.read", "facility.read", "facility.request_change",
            "department.read", "department.manage", "config.read",
            "employee.read", "report.read", "analytics.read",
            "subscription.read", "notification.broadcast",
        ],
    },
    {
        "code": "facility_manager",
        "name": "Facility Manager",
        "description": "Runs one facility day to day.",
        "max_scope": Scope.FACILITY,
        "permissions": [
            "visit.schedule",
            "organization.read", "facility.read", "facility.request_change",
            "department.read", "department.manage", "config.read",
            "user.read", "user.invite", "role.read", "role.assign",
            "patient.read", "encounter.read", "bed.manage",
            "discharge.override", "theatre.override",
            "stock.read", "stock.approve_adjustment", "stock.transfer",
            "purchase.read", "purchase.approve",
            "invoice.read", "payment.record", "refund.approve",
            "discount.approve", "employee.read", "attendance.read",
            "leave.approve", "report.read", "analytics.read", "audit.read",
        ],
        "grantable_roles": ["doctor", "nurse", "receptionist", "lab_technician",
            "pharmacy_counter", "store_keeper", "staff",],
    },
    {
        "code": "doctor",
        "name": "Doctor",
        "description": "Consulting clinician.",
        # **Facility, not department.**
        #
        # Measured before changing: a doctor could reach 6 of the 27 screens
        # in the navigation and a *receptionist* could reach 17. Six screens
        # -- the nurse workspace, ICU, theatre, blood bank, referrals and the
        # patient portal -- ask for `encounter.read` at facility scope, and
        # every one of them was refused to the only role qualified to use it.
        #
        # A consultant in a Nepali hospital covers the ward, not one
        # department: they are called to ICU, they order blood, they refer
        # out. Capping the role at department described an organisation chart
        # nobody works to.
        #
        # This widens *where* the role may be granted, not what it may do. The
        # permission list below is unchanged, and relationship narrowing still
        # holds browsing to the doctor's own patients when a customer turns
        # the privacy switch on -- the two controls are independent, which is
        # the point of having both.
        "max_scope": Scope.FACILITY,
        "permissions": [
            "visit.schedule",
            "facility.read", "department.read",
            "patient.read", "patient.create", "patient.update",
            "encounter.read", "encounter.create",
            "prescription.create", "report.read",
                    "patient.safety.read", "patient.clinical.read",
        ],
    },
    {
        "code": "nurse",
        "name": "Nurse",
        "description": "Ward and outpatient nursing.",
        # Same ceiling, and for a blunter reason: **a nurse could not open the
        # nurse workspace.** That screen asks for `encounter.read` at facility
        # scope, and the nurse role was capped below it, so the one screen
        # built for this role was the one it could not reach. Five of 27
        # visible, fewer than any other clinical role.
        #
        # A ward spans departments by construction -- that is what a ward is.
        "max_scope": Scope.FACILITY,
        "permissions": [
            "visit.schedule",
            "facility.read", "department.read",
            "patient.read", "patient.update",
            "encounter.read", "encounter.create", "stock.read",
                    "patient.safety.read", "patient.clinical.read",
        ],
    },
    {
        "code": "pharmacist",
        "name": "Pharmacist",
        "description": "Dispensing and pharmacy stock.",
        "max_scope": Scope.FACILITY,
        "permissions": [
            "catalog.manage",
            "facility.read", "patient.read",
            "prescription.dispense", "prescription.approve",
            "stock.read", "stock.adjust", "stock.count", "stock.transfer",
            "purchase.read", "purchase.create",
            "invoice.read", "invoice.create", "payment.record", "report.read",
            "sale.read", "sale.create", "sale.return", "till.open",
                    "patient.safety.read",
        ],
    },
    {
        "code": "pharmacy_counter",
        "name": "Pharmacy Counter Assistant",
        "description": "Retail counter: sells, takes payment, raises returns.",
        # Facility scope, not organization: a counter assistant sells at the
        # branch they are standing in. Nothing about the job requires seeing
        # another branch's takings.
        "max_scope": Scope.FACILITY,
        "permissions": [
            "facility.read", "patient.read", "stock.read",
            "sale.read", "sale.create", "sale.return", "till.open",
            "invoice.read", "payment.record",
                    "patient.safety.read",
        ],
    },
    {
        "code": "pharmacy_manager",
        "name": "Pharmacy Manager",
        "description": "Runs the pharmacy: approves voids, returns and tills.",
        "max_scope": Scope.FACILITY,
        # Deliberately holds neither `sale.create` nor `sale.return`, so the
        # segregation-of-duties check has something to bite on. A manager who
        # also sells can approve their own void, and the till reconciliation
        # stops meaning anything.
        "permissions": [
            "catalog.manage",
            "facility.read", "department.read", "patient.read",
            "stock.read", "stock.approve_adjustment", "stock.count",
            "sale.read", "sale.void", "sale.return_approve", "till.reconcile",
            "purchase.read", "purchase.approve", "supplier.manage",
            "invoice.read", "refund.approve", "discount.approve",
            "report.read", "analytics.read",
        ],
    },
    {
        "code": "lab_technician",
        "name": "Laboratory Technician",
        "description": "Sample handling and result entry.",
        "max_scope": Scope.DEPARTMENT,
        "permissions": [
            "facility.read", "department.read", "patient.read",
            "encounter.read", "stock.read", "report.read",
                    "patient.safety.read",
        ],
    },
    {
        "code": "receptionist",
        "name": "Receptionist",
        "description": "Registration, appointments and front-desk billing.",
        "max_scope": Scope.FACILITY,
        "permissions": [
            "visit.schedule",
            "facility.read", "patient.read", "patient.create", "patient.update",
            "encounter.read", "invoice.read", "invoice.create", "payment.record",
        ],
    },
    {
        "code": "store_keeper",
        "name": "Store Keeper",
        "description": "Receiving, storage and issue of stock.",
        "max_scope": Scope.FACILITY,
        "permissions": [
            "catalog.manage",
            "facility.read", "stock.read", "stock.adjust", "stock.count",
            "stock.transfer", "purchase.read", "purchase.create",
            "supplier.manage",
        ],
    },
    {
        "code": "accountant",
        "name": "Accountant",
        "description": "Billing, receivables and payables.",
        "max_scope": Scope.ORGANIZATION,
        "permissions": [
            "catalog.manage",
            "facility.read", "invoice.read", "invoice.create",
            "payment.record", "refund.create", "purchase.read", "salary.read",
            "report.read", "analytics.read", "subscription.read",
        ],
    },
    {
        "code": "hr_manager",
        "name": "HR Manager",
        "description": "People, attendance and payroll preparation.",
        "max_scope": Scope.ORGANIZATION,
        "permissions": [
            "facility.read", "department.read", "user.read", "user.invite",
            "employee.read", "employee.manage", "employee.hire",
            "employee.separate", "employee.transfer", "position.manage",
            "credential.read", "attendance.read",
            # Whoever runs payroll must be able to see what people are paid.
            # Withholding it while granting `payroll.process` is a rule that
            # only stops the job being done.
            "salary.read",
            "leave.approve", "payroll.process", "report.read",
        ],
    },
    {
        "code": "medical_director",
        "name": "Medical Director",
        "description": (
            "Clinical governance: verifies professional registrations and "
            "signs off who may practise."
        ),
        "max_scope": Scope.ORGANIZATION,
        # Holds `credential.verify` and deliberately not `employee.manage`:
        # the person who records a claimed registration must not be the one
        # who attests it, which is how forged registrations get caught.
        "permissions": [
            "catalog.manage",
            "organization.read", "facility.read", "department.read",
            "employee.read", "credential.read", "credential.verify",
            "patient.read", "encounter.read", "prescription.approve",
            "report.read", "analytics.read", "audit.read",
                    "patient.safety.read", "patient.clinical.read", "privacy.review",
        ],
        "grantable_roles": ["doctor", "nurse", "lab_technician", "staff",],
    },
    {
        "code": "auditor",
        "name": "Auditor",
        "description": "Read-only oversight across the organization.",
        "max_scope": Scope.ORGANIZATION,
        "permissions": [
            "organization.read", "facility.read", "department.read",
            "config.read", "user.read", "role.read", "patient.read",
            "encounter.read", "stock.read", "purchase.read", "invoice.read",
            "employee.read", "credential.read", "salary.read",
            "report.read", "analytics.read",
            "audit.read", "audit.export", "subscription.read",
                    "patient.safety.read", "patient.clinical.read", "privacy.review",
        ],
    },
    {
        "code": "staff",
        "name": "Staff / Employee",
        "description": "Base role for every employee. Grants self-service access to own profile, attendance, roster and payslips.",
        "max_scope": Scope.OWN,
        "permissions": [
            "employee.read", "attendance.read", "salary.read",
        ],
    },
]


def seed_system_roles() -> int:
    """Create the standard roles in the active tenant database.

    Idempotent: re-running refreshes system roles' permissions to match the
    current catalogue without disturbing roles the customer has created or
    permissions they have deliberately removed from a custom role.
    """
    created = 0
    for spec in SYSTEM_ROLES:
        role, was_created = Role.objects.update_or_create(
            code=spec["code"],
            defaults={
                "name": spec["name"],
                "description": spec.get("description", ""),
                "is_system": True,
                "is_superuser_role": spec.get("is_superuser_role", False),
                "permissions": sorted(spec["permissions"]),
                "grantable_roles": spec.get("grantable_roles", []),
                "max_scope": spec.get("max_scope", Scope.FACILITY),
                "is_active": True,
            },
        )
        created += int(was_created)

    logger.info("Seeded %d system roles (%d new)", len(SYSTEM_ROLES), created)
    return created


def _widest_scope(authorization) -> str:
    """The widest scope this person holds anything at.

    Used to stop somebody delegating further than they can reach themselves. A
    facility-scoped manager may hand a role to somebody at their facility; they
    may not hand out an organization-wide one.
    """
    widest = Scope.OWN
    for granted in authorization.permissions.values():
        if Scope.covers(granted.scope, widest):
            widest = granted.scope
    return widest


def _assert_may_grant(authorization, role, scope, target_user) -> None:
    """Refuse a grant the assigner is not entitled to make.

    **Rule 1 -- delegation.** A role may be granted if it is named in the
    `grantable_roles` of a role the assigner holds, or if the assigner holds
    every permission it carries. The second half is the original rule and is
    kept as a fallback so a custom role with no delegation list still cannot
    be used to invent authority; the first half exists because the original
    rule alone was unusable. Measured against the seeded roles, it let a
    facility manager grant exactly one role -- their own -- because a manager
    does not personally hold `encounter.create`, which is the whole reason
    they are a manager and not a nurse.

    **Rule 2 -- reach.** The scope asked for may not exceed the widest scope
    the assigner holds anything at. Somebody who manages one facility may pass
    a role on there, not across the organization.

    **Rule 3 -- not to yourself.** Delegation without this is an escalation
    path with an extra step: a facility manager may grant `doctor`, so without
    this rule they could grant it to their own account and acquire clinical
    permissions they are not entitled to. Granting is for other people; if you
    need a role yourself, somebody else gives it to you, and the audit log
    then names two people instead of one.

    The organization owner is exempt from rules 1 and 2 -- they already hold
    everything, and checking them against themselves would be theatre -- but
    **not from rule 3**, because "the owner cannot self-grant" costs nothing
    and removes the only case where the log would show one name.
    """
    is_owner = bool(getattr(authorization, "is_organization_owner", False))
    assigner_id = getattr(authorization, "user_id", None)

    if assigner_id is not None and str(assigner_id) == str(
        getattr(target_user, "uuid", ""),
    ):
        raise PermissionDeniedError(
            "You cannot grant a role to yourself. Ask a colleague with the "
            "same authority to do it, so the record names two people.",
            detail={"role": role.code},
        )

    if is_owner:
        return

    if not _may_delegate(authorization, role):
        held = set(authorization.permissions)
        beyond = sorted(set(role.permissions or []) - held)
        raise PermissionDeniedError(
            f"You may not grant '{role.name}'. It is not one of the roles "
            "your own roles allow you to delegate"
            + (
                f", and it carries permissions you do not hold: "
                f"{', '.join(beyond[:5])}"
                + (f" and {len(beyond) - 5} more" if len(beyond) > 5 else "")
                if beyond else ""
            )
            + ".",
            detail={"role": role.code, "beyond_your_authority": beyond},
        )

    if not Scope.covers(_widest_scope(authorization), scope):
        raise PermissionDeniedError(
            f"You may not grant a role at {scope} scope; your own authority "
            "does not reach that far.",
            detail={"role": role.code, "requested_scope": scope},
        )


def _may_delegate(authorization, role) -> bool:
    """Whether any role this person holds permits delegating `role`.

    Reads the delegation lists off the assigner's *own* active assignments --
    one query, joined to `Role`. It deliberately does not read
    `authorization.permissions`, which is flattened to permission codes by the
    time it reaches here and has lost which role each came from; delegation is
    a property of the role, not of the permissions it happens to carry.
    """
    delegable = set()
    rows = (
        RoleAssignment.objects.filter(
            user_id=authorization.user_id, status=AssignmentStatus.ACTIVE,
        )
        .select_related("role")
        .filter(role__is_active=True)
    )
    for assignment in rows:
        entries = assignment.role.grantable_roles or []
        if "*" in entries:
            return True
        delegable.update(entries)
    if role.code in delegable:
        return True

    # Fallback: the original strict rule. Holding everything a role carries is
    # sufficient on its own, and is what lets a tenant that has never
    # configured delegation still work.
    return set(role.permissions or []).issubset(set(authorization.permissions))


def assign_role(user, role_code: str, scope: str = Scope.ORGANIZATION,
                facility=None, department=None, assigned_by=None,
                reason: str = "", assigner_authorization=None) -> RoleAssignment:
    """Give a user a role in the active tenant.

    `assigner_authorization` is the resolved authority of whoever is doing the
    assigning, and passing it turns on the escalation check below. It is
    optional because the seeds and `provision_login` create the first
    administrator, and there is nobody to check them against; **every path a
    human can reach must pass it.**
    """
    role = Role.objects.filter(code=role_code, is_active=True).first()
    if role is None:
        raise PermissionDeniedError(
            f"No active role with code '{role_code}'.",
            detail={"role": role_code},
        )

    if not Scope.covers(role.max_scope, scope):
        raise PermissionDeniedError(
            f"The '{role.name}' role may not be granted at {scope} scope; its "
            f"maximum is {role.max_scope}.",
            detail={"role": role_code, "requested_scope": scope,
                    "max_scope": role.max_scope},
        )

    # A scope that names nothing reaches nothing. This was storable until now,
    # and produced a user who appeared to hold a role and could see no rows --
    # the worst kind of failure, because it looks like a working assignment
    # from the administration screen and like a broken product to the person
    # holding it. It briefly became the *opposite* failure when
    # `apply_scope_filter` arrived and its fall-through returned everything
    # (log 157); that is fixed, but the row should never have existed.
    narrow = {
        Scope.UNIT, Scope.DEPARTMENT, Scope.FACILITY, Scope.MULTI_FACILITY,
    }
    if scope in narrow and facility is None and department is None:
        raise PermissionDeniedError(
            f"A {scope}-scoped assignment has to name a facility or a "
            "department. Without one it reaches nothing, and the person would "
            "appear to hold the role while seeing none of it.",
            detail={"role": role_code, "scope": scope},
        )

    # ---------------------------------------------------------------
    # May this person grant this role?
    # ---------------------------------------------------------------
    # Three rules, and all three have to hold. Skipped entirely when no
    # `assigner_authorization` is passed, which is how the seeds and
    # `provision_login` create the first administrator of a tenant -- there is
    # nobody to check them against. **Every path a human can reach must pass
    # it**; `apps/rbac/admin_api.py` does.
    if assigner_authorization is not None:
        _assert_may_grant(
            assigner_authorization, role, scope, target_user=user,
        )

    assignment, _ = RoleAssignment.objects.update_or_create(
        user_id=user.uuid,
        role=role,
        scope=scope,
        facility=facility,
        department=department,
        unit=None,
        defaults={
            "user_email": user.email,
            "status": (
                AssignmentStatus.PENDING
                if role.requires_approval_to_assign
                else AssignmentStatus.ACTIVE
            ),
            "assigned_by_id": getattr(assigned_by, "uuid", None),
            "reason": reason,
            "valid_from": timezone.now(),
        },
    )
    return assignment


def revoke_role(assignment, actor=None, reason: str = "") -> "RoleAssignment":
    """Take a role away.

    **Revoked, not deleted.** Who could do what, and until when, has to stay
    answerable after somebody has left -- an audit that can only report the
    present tense cannot answer "who could have approved this in March?".
    `RoleAssignment` already carries `revoked_at` for exactly this; nothing
    was setting it, because until now nothing could take a role away at all.

    Idempotent: revoking an already-revoked assignment returns it unchanged
    rather than raising. Two administrators clicking the same button a second
    apart is not an error, and making it one turns a race into a support
    ticket.
    """
    if assignment.status == AssignmentStatus.REVOKED:
        return assignment

    assignment.status = AssignmentStatus.REVOKED
    assignment.revoked_at = timezone.now()
    if reason:
        assignment.reason = reason
    assignment.save(
        update_fields=["status", "revoked_at", "reason", "updated_at"]
    )

    record(
        AuditAction.UPDATE,
        entity_type="rbac.RoleAssignment",
        entity_id=assignment.uuid,
        entity_label=f"{assignment.role.name} revoked from "
                     f"{assignment.user_email}",
        reason=reason,
        # SENSITIVE, because losing a role and gaining one are the same
        # class of event to whoever reads this log later.
        severity=AuditSeverity.SENSITIVE,
        metadata={
            "role": assignment.role.code,
            "scope": assignment.scope,
            "revoked_by": str(getattr(actor, "uuid", "")),
        },
    )
    return assignment


# ---------------------------------------------------------------------------
# Who holds a permission
# ---------------------------------------------------------------------------


def holders_of(code: str, facility=None, exclude_user_id=None) -> list[dict]:
    """Everybody in the active tenant who can currently exercise `code`.

    The missing primitive underneath every approval notification: "this needs
    approving" is useless without "by whom". `resolve_authorization` answers
    the question one user at a time, from the user inwards; this answers it
    from the permission outwards, which is the direction a notification needs.

    Returns `[{"id", "name", "reason"}]`, shaped for `notify()` -- including
    the reason, because the receipt stores *why* somebody was told and a
    generic "you have permission" is not an answer anybody finds useful three
    weeks later.

    Three rules it keeps, each mirroring `resolve_authorization` so that the
    two cannot disagree about who holds what:

    **Only assignments in effect.** A lapsed locum is not an approver, and a
    notification sent to one is a request that will sit forever.

    **Denials beat grants,** exactly as they do at permission-check time.
    Telling somebody to approve something they will then be refused is worse
    than not telling them: they act on it, fail, and have no idea why.

    **Facility narrowing is a filter, not a requirement.** A grant that names
    no facility, or one held at organization scope, reaches everywhere -- so
    passing a facility narrows the list rather than demanding a match.

    `exclude_user_id` drops the person who raised the thing. Segregation of
    duties will refuse them at the point of approval anyway (§17), and a
    notification asking somebody to approve their own purchase order is an
    invitation to try.
    """
    from apps.identity.models import Membership, MembershipStatus

    facility_id = getattr(facility, "id", None)

    granted: dict = {}
    for assignment in (
        RoleAssignment.objects.filter(status=AssignmentStatus.ACTIVE)
        .select_related("role", "facility", "department")
        .prefetch_related("role__inherits_from")
    ):
        if not assignment.is_in_effect:
            continue
        if code not in assignment.role.effective_permissions():
            continue

        # Which facilities this assignment reaches. `None` means all of them.
        reach = None
        if assignment.scope != Scope.ORGANIZATION:
            reach = set()
            if assignment.facility_id:
                reach.add(assignment.facility_id)
            if assignment.department_id and assignment.department:
                reach.add(assignment.department.facility_id)
        if facility_id is not None and reach is not None and facility_id not in reach:
            continue

        granted[assignment.user_id] = (
            f"You hold {assignment.role.name}"
        )

    for override in PermissionOverride.objects.filter(permission_code=code):
        if not override.is_in_effect:
            continue
        if not override.is_granted:
            # A denial removes the person however they came to be here.
            granted.pop(override.user_id, None)
            continue
        if (
            facility_id is not None
            and override.facility_id is not None
            and override.facility_id != facility_id
        ):
            continue
        granted.setdefault(
            override.user_id, "You were granted this permission directly",
        )

    if exclude_user_id is not None:
        granted.pop(exclude_user_id, None)

    if not granted:
        return []

    # Names come from the control plane, in one query rather than per person.
    members = {
        m.user.uuid: (getattr(m.user, "full_name", "") or m.user.email)
        for m in Membership.objects.filter(
            user__uuid__in=list(granted), status=MembershipStatus.ACTIVE,
        ).select_related("user")
    }
    return [
        {"id": user_id, "name": members.get(user_id, ""), "reason": reason}
        # A user whose membership has been suspended keeps their role rows but
        # cannot sign in, so telling them is telling nobody.
        for user_id, reason in granted.items()
        if user_id in members
    ]
