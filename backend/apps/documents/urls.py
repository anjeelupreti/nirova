from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.documents.api import DocumentViewSet

router = DefaultRouter()
router.register("", DocumentViewSet, basename="document")

urlpatterns = [path("", include(router.urls))]
