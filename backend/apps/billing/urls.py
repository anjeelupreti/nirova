from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.billing.views import (
    ChargeViewSet,
    DailyCollectionView,
    InvoiceViewSet,
    PatientAccountView,
    PriceListViewSet,
    RefundPaymentView,
    ServiceItemViewSet,
)

router = DefaultRouter()
router.register("services", ServiceItemViewSet, basename="service-item")
router.register("price-lists", PriceListViewSet, basename="price-list")
router.register("charges", ChargeViewSet, basename="charge")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path(
        "patients/<uuid:uuid>/account/",
        PatientAccountView.as_view(),
        name="patient-account",
    ),
    path(
        "payments/<uuid:uuid>/refund/",
        RefundPaymentView.as_view(),
        name="refund-payment",
    ),
    path("collection/", DailyCollectionView.as_view(), name="daily-collection"),
    path("", include(router.urls)),
]
