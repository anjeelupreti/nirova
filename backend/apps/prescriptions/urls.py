from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.prescriptions.views import (
    ActiveMedicationsView,
    DiscontinueLineView,
    PrescriptionViewSet,
)

router = DefaultRouter()
router.register("prescriptions", PrescriptionViewSet, basename="prescription")

urlpatterns = [
    path(
        "patients/<uuid:uuid>/medications/",
        ActiveMedicationsView.as_view(),
        name="active-medications",
    ),
    path(
        "prescription-lines/<uuid:uuid>/discontinue/",
        DiscontinueLineView.as_view(),
        name="discontinue-line",
    ),
    path("", include(router.urls)),
]
