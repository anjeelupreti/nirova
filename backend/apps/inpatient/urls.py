from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inpatient.api import (
    AccrualRunView,
    AdmissionViewSet,
    BedViewSet,
    CensusView,
    OutcomesView,
    WardViewSet,
)
from apps.inpatient.nursing_api import (
    BedsideRoundView,
    EmarView,
    NurseAssignmentViewSet,
    NurseWorkspaceSummaryView,
    NursingHandoverViewSet,
    NursingTaskViewSet,
)

router = DefaultRouter()
router.register("admissions", AdmissionViewSet, basename="admission")
router.register("wards", WardViewSet, basename="ward")
router.register("beds", BedViewSet, basename="bed")
router.register("nurse-workspace/assignments", NurseAssignmentViewSet, basename="nurse-assignment")
router.register("nurse-workspace/handovers", NursingHandoverViewSet, basename="nurse-handover")
router.register("nurse-workspace/tasks", NursingTaskViewSet, basename="nurse-task")

urlpatterns = [
    # Before the router, so specific endpoints are not matched as admission references.
    path("census/", CensusView.as_view(), name="ipd-census"),
    path("outcomes/", OutcomesView.as_view(), name="ipd-outcomes"),
    path("accrue/", AccrualRunView.as_view(), name="ipd-accrue"),
    path("nurse-workspace/summary/", NurseWorkspaceSummaryView.as_view(), name="nurse-workspace-summary"),
    path("nurse-workspace/bedside-round/", BedsideRoundView.as_view(), name="nurse-workspace-bedside-round"),
    path("nurse-workspace/emar/", EmarView.as_view(), name="nurse-workspace-emar"),
    path("nurse-workspace/emar/administer/", EmarView.as_view(), name="nurse-workspace-emar-administer"),
    path("", include(router.urls)),
]
