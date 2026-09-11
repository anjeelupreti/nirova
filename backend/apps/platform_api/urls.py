from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.platform_api.views import (
    OrganizationViewSet,
    PlanViewSet,
    PlatformChangeRequestViewSet,
    PlatformDashboardView,
    SubscriptionViewSet,
)

from apps.provisioning.registration import RegistrationRequestViewSet

router = DefaultRouter()
router.register("organizations", OrganizationViewSet, basename="platform-organization")
router.register(
    "change-requests", PlatformChangeRequestViewSet, basename="platform-change-request"
)
router.register("plans", PlanViewSet, basename="platform-plan")
router.register(
    "registrations", RegistrationRequestViewSet, basename="platform-registration"
)
router.register(
    "subscriptions", SubscriptionViewSet, basename="platform-subscription"
)

urlpatterns = [
    path("dashboard/", PlatformDashboardView.as_view(), name="platform-dashboard"),
    path("", include(router.urls)),
]
