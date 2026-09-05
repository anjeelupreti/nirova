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
    },
    {
        "code": "doctor",
        "name": "Doctor",
        "description": "Consulting clinician.",
        "max_scope": Scope.DEPARTMENT,
        "permissions": [
            "facility.read", "department.read",
            "patient.read", "patient.create", "patient.update",
            "encounter.read", "encounter.create",
            "prescription.create", "report.read",
        ],
    },
    {
        "code": "nurse",
        "name": "Nurse",
        "description": "Ward and outpatient nursing.",
        "max_scope": Scope.DEPARTMENT,
        "permissions": [
            "facility.read", "department.read",
            "patient.read", "patient.update",
            "encounter.read", "encounter.create", "stock.read",
        ],
    },
    {
        "code": "pharmacist",
        "name": "Pharmacist",
        "description": "Dispensing and pharmacy stock.",
        "max_scope": Scope.FACILITY,
        "permissions": [
            "facility.read", "patient.read",
            "prescription.dispense", "prescription.approve",
            "stock.read", "stock.adjust", "stock.count", "stock.transfer",
            "purchase.read", "purchase.create",
            "invoice.read", "invoice.create", "payment.record", "report.read",
            "sale.read", "sale.create", "sale.return", "till.open",
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
        ],
    },
    {
        "code": "receptionist",
        "name": "Receptionist",
        "description": "Registration, appointments and front-desk billing.",
        "max_scope": Scope.FACILITY,
        "permissions": [
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
            "organization.read", "facility.read", "department.read",
            "employee.read", "credential.read", "credential.verify",
            "patient.read", "encounter.read", "prescription.approve",
            "report.read", "analytics.read", "audit.read",
        ],
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
                "max_scope": spec.get("max_scope", Scope.FACILITY),
                "is_active": True,
            },
        )
        created += int(was_created)

    logger.info("Seeded %d system roles (%d new)", len(SYSTEM_ROLES), created)
    return created


def assign_role(user, role_code: str, scope: str = Scope.ORGANIZATION,
                facility=None, department=None, assigned_by=None,
                reason: str = "") -> RoleAssignment:
    """Give a user a role in the active tenant."""
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
