from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.dataimport.api import ImportBatchViewSet, ImportKindsView

router = DefaultRouter()
router.register("batches", ImportBatchViewSet, basename="import-batch")

urlpatterns = [
    # Before the router include, so `kinds/` is not read as a batch reference.
    path("kinds/", ImportKindsView.as_view(), name="import-kinds"),
    path("", include(router.urls)),
]
