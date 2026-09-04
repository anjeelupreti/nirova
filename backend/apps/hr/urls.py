from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.hr.attendance_api import (
    AttendanceSummaryView,
    AttendanceViewSet,
    HolidayViewSet,
    LeaveBalanceView,
    LeaveCalendarView,
    LeaveLedgerView,
    LeaveRequestViewSet,
    LeaveTypeViewSet,
    RegularisationViewSet,
    RosterViewSet,
    ShiftViewSet,
)
from apps.hr.ess_api import (
    ESSMeSummaryView,
    ManagerQueueView,
    ProfileCorrectionViewSet,
    ShiftSwapViewSet,
)
from apps.hr.views import (
    CredentialViewSet,
    EmployeeViewSet,
    HrDashboardView,
    PositionViewSet,
)

router = DefaultRouter()
router.register("employees", EmployeeViewSet, basename="employee")
router.register("positions", PositionViewSet, basename="position")
router.register("credentials", CredentialViewSet, basename="credential")
router.register("shifts", ShiftViewSet, basename="shift")
router.register("holidays", HolidayViewSet, basename="holiday")
router.register("roster", RosterViewSet, basename="roster")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("regularisations", RegularisationViewSet,
                basename="regularisation")
router.register("leave-types", LeaveTypeViewSet, basename="leave-type")
router.register("leave", LeaveRequestViewSet, basename="leave-request")
router.register("profile-corrections", ProfileCorrectionViewSet,
                basename="profile-correction")
router.register("shift-swaps", ShiftSwapViewSet, basename="shift-swap")

urlpatterns = [
    # Before the router, so "dashboard" and "me" are not read as an employee code.
    path("dashboard/", HrDashboardView.as_view(), name="hr-dashboard"),
    path("me/summary/", ESSMeSummaryView.as_view(), name="ess-me-summary"),
    path("manager-queue/", ManagerQueueView.as_view(), name="ess-manager-queue"),
    path("leave-balance/", LeaveBalanceView.as_view(), name="leave-balance"),
    path("leave-ledger/", LeaveLedgerView.as_view(), name="leave-ledger"),
    path("leave-calendar/", LeaveCalendarView.as_view(), name="leave-calendar"),
    path("attendance-summary/", AttendanceSummaryView.as_view(),
         name="attendance-summary"),
    path("", include(router.urls)),
]
