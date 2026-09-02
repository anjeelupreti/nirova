from django.urls import include, path
from rest_framework.routers import DefaultRouter

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

urlpatterns = [
    # Before the router, so "dashboard" is not read as an employee code.
    path("dashboard/", HrDashboardView.as_view(), name="hr-dashboard"),
    path("", include(router.urls)),
]
