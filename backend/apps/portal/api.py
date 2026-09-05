"""Portal endpoints, in two halves that do not share an authentication.

`/api/me/…` is the patient's own view, authenticated by a portal session
token. `/api/portal/…` is the staff side — issuing invitations, granting and
withdrawing proxy access, answering messages — authenticated the way the rest
of this system is.

They are separate routers with separate permission classes because the whole
module exists to keep those two audiences apart. A single viewset with a
branch on who is calling is one bad condition away from a patient reading a
ward list.

Three things the patient half does not offer.

**No endpoint returns a result the laboratory has not released**, or a
critical one inside its hold window. The hold is stated rather than hidden.

**No endpoint takes a patient identifier.** Which record is being read comes
from the session and the proxy grants, never from the URL — a portal that
accepts `?patient=` is one guessed UUID away from somebody else's record.

**No endpoint changes clinical data.** A patient can message, and that is
answered by a person.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.patients.models import Patient
from apps.portal.auth import PortalSessionAuthentication
from apps.portal.models import (
    PatientCorrectionField,
    PatientCorrectionRequest,
    PatientCorrectionStatus,
    PortalAccount,
    PortalMessage,
    PortalSession,
    ProxyAccess,
    ProxyRelationship,
)
from apps.audit.access_reports import who_looked_at
from apps.portal.services import (
    PortalError,
    access_for,
    accessible_patients,
    adoption,
    appointments_for,
    authenticate,
    cancel_patient_correction,
    decide_patient_correction,
    generate_patient_document,
    grant_proxy,
    home,
    invite,
    invoices_for,
    messages_for,
    note_access,
    patient_profile_for,
    prescriptions_for,
    proxy_review,
    referrals_for,
    register,
    reply_to_message,
    request_patient_correction,
    results_for,
    revoke_all_sessions,
    revoke_proxy,
    revoke_session,
    send_message,
)
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class AccountSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    is_locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = PortalAccount
        fields = [
            "uuid", "patient_name", "patient_mrn", "login_identifier",
            "email", "status", "registered_at", "last_login_at",
            "is_locked", "locked_until", "wants_appointment_reminders",
            "wants_result_notifications", "preferred_language",
        ]
        read_only_fields = [
            "uuid", "patient_name", "patient_mrn", "status", "registered_at",
            "last_login_at", "is_locked", "locked_until",
        ]


class SessionSerializer(serializers.ModelSerializer):
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = PortalSession
        fields = [
            "uuid", "issued_at", "expires_at", "last_seen_at",
            "device_label", "ip_address", "revoked_at", "is_live",
        ]
        read_only_fields = fields


class ProxySerializer(serializers.ModelSerializer):
    account_holder = serializers.CharField(
        source="account.patient.full_name", read_only=True,
    )
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProxyAccess
        fields = [
            "uuid", "account_holder", "patient_name", "relationship",
            "can_see_results", "can_see_invoices", "can_book_appointments",
            "granted_at", "granted_by_name", "consent_evidence",
            "expires_at", "revoked_at", "revoked_by_name", "revoked_reason",
            "is_live",
        ]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    is_answered = serializers.BooleanField(read_only=True)

    class Meta:
        model = PortalMessage
        fields = [
            "uuid", "patient_name", "direction", "subject", "body",
            "sent_at", "sender_name", "read_at", "answered_at",
            "answered_by_name", "is_answered",
        ]
        read_only_fields = fields


# -- inputs -----------------------------------------------------------------


class InviteSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    delivered_by = serializers.CharField(
        max_length=24, required=False, allow_blank=True, default="",
    )
    delivered_to = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )


class RegisterSerializer(serializers.Serializer):
    #: The number on the patient's card. Not a UUID: building the patient app
    #: made it obvious that no patient has one, and a registration form that
    #: asks for an internal identifier is a form nobody can complete.
    mrn = serializers.CharField(max_length=32)
    code = serializers.CharField(max_length=16)
    login_identifier = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=128)
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=128)
    device = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )


class GrantProxySerializer(serializers.Serializer):
    account = serializers.UUIDField()
    patient = serializers.UUIDField()
    relationship = serializers.ChoiceField(choices=ProxyRelationship.choices)
    consent_evidence = serializers.CharField(max_length=255)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    can_see_results = serializers.BooleanField(required=False, default=False)
    can_see_invoices = serializers.BooleanField(required=False, default=True)
    can_book_appointments = serializers.BooleanField(
        required=False, default=True,
    )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class MessageInputSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField()


class PatientCorrectionSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    field_label = serializers.CharField(source="get_field_name_display", read_only=True)

    class Meta:
        model = PatientCorrectionRequest
        fields = [
            "uuid", "patient", "patient_name", "patient_mrn",
            "field_name", "field_label", "old_value", "proposed_value",
            "reason", "status", "requested_at", "decided_at",
            "decided_by_name", "decision_notes",
        ]
        read_only_fields = [
            "uuid", "patient_name", "patient_mrn", "field_label",
            "old_value", "status", "requested_at", "decided_at",
            "decided_by_name", "decision_notes",
        ]


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=8000)
    subject = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )


# ---------------------------------------------------------------------------
# The patient's own half
# ---------------------------------------------------------------------------


class PortalAuthView(APIView):
    """Register and sign in. The only unauthenticated portal endpoints."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        action_name = request.data.get("action", "login")

        if action_name == "register":
            serializer = RegisterSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            patient = Patient.objects.filter(
                mrn__iexact=data["mrn"].strip(), merged_into__isnull=True,
            ).first()
            if patient is None:
                # The same refusal as a wrong code, deliberately: a distinct
                # "no such patient" would turn this form into a way of
                # checking whether a given MRN belongs to anybody here.
                raise PortalError(
                    "That code is not valid for this patient, or it has "
                    "expired. Ask at the desk for a new one."
                )
            account = register(
                patient,
                code=data["code"],
                login_identifier=data["login_identifier"],
                password=data["password"],
                email=data.get("email", ""),
            )
            return Response(
                AccountSerializer(account).data,
                status=status.HTTP_201_CREATED,
            )

        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account, session, token = authenticate(
            data["identifier"], data["password"],
            device=data.get("device", ""),
            ip=request.META.get("REMOTE_ADDR"),
        )
        return Response({
            # Returned once. The server keeps only a hash.
            "token": token,
            "expires_at": session.expires_at,
            "account": AccountSerializer(account).data,
        })


