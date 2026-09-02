"""Serializers for procurement."""

from rest_framework import serializers

# UUIDRelatedField: foreign keys go out as the related object's uuid, never as
# the internal integer id — see apps/common/fields.py. A client that receives
# a uuid from one endpoint cannot filter with it on another otherwise.
from apps.common.fields import UUIDRelatedField

from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    Quotation,
    QuotationLine,
    ReceiptLine,
    RequisitionLine,
    Supplier,
)


class SupplierSerializer(serializers.ModelSerializer):
    can_order_from = serializers.BooleanField(read_only=True)
    licence_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Supplier
        fields = (
            "uuid", "code", "name", "legal_name", "pan_number", "vat_number",
            "contact_person", "phone", "email", "address", "district",
            "agreed_lead_time_days", "credit_days", "credit_limit",
            "product_categories", "drug_licence_number",
            "drug_licence_expires_on", "licence_expired", "status",
            "status_reason", "can_order_from", "bank_name", "notes",
        )
        read_only_fields = ("uuid", "can_order_from", "licence_expired")


class RequisitionLineSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    outstanding_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    is_fully_ordered = serializers.BooleanField(read_only=True)

    class Meta:
        model = RequisitionLine
        fields = (
            "uuid", "product", "product_name", "quantity", "ordered_quantity",
            "outstanding_quantity", "is_fully_ordered",
            "estimated_unit_price", "stock_on_hand", "reorder_level", "notes",
        )
        read_only_fields = fields


class PurchaseRequisitionSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    lines = RequisitionLineSerializer(many=True, read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = PurchaseRequisition
        fields = (
            "uuid", "reference", "facility", "facility_name", "department",
            "location", "status", "is_open", "is_urgent", "required_by",
            "justification", "raised_automatically", "requested_by_name",
            "submitted_at", "approved_by_name", "approved_at",
            "decision_notes", "estimated_value", "lines", "created_at",
        )
        read_only_fields = fields


class RequisitionItemSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    estimated_unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CreateRequisitionSerializer(serializers.Serializer):
    facility_uuid = serializers.UUIDField()
    location_uuid = serializers.UUIDField(required=False, allow_null=True)
    department_uuid = serializers.UUIDField(required=False, allow_null=True)
    items = RequisitionItemSerializer(many=True, min_length=1)
    is_urgent = serializers.BooleanField(required=False, default=False)
    required_by = serializers.DateField(required=False, allow_null=True)
    justification = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        # An urgent requisition jumps the approval queue, so it has to say
        # why. Mirrors the same rule on diagnostic orders.
        if attrs.get("is_urgent") and not attrs.get("justification", "").strip():
            raise serializers.ValidationError(
                {"justification": "An urgent requisition must say why."}
            )
        return attrs


class DecideRequisitionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class QuotationLineSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    effective_unit_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = QuotationLine
        fields = (
            "uuid", "product", "product_name", "quantity", "unit_price",
            "discount_percent", "tax_percent", "free_quantity",
            "effective_unit_cost", "total",
        )
        read_only_fields = fields


class QuotationSerializer(serializers.ModelSerializer):
    requisition = UUIDRelatedField(read_only=True)
    supplier = UUIDRelatedField(read_only=True)
    lines = QuotationLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quotation
        fields = (
            "uuid", "reference", "requisition", "supplier", "supplier_name",
            "status", "requested_at", "received_at", "valid_until",
            "is_expired", "total_value", "quoted_lead_time_days",
            "payment_terms", "selection_reason", "notes", "lines",
        )
        read_only_fields = fields


class QuotationLineInputSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )
    tax_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )
    #: Suppliers here commonly give free units instead of a discount.
    free_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, required=False, default=0
    )


class RecordQuotationSerializer(serializers.Serializer):
    supplier_uuid = serializers.UUIDField()
    lines = QuotationLineInputSerializer(many=True, min_length=1)
    valid_until = serializers.DateField(required=False, allow_null=True)
    quoted_lead_time_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    payment_terms = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    outstanding_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = (
            "uuid", "product", "product_code", "product_name", "quantity",
            "free_quantity", "received_quantity", "rejected_quantity",
            "outstanding_quantity", "is_complete", "unit_price",
            "discount_percent", "tax_percent", "line_total",
        )
        read_only_fields = fields


class PurchaseOrderSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    supplier = UUIDRelatedField(read_only=True)
    requisition = UUIDRelatedField(read_only=True)
    quotation = UUIDRelatedField(read_only=True)
    deliver_to = UUIDRelatedField(read_only=True)
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    requisition_reference = serializers.CharField(
        source="requisition.reference", read_only=True, default=None
    )
    is_open = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_late = serializers.IntegerField(read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "uuid", "reference", "facility", "facility_name", "supplier",
            "supplier_name", "requisition", "requisition_reference",
            "quotation", "deliver_to", "status", "is_open", "is_overdue",
            "days_late", "ordered_on", "expected_delivery", "subtotal",
            "discount_total", "tax_total", "total", "currency",
            "created_by_name", "approved_by_name", "approved_at",
            "payment_terms", "delivery_terms", "notes", "lines",
        )
        read_only_fields = fields


class OrderLineInputSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    free_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, required=False, default=0
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )
    tax_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )
    requisition_line_uuid = serializers.UUIDField(required=False, allow_null=True)


class CreateOrderSerializer(serializers.Serializer):
    facility_uuid = serializers.UUIDField()
    supplier_uuid = serializers.UUIDField()
    lines = OrderLineInputSerializer(many=True, min_length=1)
    requisition_uuid = serializers.UUIDField(required=False, allow_null=True)
    quotation_uuid = serializers.UUIDField(required=False, allow_null=True)
    deliver_to_uuid = serializers.UUIDField(required=False, allow_null=True)
    expected_delivery = serializers.DateField(required=False, allow_null=True)
    #: Required by the service layer when the chosen quotation is dearer than
    #: the cheapest eligible one.
    selection_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    payment_terms = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ReceiptLineSerializer(serializers.ModelSerializer):
    batch = UUIDRelatedField(read_only=True)
    product = UUIDRelatedField(read_only=True)
    total_units = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    effective_unit_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = ReceiptLine
        fields = (
            "uuid", "product", "product_name", "batch_number",
            "manufactured_on", "expires_on", "received_quantity",
            "free_quantity", "total_units", "accepted_quantity",
            "rejected_quantity", "rejection_reason", "unit_cost",
            "effective_unit_cost", "selling_price", "mrp", "line_total",
            "batch",
        )
        read_only_fields = fields


class GoodsReceiptSerializer(serializers.ModelSerializer):
    order = UUIDRelatedField(read_only=True)
    supplier = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    lines = ReceiptLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    is_posted = serializers.BooleanField(read_only=True)
    invoice_matches = serializers.BooleanField(read_only=True, allow_null=True)

    class Meta:
        model = GoodsReceipt
        fields = (
            "uuid", "reference", "order", "order_reference", "supplier",
            "supplier_name", "facility", "location", "location_code",
            "status", "is_posted", "received_on", "received_by_name",
            "delivery_note_number", "supplier_invoice_number",
            "supplier_invoice_date", "supplier_invoice_amount",
            "invoice_matches", "quality_checked_at", "quality_notes",
            "posted_at", "total_value", "notes", "lines",
        )
        read_only_fields = fields


class ReceiptLineInputSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=64)
    expires_on = serializers.DateField()
    received_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    manufactured_on = serializers.DateField(required=False, allow_null=True)
    free_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, required=False, default=0
    )
    selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    mrp = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    order_line_uuid = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        from django.utils import timezone

        # An expired batch on a goods receipt is nearly always a mistyped
        # date. Catching it here is cheaper than writing it off tomorrow.
        if attrs["expires_on"] <= timezone.localdate():
            raise serializers.ValidationError(
                {"expires_on": "This batch has already expired."}
            )
        return attrs


class CreateReceiptSerializer(serializers.Serializer):
    location_uuid = serializers.UUIDField()
    lines = ReceiptLineInputSerializer(many=True, min_length=1)
    delivery_note_number = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    supplier_invoice_number = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    supplier_invoice_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RejectionSerializer(serializers.Serializer):
    line_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    reason = serializers.CharField(min_length=3)


class QualityCheckSerializer(serializers.Serializer):
    #: Only exceptions are listed; anything absent is accepted.
    rejections = RejectionSerializer(many=True, required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)
