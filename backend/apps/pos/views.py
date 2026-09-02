"""Counter endpoints.

Every write goes through `apps.pos.services`. The views resolve UUIDs to
objects, check the permission, and hand over — no business rule lives here,
because a rule enforced only in a view is a rule the seed commands and any
future background job do not obey.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.pharmacy.models import Batch, Product, StockLocation
from apps.pos.models import CounterSession, Sale, SaleLine, SaleReturn
from apps.pos.serializers import (
    CloseSessionSerializer,
    CounterSessionSerializer,
    CreateSaleSerializer,
    DecideReturnSerializer,
    OpenSessionSerializer,
    QuoteSaleSerializer,
    ReconcileSessionSerializer,
    RequestReturnSerializer,
    SaleReturnSerializer,
    SaleSerializer,
    VoidSaleSerializer,
)
from apps.pos.services import (
    approve_return,
    close_session,
    create_sale,
    open_session,
    quote_sale,
    reconcile_session,
    reject_return,
    request_return,
    sales_summary,
    search_products,
    session_takings,
    void_sale,
)
from apps.prescriptions.models import Prescription
from apps.rbac.permissions import Scope


class CounterSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Till sessions: open one, sell, count the drawer, hand it over."""

    serializer_class = CounterSessionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("sale.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "facility", "counter"]
    ordering_fields = ["opened_at", "closed_at"]

    def get_queryset(self):
        queryset = CounterSession.objects.select_related("facility", "location")
        if self.request.query_params.get("mine") == "true":
            queryset = queryset.filter(cashier_id=self.request.user.uuid)
        return queryset.order_by("-opened_at")

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        """The session this cashier is currently on, if any.

        The till screen calls this on load. Returning 204 rather than an empty
        list makes "no session open" a distinct answer the UI can act on
        without inspecting an array's length.
        """
        session = (
            self.get_queryset()
            .filter(cashier_id=request.user.uuid, status="open")
            .first()
        )
        if session is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(CounterSessionSerializer(session).data)

    @action(detail=False, methods=["post"], url_path="open")
    def open(self, request):
        authorization = get_authorization(request)
        authorization.require("till.open", Scope.FACILITY)

        serializer = OpenSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = open_session(
            organization=request.organization,
            facility=get_object_or_404(Facility, uuid=data["facility"]),
            location=get_object_or_404(StockLocation, uuid=data["location"]),
            counter=data["counter"],
            cashier=request.user,
            opening_float=data["opening_float"],
        )
        return Response(
            CounterSessionSerializer(session).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="takings")
    def takings(self, request, reference=None):
        """What passed through the till, by method.

        Deliberately excludes `expected_cash` unless the caller asks for it:
        showing the cashier the figure they are about to count towards defeats
        the point of counting.
        """
        result = session_takings(self.get_object())
        blind = request.query_params.get("blind") != "false"
        payload = {
            "reference": result["session"].reference,
            "sales_count": result["sales_count"],
            "sales_total": result["sales_total"],
            "cash": result["cash"],
            "card": result["card"],
            "wallet": result["wallet"],
            "credit": result["credit"],
            "by_method": result["by_method"],
        }
        if not blind:
            payload["expected_cash"] = result["expected_cash"]
            payload["opening_float"] = result["session"].opening_float
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("till.open", Scope.FACILITY)

        serializer = CloseSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = close_session(
            self.get_object(),
            closing_count=data["closing_count"],
            actor=request.user,
            variance_reason=data.get("variance_reason", ""),
            notes=data.get("notes", ""),
        )
        return Response(CounterSessionSerializer(session).data)

    @action(detail=True, methods=["post"], url_path="reconcile")
    def reconcile(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("till.reconcile", Scope.FACILITY)

        serializer = ReconcileSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = reconcile_session(
            self.get_object(),
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(CounterSessionSerializer(session).data)


class SaleViewSet(viewsets.ReadOnlyModelViewSet):
    """Counter sales."""

    serializer_class = SaleSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("sale.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "sale_type", "facility", "session"]
    search_fields = ["reference", "invoice_number", "customer_name",
                     "customer_phone"]
    ordering_fields = ["sold_at", "total"]

    def get_queryset(self):
        return (
            Sale.objects.select_related("session", "facility", "patient")
            .prefetch_related("lines__product", "lines__batch")
            .order_by("-sold_at")
        )

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("sale.create", Scope.FACILITY)

        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        items = [
            {
                "product": get_object_or_404(Product, uuid=item["product"]),
                "quantity": item["quantity"],
                "batch": (
                    get_object_or_404(Batch, uuid=item["batch"])
                    if item.get("batch") else None
                ),
                "unit_price": item.get("unit_price"),
                "discount_percent": item.get("discount_percent", 0),
            }
            for item in data["items"]
        ]

        sale = create_sale(
            organization=request.organization,
            session=get_object_or_404(CounterSession, uuid=data["session"]),
            items=items,
            actor=request.user,
            sale_type=data.get("sale_type", "walk_in"),
            patient=(
                get_object_or_404(Patient, uuid=data["patient"])
                if data.get("patient") else None
            ),
            customer_name=data.get("customer_name", ""),
            customer_phone=data.get("customer_phone", ""),
            customer_pan=data.get("customer_pan", ""),
            prescription=(
                get_object_or_404(Prescription, uuid=data["prescription"])
                if data.get("prescription") else None
            ),
            payments=[dict(tender) for tender in data.get("payments", [])],
            notes=data.get("notes", ""),
        )
        sale = self.get_queryset().get(pk=sale.pk)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="quote")
    def quote(self, request):
        """Price the basket without committing it.

        The till calls this on every scan, so it must stay cheap and must
        never write. It also reports shortfalls, which is how the cashier
        learns the shelf is short before the customer has paid.
        """
        serializer = QuoteSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        items = [
            {
                "product": get_object_or_404(Product, uuid=item["product"]),
                "quantity": item["quantity"],
                "batch": (
                    get_object_or_404(Batch, uuid=item["batch"])
                    if item.get("batch") else None
                ),
                "unit_price": item.get("unit_price"),
                "discount_percent": item.get("discount_percent", 0),
            }
            for item in data["items"]
        ]
        return Response(
            quote_sale(
                session=get_object_or_404(CounterSession, uuid=data["session"]),
                items=items,
                sale_type=data.get("sale_type", "walk_in"),
            )
        )

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("sale.void", Scope.FACILITY)

        serializer = VoidSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sale = void_sale(
            self.get_object(),
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(SaleSerializer(sale).data)

    @action(detail=True, methods=["post"], url_path="return")
    def raise_return(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("sale.return", Scope.FACILITY)

        serializer = RequestReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sale = self.get_object()
        entries = [
            {
                "sale_line": get_object_or_404(
                    SaleLine, uuid=entry["sale_line"], sale=sale
                ),
                "quantity": entry["quantity"],
                "condition_note": entry.get("condition_note", ""),
            }
            for entry in data["entries"]
        ]

        sale_return = request_return(
            sale=sale,
            entries=entries,
            reason=data["reason"],
            actor=request.user,
            restock=data.get("restock", True),
            restock_note=data.get("restock_note", ""),
        )
        return Response(
            SaleReturnSerializer(sale_return).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="receipt")
    def receipt(self, request, reference=None):
        """Everything a thermal printer needs, already laid out.

        Composed server-side so a receipt reprinted next month matches the one
        handed over at the time. A client that assembles its own would drift
        the moment the facility's address or the layout changed.
        """
        sale = self.get_object()
        facility = sale.facility
        return Response(
            {
                "facility": {
                    "name": facility.name,
                    "address": getattr(facility, "address", ""),
                    "phone": getattr(facility, "phone", ""),
                    "pan_number": getattr(facility, "pan_number", ""),
                },
                "invoice_number": sale.invoice_number,
                "reference": sale.reference,
                "sold_at": sale.sold_at,
                "cashier": sale.sold_by_name,
                "counter": sale.session.counter,
                "customer": {
                    "name": sale.customer_label,
                    "phone": sale.customer_phone,
                    "pan": sale.customer_pan,
                },
                "lines": [
                    {
                        "name": line.product_name,
                        "batch": line.batch_number,
                        "expires_on": line.expires_on,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "discount": line.discount_amount,
                        "tax": line.tax_amount,
                        "total": line.total,
                    }
                    for line in sale.lines.all()
                ],
                "subtotal": sale.subtotal,
                "discount_total": sale.discount_total,
                "tax_total": sale.tax_total,
                "rounding_adjustment": sale.rounding_adjustment,
                "total": sale.total,
                "status": sale.status,
            }
        )


class SaleReturnViewSet(viewsets.ReadOnlyModelViewSet):
    """Returns awaiting a decision, and those already decided."""

    serializer_class = SaleReturnSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("sale.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "sale"]

    def get_queryset(self):
        queryset = SaleReturn.objects.select_related("sale", "session")
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(status="pending")
        return queryset.prefetch_related("lines__sale_line").order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("sale.return_approve", Scope.FACILITY)

        serializer = DecideReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sale_return = self.get_object()
        if data["approve"]:
            sale_return = approve_return(
                organization=request.organization,
                sale_return=sale_return,
                actor=request.user,
                refund_method=data.get("refund_method", "cash"),
                decision_notes=data.get("decision_notes", ""),
            )
        else:
            sale_return = reject_return(
                sale_return,
                actor=request.user,
                decision_notes=data["decision_notes"],
            )
        return Response(SaleReturnSerializer(sale_return).data)


class CounterSearchView(APIView):
    """Product lookup for the till: barcode, brand, generic or code."""

    permission_classes = [IsAuthenticated, HasPermission.of("sale.read")]

    def get(self, request):
        location = None
        if request.query_params.get("location"):
            location = get_object_or_404(
                StockLocation, uuid=request.query_params["location"]
            )
        results = search_products(
            request.query_params.get("q", ""), location=location
        )
        return Response(
            [
                {
                    "uuid": row["product"].uuid,
                    "code": row["product"].code,
                    "name": row["product"].display_name,
                    "generic_name": row["product"].generic_name,
                    "brand_name": row["product"].brand_name,
                    "dosage_form": row["product"].dosage_form,
                    "base_unit": row["product"].base_unit,
                    "barcode": row["product"].barcode,
                    "available": row["available"],
                    "batch_uuid": (
                        row["batch"].uuid if row["batch"] else None
                    ),
                    "batch_number": (
                        row["batch"].batch_number if row["batch"] else ""
                    ),
                    "expires_on": row["expires_on"],
                    "unit_price": row["unit_price"],
                    "mrp": row["mrp"],
                    "requires_prescription": row["requires_prescription"],
                }
                for row in results
            ]
        )


class SalesSummaryView(APIView):
    """A day at the counter: takings, margin, top sellers."""

    permission_classes = [IsAuthenticated, HasPermission.of("report.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(
            sales_summary(facility, on_date=request.query_params.get("date"))
        )
