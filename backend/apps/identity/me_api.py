"""A person's own account: their details, their password, their preferences.

**None of this existed.** A user could sign in and could not change their own
name, their phone number, or their password. `update_user` existed and was
reachable only through the staff-administration API, which is somebody *else*
editing you and needs `user.update` — so a doctor who married and changed
their surname had to ask an administrator, and anybody who suspected their
password was known had no way to change it at all.

**Guarded by authentication and nothing else, deliberately.** There is no
permission code here and there should not be: needing `user.update` to edit
your own name would mean the permission that lets you edit *colleagues* is the
one that lets you edit yourself, and most people have neither. The subject and
the object are the same person; that is the authorisation.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainError
from apps.identity.preferences import PREFERENCES, merge, resolved


class ProfileSerializer(serializers.Serializer):
    """What somebody may change about themselves.

    **`email` is absent on purpose.** It is the login identifier, so changing
    it is an account-recovery matter needing a verified round trip to the new
    address — and nothing in this system can send mail yet (§93). An endpoint
    that let somebody change their own login to an address nobody had proved
    they own is the shape of an account takeover, so it is refused explicitly
    below rather than quietly ignored.
    """

    full_name = serializers.CharField(max_length=255, required=False)
    preferred_name = serializers.CharField(
        max_length=128, required=False, allow_blank=True,
    )
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    locale = serializers.CharField(max_length=10, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    avatar_url = serializers.URLField(required=False, allow_blank=True)


class PasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)


def _payload(user) -> dict:
    return {
        "uuid": str(user.uuid),
        "email": user.email,
        "full_name": user.full_name,
        "preferred_name": user.preferred_name,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "locale": user.locale,
        "timezone": user.timezone,
        "mfa_enabled": user.mfa_enabled,
        "must_change_password": user.must_change_password,
        "password_changed_at": user.password_changed_at,
        "last_active_at": user.last_active_at,
        "is_platform_staff": user.is_platform_staff,
        "preferences": resolved(user.preferences),
        # The catalogue travels with the values so the screen renders labels,
        # descriptions and choices without a second copy of them in the
        # frontend -- and a preference added here appears there next release
        # with no client change.
        "preference_catalogue": [
            {
                "key": preference.key,
                "label": preference.label,
                "description": preference.description,
                "kind": preference.kind,
                "default": preference.default,
                "choices": [
                    {"value": value, "label": label}
                    for value, label in preference.choices
                ],
            }
            for preference in PREFERENCES
        ],
    }


class MeView(APIView):
    """Read and edit your own account."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_payload(request.user))

    def patch(self, request):
        if "email" in request.data:
            raise DomainError(
                "An email address is a login and cannot be changed here. Ask "
                "an administrator, who can invite you at the new address.",
                code="email_change_refused",
            )

        form = ProfileSerializer(data=request.data, partial=True)
        form.is_valid(raise_exception=True)

        user = request.user
        changed = []
        for field, value in form.validated_data.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed.append(field)

        if changed:
            user.save(update_fields=[*changed, "updated_at"])

        return Response(_payload(user))


class MyPreferencesView(APIView):
    """The interface's own settings, for this person only.

    Separate from `MeView.patch` because they are a different kind of change:
    a preference is saved the moment it is toggled and needs no form, while a
    name change is typed and submitted. Sharing an endpoint would mean every
    toggle sent the whole profile back.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        if not isinstance(request.data, dict) or not request.data:
            raise DomainError("Send at least one preference to change.")

        try:
            updated = merge(request.user.preferences, request.data)
        except ValueError as exc:
            raise DomainError(str(exc)) from exc

        request.user.preferences = updated
        request.user.save(update_fields=["preferences", "updated_at"])
        return Response(resolved(updated))


class ChangePasswordView(APIView):
    """Change your own password.

    **The current password is required**, and that is the whole security
    value. Without it, a session left open on a ward computer is a permanent
    account takeover: anybody walking past can set a new password and lock the
    owner out. Requiring the old one means possession of the session is not
    enough.

    Django's configured validators run on the new one — length, commonness,
    similarity to the user's own name and email — so the rules are the same
    ones `createsuperuser` and any future reset flow enforce, rather than a
    second opinion written here.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        form = PasswordSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        user = request.user

        if not user.check_password(form.validated_data["current_password"]):
            # Deliberately not "that is not your password" with a delay or a
            # lockout: this is an authenticated session, so it is not a
            # guessing surface in the way the login form is. The failure is
            # plain and the login lockout stays where it belongs.
            raise DomainError(
                "That is not your current password.",
                code="wrong_password",
            )

        new_password = form.validated_data["new_password"]
        if new_password == form.validated_data["current_password"]:
            raise DomainError("The new password is the one you already have.")

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise DomainError(" ".join(exc.messages)) from exc

        user.set_password(new_password)
        user.password_changed_at = timezone.now()
        # Whatever forced them here is now satisfied.
        user.must_change_password = False
        user.save(
            update_fields=[
                "password",
                "password_changed_at",
                "must_change_password",
                "updated_at",
            ]
        )

        # Every token issued before this moment is now refused (see
        # `authentication.issued_before_password_change`), this device's
        # included, so it is handed a fresh pair and stays signed in. Anybody
        # else holding the account -- often the reason for the change -- is
        # signed out on their next request.
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "changed_at": user.password_changed_at,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "note": "Every other device has been signed out.",
            },
            status=status.HTTP_200_OK,
        )


