"""Pharmacy endpoints."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.filters import uuid_filterset
from apps.common.permissions import HasPermission, get_authorization
from apps.organization.models import Facility
from apps.patients.models import Patient
from apps.pharmacy.models import (
    Batch,
    BatchStock,
    Dispense,
    MovementType,
    Product,
    StockCount,
    StockCountStatus,
    StockEntry,
    StockLocation,
)
from apps.pharmacy.serializers import (
    AdjustStockSerializer,
    ApproveCountSerializer,
    BatchSerializer,
    BatchStockSerializer,
    DispenseCreateSerializer,
    DispenseSerializer,
    ProductSerializer,
    QuarantineSerializer,
    ReceiveStockSerializer,
    RecordCountSerializer,
    StartCountSerializer,
    StockCountSerializer,
    StockEntrySerializer,
    StockLocationSerializer,
)
from apps.pharmacy.services import (
    allocate_fefo,
    approve_count,
    dispense as dispense_service,
    expiring_stock,
    post_movement,
    quarantine_batch,
    rebuild_stock_cache,
    recall_exposure,
    reorder_suggestions,
    start_count,
    stock_valuation,
)
from apps.rbac.permissions import Scope


class ProductViewSet(viewsets.ModelViewSet):
    """The product master."""

    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]
    lookup_field = "uuid"
    filterset_fields = ["category", "control_schedule", "is_active", "is_formulary"]
    search_fields = ["code", "generic_name", "brand_name", "barcode"]
    ordering_fields = ["generic_name", "code"]

    def get_queryset(self):
        return Product.objects.order_by("generic_name", "brand_name")

    @action(detail=True, methods=["get"], url_path="stock")
    def stock(self, request, uuid=None):
        """Where this product is, batch by batch, earliest expiry first.

        The order matters: it is the order the batches will actually be
        dispensed in, so the list doubles as a picking sequence.
        """
        product = self.get_object()
        levels = (
            BatchStock.objects.filter(product=product, quantity__gt=0)
            .select_related("batch", "location")
            .order_by("batch__expires_on")
        )
        return Response(
            {
                "product": product.display_name,
                "total": sum(level.quantity for level in levels),
                "batches": BatchStockSerializer(levels, many=True).data,
            }
        )


class StockLocationViewSet(viewsets.ModelViewSet):
    serializer_class = StockLocationSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]
    lookup_field = "uuid"
    # Filters match on uuid because that is the identifier the API publishes.
    filterset_class = uuid_filterset(
        StockLocation, relations=["facility"],
        fields=["location_type", "is_active"],
    )

    def get_queryset(self):
        return StockLocation.objects.select_related("facility").order_by("code")


class BatchViewSet(viewsets.ReadOnlyModelViewSet):
    """Batches. Created by receiving stock, never directly."""

    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Batch, relations=["product"], fields=["status"]
    )
    ordering_fields = ["expires_on", "received_on"]

    def get_queryset(self):
        queryset = Batch.objects.select_related("product")
        if self.request.query_params.get("expiring") == "true":
            queryset = queryset.filter(
                expires_on__lte=timezone.localdate() + timezone.timedelta(days=180)
            )
        return queryset.order_by("expires_on")

    @action(detail=True, methods=["post"], url_path="quarantine")
    def quarantine(self, request, uuid=None):
        """Take a batch out of circulation without moving it."""
        authorization = get_authorization(request)
        authorization.require("stock.adjust", Scope.FACILITY)

        serializer = QuarantineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = quarantine_batch(
            self.get_object(),
            reason=serializer.validated_data["reason"],
            actor=request.user,
            recall_reference=serializer.validated_data.get("recall_reference", ""),
        )
        return Response(BatchSerializer(batch).data)

    @action(detail=True, methods=["get"], url_path="exposure")
    def exposure(self, request, uuid=None):
        """Who received stock from this batch, and what is left.

        The question a recall asks. Answerable only because the ledger records
        the patient on every dispensing movement.
        """
        return Response(recall_exposure(self.get_object()))


class StockView(APIView):
    """Receive stock into a location."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.adjust")]

    def post(self, request):
        serializer = ReceiveStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product = get_object_or_404(Product, uuid=data["product_uuid"])
        location = get_object_or_404(StockLocation, uuid=data["location_uuid"])

        # A batch is identified by product, number and expiry together: the
        # same number from a different manufacturer run is a different batch.
        batch, _ = Batch.objects.get_or_create(
            product=product,
            batch_number=data["batch_number"],
            expires_on=data["expires_on"],
            defaults={
                "manufactured_on": data.get("manufactured_on"),
                "purchase_price": data.get("purchase_price", 0),
                "selling_price": data.get("selling_price", 0),
                "mrp": data.get("mrp", 0),
                "supplier_name": data.get("supplier_name", ""),
                "receipt_reference": data.get("receipt_reference", ""),
                "created_by_id": request.user.uuid,
            },
        )

        entry = post_movement(
            batch=batch,
            location=location,
            movement_type=MovementType.PURCHASE,
            quantity=data["quantity"],
            actor=request.user,
            reason=f"Received from {data.get('supplier_name') or 'supplier'}",
            reference_type="goods_receipt",
            reference_id=data.get("receipt_reference", ""),
        )
        return Response(
            {
                "batch": BatchSerializer(batch).data,
                "entry": StockEntrySerializer(entry).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StockLevelView(APIView):
    """Current stock at a location, or for a product."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]

    def get(self, request):
        queryset = BatchStock.objects.filter(quantity__gt=0).select_related(
            "batch", "product", "location"
        )
        if request.query_params.get("location"):
            queryset = queryset.filter(location__uuid=request.query_params["location"])
        if request.query_params.get("product"):
            queryset = queryset.filter(product__uuid=request.query_params["product"])

        queryset = queryset.order_by("product__generic_name", "batch__expires_on")
        return Response(
            {
                "count": queryset.count(),
                "levels": BatchStockSerializer(queryset[:500], many=True).data,
            }
        )


class StockLedgerView(APIView):
    """The movement ledger — the source of truth for stock."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]

    def get(self, request):
        queryset = StockEntry.objects.select_related(
            "product", "batch", "location", "patient"
        )
        params = request.query_params
        if params.get("product"):
            queryset = queryset.filter(product__uuid=params["product"])
        if params.get("batch"):
            queryset = queryset.filter(batch__uuid=params["batch"])
        if params.get("location"):
            queryset = queryset.filter(location__uuid=params["location"])
        if params.get("movement_type"):
            queryset = queryset.filter(movement_type=params["movement_type"])

        queryset = queryset.order_by("-occurred_at")[:200]
        return Response(
            {"entries": StockEntrySerializer(queryset, many=True).data}
        )


class AdjustStockView(APIView):
    """Post a manual stock movement.

    Every adjustment needs a reason, and every one is audited at
    `STOCK_ADJUST`. Adjustments are how stock discrepancies get buried, so
    they are made deliberately visible.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("stock.adjust")]

    def post(self, request):
        serializer = AdjustStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = post_movement(
            batch=get_object_or_404(Batch, uuid=data["batch_uuid"]),
            location=get_object_or_404(StockLocation, uuid=data["location_uuid"]),
            movement_type=data["movement_type"],
            quantity=data["quantity"],
            actor=request.user,
            reason=data["reason"],
        )
        return Response(
            StockEntrySerializer(entry).data, status=status.HTTP_201_CREATED
        )


class DispenseViewSet(viewsets.ModelViewSet):
    """Dispense medicines, taking stock FEFO."""

    serializer_class = DispenseSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]
    lookup_field = "uuid"
    filterset_fields = ["status", "facility", "location"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Dispense.objects.select_related(
            "patient", "location"
        ).prefetch_related("lines")
        if self.request.query_params.get("patient"):
            queryset = queryset.filter(
                patient__uuid=self.request.query_params["patient"]
            )
        if self.request.query_params.get("prescription"):
            queryset = queryset.filter(
                prescription_uuid=self.request.query_params["prescription"]
            )
        return queryset.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("prescription.dispense", Scope.FACILITY)

        serializer = DispenseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        items = []
        for entry in data["items"]:
            items.append(
                {
                    "product": get_object_or_404(
                        Product, uuid=entry["product_uuid"]
                    ),
                    "quantity": entry["quantity"],
                    "batch": (
                        Batch.objects.filter(uuid=entry["batch_uuid"]).first()
                        if entry.get("batch_uuid")
                        else None
                    ),
                    "override_reason": entry.get("override_reason", ""),
                    "prescription_line_uuid": entry.get("prescription_line_uuid"),
                    "is_substitution": entry.get("is_substitution", False),
                    "substitution_reason": entry.get("substitution_reason", ""),
                    "instructions": entry.get("instructions", ""),
                }
            )

        # InsufficientStock and FefoOverrideRequired both come back as 409
        # with the detail the pharmacist needs to decide what to do.
        result = dispense_service(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            location=get_object_or_404(StockLocation, uuid=data["location_uuid"]),
            items=items,
            actor=request.user,
            prescription_uuid=data.get("prescription_uuid"),
            prescription_reference=data.get("prescription_reference", ""),
            encounter_uuid=data.get("encounter_uuid"),
            counselling_notes=data.get("counselling_notes", ""),
            approved_by=request.user,
        )
        result = self.get_queryset().get(pk=result.pk)
        return Response(
            DispenseSerializer(result).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["get"], url_path="allocate")
    def allocate(self, request):
        """Preview which batches a quantity would come from. Changes nothing.

        Lets a counter show the patient what they are getting, and lets the
        UI warn about a FEFO override before the pharmacist commits.
        """
        product = get_object_or_404(
            Product, uuid=request.query_params.get("product")
        )
        location = get_object_or_404(
            StockLocation, uuid=request.query_params.get("location")
        )
        quantity = request.query_params.get("quantity", "1")
        preferred = (
            Batch.objects.filter(uuid=request.query_params["batch"]).first()
            if request.query_params.get("batch")
            else None
        )

        result = allocate_fefo(product, location, quantity, preferred_batch=preferred)
        return Response(
            {
                "product": product.display_name,
                "requested": quantity,
                "allocated": str(result["allocated"]),
                "shortfall": str(result["shortfall"]),
                "breaks_fefo": result["breaks_fefo"],
                "earliest_batch": (
                    result["earliest_batch"].batch_number
                    if result["earliest_batch"]
                    else None
                ),
                "allocation": [
                    {
                        "batch_uuid": str(row["batch"].uuid),
                        "batch_number": row["batch"].batch_number,
                        "expires_on": row["batch"].expires_on,
                        "quantity": str(row["quantity"]),
                        "unit_price": str(row["batch"].selling_price),
                    }
                    for row in result["allocation"]
                ],
            }
        )


class ExpiringStockView(APIView):
    """Batches approaching expiry, bucketed so action can be taken in time."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]

    def get(self, request):
        location = (
            StockLocation.objects.filter(
                uuid=request.query_params["location"]
            ).first()
            if request.query_params.get("location")
            else None
        )
        within = int(request.query_params.get("days", 180))
        rows = expiring_stock(location, within_days=within)

        buckets: dict[str, list] = {}
        for row in rows:
            buckets.setdefault(row["bucket"], []).append(row)

        return Response(
            {
                "within_days": within,
                "count": len(rows),
                "total_value_at_cost": sum(row["value_at_cost"] for row in rows),
                "by_bucket": {
                    bucket: {
                        "count": len(items),
                        "value": sum(item["value_at_cost"] for item in items),
                        "items": items,
                    }
                    for bucket, items in buckets.items()
                },
            }
        )


class ReorderView(APIView):
    """Products at or below reorder level, most urgent first."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]

    def get(self, request):
        location = (
            StockLocation.objects.filter(
                uuid=request.query_params["location"]
            ).first()
            if request.query_params.get("location")
            else None
        )
        suggestions = reorder_suggestions(location)
        return Response(
            {
                "count": len(suggestions),
                "urgent": sum(
                    1 for row in suggestions if row["stockout_before_delivery"]
                ),
                "suggestions": suggestions,
            }
        )


class ValuationView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("stock.read")]

    def get(self, request):
        location = (
            StockLocation.objects.filter(
                uuid=request.query_params["location"]
            ).first()
            if request.query_params.get("location")
            else None
        )
        return Response(stock_valuation(location))


class ReconcileView(APIView):
    """Rebuild the cached balances from the ledger and report any drift."""

    permission_classes = [IsAuthenticated, HasPermission.of("stock.adjust")]

    def post(self, request):
        return Response(rebuild_stock_cache())


class StockCountViewSet(viewsets.ModelViewSet):
    """Physical counts, and the variances they find."""

    serializer_class = StockCountSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("stock.count")]
    lookup_field = "uuid"
    filterset_fields = ["status", "location", "count_type"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            StockCount.objects.select_related("location")
            .prefetch_related("lines__product", "lines__batch")
            .order_by("-started_at")
        )

    def create(self, request, *args, **kwargs):
        serializer = StartCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        count = start_count(
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            location=get_object_or_404(StockLocation, uuid=data["location_uuid"]),
            actor=request.user,
            count_type=data["count_type"],
            is_blind=data["is_blind"],
        )
        count = self.get_queryset().get(pk=count.pk)
        return Response(
            StockCountSerializer(count).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="record")
    def record_counts(self, request, uuid=None):
        """Record counted quantities and move to variance review."""
        count = self.get_object()
        serializer = RecordCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        by_uuid = {str(line.uuid): line for line in count.lines.all()}
        for entry in serializer.validated_data["lines"]:
            line = by_uuid.get(str(entry.get("line_uuid")))
            if line is None:
                continue
            if "counted_quantity" in entry:
                line.counted_quantity = entry["counted_quantity"]
            if "recount_quantity" in entry:
                line.recount_quantity = entry["recount_quantity"]
            if "variance_reason" in entry:
                line.variance_reason = entry["variance_reason"]
            line.save(
                update_fields=[
                    "counted_quantity", "recount_quantity",
                    "variance_reason", "updated_at",
                ]
            )

        count.status = StockCountStatus.REVIEW
        count.completed_at = timezone.now()
        count.save(update_fields=["status", "completed_at", "updated_at"])
        count = self.get_queryset().get(pk=count.pk)
        return Response(StockCountSerializer(count).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, uuid=None):
        """Approve the variances and post the adjustments.

        Refused if the caller did the counting — a count that adjusts itself
        is a blank cheque.
        """
        authorization = get_authorization(request)
        authorization.require("stock.approve_adjustment", Scope.FACILITY)

        serializer = ApproveCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = approve_count(
            self.get_object(),
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(result)
