"""Appointment and queue endpoints."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.filters import uuid_filterset
from apps.common.permissions import apply_scope_filter, HasPermission, get_authorization
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.rbac.permissions import Scope
from apps.scheduling.models import (
    Appointment,
    ProviderSchedule,
    QueueToken,
)
from apps.scheduling.serializers import (
    AppointmentBookingSerializer,
    AppointmentCancelSerializer,
    AppointmentSerializer,
    IssueTokenSerializer,
    ProviderScheduleSerializer,
    QueueTokenSerializer,
)
from apps.scheduling.services import (
    available_slots,
    book_appointment,
    call_next,
    cancel_appointment,
    complete_service,
    issue_token,
    mark_no_show,
    provider_day_view,
    queue_for,
    queue_statistics,
    recall_or_skip,
    start_service,
)


class ProviderScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ProviderScheduleSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("facility.read")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        ProviderSchedule, relations=['facility', 'department'], fields=['weekday', 'is_active']
    )

    def get_queryset(self):
        return ProviderSchedule.objects.select_related(
            "facility", "department"
        ).order_by("weekday", "start_time")

    @action(detail=True, methods=["get"], url_path="slots")
    def slots(self, request, uuid=None):
        """Free slots on a date. Defaults to today."""
        schedule = self.get_object()
        on_date = request.query_params.get("date")
        target = (
            timezone.datetime.fromisoformat(on_date).date()
            if on_date
            else timezone.localdate()
        )
        for_online = request.query_params.get("online") == "true"
        slots = available_slots(schedule, target, for_online=for_online)
        return Response(
            {
                "date": target.isoformat(),
                "provider_name": schedule.provider_name,
                "slot_minutes": schedule.slot_minutes,
                "free_slots": [slot.isoformat() for slot in slots],
                "count": len(slots),
            }
        )


class AvailabilityView(APIView):
    """Every session at a facility on one date, with free-slot counts.

    The screen a receptionist looks at when a patient asks "when can I see a
    doctor?" — so it answers for the whole facility in one call rather than
    one provider at a time.
    """

    permission_classes = [IsAuthenticated, HasPermission.of("facility.read")]

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
        return Response(
            {
                "facility": facility.name,
                "date": target.isoformat(),
                "sessions": provider_day_view(
                    facility, target, request.query_params.get("provider")
                ),
            }
        )


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Appointment, relations=['facility', 'department'], fields=['status', 'provider_uuid', 'source']
    )
    ordering_fields = ["scheduled_for", "created_at"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        # Narrowed by scope, added when the permission floor was lowered to
        # Scope.OWN. Before that the check refused every department-scoped
        # clinician outright, so there was nothing to narrow; loosening the
        # check without adding this would have widened a department-scoped
        # user to every appointment in the organization.
        queryset = apply_scope_filter(
            Appointment.objects.select_related(
                "patient", "facility", "department"
            ),
            self.request,
            "encounter.read",
        )

        # Default to today unless a date range is asked for. An unfiltered
        # appointment list grows without bound and is never what anyone wants.
        params = self.request.query_params
        if self.action == "list" and not any(
            key in params for key in ("date", "date_from", "date_to", "patient")
        ):
            queryset = queryset.filter(scheduled_for__date=timezone.localdate())

        if params.get("date"):
            queryset = queryset.filter(scheduled_for__date=params["date"])
        if params.get("date_from"):
            queryset = queryset.filter(scheduled_for__date__gte=params["date_from"])
        if params.get("date_to"):
            queryset = queryset.filter(scheduled_for__date__lte=params["date_to"])
        if params.get("patient"):
            queryset = queryset.filter(patient__uuid=params["patient"])

        return queryset.order_by("scheduled_for")

    def create(self, request, *args, **kwargs):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = AppointmentBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        appointment = book_appointment(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            scheduled_for=data["scheduled_for"],
            schedule=(
                ProviderSchedule.objects.filter(uuid=data["schedule_uuid"]).first()
                if data.get("schedule_uuid")
                else None
            ),
            department=(
                Department.objects.filter(uuid=data["department_uuid"]).first()
                if data.get("department_uuid")
                else None
            ),
            provider_uuid=data.get("provider_uuid"),
            provider_name=data.get("provider_name", ""),
            reason=data.get("reason", ""),
            source=data["source"],
            priority=data.get("priority", 0),
            is_follow_up=data.get("is_follow_up", False),
            actor=request.user,
        )
        return Response(
            AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = AppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = cancel_appointment(
            self.get_object(), request.user, serializer.validated_data["reason"]
        )
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, uuid=None):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)
        appointment = mark_no_show(self.get_object(), request.user)
        return Response(AppointmentSerializer(appointment).data)


class QueueViewSet(viewsets.ReadOnlyModelViewSet):
    """The live queue and the actions that move it along."""

    serializer_class = QueueTokenSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("encounter.read", scope=Scope.OWN)]
    lookup_field = "uuid"

    def get_queryset(self):
        return QueueToken.objects.select_related(
            "patient", "department", "appointment"
        ).filter(queue_date=timezone.localdate())

    def list(self, request, *args, **kwargs):
        """The queue in the order patients will actually be seen."""
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        department = (
            Department.objects.filter(uuid=request.query_params["department"]).first()
            if request.query_params.get("department")
            else None
        )
        tokens = queue_for(
            facility, department, request.query_params.get("provider")
        )
        return Response(
            {
                "facility": facility.name,
                "statistics": queue_statistics(facility),
                "queue": QueueTokenSerializer(tokens, many=True).data,
            }
        )

    @action(detail=False, methods=["post"], url_path="issue")
    def issue(self, request):
        authorization = get_authorization(request)
        authorization.require("encounter.create", Scope.FACILITY)

        serializer = IssueTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        token = issue_token(
            organization=request.organization,
            patient=get_object_or_404(Patient, uuid=data["patient_uuid"]),
            facility=get_object_or_404(Facility, uuid=data["facility_uuid"]),
            department=(
                Department.objects.filter(uuid=data["department_uuid"]).first()
                if data.get("department_uuid")
                else None
            ),
            appointment=(
                Appointment.objects.filter(uuid=data["appointment_uuid"]).first()
                if data.get("appointment_uuid")
                else None
            ),
            provider_uuid=data.get("provider_uuid"),
            priority=data.get("priority", 0),
            is_emergency=data.get("is_emergency", False),
            actor=request.user,
        )
        return Response(
            QueueTokenSerializer(token).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="call-next")
    def call_next_patient(self, request):
        """Call the next waiting patient, or report an empty queue."""
        facility = get_object_or_404(Facility, uuid=request.data.get("facility_uuid"))
        department = (
            Department.objects.filter(uuid=request.data["department_uuid"]).first()
            if request.data.get("department_uuid")
            else None
        )
        token = call_next(
            facility,
            department,
            request.data.get("provider_uuid"),
            counter=request.data.get("counter", ""),
            actor=request.user,
        )
        if token is None:
            return Response({"queue_empty": True, "token": None})
        return Response({"queue_empty": False, "token": QueueTokenSerializer(token).data})

    @action(detail=True, methods=["post"], url_path="recall")
    def recall(self, request, uuid=None):
        token = recall_or_skip(self.get_object(), actor=request.user)
        return Response(QueueTokenSerializer(token).data)

    @action(detail=True, methods=["post"], url_path="start")
    def start(self, request, uuid=None):
        token = start_service(self.get_object(), actor=request.user)
        return Response(QueueTokenSerializer(token).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, uuid=None):
        token = complete_service(self.get_object(), actor=request.user)
        return Response(QueueTokenSerializer(token).data)

    @action(detail=False, methods=["get"], url_path="statistics")
    def statistics(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        return Response(queue_statistics(facility))
