from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.platform_api.views import (
    OrganizationViewSet,
    PlanViewSet,
    PlatformChangeRequestViewSet,
    PlatformDashboardView,
    SubscriptionViewSet,
)

from apps.platform_api.catalogue_api import (
    CatalogueView,
    FeatureEditView,
    ModuleEditView,
    PlanChangeView,
    PlanCompositionView,
    PlanEditView,
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
    # The catalogue, editable: what is for sale and what each plan contains
    # (apps/catalog/editing.py).
    path("catalogue/", CatalogueView.as_view(), name="platform-catalogue"),
    path("catalogue/plans/<slug:code>/", PlanEditView.as_view(), name="platform-plan-edit"),
    path(
        "catalogue/plans/<slug:code>/<slug:part>/",
        PlanCompositionView.as_view(), name="platform-plan-part",
    ),
    path("catalogue/modules/<slug:code>/", ModuleEditView.as_view(), name="platform-module-edit"),
    path("catalogue/features/<slug:code>/", FeatureEditView.as_view(), name="platform-feature-edit"),
    # Moving one customer between plans, with the consequences shown first.
    path(
        "subscriptions/<uuid:uuid>/plan/",
        PlanChangeView.as_view(), name="platform-plan-change",
    ),
    path("", include(router.urls)),
]
