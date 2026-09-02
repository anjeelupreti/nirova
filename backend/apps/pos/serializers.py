"""Serializers for the counter.

Read serializers expose the derived properties — `returnable_quantity`,
`variance`, `customer_label` — rather than making the client recompute them.
A till screen that recalculates a refund figure will eventually disagree with
the server about it, and the customer is standing there holding the receipt.
"""

from rest_framework import serializers

from apps.pos.models import (
    CounterSession,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
)


class CounterSessionSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    has_variance = serializers.BooleanField(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = CounterSession
        fields = (
            "uuid", "reference", "facility", "facility_name", "location",
            "location_code", "counter", "cashier_id", "cashier_name",
            "status", "opened_at", "closed_at", "opening_float",
            "closing_count", "expected_cash", "variance", "has_variance",
            "variance_reason", "card_total", "wallet_total", "credit_total",
            "reconciled_at", "duration_minutes", "notes",
        )
        read_only_fields = fields


class SaleLineSerializer(serializers.ModelSerializer):
    returnable_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )

    class Meta:
        model = SaleLine
        fields = (
            "uuid", "product", "product_name", "batch", "batch_number",
            "expires_on", "quantity", "returned_quantity",
            "returnable_quantity", "unit_price", "mrp", "discount_percent",
            "discount_amount", "tax_percent", "tax_amount", "total",
        )
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    lines = SaleLineSerializer(many=True, read_only=True)
    customer_label = serializers.CharField(read_only=True)
    is_returnable = serializers.BooleanField(read_only=True)
    session_reference = serializers.CharField(
        source="session.reference", read_only=True
    )

    class Meta:
        model = Sale
        fields = (
            "uuid", "reference", "session", "session_reference", "facility",
            "location", "sale_type", "patient", "customer_label",
            "customer_name", "customer_phone", "customer_pan",
            "prescription_reference", "status", "sold_at", "sold_by_name",
            "subtotal", "discount_total", "tax_total", "rounding_adjustment",
            "total", "invoice_number", "void_reason", "notes", "lines",
        )
        read_only_fields = fields


class SaleReturnLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="sale_line.product_name", read_only=True
    )
    batch_number = serializers.CharField(
        source="sale_line.batch_number", read_only=True
    )

    class Meta:
        model = SaleReturnLine
        fields = (
            "uuid", "sale_line", "product_name", "batch_number", "quantity",
            "refund_amount", "condition_note",
        )
        read_only_fields = fields


class SaleReturnSerializer(serializers.ModelSerializer):
    lines = SaleReturnLineSerializer(many=True, read_only=True)
    sale_reference = serializers.CharField(source="sale.reference", read_only=True)

    class Meta:
        model = SaleReturn
        fields = (
            "uuid", "reference", "sale", "sale_reference", "session",
            "status", "reason", "restock", "restock_note",
            "requested_by_name", "approved_by_name", "approved_at",
            "decision_notes", "refund_total", "refund_method",
            "credit_note_number", "completed_at", "lines",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Write serializers
# ---------------------------------------------------------------------------


class OpenSessionSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    location = serializers.UUIDField()
    counter = serializers.CharField(max_length=32)
    opening_float = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )


class CloseSessionSerializer(serializers.Serializer):
    #: Required, and taken before the expected figure is shown to the cashier.
    #: A blind count is the only kind that can disagree with the system.
    closing_count = serializers.DecimalField(max_digits=12, decimal_places=2)
    variance_reason = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class ReconcileSessionSerializer(serializers.Serializer):
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )


class SaleItemSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    #: Optional. Omitted means FEFO chooses, which is the normal case.
    batch = serializers.UUIDField(required=False, allow_null=True)
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )


class TenderSerializer(serializers.Serializer):
    method = serializers.CharField(max_length=20)
    #: Omit to settle the remaining balance with this method. That is how a
    #: counter actually tenders -- "150 cash, the rest on eSewa" -- and it
    #: spares the client from having to predict a total that is rounded to
    #: the rupee server-side.
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    reference = serializers.CharField(
        max_length=128, required=False, allow_blank=True
    )


class CreateSaleSerializer(serializers.Serializer):
    session = serializers.UUIDField()
    items = SaleItemSerializer(many=True)
    #: Several tenders are allowed: part cash, part wallet is ordinary here.
    payments = TenderSerializer(many=True, required=False)
    sale_type = serializers.CharField(max_length=16, default="walk_in")
    patient = serializers.UUIDField(required=False, allow_null=True)
    prescription = serializers.UUIDField(required=False, allow_null=True)
    customer_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    customer_phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True
    )
    customer_pan = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("A sale needs at least one item.")
        return value


class QuoteSaleSerializer(serializers.Serializer):
    session = serializers.UUIDField()
    items = SaleItemSerializer(many=True)
    sale_type = serializers.CharField(max_length=16, default="walk_in")


class VoidSaleSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)


class ReturnEntrySerializer(serializers.Serializer):
    sale_line = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    condition_note = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class RequestReturnSerializer(serializers.Serializer):
    entries = ReturnEntrySerializer(many=True)
    reason = serializers.CharField(max_length=512)
    restock = serializers.BooleanField(default=True)
    restock_note = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )


class DecideReturnSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    refund_method = serializers.CharField(max_length=20, default="cash")
    decision_notes = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )

    def validate(self, data):
        if not data["approve"] and not data.get("decision_notes", "").strip():
            raise serializers.ValidationError(
                {"decision_notes": "Say why the return was refused."}
            )
        return data
