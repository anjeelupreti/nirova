"""Insurance endpoints.

`invoice.read` sees claims — the billing desk chases them. Creating and
submitting needs `invoice.create`; recording what a payer decided needs
`payment.record`, because accepting a deduction is accepting less money and
belongs with the people who handle money rather than the people who raise the
bills.

Two things this API deliberately does not offer.

**No endpoint edits a claim's amounts directly.** They are set by
`record_response`, which requires a reason for every deduction. A settable
`approved_amount` would be a field somebody types a number into, and the
reasons — the only part of a deduction anybody can act on — would go
unrecorded.

**No endpoint deletes a claim.** A claim that will not be pursued is written
off, explicitly and with a reason, because a claim quietly abandoned is
revenue nobody records losing.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# UUIDRelatedField: relations are published by UUID, never by integer PK —
# with a database per tenant, `id` 42 is a different row per customer.
from apps.common.dates import as_date
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.billing.models import Invoice
from apps.insurance.models import (
    DEDUCTION_REASONS,
    Claim,
    ClaimLine,
    Payer,
    Policy,
    PreAuthorisation,
    SchemePackage,
)
from apps.insurance.services import (
    appeal_claim,
    check_eligibility,
    claims_ageing,
    create_claim,
    deduction_analysis,
    estimate,
    expiring_preauthorisations,
    package_margin,
    package_rate,
    payer_performance,
    preauth_warnings,
    raise_query,
    rebuild_utilisation,
    record_preauth_response,
    record_response,
    request_preauthorisation,
    settle_claim,
    submission_deadline,
    submit_claim,
    write_off_claim,
)
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class PayerSerializer(serializers.ModelSerializer):
    administers_for = UUIDRelatedField(
        queryset=Payer.objects.all(), required=False, allow_null=True,
    )
    is_scheme = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payer
        fields = [
            "uuid", "code", "name", "name_nepali", "kind", "administers_for",
            "registration_number", "pan_number", "contact_name",
            "contact_phone", "contact_email", "address", "price_list_code",
            "submission_window_days", "settlement_days",
            "requires_preauthorisation", "preauthorisation_threshold",
            "is_active", "notes", "is_scheme",
        ]
        read_only_fields = ["uuid", "is_scheme"]


class PolicySerializer(serializers.ModelSerializer):
    payer = UUIDRelatedField(queryset=Payer.objects.all())
    patient = UUIDRelatedField(queryset=Patient.objects.all())
    payer_name = serializers.CharField(source="payer.name", read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    remaining = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
    )

    class Meta:
        model = Policy
        fields = [
            "uuid", "policy_number", "payer", "payer_name", "patient",
            "patient_name", "principal_name", "relationship", "valid_from",
            "valid_to", "status", "sum_insured", "utilised", "remaining",
            "deductible", "co_payment_percent", "sub_limits", "exclusions",
            "waiting_period_until", "card_number", "notes",
        ]
        read_only_fields = ["uuid", "utilised", "remaining", "payer_name",
                            "patient_name"]


class PreAuthSerializer(serializers.ModelSerializer):
    policy_number = serializers.CharField(
        source="policy.policy_number", read_only=True,
    )
    payer_name = serializers.CharField(
        source="policy.payer.name", read_only=True,
    )
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    is_usable = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = PreAuthorisation
        fields = [
            "uuid", "reference", "policy_number", "payer_name",
            "patient_name", "requested_at", "requested_by_name",
            "planned_treatment", "diagnosis", "diagnosis_code",
            "planned_admission_on", "estimated_days", "estimated_amount",
            "status", "payer_reference", "responded_at", "approved_amount",
            "valid_until", "conditions", "rejection_reason", "notes",
            "is_usable", "days_until_expiry", "warnings",
        ]
        read_only_fields = fields

    def get_warnings(self, obj) -> list:
        return preauth_warnings(obj)


class ClaimLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimLine
        fields = [
            "uuid", "description", "service_code", "category", "quantity",
            "unit_price", "claimed_amount", "approved_amount",
            "deducted_amount", "deduction_reason", "deduction_notes",
        ]
        read_only_fields = fields


class ClaimEventSerializer(serializers.Serializer):
    happened_at = serializers.DateTimeField()
    event = serializers.CharField()
    detail = serializers.CharField()
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True,
    )
    actor_name = serializers.CharField()


class ClaimSummarySerializer(serializers.ModelSerializer):
    payer_name = serializers.CharField(source="payer.name", read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True,
    )
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    invoice_number = serializers.CharField(
        source="invoice.number", read_only=True, default="",
    )
    outstanding = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
    )
    shortfall = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
    )
    days_since_submission = serializers.IntegerField(read_only=True)
    deadline = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = [
            "uuid", "reference", "payer_name", "patient_name", "patient_mrn",
            "invoice_number", "service_date", "discharge_date", "diagnosis",
            "status", "submitted_at", "submission_count", "payer_reference",
            "claimed_amount", "approved_amount", "deducted_amount",
            "settled_amount", "patient_liability", "outstanding", "shortfall",
            "days_since_submission", "rejection_reason", "query_text",
            "deadline",
        ]
        read_only_fields = fields

    def get_deadline(self, obj) -> dict:
        return submission_deadline(obj)


class ClaimDetailSerializer(ClaimSummarySerializer):
    lines = ClaimLineSerializer(many=True, read_only=True)
    events = ClaimEventSerializer(many=True, read_only=True)
    policy_number = serializers.CharField(
        source="policy.policy_number", read_only=True, default="",
    )
    preauth_reference = serializers.CharField(
        source="preauthorisation.reference", read_only=True, default="",
    )

    class Meta(ClaimSummarySerializer.Meta):
        fields = ClaimSummarySerializer.Meta.fields + [
            "policy_number", "preauth_reference", "treatment_summary",
            "diagnosis_code", "responded_at", "settled_at",
            "query_raised_at", "query_answered_at", "notes", "lines",
            "events",
        ]
        read_only_fields = fields


class SchemePackageSerializer(serializers.ModelSerializer):
    payer = UUIDRelatedField(queryset=Payer.objects.all())

    class Meta:
        model = SchemePackage
        fields = [
            "uuid", "payer", "code", "name", "name_nepali", "category",
            "package_amount", "maximum_per_year", "includes", "excludes",
            "effective_from", "effective_to", "is_active",
        ]
        read_only_fields = ["uuid"]


# -- inputs -----------------------------------------------------------------


class PreAuthRequestSerializer(serializers.Serializer):
    policy = serializers.UUIDField()
    facility = serializers.UUIDField()
    treatment = serializers.CharField(max_length=512)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    diagnosis_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="",
    )
    planned_on = serializers.DateField(required=False, allow_null=True)
    estimated_days = serializers.IntegerField(required=False, allow_null=True)


class PreAuthResponseSerializer(serializers.Serializer):
    approved = serializers.BooleanField()
    approved_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True,
    )
    payer_reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    valid_until = serializers.DateField(required=False, allow_null=True)
    conditions = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="",
    )
    reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class ClaimCreateSerializer(serializers.Serializer):
    invoice = serializers.UUIDField()
    policy = serializers.UUIDField()
    preauthorisation = serializers.UUIDField(required=False, allow_null=True)
    diagnosis = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    diagnosis_code = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="",
    )
    service_date = serializers.DateField(required=False, allow_null=True)


class DeductionSerializer(serializers.Serializer):
    line = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reason = serializers.CharField(max_length=32)
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )


class ClaimResponseSerializer(serializers.Serializer):
    approved_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True,
    )
    deductions = DeductionSerializer(many=True, required=False, default=list)
    rejection_reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    payer_reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )


class SettlementSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_reference = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class PayerViewSet(viewsets.ModelViewSet):
    serializer_class = PayerSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(Payer, fields=["kind", "is_active"])

    def get_queryset(self):
        return Payer.objects.select_related("administers_for").order_by("name")

    def perform_create(self, serializer):
        get_authorization(self.request).require("invoice.create", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=False, methods=["get"], url_path="performance")
    def performance(self, request):
        """Approval rate, rejection rate, turnaround and write-offs."""
        return Response(payer_performance())


class PolicyViewSet(viewsets.ModelViewSet):
    serializer_class = PolicySerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Policy, relations=["payer", "patient"], fields=["status"],
    )

    def get_queryset(self):
        return Policy.objects.select_related("payer", "patient")

    def perform_create(self, serializer):
        get_authorization(self.request).require("patient.update", Scope.FACILITY)
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, uuid=None):
        """Rebuild the utilisation from the claims. A cache, not a counter."""
        return Response({"utilised": rebuild_utilisation(self.get_object())})

    @action(detail=True, methods=["get"], url_path="estimate")
    def quote(self, request, uuid=None):
        """What the payer would cover on a given bill, and why not the rest."""
        amount = request.query_params.get("amount", "0")
        return Response(estimate(
            self.get_object(), amount,
            on_date=as_date(request.query_params.get("on_date"), "on_date"),
        ))


class EligibilityView(APIView):
    """Which of a patient's policies answer on a given date.

    `on_date` is the point: a claim for last month is judged against last
    month, and asking about today gives the wrong answer on every late claim.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]

    def get(self, request):
        patient = get_object_or_404(
            Patient, uuid=request.query_params.get("patient")
        )
        return Response(check_eligibility(
            patient,
            on_date=as_date(request.query_params.get("on_date"), "on_date"),
        ))


class PreAuthViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PreAuthSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        PreAuthorisation, relations=["policy", "facility", "patient"],
        fields=["status"],
    )

    def get_queryset(self):
        return PreAuthorisation.objects.select_related(
            "policy__payer", "patient", "facility",
        )

    @action(detail=False, methods=["post"], url_path="request")
    def create_request(self, request):
        get_authorization(request).require("invoice.create", Scope.FACILITY)
        serializer = PreAuthRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        created = request_preauthorisation(
            request.organization,
            get_object_or_404(Policy, uuid=data["policy"]),
            get_object_or_404(Facility, uuid=data["facility"]),
            treatment=data["treatment"],
            amount=data["amount"],
            actor=request.user,
            diagnosis=data.get("diagnosis", ""),
            diagnosis_code=data.get("diagnosis_code", ""),
            planned_on=data.get("planned_on"),
            estimated_days=data.get("estimated_days"),
        )
        return Response(
            PreAuthSerializer(created).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="response")
    def respond(self, request, reference=None):
        get_authorization(request).require("payment.record", Scope.FACILITY)
        serializer = PreAuthResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(PreAuthSerializer(record_preauth_response(
            self.get_object(),
            approved=data["approved"],
            actor=request.user,
            approved_amount=data.get("approved_amount"),
            payer_reference=data.get("payer_reference", ""),
            valid_until=data.get("valid_until"),
            conditions=data.get("conditions", ""),
            reason=data.get("reason", ""),
        )).data)

    @action(detail=False, methods=["get"], url_path="expiring")
    def expiring(self, request):
        """Approvals about to become worthless — predictable a week ahead."""
        facility = (
            get_object_or_404(Facility, uuid=request.query_params["facility"])
            if request.query_params.get("facility") else None
        )
        return Response(expiring_preauthorisations(
            facility=facility,
            within_days=int(request.query_params.get("days", 7)),
        ))


