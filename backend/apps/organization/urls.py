from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.organization.settings_api import SettingsView
from apps.organization.views import (
    DepartmentViewSet,
    EntitlementView,
    FacilityChangeRequestViewSet,
    FacilityViewSet,
)

router = DefaultRouter()
router.register("facilities", FacilityViewSet, basename="facility")
router.register("departments", DepartmentViewSet, basename="department")
router.register(
    "facility-requests", FacilityChangeRequestViewSet, basename="facility-request"
)

urlpatterns = [
    path("entitlements/", EntitlementView.as_view(), name="entitlements"),
    # Before the router, so "settings" cannot be shadowed by a viewset that
    # later registers the same prefix.
    path("settings/", SettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
