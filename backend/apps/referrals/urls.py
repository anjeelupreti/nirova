from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.referrals.api import (
    ProviderViewSet,
    ReferralReportView,
    ReferralViewSet,
)

router = DefaultRouter()
router.register("providers", ProviderViewSet, basename="external-provider")
router.register("", ReferralViewSet, basename="referral")

urlpatterns = [
    # Before the router, so it is never read as a referral reference.
    path("reports/", ReferralReportView.as_view(), name="referral-reports"),
    path("", include(router.urls)),
]
