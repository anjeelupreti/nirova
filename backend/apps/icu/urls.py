from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.icu.api import IcuStayViewSet, UnitBoardView, UnitSummaryView

router = DefaultRouter()
router.register("stays", IcuStayViewSet, basename="icu-stay")

urlpatterns = [
    # Before the router, so "board" is never read as a stay's UUID.
    path("board/", UnitBoardView.as_view(), name="icu-board"),
    path("summary/", UnitSummaryView.as_view(), name="icu-summary"),
    path("", include(router.urls)),
]
