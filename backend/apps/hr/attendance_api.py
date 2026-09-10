"""Serializers and endpoints for shifts, rosters, attendance and leave.

Two access rules, both different from the employee record's.

**Everyone marks their own attendance.** `check_in` and `check_out` need no
permission beyond being signed in and having an employee record. Requiring
`attendance.read` to punch a clock would mean giving every ward attendant
sight of the whole facility's attendance.

**Everyone applies for their own leave, and nobody approves it.**
`leave.approve` gates the decision, and the maker-checker check in the service
layer stops the holder of that permission approving their own request.
"""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.filters import uuid_filterset
from apps.common.permissions import (
    HasPermission,
    get_authorization,
    # Self-service scoping: no grant means your own rows rather than none.
    # Used by the attendance and regularisation lists, both of which are
    # things an employee has a right to see about themselves.
    scope_or_own,
)
from apps.hr.attendance import (
    all_balances,
    apply_for_leave,
    attendance_summary,
    cancel_leave,
    check_in,
    check_out,
    decide_leave,
    decide_regularisation,
    leave_calendar,
    open_leave_year,
    publish_roster,
    request_regularisation,
    roster,
)
from apps.hr.models import (
    Attendance,
    AttendanceRegularisation,
    Employee,
    Holiday,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveType,
    RosterEntry,
    Shift,
)
from apps.organization.models import Facility
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ShiftSerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    duration_hours = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )

    class Meta:
        model = Shift
        fields = (
            "uuid", "code", "name", "shift_type", "facility", "department",
            "starts_at", "ends_at", "crosses_midnight", "duration_hours",
            "break_minutes", "grace_minutes", "half_day_hours",
            "minimum_rest_hours", "is_active", "colour",
        )
        read_only_fields = ("uuid", "duration_hours")


class HolidaySerializer(serializers.ModelSerializer):
    facility = UUIDRelatedField(read_only=True)

    class Meta:
        model = Holiday
        fields = (
            "uuid", "name", "name_nepali", "date", "facility", "is_optional",
            "applies_to", "notes",
        )
        read_only_fields = ("uuid",)


class RosterEntrySerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    shift = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    department = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    shift_code = serializers.CharField(source="shift.code", read_only=True)
    shift_name = serializers.CharField(source="shift.name", read_only=True)
    starts_at = serializers.TimeField(source="shift.starts_at", read_only=True)
    ends_at = serializers.TimeField(source="shift.ends_at", read_only=True)
    colour = serializers.CharField(source="shift.colour", read_only=True)

    class Meta:
        model = RosterEntry
        fields = (
            "uuid", "employee", "employee_code", "employee_name", "shift",
            "shift_code", "shift_name", "starts_at", "ends_at", "colour",
            "date", "facility", "department", "status", "published_at",
            "is_on_call", "notes",
        )
        read_only_fields = fields


class AttendanceSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    facility = UUIDRelatedField(read_only=True)
    roster_entry = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = Attendance
        fields = (
            "uuid", "employee", "employee_code", "employee_name", "date",
            "facility", "roster_entry", "checked_in_at", "checked_out_at",
            "is_complete", "source", "within_geofence", "status",
            "late_minutes", "early_exit_minutes", "worked_hours",
            "overtime_hours", "is_regularised", "notes",
        )
        read_only_fields = fields


