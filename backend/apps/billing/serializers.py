"""Serializers for billing."""

from rest_framework import serializers

# UUIDRelatedField: foreign keys are published as the related object's
# uuid, never as the internal integer id. With a database per tenant,
# id 42 is a different row in every tenant -- see apps/common/fields.py.
from apps.common.fields import UUIDRelatedField

from apps.billing.models import (
    Charge,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentMethod,
    PriceList,
    PriceListItem,
    ServiceItem,
)


class ServiceItemSerializer(serializers.ModelSerializer):
    department = UUIDRelatedField(read_only=True)
    effective_tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )

    class Meta:
        model = ServiceItem
        fields = (
            "uuid", "code", "name", "name_nepali", "category", "description",
            "department", "department_name", "default_price", "tax_treatment",
            "tax_rate", "effective_tax_rate", "max_discount_percent",
            "is_recurring_daily", "requires_prescription", "is_active",
            "display_order",
        )
        read_only_fields = ("uuid", "effective_tax_rate", "department_name")


class PriceListItemSerializer(serializers.ModelSerializer):
    service = UUIDRelatedField(read_only=True)
    service_code = serializers.CharField(source="service.code", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = PriceListItem
        fields = (
            "uuid", "service", "service_code", "service_name", "price",
            "discount_percent",
        )
        read_only_fields = ("uuid", "service_code", "service_name")


class PriceListSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    items = PriceListItemSerializer(many=True, read_only=True)
    facility_name = serializers.CharField(
        source="facility.name", read_only=True, default=None
    )

    class Meta:
        model = PriceList
        fields = (
            "uuid", "code", "name", "patient_category", "facility",
            "facility_name", "payer_reference", "effective_from",
            "effective_to", "is_active", "priority", "items",
        )
        read_only_fields = ("uuid", "facility_name")


class ChargeSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    service = UUIDRelatedField(read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    encounter_reference = serializers.CharField(
        source="encounter.reference", read_only=True, default=None
    )
    is_billable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Charge
        fields = (
            "uuid", "patient", "patient_mrn", "patient_name",
            "encounter_reference", "service", "service_code", "service_name",
            "quantity", "unit_price", "discount_percent", "discount_amount",
            "tax_rate", "tax_amount", "total", "price_source", "status",
            "is_billable", "charged_at", "discount_reason", "notes",
        )
        read_only_fields = fields


class CaptureChargeSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    service_uuid = serializers.UUIDField()
    encounter_uuid = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=1
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0
    )
    discount_reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = (
            "uuid", "service_code", "description", "category", "quantity",
            "unit_price", "discount_amount", "tax_rate", "tax_amount",
            "total", "display_order",
        )
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    invoice = UUIDRelatedField(read_only=True)
    is_refund = serializers.BooleanField(read_only=True)
    method_display = serializers.CharField(
        source="get_method_display", read_only=True
    )

    class Meta:
        model = Payment
        fields = (
            "uuid", "receipt_number", "invoice", "amount", "method",
            "method_display", "status", "reference", "counter", "received_at",
            "received_by_name", "is_refund", "refund_reason", "notes",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    patient = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    encounter_reference = serializers.CharField(
        source="encounter.reference", read_only=True, default=None
    )
    balance_due = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    is_settled = serializers.BooleanField(read_only=True)
    credited_by_number = serializers.CharField(
        source="credited_by.number", read_only=True, default=None
    )

    class Meta:
        model = Invoice
        fields = (
            "uuid", "number", "fiscal_year", "patient", "patient_mrn",
            "encounter_reference", "facility", "facility_name",
            "bill_to_name", "bill_to_address", "bill_to_pan",
            "patient_category", "payer_reference", "status", "issued_at",
            "due_date", "subtotal", "discount_total", "tax_total",
            "rounding_adjustment", "total", "amount_paid", "balance_due",
            "is_settled", "currency", "notes", "is_credit_note",
            "credit_reason", "credited_by_number", "lines", "payments",
        )
        read_only_fields = fields


class CreateInvoiceSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    encounter_uuid = serializers.UUIDField(required=False, allow_null=True)
    #: Specific charges to bill. Omitted means every pending charge, which is
    #: what a counter clerk means by "bill this patient".
    charge_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    issue = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RecordPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    counter = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CreditInvoiceSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)


class RefundPaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)
