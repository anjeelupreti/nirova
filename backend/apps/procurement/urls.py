from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.procurement.views import (
    GoodsReceiptViewSet,
    ProcurementDashboardView,
    PurchaseOrderViewSet,
    RequisitionViewSet,
    SupplierViewSet,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("requisitions", RequisitionViewSet, basename="requisition")
router.register("orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("receipts", GoodsReceiptViewSet, basename="goods-receipt")

urlpatterns = [
    path("dashboard/", ProcurementDashboardView.as_view(), name="procurement-dashboard"),
    path("", include(router.urls)),
]
