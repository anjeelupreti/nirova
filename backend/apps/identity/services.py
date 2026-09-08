"""Adding, changing and removing the people who can sign in.

Until this module existed there was **no way to onboard a colleague**. Every
account in any Nirova database was made by a seed script or by
`apps.hr.services.provision_login`, which requires an `Employee` and is
reachable only from `manage.py`. A hospital that bought the product could not
give its second member of staff a login.

**The seam.** `User` and `Membership` are control-plane models; `Role` and
`RoleAssignment` are tenant ones. Anything here that touches both is writing to
two databases that cannot be one transaction, so the order is chosen for what
survives a failure halfway -- the same reasoning `provision_login` documents,
and deliberately the same order:

1. **User and membership first**, in the control plane. If the tenant write
   then fails, the result is a login that can sign in and see nothing: inert,
   and obvious to whoever looks.
2. **Role assignments second.** The reverse order would leave a role assignment
   naming a user that does not exist, and every screen resolving that user
   would break on it.
"""

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog.keys import LimitKey
from apps.common.exceptions import DomainError
from apps.entitlements.services import check_quota
from apps.identity.models import Membership, MembershipStatus, User
from apps.tenancy.context import CONTROL_PLANE_ALIAS


class IdentityError(DomainError):
    """Something about a login or a membership is not allowed."""

    default_code = "identity_error"


def invite_user(
    organization,
    email: str,
    full_name: str,
    actor=None,
    consumes_seat: bool = True,
    facility_uuids=None,
    employee_uuid=None,
) -> tuple[User, bool]:
    """Give somebody a login and a membership of this organization.

    Returns `(user, created)` -- `created` describing the *membership*, not the
    user, because the interesting question for the caller is "did I just add
    somebody" and a person may already have an account from another
    organization on the same platform.

    No password is set. A user with no usable password cannot sign in until
    they set one, which is what an invitation means; issuing a password here
    would mean transmitting it, and a password somebody else has typed for you
    is not a credential.
    """
    email = (email or "").strip().lower()
    if not email:
        raise IdentityError("An invitation needs an email address.")
    full_name = (full_name or "").strip()
    if not full_name:
        raise IdentityError("An invitation needs a name.")

    existing_membership = Membership.objects.filter(
        user__email__iexact=email, organization=organization,
    ).first()
    if existing_membership and existing_membership.status == MembershipStatus.ACTIVE:
        raise IdentityError(
            f"{email} is already a member of this organization.",
            detail={"email": email},
        )

    # Seats are checked before anything is written. A plan limit enforced only
    # at billing time is not a limit -- and a reactivation consumes a seat
    # exactly as a new invitation does, which is why this is outside the
    # branch below rather than inside it.
    if consumes_seat:
        check_quota(
            organization, LimitKey.MAX_USERS, requested=1,
        ).raise_if_blocked()

    with transaction.atomic(using=CONTROL_PLANE_ALIAS):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email=email, full_name=full_name)
            # `create_user` with no password leaves a usable hash on some
            # Django paths; this makes the intent explicit and unambiguous.
            user.set_unusable_password()
            user.save(update_fields=["password"])
        elif not user.full_name:
            user.full_name = full_name
            user.save(update_fields=["full_name"])

        membership, created = Membership.objects.update_or_create(
            user=user,
            organization=organization,
            defaults={
                "status": MembershipStatus.ACTIVE,
                "employee_uuid": employee_uuid,
                "facility_uuids": list(facility_uuids or []),
                "consumes_seat": consumes_seat,
                "invited_at": timezone.now(),
                "invited_by_id": getattr(actor, "uuid", None),
                "revoked_at": None,
                # Their first organization is their default; a second one is
                # not, or switching organizations would silently move them.
                "is_default": not Membership.objects.filter(
                    user=user,
                ).exclude(organization=organization).exists(),
            },
        )

    record(
        AuditAction.CREATE,
        entity_type="identity.Membership",
        entity_id=membership.uuid,
        entity_label=f"{full_name} <{email}> invited",
        metadata={"email": email, "consumes_seat": consumes_seat},
    )
    return user, created


