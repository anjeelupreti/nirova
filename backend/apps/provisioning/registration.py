"""Signing up: a public request, and the platform team's queue of them.

**`POST /api/register/`** — anyone, no account. Records a `RegistrationRequest`
and nothing else. It is the only write the product accepts from an anonymous
caller, so it is guarded the way such an endpoint has to be:

* **Rate-limited by address and by email.** Five from one address in an hour,
  three for one email in a day. A form that anyone can post to is a form
  somebody will post to ten thousand times.
* **A honeypot.** A field no person can see; a bot that fills it is told it
  succeeded and nothing is stored, so it has no signal to adapt to.
* **No provisioning.** A request creates a row, never a database — see the
  model's docstring for why.

**`/api/platform/registrations/`** — platform staff. The queue, and two
decisions on each request: **onboard**, which hands the request's own answers
to `onboard_organization` (the same function the console's onboarding form
calls) so nobody retypes them, and **decline**, which must say why.
"""

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog.keys import ModuleCode
from apps.common.http import client_ip
from apps.common.permissions import IsPlatformStaff
from apps.provisioning.models import RegistrationRequest, RegistrationStatus
from apps.tenancy.models import BusinessType

PER_ADDRESS_PER_HOUR = 5
PER_EMAIL_PER_DAY = 3

#: Nepal's seven provinces, as the registration form offers them.
PROVINCES = (
    "Koshi", "Madhesh", "Bagmati", "Gandaki", "Lumbini", "Karnali", "Sudurpashchim",
)


def _reference() -> str:
    return f"REG-{timezone.localdate():%y%m}-{secrets.token_hex(3).upper()}"


class RegistrationSerializer(serializers.ModelSerializer):
    #: The honeypot. Hidden from people by the form; bots fill every field.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = RegistrationRequest
        fields = (
            "organization_name", "business_type", "pan_number", "province",
            "district", "facility_count", "bed_count", "modules",
            "current_system", "contact_name", "contact_email", "contact_phone",
            "contact_role", "message", "website",
        )

    def validate_business_type(self, value):
        if value not in BusinessType.values:
            raise serializers.ValidationError("Choose what kind of organization you run.")
        return value

    def validate_province(self, value):
        if value and value not in PROVINCES:
            raise serializers.ValidationError("Choose one of Nepal's seven provinces.")
        return value

    def validate_modules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("A list of module codes.")
        unknown = [code for code in value if code not in ModuleCode.ALL]
        if unknown:
            raise serializers.ValidationError(f"Unknown modules: {', '.join(unknown)}.")
        return sorted(set(value))

    def validate_facility_count(self, value):
        if not 1 <= value <= 500:
            raise serializers.ValidationError("Between 1 and 500 sites.")
        return value

    def validate_bed_count(self, value):
        if value > 5000:
            raise serializers.ValidationError("That is more beds than any hospital in Nepal.")
        return value

    def validate_pan_number(self, value):
        value = (value or "").strip()
        # A Nepali PAN is nine digits. Checked for shape only: whether it is
        # *theirs* is the platform team's call, not a regular expression's.
        if value and (not value.isdigit() or len(value) != 9):
            raise serializers.ValidationError("A PAN is nine digits.")
        return value


