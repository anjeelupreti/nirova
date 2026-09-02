"""Serializers for the pharmacy."""

from rest_framework import serializers

# UUIDRelatedField: foreign keys go out as the related object's uuid. A client
# that receives `uuid` from one endpoint and an integer id from another cannot
# build a filter out of what it was given -- see apps/common/fields.py.
from apps.common.fields import UUIDRelatedField

from apps.pharmacy.models import (
    Batch,
    BatchStock,
    Dispense,
    DispenseLine,
    MovementType,
    Product,
    StockCount,
    StockCountLine,
    StockEntry,
    StockLocation,
)


class ProductSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    needs_cold_chain = serializers.BooleanField(read_only=True)
    is_controlled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "uuid", "code", "generic_name", "brand_name", "strength",
            "dosage_form", "display_name", "manufacturer",
            "therapeutic_class", "category", "barcode", "base_unit",
            "pack_size", "pack_unit", "storage_condition",
            "needs_cold_chain", "control_schedule", "is_controlled",
            "requires_prescription", "reorder_level", "minimum_stock",
            "maximum_stock", "lead_time_days", "is_formulary", "is_active",
        )
        read_only_fields = (
            "uuid", "display_name", "needs_cold_chain", "is_controlled",
        )


class StockLocationSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    parent = UUIDRelatedField(read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)

    class Meta:
        model = StockLocation
        fields = (
            "uuid", "facility", "facility_name", "department", "parent",
            "code", "name", "location_type", "is_quarantine",
            "is_dispensable", "is_active",
        )
        read_only_fields = ("uuid", "facility_name")


class BatchSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    product_name = serializers.CharField(
        source="product.display_name", read_only=True
    )
    product_code = serializers.CharField(source="product.code", read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_dispensable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Batch
        fields = (
            "uuid", "product", "product_code", "product_name", "batch_number",
            "manufactured_on", "expires_on", "days_to_expiry", "is_expired",
            "is_dispensable", "supplier_name", "receipt_reference",
            "received_on", "purchase_price", "selling_price", "mrp",
            "status", "quarantine_reason", "recall_reference",
        )
        read_only_fields = (
            "uuid", "product_code", "product_name", "days_to_expiry",
            "is_expired", "is_dispensable",
        )


class BatchStockSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    batch = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    product_name = serializers.CharField(
        source="product.display_name", read_only=True
    )
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    expires_on = serializers.DateField(source="batch.expires_on", read_only=True)
    days_to_expiry = serializers.IntegerField(
        source="batch.days_to_expiry", read_only=True
    )
    location_code = serializers.CharField(source="location.code", read_only=True)
    available = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )

    class Meta:
        model = BatchStock
        fields = (
            "uuid", "product", "product_name", "batch", "batch_number",
            "expires_on", "days_to_expiry", "location", "location_code",
            "quantity", "reserved", "available", "last_movement_at",
        )
        read_only_fields = fields


class StockEntrySerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    batch = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    product_name = serializers.CharField(
        source="product.display_name", read_only=True
    )
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    is_inbound = serializers.BooleanField(read_only=True)
    patient_mrn = serializers.CharField(
        source="patient.mrn", read_only=True, default=None
    )

    class Meta:
        model = StockEntry
        fields = (
            "uuid", "product", "product_name", "batch", "batch_number",
            "location", "location_code", "movement_type", "is_inbound",
            "quantity", "balance_after", "unit_cost", "total_cost",
            "occurred_at", "performed_by_name", "reference_type",
            "reference_id", "patient_mrn", "reason", "fefo_overridden",
            "fefo_override_reason",
        )
        read_only_fields = fields


