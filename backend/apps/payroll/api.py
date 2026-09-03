"""Payroll endpoints.

Three access rules run through everything here.

**Seeing a payroll is `salary.read`; running one is `payroll.process`;
approving one is `payroll.approve`.** Three different authorities, and the
last two conflict with each other in the permission catalogue so a role
cannot hold both by accident.

**Everyone can see their own payslips**, without `salary.read`. Checking what
you were paid should not require permission to see what everybody was paid.

**An approved run is read-only through the API as well as the service.** The
lock is in the service layer, but the endpoints do not offer the button
either — a control the UI still shows is a control users learn to distrust.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.hr.models import Employee
from apps.organization.models import Facility
from apps.payroll.models import (
    ContributionScheme,
    EmployeePayroll,
    PayComponent,
    PayrollRun,
    Payslip,
    PayslipLine,
    SalaryPaymentBatch,
    SalaryStructure,
    TaxSlab,
)
from apps.payroll.services import (
    approve,
    bank_file_rows,
    calculate,
    cancel_run,
    confirm_payment,
    create_payment_batch,
    open_run,
    payable_days,
    run_summary,
    statutory_return,
    submit_for_approval,
)
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class PayComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayComponent
        fields = (
            "uuid", "code", "name", "name_nepali", "component_type", "basis",
            "rate", "amount", "is_taxable",
            "counts_towards_contribution_base", "is_prorated", "sequence",
            "is_statutory", "is_active", "notes",
        )
        read_only_fields = ("uuid",)


class SalaryStructureSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    components = PayComponentSerializer(many=True, read_only=True)

    class Meta:
        model = SalaryStructure
        fields = (
            "uuid", "code", "name", "description", "facility", "components",
            "is_active",
        )
        read_only_fields = ("uuid", "components")


class TaxSlabSerializer(serializers.ModelSerializer):
    width = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = TaxSlab
        fields = (
            "uuid", "fiscal_year", "regime", "sequence", "lower_bound",
            "upper_bound", "width", "rate_percent",
            "waived_for_ssf_contributors", "label",
        )
        read_only_fields = ("uuid", "width")


class ContributionSchemeSerializer(serializers.ModelSerializer):
    total_percent = serializers.DecimalField(
        max_digits=7, decimal_places=3, read_only=True
    )

    class Meta:
        model = ContributionScheme
        fields = (
            "uuid", "code", "name", "fiscal_year", "employee_percent",
            "employer_percent", "total_percent", "on_basic",
            "is_tax_deductible", "annual_deduction_ceiling",
            "replaces_social_security_tax", "is_active", "notes",
        )
        read_only_fields = ("uuid", "total_percent")


class EmployeePayrollSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    structure = UUIDRelatedField(read_only=True)
    scheme = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    structure_name = serializers.CharField(
        source="structure.name", read_only=True, default=""
    )
    scheme_name = serializers.CharField(
        source="scheme.name", read_only=True, default=""
    )

    class Meta:
        model = EmployeePayroll
        fields = (
            "uuid", "employee", "employee_name", "structure", "structure_name",
            "scheme", "scheme_name", "tax_regime", "life_insurance_premium",
            "health_insurance_premium", "cit_contribution",
            "remote_area_category", "is_disabled", "is_on_hold", "hold_reason",
        )
        read_only_fields = ("uuid", "employee", "employee_name",
                            "structure_name", "scheme_name")


class PayslipLineSerializer(serializers.ModelSerializer):
    component = UUIDRelatedField(read_only=True)

    class Meta:
        model = PayslipLine
        fields = (
            "uuid", "component", "code", "name", "component_type", "basis",
            "rate", "base_amount", "amount", "is_taxable", "sequence",
            "explanation",
        )
        read_only_fields = fields


class PayslipSerializer(serializers.ModelSerializer):
    run = UUIDRelatedField(read_only=True)
    employee = UUIDRelatedField(read_only=True)
    lines = PayslipLineSerializer(many=True, read_only=True)
    period_label = serializers.CharField(
        source="run.period_label", read_only=True
    )
    run_reference = serializers.CharField(
        source="run.reference", read_only=True
    )
    run_status = serializers.CharField(source="run.status", read_only=True)

    class Meta:
        model = Payslip
        fields = (
            "uuid", "reference", "run", "run_reference", "run_status",
            "period_label", "employee", "employee_code", "employee_name",
            "position_title", "department_name", "bank_name",
            "bank_account_number", "pan_number", "basic_salary",
            "payable_days", "days_in_period", "days_present",
            "days_paid_leave", "days_unpaid_leave", "days_absent",
            "overtime_hours", "gross", "taxable_gross", "deductions", "tax",
            "net", "employer_cost", "tax_workings", "is_held", "hold_reason",
            "notes", "lines",
        )
        read_only_fields = fields


class PayslipListSerializer(serializers.ModelSerializer):
    """Without the lines or the tax workings, which are large and per-detail."""

    run = UUIDRelatedField(read_only=True)
    employee = UUIDRelatedField(read_only=True)
    period_label = serializers.CharField(
        source="run.period_label", read_only=True
    )

    class Meta:
        model = Payslip
        fields = (
            "uuid", "reference", "run", "period_label", "employee",
            "employee_code", "employee_name", "position_title",
            "department_name", "payable_days", "gross", "deductions", "tax",
            "net", "employer_cost", "is_held", "hold_reason",
        )
        read_only_fields = fields


class PayrollRunSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    corrects = UUIDRelatedField(read_only=True)
    facility_name = serializers.CharField(
        source="facility.name", read_only=True
    )
    is_editable = serializers.BooleanField(read_only=True)
    total_cost = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )

    class Meta:
        model = PayrollRun
        fields = (
            "uuid", "reference", "facility", "facility_name", "fiscal_year",
            "period_label", "period_start", "period_end", "status",
            "is_editable", "corrects", "calculated_at", "approved_at",
            "approved_by_name", "paid_at", "employee_count", "gross_total",
            "deduction_total", "tax_total", "net_total",
            "employer_cost_total", "total_cost", "notes",
            "cancellation_reason",
        )
        read_only_fields = fields


class PaymentBatchSerializer(serializers.ModelSerializer):
    run = UUIDRelatedField(read_only=True)
    run_reference = serializers.CharField(
        source="run.reference", read_only=True
    )

    class Meta:
        model = SalaryPaymentBatch
        fields = (
            "uuid", "reference", "run", "run_reference", "method", "status",
            "total", "count", "bank_name", "exported_at", "confirmed_at",
            "value_date", "notes",
        )
        read_only_fields = fields


# -- write ------------------------------------------------------------------


class OpenRunSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    period_label = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    corrects = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ApproveRunSerializer(serializers.Serializer):
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


class CancelRunSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class PaymentBatchInputSerializer(serializers.Serializer):
    method = serializers.CharField(max_length=20, default="bank_transfer")
    bank_name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    value_date = serializers.DateField(required=False)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class PayrollRunViewSet(viewsets.ReadOnlyModelViewSet):
    """Payroll runs."""

    serializer_class = PayrollRunSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        PayrollRun, relations=["facility"],
        fields=["status", "fiscal_year"],
    )
    ordering_fields = ["period_start", "net_total"]

    def get_queryset(self):
        queryset = PayrollRun.objects.select_related("facility")
        # Cancelled runs are hidden by default. They are kept — an abandoned
        # run is part of the record of what was attempted — but a list whose
        # first row is something nobody acted on sends the reader to the wrong
        # place.
        if self.request.query_params.get("include_cancelled") != "true":
            queryset = queryset.exclude(status="cancelled")
        # Newest first *within* a period as well as across periods: several
        # runs can share a period once one has been corrected or abandoned.
        return queryset.order_by("-period_start", "-created_at")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("payroll.process", Scope.FACILITY)
        serializer = OpenRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        run = open_run(
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            period_start=data["period_start"],
            period_end=data["period_end"],
            actor=request.user,
            period_label=data.get("period_label", ""),
            corrects=(
                get_object_or_404(PayrollRun, uuid=data["corrects"])
                if data.get("corrects") else None
            ),
            notes=data.get("notes", ""),
        )
        return Response(
            PayrollRunSerializer(run).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="calculate")
    def calculate(self, request, reference=None):
        """Compute every payslip. Idempotent — recalculating replaces."""
        get_authorization(request).require("payroll.process", Scope.FACILITY)
        run = calculate(self.get_object(), actor=request.user)
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, reference=None):
        get_authorization(request).require("payroll.process", Scope.FACILITY)
        run = submit_for_approval(self.get_object(), actor=request.user)
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, reference=None):
        """Sign off. Refused for whoever ran it."""
        get_authorization(request).require("payroll.approve", Scope.FACILITY)
        serializer = ApproveRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = approve(
            self.get_object(),
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, reference=None):
        get_authorization(request).require("payroll.process", Scope.FACILITY)
        serializer = CancelRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = cancel_run(
            self.get_object(),
            actor=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, reference=None):
        return Response(run_summary(self.get_object()))

    @action(detail=True, methods=["get"], url_path="statutory")
    def statutory(self, request, reference=None):
        """What must be remitted, and to whom.

        Tax and contributions are separated because they are filed separately
        and on different schedules — a single "deductions" total is something
        somebody then has to unpick.
        """
        return Response(statutory_return(self.get_object()))

    @action(detail=True, methods=["get"], url_path="payslips")
    def payslips(self, request, reference=None):
        slips = (
            self.get_object().payslips.select_related("run")
            .order_by("employee_name")
        )
        return Response(PayslipListSerializer(slips, many=True).data)

    @action(detail=True, methods=["get", "post"], url_path="batches")
    def batches(self, request, reference=None):
        run = self.get_object()
        if request.method == "GET":
            return Response(
                PaymentBatchSerializer(
                    run.payment_batches.all(), many=True
                ).data
            )

        get_authorization(request).require("payroll.process", Scope.FACILITY)
        serializer = PaymentBatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        batch = create_payment_batch(
            run, actor=request.user,
            method=data.get("method", "bank_transfer"),
            bank_name=data.get("bank_name", ""),
            value_date=data.get("value_date"),
        )
        return Response(
            PaymentBatchSerializer(batch).data, status=status.HTTP_201_CREATED
        )


class PaymentBatchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentBatchSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "reference"

    def get_queryset(self):
        return SalaryPaymentBatch.objects.select_related("run").order_by(
            "-created_at"
        )

    @action(detail=True, methods=["get"], url_path="rows")
    def rows(self, request, reference=None):
        """The bank-file rows, with anything unpayable named.

        Missing account details are reported rather than silently skipped: a
        transfer file that quietly drops three people pays three people
        nothing, and nobody finds out until they ask.
        """
        return Response(bank_file_rows(self.get_object()))

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, reference=None):
        get_authorization(request).require("payroll.process", Scope.FACILITY)
        batch = confirm_payment(self.get_object(), actor=request.user)
        return Response(PaymentBatchSerializer(batch).data)


class PayslipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PayslipSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        Payslip, relations=["run", "employee"], fields=["is_held"]
    )

    def get_queryset(self):
        return Payslip.objects.select_related("run", "employee").order_by(
            "-run__period_start", "employee_name"
        )

    @action(
        detail=False, methods=["get"], url_path="mine",
        permission_classes=[IsAuthenticated],
    )
    def mine(self, request):
        """Your own payslips.

        Outside `salary.read` deliberately: checking what you were paid should
        not require permission to see what everybody was paid. Only approved
        and paid runs are shown — a draft payslip is a working figure, and
        showing it would have people querying numbers that are about to
        change.
        """
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        slips = (
            Payslip.objects.filter(
                employee=employee, run__status__in=["approved", "paid"]
            )
            .select_related("run")
            .prefetch_related("lines")
            .order_by("-run__period_start")
        )
        return Response(PayslipSerializer(slips, many=True).data)


class EmployeePayrollViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeePayrollSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        EmployeePayroll, relations=["employee", "structure", "scheme"],
        fields=["tax_regime", "is_on_hold"],
    )
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return EmployeePayroll.objects.select_related(
            "employee", "structure", "scheme"
        ).order_by("employee__first_name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "payroll.process", Scope.FACILITY
        )
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        get_authorization(self.request).require(
            "payroll.process", Scope.FACILITY
        )
        serializer.save()


class PayComponentViewSet(viewsets.ModelViewSet):
    serializer_class = PayComponentSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "code"
    filterset_fields = ["component_type", "is_active", "is_statutory"]

    def get_queryset(self):
        return PayComponent.objects.order_by("sequence", "name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "payroll.process", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)


class SalaryStructureViewSet(viewsets.ModelViewSet):
    serializer_class = SalaryStructureSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "code"

    def get_queryset(self):
        return SalaryStructure.objects.prefetch_related(
            "components"
        ).order_by("name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "payroll.process", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)


class TaxSlabViewSet(viewsets.ModelViewSet):
    """The tax table, editable because it changes with every budget."""

    serializer_class = TaxSlabSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "uuid"
    filterset_fields = ["fiscal_year", "regime"]

    def get_queryset(self):
        return TaxSlab.objects.order_by("fiscal_year", "regime", "sequence")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "payroll.approve", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        # Editing a tax band changes what everybody is paid, so it sits behind
        # the approval permission rather than the processing one.
        get_authorization(self.request).require(
            "payroll.approve", Scope.ORGANIZATION
        )
        serializer.save()


class ContributionSchemeViewSet(viewsets.ModelViewSet):
    serializer_class = ContributionSchemeSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("salary.read")]
    lookup_field = "uuid"
    filterset_fields = ["fiscal_year", "code", "is_active"]

    def get_queryset(self):
        return ContributionScheme.objects.order_by("-fiscal_year", "name")

    def perform_create(self, serializer):
        get_authorization(self.request).require(
            "payroll.approve", Scope.ORGANIZATION
        )
        serializer.save(created_by_id=self.request.user.uuid)

    def perform_update(self, serializer):
        get_authorization(self.request).require(
            "payroll.approve", Scope.ORGANIZATION
        )
        serializer.save()


class PayablePreviewView(APIView):
    """What one employee's period looks like before a run is calculated.

    Exists so an officer can check an odd-looking figure — "why is she only
    down for eleven days?" — without calculating the whole payroll to find
    out.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("payroll.process")]

    def get(self, request):
        employee = get_object_or_404(
            Employee, uuid=request.query_params.get("employee")
        )
        start = request.query_params.get("from")
        end = request.query_params.get("to")
        if not (start and end):
            return Response(
                {"detail": "Give a from and a to date."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = payable_days(employee, start, end)
        result["employee"] = employee.employee_code
        result["employee_name"] = employee.full_name
        return Response(result)
