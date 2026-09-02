"""Billing endpoints."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import (
    Charge,
    ChargeStatus,
    Invoice,
    Payment,
    PriceList,
    ServiceItem,
)
from apps.billing.serializers import (
    CaptureChargeSerializer,
    ChargeSerializer,
    CreateInvoiceSerializer,
    CreditInvoiceSerializer,
    InvoiceSerializer,
    PaymentSerializer,
    PriceListSerializer,
    RecordPaymentSerializer,
    RefundPaymentSerializer,
    ServiceItemSerializer,
)
from apps.billing.services import (
    cancel_charge,
    capture_charge,
    create_invoice,
    credit_invoice,
    daily_collection,
    patient_account,
    record_payment,
    refund_payment,
    resolve_price,
)
from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope


class ServiceItemViewSet(viewsets.ModelViewSet):
    """The billable services catalogue."""

    serializer_class = ServiceItemSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        ServiceItem, relations=['department'], fields=['category', 'is_active']
    )
    search_fields = ["code", "name", "name_nepali"]
    ordering_fields = ["category", "name", "default_price"]

    def get_queryset(self):
        return ServiceItem.objects.select_related("department").order_by(
            "category", "display_order", "name"
        )

    @action(detail=True, methods=["get"], url_path="price")
    def price(self, request, uuid=None):
        """What this service costs for a given patient, and why.

        The provenance matters as much as the number: "why was I charged
        this?" is a question a counter clerk has to answer on the spot.
        """
        service = self.get_object()
        patient = get_object_or_404(
            Patient, uuid=request.query_params.get("patient")
        )
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        pricing = resolve_price(service, patient, facility)
        return Response(
            {
                "service_code": service.code,
                "service_name": service.name,
                "unit_price": pricing["unit_price"],
                "discount_percent": pricing["discount_percent"],
                "tax_rate": service.effective_tax_rate,
                "tax_treatment": service.tax_treatment,
                "source": pricing["source"],
                "price_list": (
                    pricing["price_list"].name if pricing["price_list"] else None
                ),
            }
        )


class PriceListViewSet(viewsets.ModelViewSet):
    serializer_class = PriceListSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        PriceList, relations=['facility'], fields=['patient_category', 'is_active']
    )

    def get_queryset(self):
        return (
            PriceList.objects.select_related("facility")
            .prefetch_related("items__service")
            .order_by("-priority", "name")
        )


class ChargeViewSet(viewsets.ModelViewSet):
    """Charge capture.

    No update endpoint: a charge is captured with the price that applied at
    the time, and correcting it means cancelling and re-capturing so the
    original stays on the record.
    """

    serializer_class = ChargeSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Charge, relations=['facility', 'service'], fields=['status']
    )
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Charge.objects.select_related(
            "patient", "encounter", "service"
        )
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])
        if params.get("encounter"):
            queryset = queryset.filter(encounter__uuid=params["encounter"])
        if params.get("pending") == "true":
            queryset = queryset.filter(status=ChargeStatus.PENDING)
        return queryset.order_by("-charged_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("invoice.create", Scope.FACILITY)

        serializer = CaptureChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # A discount beyond the service's ceiling needs an approver. The
        # caller is offered as approver only when they hold the permission --
        # otherwise the service layer refuses, which is the intended path.
        approver = (
            request.user
            if authorization.has("discount.approve", Scope.FACILITY)
            else None
        )

        charge = capture_charge(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            service=get_object_or_404(ServiceItem, uuid=data["service_uuid"]),
            actor=request.user,
            encounter=(
                Encounter.objects.filter(uuid=data["encounter_uuid"]).first()
                if data.get("encounter_uuid")
                else None
            ),
            quantity=data.get("quantity", 1),
            discount_percent=data.get("discount_percent", 0),
            discount_reason=data.get("discount_reason", ""),
            discount_approved_by=approver,
            notes=data.get("notes", ""),
        )
        return Response(
            ChargeSerializer(charge).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("invoice.create", Scope.FACILITY)
        charge = cancel_charge(
            self.get_object(), request.data.get("reason", ""), actor=request.user
        )
        return Response(ChargeSerializer(charge).data)


class InvoiceViewSet(viewsets.ModelViewSet):
    """Invoices.

    No update or delete. An issued invoice is a statutory document: it is
    reversed by a credit note and reissued, never edited.
    """

    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Invoice, relations=['facility'], fields=['status', 'fiscal_year', 'is_credit_note']
    )
    ordering_fields = ["issued_at", "total"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Invoice.objects.select_related(
            "patient", "facility", "encounter", "credited_by"
        ).prefetch_related("lines", "payments")
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])
        if params.get("unpaid") == "true":
            queryset = queryset.filter(status__in=["issued", "partially_paid"])
        return queryset.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("invoice.create", Scope.FACILITY)

        serializer = CreateInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        charges = None
        if data.get("charge_uuids"):
            charges = list(
                Charge.objects.filter(uuid__in=data["charge_uuids"]).order_by(
                    "charged_at"
                )
            )

        invoice = create_invoice(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            actor=request.user,
            encounter=(
                Encounter.objects.filter(uuid=data["encounter_uuid"]).first()
                if data.get("encounter_uuid")
                else None
            ),
            charges=charges,
            issue=data.get("issue", True),
            notes=data.get("notes", ""),
        )
        invoice = self.get_queryset().get(pk=invoice.pk)
        return Response(
            InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="pay")
    def pay(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("payment.record", Scope.FACILITY)

        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = record_payment(
            self.get_object(),
            amount=data["amount"],
            method=data["method"],
            actor=request.user,
            reference=data.get("reference", ""),
            counter=data.get("counter", ""),
            notes=data.get("notes", ""),
        )
        invoice = self.get_queryset().get(pk=payment.invoice_id)
        return Response(
            {
                "payment": PaymentSerializer(payment).data,
                "invoice": InvoiceSerializer(invoice).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="credit")
    def credit(self, request, uuid=None):
        """Reverse this invoice with a credit note."""
        authorization = get_authorization(request)
        authorization.require("refund.approve", Scope.FACILITY)

        serializer = CreditInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        credit = credit_invoice(
            self.get_object(),
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        credit = self.get_queryset().get(pk=credit.pk)
        return Response(
            InvoiceSerializer(credit).data, status=status.HTTP_201_CREATED
        )


class RefundPaymentView(APIView):
    """Refund a payment.

    Requires `refund.approve`, which conflicts with `refund.create` under
    segregation of duties — and the service layer additionally refuses when
    the approver is the person who took the money.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("refund.approve")]

    def post(self, request, uuid):
        payment = get_object_or_404(Payment, uuid=uuid)
        serializer = RefundPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refund = refund_payment(
            payment,
            reason=serializer.validated_data["reason"],
            actor=request.user,
            approved_by=request.user,
        )
        return Response(
            PaymentSerializer(refund).data, status=status.HTTP_201_CREATED
        )


class PatientAccountView(APIView):
    """What a patient owes, has paid, and has outstanding."""

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]

    def get(self, request, uuid):
        patient = get_object_or_404(Patient, uuid=uuid)
        return Response(patient_account(patient))


class DailyCollectionView(APIView):
    """End-of-day cash-up, split by payment method.

    By method rather than one total, because the cash drawer is counted
    separately from the wallet settlements and each provider settles on its
    own schedule.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("invoice.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        on_date = request.query_params.get("date")
        target = (
            timezone.datetime.fromisoformat(on_date).date()
            if on_date
            else timezone.localdate()
        )
        return Response(daily_collection(facility, target))
