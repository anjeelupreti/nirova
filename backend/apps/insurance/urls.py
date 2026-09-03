from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.insurance.api import (
    ClaimReportView,
    ClaimViewSet,
    EligibilityView,
    PayerViewSet,
    PolicyViewSet,
    PreAuthViewSet,
    SchemePackageViewSet,
)

router = DefaultRouter()
router.register("payers", PayerViewSet, basename="payer")
router.register("policies", PolicyViewSet, basename="policy")
router.register("preauthorisations", PreAuthViewSet, basename="preauthorisation")
router.register("claims", ClaimViewSet, basename="claim")
router.register("packages", SchemePackageViewSet, basename="scheme-package")

urlpatterns = [
    # Before the router, so neither is read as a claim reference.
    path("eligibility/", EligibilityView.as_view(), name="insurance-eligibility"),
    path("reports/", ClaimReportView.as_view(), name="insurance-reports"),
    path("", include(router.urls)),
]
