from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.emergency.api import (
    AlertViewSet,
    ArrivalViewSet,
    BoardView,
    DepartmentSummaryView,
)

router = DefaultRouter()
router.register("arrivals", ArrivalViewSet, basename="ed-arrival")
router.register("alerts", AlertViewSet, basename="ed-alert")

urlpatterns = [
    # Before the router, so "board" is not read as an arrival reference.
    path("board/", BoardView.as_view(), name="ed-board"),
    path("summary/", DepartmentSummaryView.as_view(), name="ed-summary"),
    path("", include(router.urls)),
]