def update_user(user, actor=None, **fields):
    """Change a person's own details. Not their access -- see `assign_role`.

    Only the fields somebody may correct about a colleague are accepted, by
    allow-list rather than by passing `**fields` to `setattr`: the difference
    between the two is whether `is_platform_staff` is editable over HTTP.
    """
    editable = {"full_name", "preferred_name", "phone", "locale", "timezone"}
    changes = {}
    for key, value in fields.items():
        if key not in editable or value is None:
            continue
        if getattr(user, key) != value:
            changes[key] = {"from": getattr(user, key), "to": value}
            setattr(user, key, value)

    if not changes:
        return user

    user.save(update_fields=[*changes, "updated_at"])
    record(
        AuditAction.UPDATE,
        entity_type="identity.User",
        entity_id=user.uuid,
        entity_label=user.full_name or user.email,
        changes=changes,
    )
    return user


def deactivate_membership(organization, user, actor=None, reason: str = ""):
    """End somebody's access to this organization, and free their seat.

    Revokes their role assignments in the tenant as well, because a membership
    that is revoked while its role assignments stay active is a person who
    reappears the moment anybody reactivates them -- with authority nobody
    reviewed. Leavers come back; their old permissions should not.

    The membership is **revoked, not deleted**. Who could see what, and when,
    has to stay answerable after they have gone.
    """
    membership = Membership.objects.filter(
        user=user, organization=organization,
    ).first()
    if membership is None:
        raise IdentityError("That person is not a member of this organization.")
    if membership.status != MembershipStatus.ACTIVE:
        raise IdentityError(f"{user.email} is already {membership.status}.")
    if membership.is_organization_owner:
        # Not a permission check -- an owner with `user.deactivate` would pass
        # one. This is the invariant that an organization always has somebody
        # who can administer it.
        raise IdentityError(
            "The organization owner cannot be deactivated. Transfer "
            "ownership first.",
        )

    revoked = revoke_all_roles(user, actor=actor, reason=reason or "Deactivated")

    membership.status = MembershipStatus.REVOKED
    membership.revoked_at = timezone.now()
    membership.save(update_fields=["status", "revoked_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="identity.Membership",
        entity_id=membership.uuid,
        entity_label=f"{user.full_name or user.email} deactivated",
        reason=reason,
        metadata={"roles_revoked": revoked},
    )
    return membership


def reactivate_membership(organization, user, actor=None, reason: str = ""):
    """Let a returning colleague back in -- with no roles.

    Deliberately not the inverse of `deactivate_membership`. That one revoked
    their assignments; this one does not restore them, because the authority
    somebody held a year ago is not authority anybody has reviewed today.
    Whoever readmits them assigns roles as a separate, visible act.
    """
    membership = Membership.objects.filter(
        user=user, organization=organization,
    ).first()
    if membership is None:
        raise IdentityError("That person has never been a member here.")
    if membership.status == MembershipStatus.ACTIVE:
        raise IdentityError(f"{user.email} is already active.")

    if membership.consumes_seat:
        check_quota(
            organization, LimitKey.MAX_USERS, requested=1,
        ).raise_if_blocked()

    membership.status = MembershipStatus.ACTIVE
    membership.revoked_at = None
    membership.save(update_fields=["status", "revoked_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="identity.Membership",
        entity_id=membership.uuid,
        entity_label=f"{user.full_name or user.email} reactivated",
        reason=reason,
        metadata={"roles_restored": 0},
    )
    return membership


def revoke_all_roles(user, actor=None, reason: str = "") -> int:
    """Revoke every active assignment this user holds in the active tenant.

    Lives here rather than in `apps.rbac.services` only because its one caller
    is the deactivation above; the work is delegated to `revoke_role` so there
    is a single definition of what revoking means.
    """
    from apps.rbac.models import AssignmentStatus, RoleAssignment
    from apps.rbac.services import revoke_role

    assignments = list(
        RoleAssignment.objects.filter(
            user_id=user.uuid, status=AssignmentStatus.ACTIVE,
        )
    )
    for assignment in assignments:
        revoke_role(assignment, actor=actor, reason=reason)
    return len(assignments)