class ReceiveStockSerializer(serializers.Serializer):
    """Book a batch in. Creates the batch if it is new."""

    product_uuid = serializers.UUIDField()
    location_uuid = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=64)
    expires_on = serializers.DateField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    manufactured_on = serializers.DateField(required=False, allow_null=True)
    purchase_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    mrp = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )
    supplier_name = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    receipt_reference = serializers.CharField(
        required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        from django.utils import timezone

        # Receiving stock that is already expired is almost always a typo in
        # the date. Refusing here is cheaper than writing it off tomorrow.
        if attrs["expires_on"] < timezone.localdate():
            raise serializers.ValidationError(
                {"expires_on": "This batch has already expired."}
            )
        if attrs["quantity"] <= 0:
            raise serializers.ValidationError(
                {"quantity": "Receive a positive quantity."}
            )
        return attrs


class DispenseItemSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    #: Naming a batch bypasses FEFO selection and may require an override.
    batch_uuid = serializers.UUIDField(required=False, allow_null=True)
    override_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    prescription_line_uuid = serializers.UUIDField(required=False, allow_null=True)
    is_substitution = serializers.BooleanField(required=False, default=False)
    substitution_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    instructions = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class DispenseCreateSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    location_uuid = serializers.UUIDField()
    items = DispenseItemSerializer(many=True, min_length=1)
    prescription_uuid = serializers.UUIDField(required=False, allow_null=True)
    prescription_reference = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    encounter_uuid = serializers.UUIDField(required=False, allow_null=True)
    counselling_notes = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class DispenseLineSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    batch = UUIDRelatedField(read_only=True)
    class Meta:
        model = DispenseLine
        fields = (
            "uuid", "product", "product_name", "batch", "batch_number",
            "expires_on", "quantity", "unit_price", "total",
            "is_substitution", "substitution_reason", "fefo_overridden",
            "fefo_override_reason", "instructions",
        )
        read_only_fields = fields


class DispenseSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    lines = DispenseLineSerializer(many=True, read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = Dispense
        fields = (
            "uuid", "reference", "patient", "patient_mrn", "patient_name",
            "facility", "location", "location_code", "prescription_uuid",
            "prescription_reference", "status", "dispensed_at",
            "dispensed_by_name", "counselling_notes", "total_value", "lines",
        )
        read_only_fields = fields


class AdjustStockSerializer(serializers.Serializer):
    batch_uuid = serializers.UUIDField()
    location_uuid = serializers.UUIDField()
    movement_type = serializers.ChoiceField(choices=MovementType.choices)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    reason = serializers.CharField(min_length=5)


class QuarantineSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)
    recall_reference = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class StockCountLineSerializer(serializers.ModelSerializer):
    product = UUIDRelatedField(read_only=True)
    batch = UUIDRelatedField(read_only=True)
    product_name = serializers.CharField(
        source="product.display_name", read_only=True
    )
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    variance = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    has_variance = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockCountLine
        fields = (
            "uuid", "product", "product_name", "batch", "batch_number",
            "expected_quantity", "counted_quantity", "recount_quantity",
            "variance", "has_variance", "variance_reason", "is_approved",
        )
        read_only_fields = (
            "uuid", "product_name", "batch_number", "expected_quantity",
            "variance", "has_variance", "is_approved",
        )

    def to_representation(self, instance):
        """Hide the expected quantity during a blind count.

        Showing it produces counts that match expectation rather than
        reality, which is the entire failure mode a blind count exists to
        prevent.
        """
        data = super().to_representation(instance)
        if instance.count.is_blind and instance.count.status == "counting":
            data["expected_quantity"] = None
        return data


class StockCountSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    location = UUIDRelatedField(read_only=True)
    lines = StockCountLineSerializer(many=True, read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = StockCount
        fields = (
            "uuid", "reference", "facility", "location", "location_code",
            "count_type", "is_blind", "status", "started_at", "completed_at",
            "approved_at", "approval_notes", "lines",
        )
        read_only_fields = fields


class StartCountSerializer(serializers.Serializer):
    facility_uuid = serializers.UUIDField()
    location_uuid = serializers.UUIDField()
    count_type = serializers.ChoiceField(
        choices=["full", "cycle", "abc", "spot"], default="cycle"
    )
    is_blind = serializers.BooleanField(default=True)


class RecordCountSerializer(serializers.Serializer):
    lines = serializers.ListField(child=serializers.DictField(), min_length=1)


class ApproveCountSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")
