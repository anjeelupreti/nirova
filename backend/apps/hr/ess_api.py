"""Employee Self-Service (ESS) and Manager Worklist Endpoints.

Implements Phase 5 §95:
- Combined summary for an employee (profile, credentials, today's attendance, balances, upcoming shifts)
- Profile correction proposals (contact details, bank account) that require sign-off
- Peer-to-peer shift swaps requiring colleague acceptance and manager approval
- Unified manager approval queue combining leave, regularisations, swaps, and profile changes
"""

from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import UUIDRelatedField
from apps.common.permissions import get_authorization
from apps.hr.attendance import (
    all_balances,
    cancel_shift_swap,
    manager_decide_shift_swap,
    peer_decide_shift_swap,
    request_shift_swap,
)
from apps.hr.attendance_models import (
    Attendance,
    AttendanceRegularisation,
    AttendanceStatus,
    LeaveRequest,
    RosterEntry,
    RosterStatus,
    ShiftSwapRequest,
    ShiftSwapStatus,
)
from apps.hr.models import (
    WORKING_STATUSES,
    Employee,
    ProfileCorrectionRequest,
    ProfileCorrectionStatus,
)
from apps.hr.serializers import CredentialSerializer, EmployeeDetailSerializer
from apps.hr.services import (
    cancel_profile_correction,
    decide_profile_correction,
    request_profile_correction,
    team_of,
)
from apps.rbac.permissions import Scope

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ProfileCorrectionSerializer(serializers.ModelSerializer):
    employee = UUIDRelatedField(read_only=True)
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True
    )
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    department_name = serializers.CharField(
        source="employee.department.name", read_only=True, default=""
    )

    class Meta:
        model = ProfileCorrectionRequest
        fields = (
            "uuid",
            "employee",
            "employee_code",
            "employee_name",
            "department_name",
            "requested_by_user_id",
            "fields_payload",
            "reason",
            "status",
            "decided_by_name",
            "decided_at",
            "decision_notes",
            "created_at",
        )
        read_only_fields = fields


class CreateProfileCorrectionSerializer(serializers.Serializer):
    fields_payload = serializers.DictField()
    reason = serializers.CharField(max_length=512)


class DecideProfileCorrectionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")

    def validate(self, data):
        if not data["approve"] and not data.get("notes", "").strip():
            raise serializers.ValidationError({"notes": "A refusal must state a reason."})
        return data


class ShiftSwapSerializer(serializers.ModelSerializer):
    requester = UUIDRelatedField(read_only=True)
    requester_code = serializers.CharField(
        source="requester.employee_code", read_only=True
    )
    requester_name = serializers.CharField(
        source="requester.full_name", read_only=True
    )
    target_employee = UUIDRelatedField(read_only=True)
    target_code = serializers.CharField(
        source="target_employee.employee_code", read_only=True
    )
    target_name = serializers.CharField(
        source="target_employee.full_name", read_only=True
    )

    requester_entry_date = serializers.DateField(
        source="requester_entry.date", read_only=True
    )
    requester_shift_code = serializers.CharField(
        source="requester_entry.shift.code", read_only=True
    )
    requester_shift_name = serializers.CharField(
        source="requester_entry.shift.name", read_only=True
    )
    requester_starts_at = serializers.TimeField(
        source="requester_entry.shift.starts_at", read_only=True
    )
    requester_ends_at = serializers.TimeField(
        source="requester_entry.shift.ends_at", read_only=True
    )

    target_entry_date = serializers.DateField(
        source="target_entry.date", read_only=True, allow_null=True
    )
    target_shift_code = serializers.CharField(
        source="target_entry.shift.code", read_only=True, allow_null=True
    )
    target_shift_name = serializers.CharField(
        source="target_entry.shift.name", read_only=True, allow_null=True
    )

    class Meta:
        model = ShiftSwapRequest
        fields = (
            "uuid",
            "requester",
            "requester_code",
            "requester_name",
            "target_employee",
            "target_code",
            "target_name",
            "requester_entry",
            "requester_entry_date",
            "requester_shift_code",
            "requester_shift_name",
            "requester_starts_at",
            "requester_ends_at",
            "target_entry",
            "target_entry_date",
            "target_shift_code",
            "target_shift_name",
            "reason",
            "status",
            "peer_notes",
            "peer_decided_at",
            "manager_name",
            "manager_notes",
            "manager_decided_at",
            "created_at",
        )
        read_only_fields = fields