class RegularisationSerializer(serializers.ModelSerializer):
    attendance = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="attendance.employee.full_name", read_only=True
    )
    date = serializers.DateField(source="attendance.date", read_only=True)

    class Meta:
        model = AttendanceRegularisation
        fields = (
            "uuid", "attendance", "employee_name", "date",
            "requested_by_name", "original_checked_in_at",
            "original_checked_out_at", "original_status",
            "requested_checked_in_at", "requested_checked_out_at", "reason",
            "status", "decided_by_name", "decided_at", "decision_notes",
        )
        read_only_fields = fields


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = (
            "uuid", "code", "name", "name_nepali", "description",
            "annual_entitlement", "unit", "accrues_monthly", "is_paid",
            "carry_forward", "max_carry_forward", "encashable",
            "requires_document", "document_required_after_days",
            "minimum_notice_days", "maximum_consecutive_days", "eligibility",
            "minimum_service_months", "allow_negative_balance", "is_active",
            "colour",
        )
        read_only_fields = ("uuid",)


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    leave_type = UUIDRelatedField(read_only=True)
    delegate = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    leave_type_name = serializers.CharField(
        source="leave_type.name", read_only=True
    )
    delegate_name = serializers.CharField(
        source="delegate.full_name", read_only=True, default=""
    )
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = (
            "uuid", "reference", "employee", "employee_code", "employee_name",
            "leave_type", "leave_type_name", "starts_on", "ends_on",
            "is_half_day", "calendar_days", "working_days", "reason",
            "contact_during_leave", "delegate", "delegate_name",
            "document_url", "status", "is_open", "applied_at",
            "decided_by_name", "decided_at", "decision_notes",
            "cancellation_reason", "is_unpaid", "leave_year",
        )
        read_only_fields = fields


class LeaveLedgerSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    leave_type = UUIDRelatedField(read_only=True)
    leave_type_name = serializers.CharField(
        source="leave_type.name", read_only=True
    )

    class Meta:
        model = LeaveLedgerEntry
        fields = (
            "uuid", "employee", "leave_type", "leave_type_name", "leave_year",
            "days", "reason", "effective_on", "reference_type",
            "reference_id", "recorded_by_name", "notes",
        )
        read_only_fields = fields


# -- write ------------------------------------------------------------------


class MarkAttendanceSerializer(serializers.Serializer):
    #: Optional. A manager marking somebody else needs it; a person marking
    #: themselves does not, and defaulting to the caller is what makes the
    #: endpoint usable from a wall-mounted tablet.
    employee = serializers.UUIDField(required=False, allow_null=True)
    at = serializers.DateTimeField(required=False)
    source = serializers.CharField(max_length=16, required=False, default="web")
    latitude = serializers.CharField(max_length=32, required=False,
                                     allow_blank=True, default="")
    longitude = serializers.CharField(max_length=32, required=False,
                                      allow_blank=True, default="")
    within_geofence = serializers.BooleanField(required=False, allow_null=True)
    device_reference = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )


class RosterSerializer(serializers.Serializer):
    employee = serializers.UUIDField()
    shift = serializers.UUIDField()
    date = serializers.DateField()
    is_on_call = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(max_length=255, required=False,
                                  allow_blank=True, default="")


class PublishRosterSerializer(serializers.Serializer):
    facility = serializers.UUIDField()
    start = serializers.DateField()
    end = serializers.DateField()


class ApplyLeaveSerializer(serializers.Serializer):
    employee = serializers.UUIDField(required=False, allow_null=True)
    leave_type = serializers.UUIDField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    reason = serializers.CharField(max_length=512)
    is_half_day = serializers.BooleanField(required=False, default=False)
    delegate = serializers.UUIDField(required=False, allow_null=True)
    document_url = serializers.CharField(required=False, allow_blank=True,
                                         default="")
    contact = serializers.CharField(max_length=128, required=False,
                                    allow_blank=True, default="")
    #: Explicit rather than implicit. Taking leave you have not accrued is a
    #: decision with a pay consequence, and it should be made deliberately.
    allow_unpaid = serializers.BooleanField(required=False, default=False)


class DecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(max_length=512, required=False,
                                  allow_blank=True, default="")

    def validate(self, data):
        if not data["approve"] and not data.get("notes", "").strip():
            raise serializers.ValidationError(
                {"notes": "A refusal must say why."}
            )
        return data


class RegulariseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512)
    checked_in_at = serializers.DateTimeField(required=False, allow_null=True)
    checked_out_at = serializers.DateTimeField(required=False, allow_null=True)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _self_or(request, employee_uuid):
    """The named employee, or the caller's own record.

    Defaulting to the caller is what lets one endpoint serve both a person
    marking themselves in and a manager marking somebody else, without the
    client having to look its own employee record up first.
    """
    if employee_uuid:
        return get_object_or_404(Employee, uuid=employee_uuid)
    employee = Employee.for_user(request.user.uuid)
    if employee is None:
        # Written for the person reading it, not for the API client. This
        # fires on the self-service screen for anybody whose login is not
        # linked to an employee -- an administrator, a platform operator, a
        # counter account -- and telling them to "name one explicitly" is
        # advice they cannot act on from a screen with no such field.
        raise serializers.ValidationError(
            {
                "employee": (
                    "Your account is not linked to an employee record, so "
                    "there is nothing here to show. An administrator can "
                    "link it from the staff directory."
                )
            }
        )
    return employee


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer
    permission_classes = [IsAuthenticated, HasPermission.of("employee.read", write="employee.manage")]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Shift, relations=["facility", "department"],
        fields=["shift_type", "is_active"],
    )

    def get_queryset(self):
        return Shift.objects.select_related("facility").order_by("starts_at")

    def perform_create(self, serializer):
        get_authorization(self.request).require("position.manage", Scope.FACILITY)
        serializer.save(created_by_id=self.request.user.uuid)


class HolidayViewSet(viewsets.ModelViewSet):
    serializer_class = HolidaySerializer
    # Read by everybody, changed by few. The holiday calendar decides which
    # days are worked, which decides attendance, which decides pay -- and this
    # viewset carried no permission at all beyond being signed in, so any
    # authenticated user in the tenant could add a public holiday. Found by
    # sending an empty PATCH as eight roles and watching all eight succeed.
    permission_classes = [
        IsAuthenticated,
        HasPermission.of("attendance.read", write="employee.manage"),
    ]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Holiday, relations=["facility"], fields=["is_optional"]
    )

    def get_queryset(self):
        queryset = Holiday.objects.all()
        year = self.request.query_params.get("year")
        if year:
            queryset = queryset.filter(date__year=year)
        return queryset.order_by("date")

    def perform_create(self, serializer):
        get_authorization(self.request).require("config.read", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)


class RosterViewSet(viewsets.ReadOnlyModelViewSet):
    """Who is on which shift."""

    serializer_class = RosterEntrySerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        RosterEntry, relations=["employee", "facility", "shift"],
        fields=["status", "date", "is_on_call"],
    )

    def get_queryset(self):
        queryset = RosterEntry.objects.select_related(
            "employee", "shift", "facility"
        )
        start = self.request.query_params.get("from")
        end = self.request.query_params.get("to")
        if start:
            queryset = queryset.filter(date__gte=start)
        if end:
            queryset = queryset.filter(date__lte=end)
        if self.request.query_params.get("mine") == "true":
            employee = Employee.for_user(self.request.user.uuid)
            queryset = queryset.filter(employee=employee) if employee else (
                queryset.none()
            )
        return queryset.order_by("date", "shift__starts_at")

    def create(self, request, *args, **kwargs):
        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = RosterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = roster(
            employee=get_object_or_404(Employee, uuid=data["employee"]),
            shift=get_object_or_404(Shift, uuid=data["shift"]),
            date=data["date"],
            actor=request.user,
            is_on_call=data.get("is_on_call", False),
            notes=data.get("notes", ""),
        )
        return Response(
            RosterEntrySerializer(entry).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="publish")
    def publish(self, request):
        get_authorization(request).require("employee.manage", Scope.FACILITY)
        serializer = PublishRosterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            publish_roster(
                get_object_or_404(Facility, uuid=data["facility"]),
                data["start"], data["end"], actor=request.user,
            )
        )


class AttendanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AttendanceSerializer
    # Authenticated, not `attendance.read`. Seeing your own attendance is not
    # the same question as seeing the facility's, and `scope_or_own` below is
    # what keeps them apart: no grant means your own rows, not everybody's.
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    filterset_class = uuid_filterset(
        Attendance, relations=["employee", "facility"],
        fields=["status", "date", "is_regularised"],
    )

    def get_queryset(self):
        queryset = Attendance.objects.select_related("employee", "facility")
        start = self.request.query_params.get("from")
        end = self.request.query_params.get("to")
        if start:
            queryset = queryset.filter(date__gte=start)
        if end:
            queryset = queryset.filter(date__lte=end)

        # Scope filter: Scope.OWN, *and* holding nothing, see only their own.
        queryset = scope_or_own(
            queryset, self.request, "attendance.read", employee_attr="employee"
        )

        # `?mine=true` narrows to the caller even when they could see more --
        # the self-service screen asks for it explicitly so that a manager
        # opening their own timesheet is not handed the whole ward's.
        if self.request.query_params.get("mine") == "true":
            employee = Employee.for_user(self.request.user.uuid)
            queryset = (
                queryset.filter(employee=employee) if employee
                else queryset.none()
            )

        return queryset.order_by("-date", "employee__first_name")

    # -- marking, which needs no permission beyond having a record ----------

    @action(
        detail=False, methods=["get", "post"], url_path="me",
        permission_classes=[IsAuthenticated],
    )
    def me(self, request):
        """Your own attendance: today's on GET, a check-in on POST.

        Deliberately outside `attendance.read`. Requiring permission to punch
        a clock would mean giving every ward attendant sight of the whole
        facility's attendance.
        """
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        if request.method == "GET":
            days = int(request.query_params.get("days", 30))
            rows = Attendance.objects.filter(
                employee=employee,
                date__gte=timezone.localdate() - timedelta(days=days),
            ).select_related("employee", "facility").order_by("-date")
            return Response(AttendanceSerializer(rows, many=True).data)

        serializer = MarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = check_in(
            employee,
            actor=request.user,
            at=data.get("at"),
            source=data.get("source", "web"),
            latitude=data.get("latitude", ""),
            longitude=data.get("longitude", ""),
            within_geofence=data.get("within_geofence"),
            device_reference=data.get("device_reference", ""),
        )
        return Response(AttendanceSerializer(record).data)

    @action(
        detail=False, methods=["post"], url_path="check-in",
        permission_classes=[IsAuthenticated],
    )
    def mark_in(self, request):
        serializer = MarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("employee"):
            get_authorization(request).require("attendance.read", Scope.FACILITY)
        record = check_in(
            _self_or(request, data.get("employee")),
            actor=request.user,
            at=data.get("at"),
            source=data.get("source", "web"),
            latitude=data.get("latitude", ""),
            longitude=data.get("longitude", ""),
            within_geofence=data.get("within_geofence"),
            device_reference=data.get("device_reference", ""),
        )
        return Response(AttendanceSerializer(record).data)

    @action(
        detail=False, methods=["post"], url_path="check-out",
        permission_classes=[IsAuthenticated],
    )
    def mark_out(self, request):
        serializer = MarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("employee"):
            get_authorization(request).require("attendance.read", Scope.FACILITY)
        record = check_out(
            _self_or(request, data.get("employee")),
            actor=request.user,
            at=data.get("at"),
        )
        return Response(AttendanceSerializer(record).data)

    @action(detail=True, methods=["post"], url_path="regularise")
    def regularise(self, request, uuid=None):
        serializer = RegulariseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        correction = request_regularisation(
            self.get_object(),
            actor=request.user,
            reason=data["reason"],
            checked_in_at=data.get("checked_in_at"),
            checked_out_at=data.get("checked_out_at"),
        )
        return Response(
            RegularisationSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )


class RegularisationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RegularisationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"

    def get_queryset(self):
        queryset = AttendanceRegularisation.objects.select_related(
            "attendance", "attendance__employee"
        )

        # This viewset had no scope filter at all: `attendance.read` at
        # Scope.OWN -- the grant the `staff` role hands every employee --
        # returned every correction request in the organization, reason text
        # included ("hospital visit", "child's surgery"). The permission was
        # checked and then ignored. A leak of exactly the kind that survives
        # because the list looks plausible when an admin opens it.
        queryset = scope_or_own(
            queryset,
            self.request,
            "attendance.read",
            employee_attr="attendance__employee",
            facility_attr="attendance__facility",
        )

        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(status="pending")
        return queryset.order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, uuid=None):
        get_authorization(request).require("leave.approve", Scope.FACILITY)
        serializer = DecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correction = decide_regularisation(
            self.get_object(),
            actor=request.user,
            approve=serializer.validated_data["approve"],
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(RegularisationSerializer(correction).data)


class LeaveTypeViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveTypeSerializer
    # Readable by anybody signed in; writable only with `employee.manage`.
    #
    # It used to require `attendance.read` to read, which made the *reference
    # list you need in order to request leave* depend on the permission to
    # read everybody's attendance. A doctor could open the leave form and find
    # the "type" dropdown empty, with a 403 behind it. Leave types are a
    # published policy -- the entitlement and whether it is paid is on the
    # notice board -- so there is nothing here to withhold from staff.
    permission_classes = [
        IsAuthenticated,
        HasPermission.of(None, write="employee.manage"),
    ]
    lookup_field = "code"

    def get_queryset(self):
        return LeaveType.objects.filter(is_active=True).order_by(
            "display_order", "name"
        )

    def perform_create(self, serializer):
        get_authorization(self.request).require("config.read", Scope.ORGANIZATION)
        serializer.save(created_by_id=self.request.user.uuid)


class LeaveRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "reference"
    filterset_class = uuid_filterset(
        LeaveRequest, relations=["employee", "leave_type"],
        fields=["status", "is_unpaid", "leave_year"],
    )

    def get_queryset(self):
        queryset = LeaveRequest.objects.select_related(
            "employee", "leave_type", "delegate"
        )
        # Somebody without `employee.read` sees only their own requests. This
        # is a filter rather than a refusal: the endpoint is useful to
        # everybody, and scoping it is what makes that safe.
        if not get_authorization(self.request).has(
            "employee.read", Scope.FACILITY
        ):
            employee = Employee.for_user(self.request.user.uuid)
            queryset = queryset.filter(employee=employee) if employee else (
                queryset.none()
            )
        if self.request.query_params.get("pending") == "true":
            queryset = queryset.filter(status="pending")
        if self.request.query_params.get("mine") == "true":
            employee = Employee.for_user(self.request.user.uuid)
            queryset = queryset.filter(employee=employee) if employee else (
                queryset.none()
            )
        return queryset.order_by("-starts_on")

    def create(self, request, *args, **kwargs):
        serializer = ApplyLeaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Applying on somebody else's behalf is a manager action; applying for
        # yourself is not.
        if data.get("employee"):
            get_authorization(request).require("employee.manage", Scope.FACILITY)

        leave_request = apply_for_leave(
            employee=_self_or(request, data.get("employee")),
            leave_type=get_object_or_404(LeaveType, uuid=data["leave_type"]),
            starts_on=data["starts_on"],
            ends_on=data["ends_on"],
            reason=data["reason"],
            actor=request.user,
            is_half_day=data.get("is_half_day", False),
            delegate=(
                get_object_or_404(Employee, uuid=data["delegate"])
                if data.get("delegate") else None
            ),
            document_url=data.get("document_url", ""),
            contact=data.get("contact", ""),
            allow_unpaid=data.get("allow_unpaid", False),
        )
        return Response(
            LeaveRequestSerializer(leave_request).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, reference=None):
        get_authorization(request).require("leave.approve", Scope.FACILITY)
        serializer = DecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        leave_request = decide_leave(
            self.get_object(),
            actor=request.user,
            approve=serializer.validated_data["approve"],
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(LeaveRequestSerializer(leave_request).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, reference=None):
        leave_request = self.get_object()
        # You may cancel your own; cancelling somebody else's needs authority.
        employee = Employee.for_user(request.user.uuid)
        if employee is None or leave_request.employee_id != employee.pk:
            get_authorization(request).require("leave.approve", Scope.FACILITY)
        leave_request = cancel_leave(
            leave_request,
            actor=request.user,
            reason=request.data.get("reason", ""),
        )
        return Response(LeaveRequestSerializer(leave_request).data)


class LeaveBalanceView(APIView):
    """What somebody has left, per leave type."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        named = request.query_params.get("employee")
        if named:
            get_authorization(request).require("employee.read", Scope.FACILITY)
            employee = _self_or(request, named)
        else:
            # **A read answers emptily rather than failing.** This used to go
            # through `_self_or`, which raises a 400 for a caller with no
            # employee record -- an owner, an administrator, a platform
            # operator. The Time screen loads four endpoints with
            # `Promise.all`, so that one 400 rejected the lot and the whole
            # screen failed for exactly the people who are not employees. They
            # were not asking for their own balance; they were opening a page.
            #
            # 200 with a null employee rather than 204, because the reason is
            # worth carrying: the screen can say why the card is empty instead
            # of leaving a blank. Matches `/hr/attendance/me/` and
            # `/payroll/payslips/mine/`, which both answer emptily for the
            # same caller. POST still refuses -- a write genuinely cannot
            # proceed without knowing whose leave year to open.
            employee = Employee.for_user(request.user.uuid)
            if employee is None:
                return Response(
                    {
                        "employee": None,
                        "employee_name": "",
                        "balances": [],
                        "detail": (
                            "Your account is not linked to an employee "
                            "record, so you have no leave balance. An "
                            "administrator can link it from the staff "
                            "directory."
                        ),
                    }
                )

        # The permission check above deliberately precedes `_self_or`: asking
        # for somebody else's balance by uuid should be refused for lacking
        # the permission, not answered with 404 for a uuid that does not
        # exist. The old order let a caller probe which employee uuids are
        # real by reading the difference between 404 and 403.
        return Response(
            {
                "employee": employee.employee_code,
                "employee_name": employee.full_name,
                "balances": all_balances(
                    employee, request.query_params.get("year")
                ),
            }
        )

    def post(self, request):
        """Grant a leave year's entitlement. Idempotent."""
        get_authorization(request).require("employee.manage", Scope.FACILITY)
        employee = _self_or(request, request.data.get("employee"))
        granted = open_leave_year(
            employee, actor=request.user, year=request.data.get("year")
        )
        return Response(
            {
                "granted": len(granted),
                "balances": all_balances(employee),
            }
        )


class LeaveLedgerView(APIView):
    """Every movement behind a balance.

    Exists because an employee disputing their balance is asking *why*, and a
    single number cannot answer that.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # The same shape as `LeaveBalanceView`, and it had the same two faults:
        # a *read* that raised 400 for a caller with no employee record, and a
        # permission check that ran after the lookup so the gap between 404 and
        # 403 revealed which employee uuids are real. Fixed here too rather than
        # left as the one that got away -- log 256 fixed the balance and this
        # sits four hundred lines below it.
        named = request.query_params.get("employee")
        if named:
            get_authorization(request).require("employee.read", Scope.FACILITY)
            employee = _self_or(request, named)
        else:
            employee = Employee.for_user(request.user.uuid)
            if employee is None:
                # An empty *list*, not an object: this endpoint answers with a
                # bare array and the screen renders it directly. An empty
                # answer of a different shape is a different bug.
                return Response([])

        entries = LeaveLedgerEntry.objects.filter(
            employee=employee
        ).select_related("leave_type")
        if request.query_params.get("year"):
            entries = entries.filter(leave_year=request.query_params["year"])
        return Response(
            LeaveLedgerSerializer(entries.order_by("-effective_on"), many=True).data
        )


class LeaveCalendarView(APIView):
    """Who is away across a facility, and when."""

    permission_classes = [IsAuthenticated, HasPermission.of("employee.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        start = request.query_params.get("from") or timezone.localdate()
        end = request.query_params.get("to") or (
            timezone.localdate() + timedelta(days=60)
        )
        return Response(leave_calendar(facility, start, end))


class AttendanceSummaryView(APIView):
    permission_classes = [IsAuthenticated, HasPermission.of("attendance.read")]

    def get(self, request):
        facility = get_object_or_404(
            Facility, uuid=request.query_params.get("facility")
        )
        end = request.query_params.get("to") or timezone.localdate()
        start = request.query_params.get("from") or (
            timezone.localdate() - timedelta(days=30)
        )
        return Response(attendance_summary(facility, start, end))