class MeView(APIView):
    """Everything the signed-in patient may see, about one record at a time.

    Which record comes from the session and the live proxy grants, never from
    the request. A portal that accepts `?patient=` is one guessed UUID away
    from somebody else's record — so the caller names a record by its position
    in *their own* list of accessible records, and an out-of-range index is
    simply not found.
    """

    authentication_classes = [PortalSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def _target(self, request):
        """The record being read, chosen from what this account may open."""
        reachable = accessible_patients(request.user.account)
        wanted = request.query_params.get("record", "")
        if not wanted:
            return reachable[0]
        for row in reachable:
            if str(row["patient"].uuid) == wanted:
                return row
        raise PortalError(
            "That record is not available to this account.",
            code="not_permitted",
        )

    def get(self, request):
        account = request.user.account
        row = self._target(request)
        patient = row["patient"]
        section = request.query_params.get("section", "home")
        ip = request.META.get("REMOTE_ADDR")

        if section == "home":
            note_access(account, patient, "home", ip=ip)
            return Response({
                **home(account, patient),
                "records": [
                    {
                        "uuid": str(entry["patient"].uuid),
                        "name": entry["patient"].full_name,
                        "relationship": entry["relationship"],
                        "via_proxy": entry["via_proxy"],
                    }
                    for entry in accessible_patients(account)
                ],
            })

        if section == "results":
            if not row["can_see_results"]:
                raise PortalError(
                    "This account may not see results for that record.",
                    code="not_permitted",
                )
            note_access(account, patient, "results", ip=ip)
            return Response(results_for(patient))

        if section == "appointments":
            note_access(account, patient, "appointments", ip=ip)
            return Response(appointments_for(patient))

        if section == "invoices":
            if not row["can_see_invoices"]:
                raise PortalError(
                    "This account may not see invoices for that record.",
                    code="not_permitted",
                )
            note_access(account, patient, "invoices", ip=ip)
            return Response(invoices_for(patient))

        if section == "prescriptions":
            if not row["can_see_results"]:
                raise PortalError(
                    "This account may not see prescriptions for that record.",
                    code="not_permitted",
                )
            note_access(account, patient, "prescriptions", ip=ip)
            return Response(prescriptions_for(patient))

        if section == "referrals":
            note_access(account, patient, "referrals", ip=ip)
            return Response(referrals_for(patient))

        if section == "messages":
            note_access(account, patient, "messages", ip=ip)
            return Response(messages_for(patient, account))

        if section == "profile":
            note_access(account, patient, "profile", ip=ip)
            return Response(patient_profile_for(patient, account))

        if section == "document":
            doc_type = request.query_params.get("type", "")
            reference = request.query_params.get("reference", "")
            if not doc_type or not reference:
                raise PortalError(
                    "Document request requires 'type' (result/prescription/invoice) and 'reference'.",
                    code="invalid_request",
                )
            doc = generate_patient_document(account, patient, doc_type, reference)
            note_access(account, patient, f"document:{doc_type}", detail=reference, ip=ip)
            if request.query_params.get("format") == "html":
                return HttpResponse(doc["html"], content_type="text/html")
            return Response(doc)

        if section == "sessions":
            return Response(SessionSerializer(
                account.sessions.order_by("-issued_at")[:20], many=True,
            ).data)

        if section == "access":
            # Who has opened this record. Phase 3 of ACCESS_DESIGN.md, and the
            # one report a patient is entitled to without asking anybody.
            #
            # Shown as individual lines rather than a summary: somebody asking
            # this question wants the Tuesday afternoon they remember, not a
            # count. And staff are named -- a log that says "a member of staff"
            # answers nothing, and the people reading records know they are
            # named, which is most of what makes the logging work.
            #
            # A proxy may not see it. Who has read somebody's record is about
            # that person, and a carer arranging appointments has no business
            # in it.
            if account.patient_id != row["patient"].id:
                raise PortalError(
                    "You can only see who has opened your own record.",
                    code="not_permitted",
                )
            note_access(account, patient, "access_log", ip=ip)
            return Response({
                "entries": who_looked_at(patient, days=365),
                "note": (
                    "Everyone who opened your record in the last year. Staff "
                    "treating you will appear here often — that is what "
                    "treating you looks like."
                ),
            })

        return Response(
            {"detail": f"Unknown section '{section}'.",
             "available": [
                 "home", "results", "appointments", "invoices",
                 "prescriptions", "referrals", "messages", "sessions",
                 "profile", "document", "access",
             ]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def post(self, request):
        """Send a message, sign out, or submit a demographic correction."""
        account = request.user.account
        what = request.data.get("action", "message")

        if what == "sign_out":
            revoke_session(request.user.session, reason="Signed out")
            return Response({"signed_out": True})

        if what == "sign_out_everywhere":
            count = revoke_all_sessions(account, reason="Signed out everywhere")
            return Response({"sessions_ended": count})

        if what == "request_correction":
            row = self._target(request)
            field_name = request.data.get("field_name", "")
            proposed_value = request.data.get("proposed_value", "")
            reason = request.data.get("reason", "")
            correction = request_patient_correction(
                account, row["patient"], field_name, proposed_value, reason,
            )
            return Response(
                PatientCorrectionSerializer(correction).data,
                status=status.HTTP_201_CREATED,
            )

        if what == "cancel_correction":
            corr_uuid = request.data.get("correction")
            correction = get_object_or_404(PatientCorrectionRequest, uuid=corr_uuid)
            cancelled = cancel_patient_correction(correction, account)
            return Response(PatientCorrectionSerializer(cancelled).data)

        serializer = MessageInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = self._target(request)
        message = send_message(
            account, row["patient"],
            serializer.validated_data["subject"],
            serializer.validated_data["body"],
        )
        return Response(
            MessageSerializer(message).data, status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# The staff half
# ---------------------------------------------------------------------------


class PortalAccountViewSet(viewsets.ReadOnlyModelViewSet):
    """Accounts, as staff see them. No password is readable here or anywhere."""

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        PortalAccount, relations=["patient"], fields=["status"],
    )

    def get_queryset(self):
        return PortalAccount.objects.select_related("patient")

    @action(detail=False, methods=["post"], url_path="invite")
    def send_invitation(self, request):
        """Issue a registration code, returned once.

        The code comes back in this response and nowhere else: the database
        holds only a hash, so an invitation list is not a list of working
        credentials for other people's records.
        """
        get_authorization(request).require("patient.update", Scope.FACILITY)
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invitation, code = invite(
            get_object_or_404(Patient, uuid=data["patient"]),
            actor=request.user,
            delivered_by=data.get("delivered_by", ""),
            delivered_to=data.get("delivered_to", ""),
        )
        return Response({
            "code": code,
            "hint": invitation.code_hint,
            "expires_at": invitation.expires_at,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, uuid=None):
        """Lift a lockout early. It would expire on its own anyway."""
        get_authorization(request).require("patient.update", Scope.FACILITY)
        account = self.get_object()
        account.locked_until = None
        account.failed_attempts = 0
        account.save(update_fields=[
            "locked_until", "failed_attempts", "updated_at",
        ])
        return Response(AccountSerializer(account).data)

    @action(detail=True, methods=["get"], url_path="access-log")
    def access_log(self, request, uuid=None):
        """What this account has looked at through a proxy grant."""
        get_authorization(request).require("audit.read", Scope.ORGANIZATION)
        return Response([
            {
                "looked_at": row.looked_at,
                "patient": row.patient.full_name,
                "resource": row.resource,
                "detail": row.detail,
                "ip": row.ip_address,
            }
            for row in self.get_object().access_log.select_related(
                "patient"
            )[:200]
        ])


class ProxyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProxySerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        ProxyAccess, relations=["account", "patient"],
        fields=["relationship"],
    )

    def get_queryset(self):
        return ProxyAccess.objects.select_related("account__patient", "patient")

    @action(detail=False, methods=["post"], url_path="grant")
    def grant(self, request):
        get_authorization(request).require("patient.update", Scope.FACILITY)
        serializer = GrantProxySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        access = grant_proxy(
            get_object_or_404(PortalAccount, uuid=data["account"]),
            get_object_or_404(Patient, uuid=data["patient"]),
            relationship=data["relationship"],
            actor=request.user,
            consent_evidence=data["consent_evidence"],
            expires_at=data.get("expires_at"),
            can_see_results=data.get("can_see_results", False),
            can_see_invoices=data.get("can_see_invoices", True),
            can_book_appointments=data.get("can_book_appointments", True),
        )
        return Response(
            ProxySerializer(access).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request, uuid=None):
        """Withdraw access, effective immediately."""
        get_authorization(request).require("patient.update", Scope.FACILITY)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ProxySerializer(revoke_proxy(
            self.get_object(), actor=request.user,
            reason=serializer.validated_data["reason"],
        )).data)

    @action(detail=False, methods=["get"], url_path="review")
    def review(self, request):
        """Grants nobody has revisited, oldest first."""
        return Response(proxy_review(
            days=int(request.query_params.get("days", 365)),
        ))


class PortalMessageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        PortalMessage, relations=["patient"], fields=["direction"],
    )

    def get_queryset(self):
        return PortalMessage.objects.select_related("patient")

    @action(detail=True, methods=["post"], url_path="reply")
    def reply(self, request, uuid=None):
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(MessageSerializer(reply_to_message(
            self.get_object(),
            serializer.validated_data["body"],
            actor=request.user,
            subject=serializer.validated_data.get("subject", ""),
        )).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="unanswered")
    def unanswered(self, request):
        """Messages from patients that nobody has answered.

        Read separately from answered because a message somebody glanced at
        is not a message anybody replied to.
        """
        rows = self.get_queryset().filter(
            direction="from_patient", answered_at__isnull=True,
        ).order_by("sent_at")
        return Response(MessageSerializer(rows, many=True).data)


class PortalAdoptionView(APIView):
    """How much of the patient list actually uses it."""

    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        return Response(adoption())


class PatientCorrectionViewSet(viewsets.ReadOnlyModelViewSet):
    """Demographic correction proposals submitted by patients for desk review."""

    serializer_class = PatientCorrectionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("patient.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        PatientCorrectionRequest, relations=["patient"], fields=["status", "field_name"],
    )

    def get_queryset(self):
        return PatientCorrectionRequest.objects.select_related("patient", "account")

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, uuid=None):
        """Approve or reject a correction proposal. Mutates Patient on approval."""
        get_authorization(request).require("patient.update", Scope.FACILITY)
        correction = self.get_object()
        approved = request.data.get("approved", True)
        notes = request.data.get("notes", "")
        updated = decide_patient_correction(
            correction,
            actor=request.user,
            approved=bool(approved),
            decision_notes=str(notes),
        )
        return Response(PatientCorrectionSerializer(updated).data)

