from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.encounters.views import (
    ClinicalSummaryView,
    EncounterViewSet,
    MyWorklistView,
    NoteAmendmentView,
    PromoteDiagnosisView,
)

router = DefaultRouter()
router.register("encounters", EncounterViewSet, basename="encounter")

urlpatterns = [
    path("worklist/", MyWorklistView.as_view(), name="worklist"),
    path(
        "patients/<uuid:uuid>/summary/",
        ClinicalSummaryView.as_view(),
        name="clinical-summary",
    ),
    path("notes/<uuid:uuid>/amend/", NoteAmendmentView.as_view(), name="amend-note"),
    path(
        "diagnoses/<uuid:uuid>/promote/",
        PromoteDiagnosisView.as_view(),
        name="promote-diagnosis",
    ),
    path("", include(router.urls)),
]
