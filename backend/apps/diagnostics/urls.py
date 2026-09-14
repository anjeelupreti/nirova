from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.diagnostics.views import (
    AmendResultView,
    CriticalAlertViewSet,
    DiagnosticOrderViewSet,
    PatientResultsView,
    TestDefinitionViewSet,
    TurnaroundReportView,
    WorklistView,
)

from apps.diagnostics.report_templates import ReportTemplateDetailView, ReportTemplateView

router = DefaultRouter()
router.register("tests", TestDefinitionViewSet, basename="test-definition")
router.register("orders", DiagnosticOrderViewSet, basename="diagnostic-order")
router.register("critical-alerts", CriticalAlertViewSet, basename="critical-alert")

urlpatterns = [
    path("worklist/", WorklistView.as_view(), name="diagnostics-worklist"),
    path("report-templates/", ReportTemplateView.as_view(), name="report-templates"),
    path(
        "report-templates/<uuid:uuid>/",
        ReportTemplateDetailView.as_view(),
        name="report-template",
    ),
    path("turnaround/", TurnaroundReportView.as_view(), name="turnaround-report"),
    path(
        "patients/<uuid:uuid>/results/",
        PatientResultsView.as_view(),
        name="patient-results",
    ),
    path("results/<uuid:uuid>/amend/", AmendResultView.as_view(), name="amend-result"),
    path("", include(router.urls)),
]
