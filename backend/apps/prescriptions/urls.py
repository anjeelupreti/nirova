from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.prescriptions.templates_api import (
    PrescriptionTemplateDetailView,
    PrescriptionTemplateView,
)
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
    # Prescribing aids: the same script, written once
    # (apps/prescriptions/templating.py).
    path(
        "prescription-templates/",
        PrescriptionTemplateView.as_view(), name="prescription-templates",
    ),
    path(
        "prescription-templates/<uuid:uuid>/",
        PrescriptionTemplateDetailView.as_view(), name="prescription-template",
    ),
    path("", include(router.urls)),
]
