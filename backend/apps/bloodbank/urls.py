from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.bloodbank.api import (
    BloodBankReportView,
    BloodRequestViewSet,
    CrossMatchView,
    DonationViewSet,
    DonorViewSet,
    TransfusionViewSet,
    UnitViewSet,
)

router = DefaultRouter()
router.register("donors", DonorViewSet, basename="donor")
router.register("donations", DonationViewSet, basename="donation")
router.register("units", UnitViewSet, basename="blood-unit")
router.register("requests", BloodRequestViewSet, basename="blood-request")
router.register("transfusions", TransfusionViewSet, basename="transfusion")

urlpatterns = [
    # Before the router, so neither is read as a donor number.
    path("cross-match/", CrossMatchView.as_view(), name="cross-match"),
    path("reports/", BloodBankReportView.as_view(), name="bloodbank-reports"),
    path("", include(router.urls)),
]
