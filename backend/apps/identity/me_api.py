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

        return Response(
            {
                "changed_at": user.password_changed_at,
                # Said plainly rather than implied. Access tokens already
                # issued stay valid until they expire -- they are signed, not
                # looked up -- so "change your password" is not "sign everyone
                # else out", and somebody changing it because they fear their
                # account is compromised deserves to know that.
                "note": (
                    "Sessions already signed in elsewhere stay active until "
                    "their token expires."
                ),
            },
            status=status.HTTP_200_OK,
        )
