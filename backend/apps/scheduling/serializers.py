"""Serializers for appointments and the queue."""

from rest_framework import serializers

from apps.scheduling.models import (
    Appointment,
    AppointmentSource,
    ProviderSchedule,
    QueueToken,
)


class ProviderScheduleSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    total_slots = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProviderSchedule
        fields = (
            "uuid", "provider_uuid", "provider_name", "provider_speciality",
            "facility", "facility_name", "department", "department_name",
            "room", "weekday", "start_time", "end_time", "slot_minutes",
            "slot_capacity", "walk_in_reserve", "effective_from",
            "effective_to", "is_accepting_online", "consultation_fee",
            "is_active", "total_slots",
        )
        read_only_fields = ("uuid", "total_slots", "facility_name", "department_name")


class AppointmentSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )
    waiting_minutes = serializers.IntegerField(read_only=True)
    consultation_minutes = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "uuid", "reference", "patient", "patient_mrn", "patient_name",
            "patient_phone", "facility", "facility_name", "department",
            "department_name", "provider_uuid", "provider_name",
            "scheduled_for", "duration_minutes", "status", "source", "reason",
            "priority", "is_follow_up", "arrived_at",
            "consultation_started_at", "consultation_ended_at",
            "cancelled_at", "cancellation_reason", "waiting_minutes",
            "consultation_minutes", "is_overdue", "notes", "created_at",
        )
        read_only_fields = (
            "uuid", "reference", "status", "arrived_at",
            "consultation_started_at", "consultation_ended_at", "cancelled_at",
            "waiting_minutes", "consultation_minutes", "is_overdue",
        )


class AppointmentBookingSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    scheduled_for = serializers.DateTimeField()
    schedule_uuid = serializers.UUIDField(required=False, allow_null=True)
    department_uuid = serializers.UUIDField(required=False, allow_null=True)
    provider_uuid = serializers.UUIDField(required=False, allow_null=True)
    provider_name = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.ChoiceField(
        choices=AppointmentSource.choices, default=AppointmentSource.COUNTER
    )
    priority = serializers.IntegerField(required=False, default=0, min_value=0)
    is_follow_up = serializers.BooleanField(required=False, default=False)


class AppointmentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class QueueTokenSerializer(serializers.ModelSerializer):
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )
    waiting_minutes = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = QueueToken
        fields = (
            "uuid", "token_number", "queue_date", "patient", "patient_mrn",
            "patient_name", "appointment", "facility", "department",
            "department_name", "provider_uuid", "counter", "status",
            "priority", "is_emergency", "issued_at", "called_at",
            "service_started_at", "completed_at", "call_count",
            "waiting_minutes", "is_active", "notes",
        )
        read_only_fields = (
            "uuid", "token_number", "queue_date", "issued_at", "called_at",
            "service_started_at", "completed_at", "call_count",
            "waiting_minutes", "is_active",
        )


class IssueTokenSerializer(serializers.Serializer):
    patient_uuid = serializers.UUIDField()
    facility_uuid = serializers.UUIDField()
    department_uuid = serializers.UUIDField(required=False, allow_null=True)
    appointment_uuid = serializers.UUIDField(required=False, allow_null=True)
    provider_uuid = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=0, min_value=0)
    is_emergency = serializers.BooleanField(required=False, default=False)
