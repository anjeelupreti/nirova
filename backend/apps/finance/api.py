"""Finance endpoints.

`report.read` reads the books. Posting, reversing and closing need
`finance.post`, which exists separately from every other permission in the
system because the people who raise invoices and the people who keep the
ledger are deliberately not the same people.

What this API does not offer, and why.

**No endpoint edits or deletes a journal entry.** A mistake is reversed. The
original stays, and the correction is itself a fact worth seeing.

**No endpoint sets an account balance.** A balance is the sum of its
postings — anything else is a number somebody typed.

**No endpoint posts into a closed period.** It posts into the next open one,
keeping the document's own date, and says so in the response.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# UUIDRelatedField: relations are published by UUID. With a database per
# tenant an integer PK means a different row in every customer's database.
from apps.common.dates import as_date, date_params
from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.finance.models import (
    Account,
    AccountingPeriod,
    BankAccount,
    Expense,
    ExpenseStatus,
    JournalEntry,
    JournalLine,
    PeriodStatus,
    StatementLine,
    SupplierInvoice,
    SupplierInvoiceStatus,
)
from apps.finance.services import (
    account_for,
    account_ledger,
    balance_sheet,
    build_chart,
    close_period,
    match_statement_line,
    open_year,
    payables_ageing,
    post_document,
    post_entry,
    post_expense,
    post_supplier_invoice,
    profit_and_loss,
    receivables_ageing,
    reconcile_receivables,
    reconciliation,
    reopen_period,
    reverse_entry,
    trial_balance,
    vat_return,
)
from apps.organization.models import Facility
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class AccountSerializer(serializers.ModelSerializer):
    parent = UUIDRelatedField(queryset=Account.objects.all(), required=False,
                              allow_null=True)
    facility = UUIDRelatedField(queryset=Facility.objects.all(), required=False,
                                allow_null=True)
    normal_balance = serializers.CharField(read_only=True)

    class Meta:
        model = Account
        fields = [
            "uuid", "code", "name", "name_nepali", "account_type", "parent",
            "is_postable", "control_key", "is_control", "facility",
            "is_active", "description", "normal_balance",
        ]
        read_only_fields = ["uuid", "is_postable", "normal_balance"]


class PeriodSerializer(serializers.ModelSerializer):
    accepts_postings = serializers.BooleanField(read_only=True)
    entries = serializers.IntegerField(source="entries.count", read_only=True)

    class Meta:
        model = AccountingPeriod
        fields = [
            "uuid", "fiscal_year", "period_number", "name", "starts_on",
            "ends_on", "status", "closed_at", "closed_by_name", "notes",
            "accepts_postings", "entries",
        ]
        read_only_fields = fields


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalLine
        fields = [
            "uuid", "account_code", "account_name", "debit", "credit",
            "narration", "party_type", "party_reference", "party_name",
            "cost_centre",
        ]
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)
    period_name = serializers.CharField(source="period.name", read_only=True)
    facility_name = serializers.CharField(
        source="facility.name", read_only=True, default="",
    )
    reversed_by_reference = serializers.SerializerMethodField()
    #: True when the entry landed in a period other than its document's own.
    posted_late = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = [
            "uuid", "reference", "document_date", "posting_date",
            "period_name", "facility_name", "narration", "source",
            "source_reference", "status", "posted_at", "posted_by_name",
            "total_debit", "total_credit", "reversal_reason",
            "reversed_by_reference", "posted_late", "lines",
        ]
        read_only_fields = fields

    def get_reversed_by_reference(self, obj) -> str:
        reversal = getattr(obj, "reversed_by", None)
        return reversal.reference if reversal else ""

    def get_posted_late(self, obj) -> bool:
        return obj.posting_date != obj.document_date


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(queryset=Facility.objects.all())
    outstanding = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True,
    )
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = SupplierInvoice
        fields = [
            "uuid", "reference", "supplier_invoice_number", "supplier_uuid",
            "supplier_name", "facility", "invoice_date", "due_date",
            "received_on", "subtotal", "tax_amount", "total", "paid_amount",
            "goods_receipts", "variance", "variance_notes", "status",
            "approved_by_name", "approved_at", "notes", "outstanding",
            "is_overdue",
        ]
        read_only_fields = [
            "uuid", "reference", "paid_amount", "approved_by_name",
            "approved_at", "outstanding", "is_overdue",
        ]


class ExpenseSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(queryset=Facility.objects.all())
    account = UUIDRelatedField(queryset=Account.objects.all())
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "uuid", "reference", "facility", "spent_on", "account",
            "account_name", "cost_centre", "description", "amount",
            "tax_amount", "claimed_by_name", "payment_method",
            "receipt_number", "has_receipt", "status", "approved_by_name",
            "approved_at", "rejection_reason",
        ]
        read_only_fields = [
            "uuid", "reference", "account_name", "status", "approved_by_name",
            "approved_at",
        ]


class BankAccountSerializer(serializers.ModelSerializer):
    account = UUIDRelatedField(queryset=Account.objects.all())
    facility = UUIDRelatedField(queryset=Facility.objects.all(),
                                required=False, allow_null=True)

    class Meta:
        model = BankAccount
        fields = [
            "uuid", "name", "bank_name", "branch", "account_number",
            "account", "facility", "is_active", "notes",
        ]
        read_only_fields = ["uuid"]


class StatementLineSerializer(serializers.ModelSerializer):
    is_matched = serializers.BooleanField(read_only=True)

    class Meta:
        model = StatementLine
        fields = [
            "uuid", "transaction_date", "description", "reference", "amount",
            "balance_after", "matched_at", "matched_by_name", "is_matched",
        ]
        read_only_fields = fields


# -- inputs -----------------------------------------------------------------


class JournalLineInputSerializer(serializers.Serializer):
    account = serializers.CharField(
        help_text="Account UUID, code, or a control key.",
    )
    debit = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, default=0,
    )
    credit = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, default=0,
    )
    narration = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default="",
    )
    party_type = serializers.CharField(
        max_length=24, required=False, allow_blank=True, default="",
    )
    party_reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )
    party_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
    )
    cost_centre = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )


class JournalInputSerializer(serializers.Serializer):
    narration = serializers.CharField(max_length=512)
    document_date = serializers.DateField(required=False)
    facility = serializers.UUIDField(required=False, allow_null=True)
    lines = JournalLineInputSerializer(many=True)

    def validate_lines(self, lines):
        # Two lines is the minimum that can balance. One line is somebody
        # halfway through typing, and the balancing check further down would
        # report it as an imbalance rather than as what it is.
        if len(lines) < 2:
            raise serializers.ValidationError(
                "A journal needs at least two lines — one account cannot "
                "balance against itself."
            )
        return lines


class ReversalSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)
    on_date = serializers.DateField(required=False)


class ClosePeriodSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[PeriodStatus.SOFT_CLOSED, PeriodStatus.LOCKED],
        default=PeriodStatus.SOFT_CLOSED,
    )
    force = serializers.BooleanField(required=False, default=False)


class ReopenSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class MatchSerializer(serializers.Serializer):
    journal_line = serializers.UUIDField()


def _resolve_account(value: str) -> Account:
    """Accept a UUID, a code, or a control key.

    Three ways of naming an account because three kinds of caller exist: a
    screen has the UUID, an importer has the code, and an integration knows
    only what the account is for.
    """
    account = (
        Account.objects.filter(uuid=value).first()
        if len(value) == 36
        else None
    )
    account = account or Account.objects.filter(code=value).first()
    account = account or Account.objects.filter(control_key=value).first()
    if account is None:
        raise serializers.ValidationError(
            {"account": f"No account matches '{value}'."}
        )
    return account


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Account, relations=["facility", "parent"],
        fields=["account_type", "is_active", "is_postable", "is_control"],
    )

    def get_queryset(self):
        return Account.objects.select_related("parent").order_by("code")

    def perform_create(self, serializer):
        get_authorization(self.request).require("finance.post", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        get_authorization(self.request).require("finance.post", Scope.ORGANIZATION)
        serializer.save()

    @action(detail=False, methods=["post"], url_path="build")
    def build(self, request):
        """Create the starter chart. Idempotent; adds only what is missing."""
        get_authorization(request).require("finance.post", Scope.ORGANIZATION)
        return Response(build_chart(request.organization, actor=request.user))

    @action(detail=True, methods=["get"], url_path="ledger")
    def ledger(self, request, uuid=None):
        return Response(account_ledger(
            self.get_object(), **date_params(request, "since", "until"),
        ))


class PeriodViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PeriodSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        AccountingPeriod, fields=["fiscal_year", "status"],
    )

    def get_queryset(self):
        return AccountingPeriod.objects.order_by("-starts_on")

    @action(detail=False, methods=["post"], url_path="open-year")
    def open_fiscal_year(self, request):
        get_authorization(request).require("finance.close", Scope.ORGANIZATION)
        periods = open_year(
            request.data.get("on_date") or None, actor=request.user,
        )
        return Response(PeriodSerializer(periods, many=True).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, uuid=None):
        get_authorization(request).require("finance.close", Scope.ORGANIZATION)
        serializer = ClosePeriodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period = close_period(
            self.get_object(), actor=request.user,
            status=serializer.validated_data["status"],
            force=serializer.validated_data["force"],
        )
        return Response(PeriodSerializer(period).data)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, uuid=None):
        get_authorization(request).require("finance.close", Scope.ORGANIZATION)
        serializer = ReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period = reopen_period(
            self.get_object(), actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(PeriodSerializer(period).data)


class JournalViewSet(viewsets.ReadOnlyModelViewSet):
    """Read, post and reverse. There is no update and no delete."""

    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        JournalEntry, relations=["facility", "period"],
        fields=["status", "source", "posting_date"],
    )

    def get_queryset(self):
        return (
            JournalEntry.objects.select_related("period", "facility")
            .prefetch_related("lines__account", "reversed_by")
            .order_by("-posting_date", "-reference")
        )

    @action(detail=False, methods=["post"], url_path="post")
    def create_entry(self, request):
        get_authorization(request).require("finance.post", Scope.ORGANIZATION)
        serializer = JournalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lines = [
            {**line, "account": _resolve_account(line["account"])}
            for line in data["lines"]
        ]
        entry = post_entry(
            lines, data["narration"], request.user,
            document_date=data.get("document_date"),
            facility=(
                get_object_or_404(Facility, uuid=data["facility"])
                if data.get("facility") else None
            ),
        )
        return Response(
            JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, reference=None):
        get_authorization(request).require("finance.post", Scope.ORGANIZATION)
        serializer = ReversalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contra = reverse_entry(
            self.get_object(), actor=request.user,
            reason=serializer.validated_data["reason"],
            on_date=serializer.validated_data.get("on_date"),
        )
        return Response(
            JournalEntrySerializer(contra).data, status=status.HTTP_201_CREATED
        )


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierInvoiceSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        SupplierInvoice, relations=["facility"], fields=["status"],
    )

    def get_queryset(self):
        return SupplierInvoice.objects.select_related("facility")

    def perform_create(self, serializer):
        get_authorization(self.request).require("purchase.create", Scope.FACILITY)
        count = SupplierInvoice.objects.count() + 1
        serializer.save(
            reference=f"SI-{count:06d}",
            created_by_id=self.request.user.uuid,
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, reference=None):
        """Approve for payment, and post it.

        Approval and posting are one step deliberately. An approved invoice
        that is not in the books is a liability the hospital does not know it
        has, and the gap between the two actions is where that happens.
        """
        get_authorization(request).require("purchase.approve", Scope.FACILITY)
        invoice = self.get_object()
        if invoice.status != SupplierInvoiceStatus.DRAFT:
            return Response(
                {"detail": f"{invoice.reference} is already "
                           f"{invoice.get_status_display().lower()}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invoice.status = SupplierInvoiceStatus.APPROVED
        invoice.approved_by_id = request.user.uuid
        invoice.approved_by_name = request.user.full_name
        invoice.save(update_fields=[
            "status", "approved_by_id", "approved_by_name", "updated_at",
        ])
        post_supplier_invoice(invoice, actor=request.user)
        return Response(SupplierInvoiceSerializer(invoice).data)


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Expense, relations=["facility", "account"], fields=["status"],
    )

    def get_queryset(self):
        return Expense.objects.select_related("facility", "account")

    def perform_create(self, serializer):
        count = Expense.objects.count() + 1
        serializer.save(
            reference=f"EX-{count:06d}",
            claimed_by_id=self.request.user.uuid,
            claimed_by_name=self.request.user.full_name,
            created_by_id=self.request.user.uuid,
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, reference=None):
        """Approved by somebody other than the person who claimed it."""
        get_authorization(request).require("finance.post", Scope.ORGANIZATION)
        expense = self.get_object()
        if expense.claimed_by_id == request.user.uuid:
            return Response(
                {"detail": "An expense cannot be approved by the person who "
                           "claimed it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        expense.status = ExpenseStatus.APPROVED
        expense.approved_by_id = request.user.uuid
        expense.approved_by_name = request.user.full_name
        expense.save(update_fields=[
            "status", "approved_by_id", "approved_by_name", "updated_at",
        ])
        post_expense(expense, actor=request.user)
        return Response(ExpenseSerializer(expense).data)


class BankAccountViewSet(viewsets.ModelViewSet):
    serializer_class = BankAccountSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        BankAccount, relations=["facility"], fields=["is_active"],
    )

    def get_queryset(self):
        return BankAccount.objects.select_related("account", "facility")

    def perform_create(self, serializer):
        get_authorization(self.request).require("finance.post", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["get"], url_path="reconciliation")
    def reconcile(self, request, uuid=None):
        return Response(reconciliation(
            self.get_object(), **date_params(request, "since", "until"),
        ))

    @action(detail=True, methods=["get"], url_path="statement")
    def statement(self, request, uuid=None):
        return Response(StatementLineSerializer(
            self.get_object().statement_lines.order_by("-transaction_date")[:200],
            many=True,
        ).data)

    @action(
        detail=True, methods=["post"],
        url_path="statement/(?P<line>[^/.]+)/match",
    )
    def match(self, request, uuid=None, line=None):
        get_authorization(request).require("finance.post", Scope.ORGANIZATION)
        serializer = MatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        statement_line = get_object_or_404(
            StatementLine, uuid=line, bank_account=self.get_object(),
        )
        journal_line = get_object_or_404(
            JournalLine, uuid=serializer.validated_data["journal_line"],
        )
        return Response(StatementLineSerializer(
            match_statement_line(statement_line, journal_line, actor=request.user)
        ).data)


class ReportView(APIView):
    """Every finance report behind one endpoint, chosen by `report=`.

    One view rather than seven because they take the same three parameters and
    a screen switching between them should not have to know seven URLs.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        which = request.query_params.get("report", "trial_balance")
        since = as_date(request.query_params.get("since"), "since")
        until = as_date(request.query_params.get("until"), "until")
        facility = (
            get_object_or_404(Facility, uuid=request.query_params["facility"])
            if request.query_params.get("facility") else None
        )

        if which == "trial_balance":
            return Response(trial_balance(until=until, facility=facility))
        if which == "profit_and_loss":
            return Response(
                profit_and_loss(since=since, until=until, facility=facility)
            )
        if which == "balance_sheet":
            return Response(balance_sheet(until=until))
        if which == "receivables":
            return Response(receivables_ageing(until=until))
        if which == "payables":
            return Response(payables_ageing(until=until))
        if which == "reconcile_receivables":
            return Response(reconcile_receivables(until=until))
        if which == "vat":
            return Response(vat_return(since=since, until=until))

        return Response(
            {"detail": f"Unknown report '{which}'.",
             "available": [
                 "trial_balance", "profit_and_loss", "balance_sheet",
                 "receivables", "payables", "reconcile_receivables", "vat",
             ]},
            status=status.HTTP_400_BAD_REQUEST,
        )
