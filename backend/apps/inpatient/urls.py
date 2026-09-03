from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inpatient.api import (
    AccrualRunView,
    AdmissionViewSet,
    BedViewSet,
    CensusView,
    OutcomesView,
    WardViewSet,
)

router = DefaultRouter()
router.register("admissions", AdmissionViewSet, basename="admission")
router.register("wards", WardViewSet, basename="ward")
router.register("beds", BedViewSet, basename="bed")

urlpatterns = [
    # Before the router, so "census" is not read as an admission reference.
    path("census/", CensusView.as_view(), name="ipd-census"),
    path("outcomes/", OutcomesView.as_view(), name="ipd-outcomes"),
    path("accrue/", AccrualRunView.as_view(), name="ipd-accrue"),
    path("", include(router.urls)),
]
