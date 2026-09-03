"""Referral endpoints.

`encounter.read` sees referrals. Raising and sending one needs
`encounter.create`; accepting, declining and answering need it too, because
the person answering a referral is a clinician either way.

Three things this API does not offer.

**No endpoint sends a referral without a question.** The refusal is in the
service and the message says why, because this is the single change that most
improves what comes back.

**No endpoint edits a sent referral's letter.** It was frozen when it was
sent, and a letter that can be rewritten afterwards is not a record of what
was said.

**No endpoint deletes a referral.** One that will not be pursued is cancelled
with a reason, and one nobody touched is lapsed by a sweep — because a
referral that quietly disappeared is the failure this module exists to make
visible.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# as_date: a query parameter is always a string, and a service that does
# arithmetic on one raises rather than filtering. Parsed at the boundary.
from apps.common.dates import as_date
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.encounters.models import Encounter
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope
from apps.referrals.models import (
    DECLINE_REASONS,
    TARGET_DAYS,
    ExternalProvider,
    Referral,
    ReferralResponse,
)
from apps.referrals.services import (
    accept,
    acknowledge,
    book,
    build_letter,
    cancel,
    create_referral,
    decline,
    lapse_stale,
    mark_did_not_attend,
    mark_seen,
    patient_history,
    respond,
    send_referral,
    summary,
    unanswered,
    worklist,
)

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalProvider
        fields = [
            "uuid", "code", "name", "name_nepali", "provider_type",
            "specialties", "contact_name", "phone", "email", "address",
            "district", "accepts_email", "accepts_paper", "notes",
            "is_active",
        ]
        read_only_fields = ["uuid"]


class ResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralResponse
        fields = [
            "uuid", "responded_at", "responder_name", "answer", "findings",
            "diagnosis", "treatment", "advice_to_referrer",
            "care_handed_back", "follow_up_here", "follow_up_on",
            "is_interim", "attachments",
        ]
        read_only_fields = fields


class EventSerializer(serializers.Serializer):
    happened_at = serializers.DateTimeField()
    event = serializers.CharField()
    detail = serializers.CharField()
    actor_name = serializers.CharField()


class ReferralSummarySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    to_provider_name = serializers.CharField(
        source="to_provider.name", read_only=True, default="",
    )
    to_department_name = serializers.CharField(
        source="to_department.name", read_only=True, default="",
    )
    days_waiting = serializers.IntegerField(read_only=True)
    days_to_target = serializers.IntegerField(read_only=True)
    is_breaching = serializers.BooleanField(read_only=True)
    awaiting_answer = serializers.BooleanField(read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Referral
        fields = [
            "uuid", "reference", "patient_name", "patient_mrn", "direction",
            "specialty", "urgency", "status", "reason", "question",
            "referrer_name", "to_provider_name", "to_department_name",
            "to_clinician_name", "created_on", "sent_at", "acknowledged_at",
            "accepted_at", "declined_at", "decline_reason", "decline_notes",
            "booked_for", "seen_at", "responded_at", "closed_at",
            "target_date", "days_waiting", "days_to_target", "is_breaching",
            "awaiting_answer", "is_open",
        ]
        read_only_fields = fields


class ReferralDetailSerializer(ReferralSummarySerializer):
    responses = ResponseSerializer(many=True, read_only=True)
    events = EventSerializer(many=True, read_only=True)
    patient = UUIDRelatedField(read_only=True)

    class Meta(ReferralSummarySerializer.Meta):
        fields = ReferralSummarySerializer.Meta.fields + [
            "patient", "clinical_summary", "provisional_diagnosis",
            "diagnosis_code", "referrer_registration", "referrer_contact",
            "letter", "letter_generated_at", "sent_by_method", "sent_notes",
            "cancelled_reason", "notes", "responses", "events",
        ]
        read_only_fields = fields


# -- inputs -----------------------------------------------------------------


class CreateSerializer(serializers.Serializer):
    patient = serializers.UUIDField()
    specialty = serializers.CharField(max_length=64)
    reason = serializers.CharField(max_length=512)
    direction = serializers.CharField(max_length=12, required=False,
                                      default="internal")
    urgency = serializers.CharField(max_length=12, required=False,
                                    default="routine")
    question = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    clinical_summary = serializers.CharField(
        max_length=8000, required=False, allow_blank=True, default="",
    )
    provisional_diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    diagnosis_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="",
    )
    encounter = serializers.UUIDField(required=False, allow_null=True)
    from_facility = serializers.UUIDField(required=False, allow_null=True)
    from_department = serializers.UUIDField(required=False, allow_null=True)
    to_facility = serializers.UUIDField(required=False, allow_null=True)
    to_department = serializers.UUIDField(required=False, allow_null=True)
    to_provider = serializers.UUIDField(required=False, allow_null=True)
    to_clinician_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )


class SendSerializer(serializers.Serializer):
    method = serializers.CharField(
        max_length=24, required=False, allow_blank=True, default="",
    )
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=32)
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class BookSerializer(serializers.Serializer):
    when = serializers.DateTimeField()
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class SeenSerializer(serializers.Serializer):
    at = serializers.DateTimeField(required=False, allow_null=True)
    encounter = serializers.UUIDField(required=False, allow_null=True)


class RespondSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=8000)
    findings = serializers.CharField(
        max_length=8000, required=False, allow_blank=True, default="",
    )
    diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    treatment = serializers.CharField(
        max_length=8000, required=False, allow_blank=True, default="",
    )
    advice = serializers.CharField(
        max_length=8000, required=False, allow_blank=True, default="",
    )
    care_handed_back = serializers.BooleanField(required=False, default=True)
    follow_up_here = serializers.BooleanField(required=False, default=False)
    follow_up_on = serializers.DateField(required=False, allow_null=True)
    is_interim = serializers.BooleanField(required=False, default=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class ProviderViewSet(viewsets.ModelViewSet):
    serializer_class = ProviderSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "code"
    filterset_class = uuid_filterset(
        ExternalProvider, fields=["provider_type", "is_active", "district"],
    )

    def get_queryset(self):
        return ExternalProvider.objects.order_by("name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "department.manage", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)


class ReferralViewSet(viewsets.ReadOnlyModelViewSet):
    """Read, and move through the states. There is no update and no delete."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Referral,
        relations=["patient", "from_facility", "to_facility", "to_provider"],
        fields=["status", "urgency", "direction", "specialty"],
    )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ReferralDetailSerializer
        return ReferralSummarySerializer

    def get_queryset(self):
        return (
            Referral.objects.select_related(
                "patient", "to_provider", "to_department", "from_department",
            )
            .prefetch_related("responses", "events")
        )

    def _writable(self):
        get_authorization(self.request).require(
            "encounter.create", Scope.FACILITY
        )

    @action(detail=False, methods=["post"], url_path="create")
    def raise_referral(self, request):
        self._writable()
        serializer = CreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def maybe(model, key):
            return (
                get_object_or_404(model, uuid=data[key])
                if data.get(key) else None
            )

        referral = create_referral(
            get_object_or_404(Patient, uuid=data["patient"]),
            specialty=data["specialty"],
            reason=data["reason"],
            actor=request.user,
            direction=data.get("direction", "internal"),
            urgency=data.get("urgency", "routine"),
            question=data.get("question", ""),
            clinical_summary=data.get("clinical_summary", ""),
            provisional_diagnosis=data.get("provisional_diagnosis", ""),
            diagnosis_code=data.get("diagnosis_code", ""),
            encounter=maybe(Encounter, "encounter"),
            from_facility=maybe(Facility, "from_facility"),
            from_department=maybe(Department, "from_department"),
            to_facility=maybe(Facility, "to_facility"),
            to_department=maybe(Department, "to_department"),
            to_provider=maybe(ExternalProvider, "to_provider"),
            to_clinician_name=data.get("to_clinician_name", ""),
        )
        return Response(
            ReferralDetailSerializer(referral).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, reference=None):
        """Send it. Refuses without a question, and without a route out."""
        self._writable()
        serializer = SendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(send_referral(
            self.get_object(), actor=request.user,
            method=serializer.validated_data.get("method", ""),
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge_receipt(self, request, reference=None):
        self._writable()
        serializer = NotesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(acknowledge(
            self.get_object(), actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_referral(self, request, reference=None):
        self._writable()
        serializer = NotesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(accept(
            self.get_object(), actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline_referral(self, request, reference=None):
        self._writable()
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(decline(
            self.get_object(),
            serializer.validated_data["reason"],
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="book")
    def book_appointment(self, request, reference=None):
        self._writable()
        serializer = BookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(book(
            self.get_object(),
            serializer.validated_data["when"],
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="seen")
    def seen(self, request, reference=None):
        self._writable()
        serializer = SeenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(ReferralDetailSerializer(mark_seen(
            self.get_object(), actor=request.user,
            at=data.get("at"),
            encounter=(
                get_object_or_404(Encounter, uuid=data["encounter"])
                if data.get("encounter") else None
            ),
        )).data)

    @action(detail=True, methods=["post"], url_path="did-not-attend")
    def did_not_attend(self, request, reference=None):
        self._writable()
        serializer = NotesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(mark_did_not_attend(
            self.get_object(), actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="respond")
    def answer(self, request, reference=None):
        """Answer the referrer. Refused before the patient has been seen."""
        self._writable()
        serializer = RespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        respond(
            self.get_object(),
            data["answer"],
            actor=request.user,
            findings=data.get("findings", ""),
            diagnosis=data.get("diagnosis", ""),
            treatment=data.get("treatment", ""),
            advice=data.get("advice", ""),
            care_handed_back=data.get("care_handed_back", True),
            follow_up_here=data.get("follow_up_here", False),
            follow_up_on=data.get("follow_up_on"),
            is_interim=data.get("is_interim", False),
        )
        return Response(ReferralDetailSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_referral(self, request, reference=None):
        self._writable()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ReferralDetailSerializer(cancel(
            self.get_object(), serializer.validated_data["reason"],
            actor=request.user,
        )).data)

    @action(detail=True, methods=["get"], url_path="letter")
    def letter(self, request, reference=None):
        """The letter as sent, or a preview if it has not gone yet.

        A sent referral returns the frozen copy. A draft returns a preview
        assembled now — clearly labelled, because it is not yet a record of
        anything.
        """
        referral = self.get_object()
        if referral.letter:
            return Response({
                "frozen": True,
                "generated_at": referral.letter_generated_at,
                "letter": referral.letter,
            })
        return Response({
            "frozen": False,
            "generated_at": None,
            "letter": build_letter(referral),
        })

    @action(detail=False, methods=["get"], url_path="decline-reasons")
    def decline_reasons(self, request):
        """The countable vocabulary, served rather than hard-coded."""
        return Response([
            {"key": key, "label": label} for key, label in DECLINE_REASONS
        ])

    @action(detail=False, methods=["get"], url_path="targets")
    def targets(self, request):
        """Days per urgency, so a client can show the clock it is against."""
        return Response(
            [{"urgency": key, "days": value} for key, value in TARGET_DAYS.items()]
        )


class ReferralReportView(APIView):
    """The worklist, the unanswered pile, and how the process is working."""

    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read")]

    def get(self, request):
        which = request.query_params.get("report", "worklist")
        facility = (
            get_object_or_404(Facility, uuid=request.query_params["facility"])
            if request.query_params.get("facility") else None
        )

        if which == "worklist":
            return Response(worklist(
                facility=facility,
                specialty=request.query_params.get("specialty", ""),
                direction=request.query_params.get("direction", ""),
            ))
        if which == "unanswered":
            return Response(unanswered(
                facility=facility,
                days=int(request.query_params.get("days", 14)),
            ))
        if which == "summary":
            return Response(summary(
                facility=facility,
                since=as_date(request.query_params.get("since"), "since"),
            ))
        if which == "patient":
            return Response(patient_history(get_object_or_404(
                Patient, uuid=request.query_params.get("patient"),
            )))

        return Response(
            {"detail": f"Unknown report '{which}'.",
             "available": ["worklist", "unanswered", "summary", "patient"]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def post(self, request):
        """Run the lapse sweep. Idempotent; safe to run repeatedly."""
        get_authorization(request).require("encounter.create", Scope.FACILITY)
        facility = (
            get_object_or_404(Facility, uuid=request.data["facility"])
            if request.data.get("facility") else None
        )
        return Response(lapse_stale(facility=facility))