class RegisterView(APIView):
    """`POST /api/register/` — ask to use the product."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        form = RegistrationSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = dict(form.validated_data)

        if data.pop("website", ""):
            # Filled the invisible field: a bot. Say yes, keep nothing.
            return Response(
                {"reference": _reference(), "status": "new"}, status=status.HTTP_201_CREATED
            )

        ip = client_ip(request)
        now = timezone.now()
        email = data["contact_email"].strip().lower()
        if ip and RegistrationRequest.objects.filter(
            ip_address=ip, created_at__gte=now - timedelta(hours=1)
        ).count() >= PER_ADDRESS_PER_HOUR:
            return Response(
                {"message": "Too many requests from this network. Try again in an hour."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if RegistrationRequest.objects.filter(
            contact_email=email, created_at__gte=now - timedelta(days=1)
        ).count() >= PER_EMAIL_PER_DAY:
            return Response(
                {"message": "We already have your request. Our team will be in touch."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        registration = RegistrationRequest.objects.create(
            reference=_reference(),
            ip_address=ip or None,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            **{**data, "contact_email": email},
        )
        return Response(
            {"reference": registration.reference, "status": registration.status},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# The platform team's queue
# ---------------------------------------------------------------------------


class RegistrationRequestSerializer(serializers.ModelSerializer):
    organization_slug = serializers.CharField(source="organization.slug", read_only=True, default="")

    class Meta:
        model = RegistrationRequest
        fields = (
            "uuid", "reference", "organization_name", "business_type", "pan_number",
            "province", "district", "facility_count", "bed_count", "modules",
            "current_system", "contact_name", "contact_email", "contact_phone",
            "contact_role", "message", "status", "created_at", "reviewed_by_email",
            "reviewed_at", "review_notes", "organization_slug",
        )
        read_only_fields = fields


class OnboardFromRequestSerializer(serializers.Serializer):
    """What the request does not already say: the tenant's address and plan."""

    slug = serializers.SlugField(max_length=64)
    plan_code = serializers.CharField(max_length=64)
    trial_days = serializers.IntegerField(required=False, min_value=0, max_value=365)


class RegistrationRequestViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsPlatformStaff]
    serializer_class = RegistrationRequestSerializer
    lookup_field = "reference"
    filterset_fields = ["status", "business_type"]
    search_fields = ["organization_name", "contact_name", "contact_email", "reference"]

    def get_queryset(self):
        return RegistrationRequest.objects.select_related("organization").order_by("-created_at")

    def _decided(self, registration, request, new_status, notes=""):
        registration.status = new_status
        registration.reviewed_by_email = getattr(request.user, "email", "")
        registration.reviewed_at = timezone.now()
        if notes:
            registration.review_notes = notes
        registration.save(update_fields=[
            "status", "reviewed_by_email", "reviewed_at", "review_notes", "organization", "updated_at",
        ])

    @action(detail=True, methods=["post"])
    def contacted(self, request, reference=None):
        registration = self.get_object()
        self._decided(registration, request, RegistrationStatus.CONTACTED,
                      request.data.get("notes", ""))
        return Response(self.get_serializer(registration).data)

    @action(detail=True, methods=["post"])
    def decline(self, request, reference=None):
        registration = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"message": "Declining must say why."}, status=status.HTTP_400_BAD_REQUEST)
        self._decided(registration, request, RegistrationStatus.DECLINED, reason)
        return Response(self.get_serializer(registration).data)

    @action(detail=True, methods=["post"])
    def onboard(self, request, reference=None):
        from apps.provisioning.onboarding import onboard_organization

        registration = self.get_object()
        if registration.status == RegistrationStatus.ONBOARDED:
            return Response({"message": "This request is already a customer."},
                            status=status.HTTP_409_CONFLICT)
        form = OnboardFromRequestSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        result = onboard_organization(
            actor=request.user,
            slug=form.validated_data["slug"],
            plan_code=form.validated_data["plan_code"],
            legal_name=registration.organization_name,
            display_name=registration.organization_name,
            primary_email=registration.contact_email,
            owner_email=registration.contact_email,
            owner_name=registration.contact_name,
            business_type=registration.business_type,
            province=registration.province,
            district=registration.district,
            phone=registration.contact_phone,
            **({"trial_days": form.validated_data["trial_days"]}
               if "trial_days" in form.validated_data else {}),
        )
        with transaction.atomic():
            registration.organization = result["organization"]
            self._decided(registration, request, RegistrationStatus.ONBOARDED,
                          request.data.get("notes", ""))
        record(
            AuditAction.CREATE,
            entity_type="tenancy.Organization",
            entity_id=result["organization"].uuid,
            entity_label=f"{registration.organization_name} onboarded from {registration.reference}",
            metadata={"registration": registration.reference, "plan": result["plan"]},
        )
        return Response({
            **self.get_serializer(registration).data,
            "database_status": result["database_status"],
            "owner_email": result["owner"].email,
        })
