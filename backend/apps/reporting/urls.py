from django.urls import path

from apps.reporting.api import ReportLibraryView, RunReportView

urlpatterns = [
    path("", ReportLibraryView.as_view(), name="report-library"),
    path("<str:code>/", RunReportView.as_view(), name="run-report"),
]
