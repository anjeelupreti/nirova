from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.pharmacy.views import (
    AdjustStockView,
    BatchViewSet,
    DispenseViewSet,
    ExpiringStockView,
    ProductViewSet,
    ReconcileView,
    ReorderView,
    StockCountViewSet,
    StockLedgerView,
    StockLevelView,
    StockLocationViewSet,
    StockView,
    ValuationView,
)

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("locations", StockLocationViewSet, basename="stock-location")
router.register("batches", BatchViewSet, basename="batch")
router.register("dispenses", DispenseViewSet, basename="dispense")
router.register("counts", StockCountViewSet, basename="stock-count")

urlpatterns = [
    path("stock/receive/", StockView.as_view(), name="receive-stock"),
    path("stock/levels/", StockLevelView.as_view(), name="stock-levels"),
    path("stock/ledger/", StockLedgerView.as_view(), name="stock-ledger"),
    path("stock/adjust/", AdjustStockView.as_view(), name="adjust-stock"),
    path("stock/expiring/", ExpiringStockView.as_view(), name="expiring-stock"),
    path("stock/reorder/", ReorderView.as_view(), name="reorder-suggestions"),
    path("stock/valuation/", ValuationView.as_view(), name="stock-valuation"),
    path("stock/reconcile/", ReconcileView.as_view(), name="reconcile-stock"),
    path("", include(router.urls)),
]