class MySecondFactorView(APIView):
    """Turn two-step sign-in on, off, or renew its recovery codes.

    `GET` says whether it is on and how many recovery codes are left.
    `POST {action}`:

    - `begin` — a new secret, returned once with the `otpauth://` link the
      screen draws as a QR code. Stored sealed but **not yet enabled**: a
      secret nobody has proved they scanned would lock the person out.
    - `confirm {code}` — the first code from the app switches it on and
      returns ten recovery codes, shown this once and stored hashed.
    - `regenerate {code}` — ten new recovery codes; the old ones stop working.
    - `disable {password, code}` — both, because turning it off from a session
      left open on a ward computer must not be possible with the session alone.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "enabled": user.mfa_enabled,
            "enabled_at": user.mfa_enabled_at,
            "recovery_codes_left": len(user.mfa_recovery_codes or []) if user.mfa_enabled else 0,
        })

    def post(self, request):
        from apps.audit.models import AuditAction
        from apps.audit.services import record
        from apps.identity import mfa

        user = request.user
        action = request.data.get("action", "")
        code = str(request.data.get("code", ""))

        if action == "begin":
            if user.mfa_enabled:
                raise DomainError("Two-step sign-in is already on.", code="already_enabled")
            secret = mfa.new_secret()
            user.mfa_secret = mfa.seal(secret)
            user.mfa_last_step = None
            user.save(update_fields=["mfa_secret", "mfa_last_step"])
            return Response({
                "secret": secret,
                "uri": mfa.provisioning_uri(secret, user.email),
            })

        if action == "confirm":
            if user.mfa_enabled:
                raise DomainError("Two-step sign-in is already on.", code="already_enabled")
            secret = mfa.unseal(user.mfa_secret) if user.mfa_secret else None
            if not secret:
                raise DomainError("Start again: scan a new code.", code="not_started")
            step = mfa.verify(secret, code)
            if step is None:
                raise DomainError(
                    "That code did not match. Check the time on your phone and use the newest code.",
                    code="invalid_code",
                )
            plain, hashed = mfa.new_recovery_codes()
            user.mfa_enabled = True
            user.mfa_enabled_at = timezone.now()
            user.mfa_last_step = step
            user.mfa_recovery_codes = hashed
            user.save(update_fields=[
                "mfa_enabled", "mfa_enabled_at", "mfa_last_step", "mfa_recovery_codes",
            ])
            record(AuditAction.UPDATE, entity_type="identity.User", entity_id=user.uuid,
                   entity_label=f"{user.email} turned on two-step sign-in")
            return Response({"enabled": True, "recovery_codes": plain})

        if action == "regenerate":
            if not user.mfa_enabled or mfa.check_second_factor(user, code) != "totp":
                raise DomainError("Enter a current code from your app.", code="invalid_code")
            plain, hashed = mfa.new_recovery_codes()
            user.mfa_recovery_codes = hashed
            user.save(update_fields=["mfa_recovery_codes"])
            record(AuditAction.UPDATE, entity_type="identity.User", entity_id=user.uuid,
                   entity_label=f"{user.email} renewed recovery codes")
            return Response({"recovery_codes": plain})

        if action == "disable":
            if not user.mfa_enabled:
                raise DomainError("Two-step sign-in is not on.", code="not_enabled")
            if not user.check_password(str(request.data.get("password", ""))):
                raise DomainError("That is not your current password.", code="wrong_password")
            if mfa.check_second_factor(user, code) is None:
                raise DomainError("Enter a current code from your app, or a recovery code.",
                                  code="invalid_code")
            user.mfa_enabled = False
            user.mfa_enabled_at = None
            user.mfa_secret = ""
            user.mfa_last_step = None
            user.mfa_recovery_codes = []
            user.save(update_fields=[
                "mfa_enabled", "mfa_enabled_at", "mfa_secret", "mfa_last_step",
                "mfa_recovery_codes",
            ])
            record(AuditAction.UPDATE, entity_type="identity.User", entity_id=user.uuid,
                   entity_label=f"{user.email} turned off two-step sign-in")
            return Response({"enabled": False})

        raise DomainError("Unknown action.", code="invalid")
