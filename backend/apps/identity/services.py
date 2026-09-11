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


#: Letters and digits a person can read aloud over the phone without
#: confusion — no 0/O, 1/l/I, 5/S.
_READABLE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRTUVWXYZ2346789"


def _only_within(organization, user, actor, what: str, yourself: str) -> None:
    """Refuse an administrator action on a login that reaches beyond this
    organization, or on the administrator's own account. Shared by the
    temporary password and the second-factor reset, which hand over the same
    thing — a way to sign in as the person — and so draw the same lines."""
    if actor is not None and getattr(actor, "uuid", None) == user.uuid:
        raise IdentityError(yourself)
    if user.is_platform_staff:
        raise IdentityError("Platform staff accounts are reset by the platform team.")

    membership = Membership.objects.filter(user=user, organization=organization).first()
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        raise IdentityError("That person does not have active access to this organization.")
    elsewhere = (
        Membership.objects.filter(user=user, status=MembershipStatus.ACTIVE)
        .exclude(organization=organization)
        .exists()
    )
    if elsewhere:
        raise IdentityError(
            f"{user.email} also signs in to another organization, so their "
            f"{what} can only be changed by them or by platform support.",
        )


def reset_second_factor(organization, user, actor=None, reason: str = "") -> None:
    """Turn off somebody's two-step sign-in so they can set it up again.

    For the phone that fell in the river with the recovery codes in the same
    pocket. Without it, two-step sign-in is a way to lock a nurse out of the
    system at the start of a night shift with nobody able to let them back in.
    A reason is required, and the reset is audited, because it is a way to
    weaken somebody's sign-in that they did not ask for.
    """
    if not reason.strip():
        raise IdentityError("Say why — for example, 'lost phone, identity checked in person'.")
    _only_within(organization, user, actor, "two-step sign-in",
                 "Turn off your own two-step sign-in from your account instead.")
    if not user.mfa_enabled:
        raise IdentityError(f"{user.email} does not have two-step sign-in on.")

    user.mfa_enabled = False
    user.mfa_enabled_at = None
    user.mfa_secret = ""
    user.mfa_last_step = None
    user.mfa_recovery_codes = []
    user.save(update_fields=[
        "mfa_enabled", "mfa_enabled_at", "mfa_secret", "mfa_last_step",
        "mfa_recovery_codes",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="identity.User",
        entity_id=user.uuid,
        entity_label=f"Two-step sign-in reset for {user.full_name or user.email}",
        reason=reason,
        metadata={"by": getattr(actor, "email", "")},
    )


def issue_temporary_password(organization, user, actor=None, reason: str = "") -> str:
    """Give somebody a one-time password, which they must change on first use.

    **The only way a person without a password could ever get one.** Invited
    staff and onboarded owners are created with an unusable password — rightly,
    since a password chosen by somebody else is a password somebody else
    knows — and until this existed there was no path from there to signing in
    at all: no reset email, no set-password link, no administrator action. An
    organization could be onboarded and its owner could never log in.

    Returned once, to be handed over in person or read out; never stored in
    the clear and never written to the audit log. `must_change_password` means
    the first thing the holder does is replace it with one only they know.

    Refused where it would reach further than this organization:

    * **Somebody who also belongs to another organization.** A login is one
      account across every organization it belongs to, so resetting it here
      would hand this organization's administrator the keys to the others.
    * **Platform staff**, whose accounts reach every customer.
    * **Yourself** — change your own password from your account, with your
      current one, rather than through the administrator path.
    """
    import secrets

    _only_within(organization, user, actor, "password", "Change your own password from your account instead.")

    temporary = "-".join(
        "".join(secrets.choice(_READABLE) for _ in range(4)) for _ in range(3)
    )
    user.set_password(temporary)
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=[
        "password", "password_changed_at", "must_change_password",
        "failed_login_attempts", "locked_until",
    ])

    record(
        AuditAction.UPDATE,
        entity_type="identity.User",
        entity_id=user.uuid,
        entity_label=f"Temporary password issued to {user.full_name or user.email}",
        reason=reason,
        metadata={"by": getattr(actor, "email", "")},
    )
    return temporary
