from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.theatre.api import (
    ImplantRegistryView,
    SafetyAuditView,
    SurgicalCaseViewSet,
    TheatreViewSet,
)

router = DefaultRouter()
router.register("cases", SurgicalCaseViewSet, basename="surgical-case")
router.register("theatres", TheatreViewSet, basename="theatre")

urlpatterns = [
    # Before the router, so "implants" is not read as a case reference.
    path("implants/", ImplantRegistryView.as_view(), name="ot-implants"),
    path("safety/", SafetyAuditView.as_view(), name="ot-safety"),
    path("", include(router.urls)),
]
