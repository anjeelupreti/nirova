from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rbac.privacy_api import (
    AccessPatternView,
    BreakGlassReviewViewSet,
    BreakGlassView,
)

router = DefaultRouter()
router.register("grants", BreakGlassReviewViewSet, basename="break-glass-grant")

urlpatterns = [
    # Before the router: taking access and reviewing it are different acts by
    # different people, and the take endpoint must not be reachable through
    # the reviewer's permission by accident.
    path("break-glass/", BreakGlassView.as_view(), name="break-glass"),
    path("access-patterns/", AccessPatternView.as_view(),
         name="access-patterns"),
    path("", include(router.urls)),
]