class ClaimViewSet(viewsets.ReadOnlyModelViewSet):
    """Read, and move through the states. There is no update and no delete."""

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Claim, relations=["payer", "policy", "patient", "facility"],
        fields=["status", "service_date"],
    )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClaimDetailSerializer
        return ClaimSummarySerializer

    def get_queryset(self):
        return (
            Claim.objects.select_related(
                "payer", "patient", "invoice", "policy", "preauthorisation",
            )
            .prefetch_related("lines", "events")
        )

    @action(detail=False, methods=["post"], url_path="create")
    def build(self, request):
        get_authorization(request).require("invoice.create", Scope.FACILITY)
        serializer = ClaimCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        claim = create_claim(
            request.organization,
            get_object_or_404(Invoice, uuid=data["invoice"]),
            get_object_or_404(Policy, uuid=data["policy"]),
            actor=request.user,
            preauthorisation=(
                get_object_or_404(
                    PreAuthorisation, uuid=data["preauthorisation"]
                ) if data.get("preauthorisation") else None
            ),
            diagnosis=data.get("diagnosis", ""),
            diagnosis_code=data.get("diagnosis_code", ""),
            service_date=data.get("service_date"),
        )
        return Response(
            ClaimDetailSerializer(claim).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, reference=None):
        get_authorization(request).require("invoice.create", Scope.FACILITY)
        return Response(ClaimDetailSerializer(submit_claim(
            self.get_object(), actor=request.user,
            payer_reference=request.data.get("payer_reference", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="response")
    def respond(self, request, reference=None):
        get_authorization(request).require("payment.record", Scope.FACILITY)
        serializer = ClaimResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        claim = self.get_object()
        deductions = [
            {
                "line": get_object_or_404(
                    ClaimLine, uuid=entry["line"], claim=claim,
                ),
                "amount": entry["amount"],
                "reason": entry["reason"],
                "notes": entry.get("notes", ""),
            }
            for entry in data.get("deductions", [])
        ]
        return Response(ClaimDetailSerializer(record_response(
            claim, actor=request.user,
            approved_amount=data.get("approved_amount"),
            deductions=deductions,
            rejection_reason=data.get("rejection_reason", ""),
            payer_reference=data.get("payer_reference", ""),
        )).data)

    @action(detail=True, methods=["post"], url_path="query")
    def query(self, request, reference=None):
        get_authorization(request).require("payment.record", Scope.FACILITY)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ClaimDetailSerializer(raise_query(
            self.get_object(), serializer.validated_data["reason"],
            actor=request.user,
        )).data)

    @action(detail=True, methods=["post"], url_path="appeal")
    def appeal(self, request, reference=None):
        get_authorization(request).require("invoice.create", Scope.FACILITY)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ClaimDetailSerializer(appeal_claim(
            self.get_object(), serializer.validated_data["reason"],
            actor=request.user,
        )).data)

    @action(detail=True, methods=["post"], url_path="settle")
    def settle(self, request, reference=None):
        get_authorization(request).require("payment.record", Scope.FACILITY)
        serializer = SettlementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ClaimDetailSerializer(settle_claim(
            self.get_object(),
            serializer.validated_data["amount"],
            actor=request.user,
            payment_reference=serializer.validated_data.get(
                "payment_reference", ""
            ),
        )).data)

    @action(detail=True, methods=["post"], url_path="write-off")
    def write_off(self, request, reference=None):
        get_authorization(request).require("payment.record", Scope.ORGANIZATION)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ClaimDetailSerializer(write_off_claim(
            self.get_object(), serializer.validated_data["reason"],
            actor=request.user,
        )).data)

    @action(detail=True, methods=["get"], url_path="package")
    def package(self, request, reference=None):
        """Cost against the scheme's fixed package rate."""
        claim = self.get_object()
        code = request.query_params.get("code", "")
        return Response(package_margin(
            claim, package_rate(claim.payer, code, on_date=claim.service_date),
        ))