class CreateShiftSwapSerializer(serializers.Serializer):
    requester_entry = serializers.UUIDField()
    target_employee = serializers.UUIDField()
    target_entry = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=512)


class DecideSwapSerializer(serializers.Serializer):
    accept = serializers.BooleanField(required=False)
    approve = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class ESSMeSummaryView(APIView):
    """Aggregated self-service profile and status in a single call."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        today = timezone.localdate()
        today_attendance = Attendance.objects.filter(
            employee=employee, date=today
        ).first()

        upcoming_shifts = RosterEntry.objects.filter(
            employee=employee,
            date__gte=today,
            date__lte=today + timedelta(days=14),
            status=RosterStatus.PUBLISHED,
        ).select_related("shift").order_by("date", "shift__starts_at")

        balances = all_balances(employee)

        credentials = employee.credentials.all()
        cred_data = []
        for c in credentials:
            days = c.days_to_expiry
            status_tag = "valid"
            if c.is_expired:
                status_tag = "expired"
            elif days is not None and days <= 90:
                status_tag = "expiring_soon"
            cred_data.append(
                {
                    "uuid": str(c.uuid),
                    "name": c.name,
                    # `reference_number` on the model. The wrong name
                    # here crashed every call to this endpoint, and
                    # nothing noticed because no test drove it.
                    "registration_number": c.reference_number,
                    "issuing_body": c.issuing_body,
                    "expires_on": c.expires_on,
                    "days_to_expiry": days,
                    "is_expired": c.is_expired,
                    "status_tag": status_tag,
                    "verified_at": c.verified_at,
                    "blocks_practice": c.blocks_practice,
                }
            )

        pending_incoming_swaps = ShiftSwapRequest.objects.filter(
            target_employee=employee, status=ShiftSwapStatus.PENDING_PEER
        ).count()

        pending_corrections = ProfileCorrectionRequest.objects.filter(
            employee=employee, status=ProfileCorrectionStatus.PENDING
        ).count()

        is_manager = Employee.objects.filter(
            reports_to=employee, status__in=WORKING_STATUSES
        ).exists()

        return Response(
            {
                "employee": {
                    "uuid": str(employee.uuid),
                    "code": employee.employee_code,
                    "full_name": employee.full_name,
                    "first_name": employee.first_name,
                    "last_name": employee.last_name,
                    "position": (
                        employee.position.title if employee.position else ""
                    ),
                    "department": (
                        employee.department.name if employee.department else ""
                    ),
                    "facility": employee.facility.name,
                    "facility_uuid": str(employee.facility.uuid),
                    "reports_to": (
                        employee.reports_to.full_name
                        if employee.reports_to else ""
                    ),
                    "joined_on": employee.joined_on,
                    "employment_type": employee.get_employment_type_display(),
                    "phone": employee.phone,
                    "personal_email": employee.personal_email,
                    "work_email": employee.work_email,
                    "address": employee.address,
                    "province": employee.province,
                    "district": employee.district,
                    "municipality": employee.municipality,
                    "citizenship_number": employee.citizenship_number,
                    "pan_number": employee.pan_number,
                    "blood_group": employee.blood_group,
                    "bank_name": employee.bank_name,
                    "bank_account_number": employee.bank_account_number,
                    "bank_branch": employee.bank_branch,
                    "emergency_contact_name": employee.emergency_contact_name,
                    "emergency_contact_phone": employee.emergency_contact_phone,
                    "emergency_contact_relation": (
                        employee.emergency_contact_relation
                    ),
                    "is_clinical": employee.is_clinical,
                    "is_provider": employee.is_provider,
                },
                "attendance_today": (
                    {
                        "uuid": str(today_attendance.uuid),
                        "status": today_attendance.status,
                        "checked_in_at": today_attendance.checked_in_at,
                        "checked_out_at": today_attendance.checked_out_at,
                        "late_minutes": today_attendance.late_minutes,
                        "early_exit_minutes": today_attendance.early_exit_minutes,
                        "worked_hours": str(today_attendance.worked_hours),
                    }
                    if today_attendance
                    else None
                ),
                # `leave_balance` returns the type's *code* and *name* as
                # strings, not the object -- this read them as if they were a
                # `LeaveType` and crashed. Third field-shape mistake in one
                # endpoint, all of the same kind: written against what the
                # data was assumed to look like rather than what it is, and
                # never once called.
                "leave_balances": [
                    {
                        "code": b["leave_type"],
                        "name": b["leave_type_name"],
                        "balance": str(b["balance"]),
                        "available": str(b["available"]),
                        "annual_entitlement": str(b["entitlement"]),
                    }
                    for b in balances
                ],
                "upcoming_shifts": [
                    {
                        "uuid": str(s.uuid),
                        "date": s.date,
                        "shift_name": s.shift.name,
                        "shift_code": s.shift.code,
                        "starts_at": s.shift.starts_at,
                        "ends_at": s.shift.ends_at,
                        "colour": s.shift.colour,
                        "is_on_call": s.is_on_call,
                    }
                    for s in upcoming_shifts
                ],
                "credentials": cred_data,
                "pending_incoming_swaps": pending_incoming_swaps,
                "pending_corrections": pending_corrections,
                "is_manager": is_manager,
            }
        )


class ProfileCorrectionViewSet(viewsets.ReadOnlyModelViewSet):
    """View and submit profile change requests."""

    serializer_class = ProfileCorrectionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"

    def get_queryset(self):
        employee = Employee.for_user(self.request.user.uuid)
        if employee is None:
            return ProfileCorrectionRequest.objects.none()

        auth = get_authorization(self.request)
        if auth and (
            auth.is_organization_owner
            or auth.has("employee.manage", Scope.FACILITY)
        ):
            queryset = ProfileCorrectionRequest.objects.select_related(
                "employee", "employee__department"
            )
        else:
            queryset = ProfileCorrectionRequest.objects.filter(
                employee=employee
            ).select_related("employee", "employee__department")

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(
                {"detail": "No employee record linked to current user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreateProfileCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        correction = request_profile_correction(
            employee=employee,
            fields_payload=data["fields_payload"],
            reason=data["reason"],
            actor=request.user,
        )
        return Response(
            ProfileCorrectionSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, uuid=None):
        correction = self.get_object()
        cancelled = cancel_profile_correction(correction, actor=request.user)
        return Response(ProfileCorrectionSerializer(cancelled).data)

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(self, request, uuid=None):
        auth = get_authorization(request)
        if not auth or (
            not auth.is_organization_owner
            and not auth.has("employee.manage", Scope.FACILITY)
            and not auth.has("leave.approve", Scope.FACILITY)
        ):
            return Response(
                {"detail": "Authority to approve profile requests required."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DecideProfileCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        correction = decide_profile_correction(
            self.get_object(),
            actor=request.user,
            approve=data["approve"],
            notes=data.get("notes", ""),
        )
        return Response(ProfileCorrectionSerializer(correction).data)


class ShiftSwapViewSet(viewsets.ReadOnlyModelViewSet):
    """Peer shift swap requests and peer/manager decisions."""

    serializer_class = ShiftSwapSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"

    def get_queryset(self):
        employee = Employee.for_user(self.request.user.uuid)
        if employee is None:
            return ShiftSwapRequest.objects.none()

        auth = get_authorization(self.request)
        if auth and (
            auth.is_organization_owner
            or auth.has("leave.approve", Scope.FACILITY)
        ):
            queryset = ShiftSwapRequest.objects.select_related(
                "requester",
                "target_employee",
                "requester_entry",
                "requester_entry__shift",
                "target_entry",
                "target_entry__shift",
            )
        else:
            queryset = ShiftSwapRequest.objects.filter(
                models.Q(requester=employee) | models.Q(target_employee=employee)
            ).select_related(
                "requester",
                "target_employee",
                "requester_entry",
                "requester_entry__shift",
                "target_entry",
                "target_entry__shift",
            )

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        employee = Employee.for_user(request.user.uuid)
        if employee is None:
            return Response(
                {"detail": "No employee record linked to current user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreateShiftSwapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        req_entry = get_object_or_404(
            RosterEntry, uuid=data["requester_entry"], employee=employee
        )
        target_emp = get_object_or_404(
            Employee, uuid=data["target_employee"]
        )
        target_entry = (
            get_object_or_404(RosterEntry, uuid=data["target_entry"])
            if data.get("target_entry")
            else None
        )

        swap = request_shift_swap(
            requester_entry=req_entry,
            target_employee=target_emp,
            target_entry=target_entry,
            reason=data["reason"],
            actor=request.user,
        )
        return Response(
            ShiftSwapSerializer(swap).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="peer-decide")
    def peer_decide(self, request, uuid=None):
        serializer = DecideSwapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accept = serializer.validated_data.get(
            "accept", serializer.validated_data.get("approve", False)
        )
        notes = serializer.validated_data.get("notes", "")

        swap = peer_decide_shift_swap(
            self.get_object(), actor=request.user, accept=accept, notes=notes
        )
        return Response(ShiftSwapSerializer(swap).data)

    @action(detail=True, methods=["post"], url_path="manager-decide")
    def manager_decide(self, request, uuid=None):
        auth = get_authorization(request)
        if not auth or (
            not auth.is_organization_owner
            and not auth.has("leave.approve", Scope.FACILITY)
            and not auth.has("employee.manage", Scope.FACILITY)
        ):
            return Response(
                {"detail": "Authority to approve shift swaps required."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DecideSwapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approve = serializer.validated_data.get(
            "approve", serializer.validated_data.get("accept", False)
        )
        notes = serializer.validated_data.get("notes", "")

        swap = manager_decide_shift_swap(
            self.get_object(), actor=request.user, approve=approve, notes=notes
        )
        return Response(ShiftSwapSerializer(swap).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, uuid=None):
        swap = self.get_object()
        cancelled = cancel_shift_swap(swap, actor=request.user)
        return Response(ShiftSwapSerializer(cancelled).data)


class ManagerQueueView(APIView):
    """Unified worklist for team managers.

    Combines leave requests, attendance regularisations, shift swaps,
    and profile corrections for team members into one approval hub.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        caller = Employee.for_user(request.user.uuid)
        auth = get_authorization(request)

        team_members = []
        if caller:
            team_members = team_of(caller)

        is_broad = bool(
            auth
            and (
                auth.is_organization_owner
                or auth.has("leave.approve", Scope.FACILITY)
                or auth.has("employee.manage", Scope.FACILITY)
            )
        )

        if not team_members and not is_broad:
            return Response(
                {
                    "is_manager": False,
                    "summary": {
                        "pending_total": 0,
                        "leave_count": 0,
                        "regularisation_count": 0,
                        "swap_count": 0,
                        "correction_count": 0,
                    },
                    "team_status_today": [],
                    "items": [],
                }
            )

        if team_members and not is_broad:
            member_ids = [m.pk for m in team_members]
            leave_qs = LeaveRequest.objects.filter(
                employee_id__in=member_ids, status="pending"
            )
            reg_qs = AttendanceRegularisation.objects.filter(
                attendance__employee_id__in=member_ids, status="pending"
            )
            swap_qs = ShiftSwapRequest.objects.filter(
                requester_id__in=member_ids, status=ShiftSwapStatus.PENDING_MANAGER
            )
            corr_qs = ProfileCorrectionRequest.objects.filter(
                employee_id__in=member_ids,
                status=ProfileCorrectionStatus.PENDING,
            )
            tracked_members = team_members
        else:
            leave_qs = LeaveRequest.objects.filter(status="pending")
            reg_qs = AttendanceRegularisation.objects.filter(status="pending")
            swap_qs = ShiftSwapRequest.objects.filter(
                status=ShiftSwapStatus.PENDING_MANAGER
            )
            corr_qs = ProfileCorrectionRequest.objects.filter(
                status=ProfileCorrectionStatus.PENDING
            )
            tracked_members = team_members or list(
                Employee.objects.filter(status__in=WORKING_STATUSES)[:50]
            )

        items = []

        for l in leave_qs.select_related("employee", "leave_type"):
            items.append(
                {
                    "id": str(l.uuid),
                    "reference": l.reference,
                    "type": "leave",
                    "type_label": "Leave Request",
                    "employee_code": l.employee.employee_code,
                    "employee_name": l.employee.full_name,
                    "department": (
                        l.employee.department.name
                        if l.employee.department else ""
                    ),
                    "title": f"{l.leave_type.name} ({l.working_days} days)",
                    "subtitle": f"{l.starts_on} to {l.ends_on}",
                    "reason": l.reason,
                    "submitted_at": l.created_at,
                    "badge_colour": l.leave_type.colour or "#3b82f6",
                }
            )

        for r in reg_qs.select_related("attendance", "attendance__employee"):
            items.append(
                {
                    "id": str(r.uuid),
                    "reference": f"REG-{r.uuid.hex[:8].upper()}",
                    "type": "regularisation",
                    "type_label": "Clock Regularisation",
                    "employee_code": r.attendance.employee.employee_code,
                    "employee_name": r.attendance.employee.full_name,
                    "department": (
                        r.attendance.employee.department.name
                        if r.attendance.employee.department else ""
                    ),
                    "title": f"Attendance on {r.attendance.date}",
                    "subtitle": (
                        f"Requested in: {r.requested_checked_in_at or 'none'} | "
                        f"out: {r.requested_checked_out_at or 'none'}"
                    ),
                    "reason": r.reason,
                    "submitted_at": r.created_at,
                    "badge_colour": "#f59e0b",
                }
            )

        for s in swap_qs.select_related(
            "requester", "target_employee", "requester_entry__shift", "target_entry__shift"
        ):
            subtitle = (
                f"With {s.target_employee.full_name} "
                f"({s.target_entry.shift.name if s.target_entry else 'Cover'})"
            )
            items.append(
                {
                    "id": str(s.uuid),
                    "reference": f"SWAP-{s.uuid.hex[:8].upper()}",
                    "type": "swap",
                    "type_label": "Shift Swap",
                    "employee_code": s.requester.employee_code,
                    "employee_name": s.requester.full_name,
                    "department": (
                        s.requester.department.name
                        if s.requester.department else ""
                    ),
                    "title": f"{s.requester_entry.date} ({s.requester_entry.shift.name})",
                    "subtitle": subtitle,
                    "reason": s.reason,
                    "submitted_at": s.created_at,
                    "badge_colour": "#8b5cf6",
                }
            )

        for c in corr_qs.select_related("employee"):
            changes_summary = ", ".join(c.fields_payload.keys())
            items.append(
                {
                    "id": str(c.uuid),
                    "reference": f"CORR-{c.uuid.hex[:8].upper()}",
                    "type": "correction",
                    "type_label": "Profile Correction",
                    "employee_code": c.employee.employee_code,
                    "employee_name": c.employee.full_name,
                    "department": (
                        c.employee.department.name
                        if c.employee.department else ""
                    ),
                    "title": f"Update: {changes_summary}",
                    "subtitle": c.reason or "Contact/bank update",
                    "reason": c.reason,
                    "submitted_at": c.created_at,
                    "badge_colour": "#10b981",
                }
            )

        items.sort(key=lambda x: x["submitted_at"], reverse=True)

        today = timezone.localdate()
        team_status = []
        for m in tracked_members[:30]:
            att = Attendance.objects.filter(employee=m, date=today).first()
            team_status.append(
                {
                    "employee_code": m.employee_code,
                    "employee_name": m.full_name,
                    "department": m.department.name if m.department else "",
                    "status": att.status if att else "not_marked",
                    "checked_in_at": att.checked_in_at if att else None,
                    "checked_out_at": att.checked_out_at if att else None,
                }
            )

        return Response(
            {
                "is_manager": True,
                "summary": {
                    "pending_total": len(items),
                    "leave_count": leave_qs.count(),
                    "regularisation_count": reg_qs.count(),
                    "swap_count": swap_qs.count(),
                    "correction_count": corr_qs.count(),
                },
                "team_status_today": team_status,
                "items": items,
            }
        )
