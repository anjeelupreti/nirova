"""Procurement endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPermission, get_authorization
from apps.organization.models import Department, Facility
from apps.pharmacy.models import Product, StockLocation
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    Quotation,
    RequisitionLine,
    Supplier,
)
from apps.procurement.serializers import (
    CancelOrderSerializer,
    CreateOrderSerializer,
    CreateReceiptSerializer,
    CreateRequisitionSerializer,
    DecideRequisitionSerializer,
    GoodsReceiptSerializer,
    PurchaseOrderSerializer,
    PurchaseRequisitionSerializer,
    QualityCheckSerializer,
    QuotationSerializer,
    RecordQuotationSerializer,
    SupplierSerializer,
)
from apps.procurement.services import (
    approve_order,
    cancel_order,
    compare_quotations,
    create_order,
    create_receipt,
    create_requisition,
    decide_requisition,
    post_receipt,
    procurement_dashboard,
    quality_check,
    record_quotation,
    requisitions_from_reorder,
    submit_requisition,
    supplier_performance,
)
from apps.rbac.permissions import Scope


class SupplierViewSet(viewsets.ModelViewSet):
    """The supplier master."""

    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("purchase.read")]
    lookup_field = "uuid"
    filterset_fields = ["status", "district"]
    search_fields = ["code", "name", "legal_name", "pan_number"]
    ordering_fields = ["name", "code"]

    def get_queryset(self):
        queryset = Supplier.objects.all()
        # A buyer building an order wants the ones they can actually order
        # from, not a list that includes blacklisted vendors.
        if self.request.query_params.get("orderable") == "true":
            queryset = queryset.filter(status="active")
        return queryset.order_by("name")

    def perform_create(self, serializer):
        authorization = get_authorization(self.request)
        authorization.require("supplier.manage", Scope.FACILITY)
        serializer.save(created_by_id=self.request.user.uuid)

    @action(detail=True, methods=["get"], url_path="performance")
    def performance(self, request, uuid=None):
        """What this supplier has actually done, computed from receipts."""
        return Response(supplier_performance(self.get_object()))


class RequisitionViewSet(viewsets.ModelViewSet):
    """Internal requests to buy."""

    serializer_class = PurchaseRequisitionSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("purchase.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "facility", "is_urgent"]
    ordering_fields = ["created_at", "required_by"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = PurchaseRequisition.objects.select_related(
            "facility", "department", "location"
        ).prefetch_related("lines__product")
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(status="submitted")
        return queryset.order_by("-is_urgent", "-created_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("purchase.create", Scope.FACILITY)

        serializer = CreateRequisitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        items = [
            {
                "product": get_object_or_404(Product, uuid=item["product_uuid"]),
                "quantity": item["quantity"],
                "estimated_unit_price": item.get("estimated_unit_price", 0),
                "notes": item.get("notes", ""),
            }
            for item in data["items"]
        ]

        requisition = create_requisition(
            organization=request.organization,
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            items=items,
            actor=request.user,
            department=(
                Department.objects.filter(uuid=data["department_uuid"]).first()
                if data.get("department_uuid")
                else None
            ),
            location=(
                StockLocation.objects.filter(uuid=data["location_uuid"]).first()
                if data.get("location_uuid")
                else None
            ),
            is_urgent=data.get("is_urgent", False),
            required_by=data.get("required_by"),
            justification=data.get("justification", ""),
        )
        requisition = self.get_queryset().get(pk=requisition.pk)
        return Response(
            PurchaseRequisitionSerializer(requisition).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="from-reorder")
    def from_reorder(self, request):
        """Raise a requisition from the reorder suggestions.

        Returns 204 when nothing needs ordering — an empty requisition would
        just be noise in the approval queue.
        """
        authorization = get_authorization(request)
        authorization.require("purchase.create", Scope.FACILITY)

        requisition = requisitions_from_reorder(
            organization=request.organization,
            facility=get_object_or_404(
                Facility, uuid=request.data.get("facility_uuid")
            ),
            location=get_object_or_404(
                StockLocation, uuid=request.data.get("location_uuid")
            ),
            actor=request.user,
        )
        if requisition is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        requisition = self.get_queryset().get(pk=requisition.pk)
        return Response(
            PurchaseRequisitionSerializer(requisition).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, reference=None):
        requisition = submit_requisition(self.get_object(), actor=request.user)
        return Response(PurchaseRequisitionSerializer(requisition).data)

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        """Approve or reject. Refused for the person who raised it."""
        authorization = get_authorization(request)
        authorization.require("purchase.approve", Scope.FACILITY)

        serializer = DecideRequisitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requisition = decide_requisition(
            self.get_object(),
            approve=serializer.validated_data["approve"],
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(PurchaseRequisitionSerializer(requisition).data)

    @action(detail=True, methods=["post"], url_path="quotations")
    def add_quotation(self, request, reference=None):
        """Record what a supplier quoted."""
        authorization = get_authorization(request)
        authorization.require("purchase.create", Scope.FACILITY)

        serializer = RecordQuotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quotation = record_quotation(
            requisition=self.get_object(),
            supplier=get_object_or_404(Supplier, uuid=data["supplier_uuid"]),
            lines=[
                {
                    "product": get_object_or_404(
                        Product, uuid=line["product_uuid"]
                    ),
                    "quantity": line["quantity"],
                    "unit_price": line["unit_price"],
                    "discount_percent": line.get("discount_percent", 0),
                    "tax_percent": line.get("tax_percent", 0),
                    "free_quantity": line.get("free_quantity", 0),
                }
                for line in data["lines"]
            ],
            actor=request.user,
            valid_until=data.get("valid_until"),
            quoted_lead_time_days=data.get("quoted_lead_time_days"),
            payment_terms=data.get("payment_terms", ""),
        )
        return Response(
            QuotationSerializer(quotation).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="compare")
    def compare(self, request, reference=None):
        """Line the quotations up against each other.

        Ranked on effective unit cost, which spreads free quantity across the
        delivery — a dearer headline price with free units can genuinely win.
        """
        return Response(compare_quotations(self.get_object()))


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """Commitments to buy."""

    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("purchase.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "supplier", "facility"]
    ordering_fields = ["ordered_on", "expected_delivery", "total"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = PurchaseOrder.objects.select_related(
            "supplier", "facility", "requisition"
        ).prefetch_related("lines__product")
        params = self.request.query_params
        if params.get("open") == "true":
            queryset = queryset.filter(
                status__in=["approved", "sent", "partially_received"]
            )
        if params.get("awaiting_approval") == "true":
            queryset = queryset.filter(status__in=["draft", "pending_approval"])
        return queryset.order_by("-ordered_on", "-created_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("purchase.create", Scope.FACILITY)

        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # SupplierNotOrderable and QuotationComparisonRequired both surface as
        # 409 with the detail the buyer needs to act on.
        order = create_order(
            organization=request.organization,
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            supplier=get_object_or_404(Supplier, uuid=data["supplier_uuid"]),
            lines=[
                {
                    "product": get_object_or_404(
                        Product, uuid=line["product_uuid"]
                    ),
                    "quantity": line["quantity"],
                    "unit_price": line["unit_price"],
                    "free_quantity": line.get("free_quantity", 0),
                    "discount_percent": line.get("discount_percent", 0),
                    "tax_percent": line.get("tax_percent", 0),
                    "requisition_line": (
                        RequisitionLine.objects.filter(
                            uuid=line["requisition_line_uuid"]
                        ).first()
                        if line.get("requisition_line_uuid")
                        else None
                    ),
                }
                for line in data["lines"]
            ],
            actor=request.user,
            requisition=(
                PurchaseRequisition.objects.filter(
                    uuid=data["requisition_uuid"]
                ).first()
                if data.get("requisition_uuid")
                else None
            ),
            quotation=(
                Quotation.objects.filter(uuid=data["quotation_uuid"]).first()
                if data.get("quotation_uuid")
                else None
            ),
            deliver_to=(
                StockLocation.objects.filter(uuid=data["deliver_to_uuid"]).first()
                if data.get("deliver_to_uuid")
                else None
            ),
            expected_delivery=data.get("expected_delivery"),
            selection_reason=data.get("selection_reason", ""),
            payment_terms=data.get("payment_terms", ""),
            notes=data.get("notes", ""),
        )
        order = self.get_queryset().get(pk=order.pk)
        return Response(
            PurchaseOrderSerializer(order).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, reference=None):
        """Approve the order. Refused for whoever raised it."""
        authorization = get_authorization(request)
        authorization.require("purchase.approve", Scope.FACILITY)

        order = approve_order(self.get_object(), actor=request.user)
        order = self.get_queryset().get(pk=order.pk)
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, reference=None):
        authorization = get_authorization(request)
        authorization.require("purchase.approve", Scope.FACILITY)

        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = cancel_order(
            self.get_object(),
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="receive")
    def receive(self, request, reference=None):
        """Book a delivery in, pending quality check.

        Nothing reaches stock until the receipt is checked and posted.
        """
        authorization = get_authorization(request)
        authorization.require("stock.adjust", Scope.FACILITY)

        serializer = CreateReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        receipt = create_receipt(
            order=self.get_object(),
            location=get_object_or_404(
                StockLocation, uuid=data["location_uuid"]
            ),
            lines=[
                {
                    "product": get_object_or_404(
                        Product, uuid=line["product_uuid"]
                    ),
                    "batch_number": line["batch_number"],
                    "expires_on": line["expires_on"],
                    "manufactured_on": line.get("manufactured_on"),
                    "received_quantity": line["received_quantity"],
                    "free_quantity": line.get("free_quantity", 0),
                    "unit_cost": line["unit_cost"],
                    "selling_price": line.get("selling_price", 0),
                    "mrp": line.get("mrp", 0),
                    "order_line": (
                        PurchaseOrderLine.objects.filter(
                            uuid=line["order_line_uuid"]
                        ).first()
                        if line.get("order_line_uuid")
                        else None
                    ),
                }
                for line in data["lines"]
            ],
            actor=request.user,
            delivery_note_number=data.get("delivery_note_number", ""),
            supplier_invoice_number=data.get("supplier_invoice_number", ""),
            supplier_invoice_amount=data.get("supplier_invoice_amount"),
            notes=data.get("notes", ""),
        )
        return Response(
            GoodsReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED
        )


class GoodsReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    """Deliveries, from arrival through quality check to stock."""

    serializer_class = GoodsReceiptSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("purchase.read")]
    lookup_field = "reference"
    filterset_fields = ["status", "supplier", "facility"]

    def get_queryset(self):
        queryset = GoodsReceipt.objects.select_related(
            "supplier", "order", "location"
        ).prefetch_related("lines__product")
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(
                status__in=["quality_check", "accepted", "partially_rejected"]
            )
        return queryset.order_by("-received_on", "-created_at")

    @action(detail=True, methods=["post"], url_path="quality-check")
    def check(self, request, reference=None):
        """Record what failed inspection. Anything not listed is accepted."""
        authorization = get_authorization(request)
        authorization.require("stock.adjust", Scope.FACILITY)

        serializer = QualityCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = quality_check(
            self.get_object(),
            rejections=[dict(r) for r in serializer.validated_data["rejections"]],
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        receipt = self.get_queryset().get(pk=receipt.pk)
        return Response(GoodsReceiptSerializer(receipt).data)

    @action(detail=True, methods=["post"], url_path="post")
    def post_to_stock(self, request, reference=None):
        """Create the batches and post the stock movements."""
        authorization = get_authorization(request)
        authorization.require("stock.adjust", Scope.FACILITY)
        return Response(post_receipt(self.get_object(), actor=request.user))


class ProcurementDashboardView(APIView):
    """What the buyer needs to see this morning."""

    permission_classes = [IsAuthenticated, HasPermission.of("purchase.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(procurement_dashboard(facility))
