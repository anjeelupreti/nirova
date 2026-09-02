from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.organization.views import (
    EntitlementView,
    FacilityChangeRequestViewSet,
    FacilityViewSet,
)

router = DefaultRouter()
router.register("facilities", FacilityViewSet, basename="facility")
router.register(
    "facility-requests", FacilityChangeRequestViewSet, basename="facility-request"
)

urlpatterns = [
    path("entitlements/", EntitlementView.as_view(), name="entitlements"),
    path("", include(router.urls)),
]