class SchemePackageViewSet(viewsets.ModelViewSet):
    serializer_class = SchemePackageSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        SchemePackage, relations=["payer"], fields=["is_active", "category"],
    )

    def get_queryset(self):
        return SchemePackage.objects.select_related("payer")

    def perform_create(self, serializer):
        get_authorization(self.request).require("invoice.create", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)


class ClaimReportView(APIView):
    """Ageing, deduction analysis and the deduction vocabulary."""

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]

    def get(self, request):
        which = request.query_params.get("report", "ageing")
        facility = (
            get_object_or_404(Facility, uuid=request.query_params["facility"])
            if request.query_params.get("facility") else None
        )

        if which == "ageing":
            payer = (
                get_object_or_404(Payer, uuid=request.query_params["payer"])
                if request.query_params.get("payer") else None
            )
            return Response(claims_ageing(facility=facility, payer=payer))
        if which == "deductions":
            return Response(deduction_analysis(
                facility=facility,
                since=as_date(request.query_params.get("since"), "since"),
            ))
        if which == "reasons":
            #: Served rather than hard-coded in the client, so the vocabulary
            #: a hospital deducts against can be audited and extended in one
            #: place.
            return Response([
                {"key": key, "label": label} for key, label in DEDUCTION_REASONS
            ])

        return Response(
            {"detail": f"Unknown report '{which}'.",
             "available": ["ageing", "deductions", "reasons"]},
            status=status.HTTP_400_BAD_REQUEST,
        )
