from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.finance.api import (
    AccountViewSet,
    BankAccountViewSet,
    ExpenseViewSet,
    JournalViewSet,
    PeriodViewSet,
    ReportView,
    SupplierInvoiceViewSet,
)

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("periods", PeriodViewSet, basename="period")
router.register("journals", JournalViewSet, basename="journal")
router.register("supplier-invoices", SupplierInvoiceViewSet,
                basename="supplier-invoice")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("bank-accounts", BankAccountViewSet, basename="bank-account")

urlpatterns = [
    # Before the router, so "reports" is never read as a journal reference.
    path("reports/", ReportView.as_view(), name="finance-reports"),
    path("", include(router.urls)),
]
