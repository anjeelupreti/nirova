from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.pos.views import (
    CounterSearchView,
    CounterSessionViewSet,
    SaleReturnViewSet,
    SaleViewSet,
    SalesSummaryView,
)

router = DefaultRouter()
router.register("sessions", CounterSessionViewSet, basename="counter-session")
router.register("sales", SaleViewSet, basename="pos-sale")
router.register("returns", SaleReturnViewSet, basename="pos-return")

urlpatterns = [
    # Before the router, so "search" and "summary" are not mistaken for a
    # session reference by the detail route.
    path("search/", CounterSearchView.as_view(), name="pos-search"),
    path("summary/", SalesSummaryView.as_view(), name="pos-summary"),
    path("", include(router.urls)),
]
