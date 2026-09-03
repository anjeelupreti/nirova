from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payroll.api import (
    ContributionSchemeViewSet,
    EmployeePayrollViewSet,
    PayComponentViewSet,
    PayablePreviewView,
    PaymentBatchViewSet,
    PayrollRunViewSet,
    PayslipViewSet,
    SalaryStructureViewSet,
    TaxSlabViewSet,
)

router = DefaultRouter()
router.register("runs", PayrollRunViewSet, basename="payroll-run")
router.register("payslips", PayslipViewSet, basename="payslip")
router.register("batches", PaymentBatchViewSet, basename="payment-batch")
router.register("profiles", EmployeePayrollViewSet, basename="payroll-profile")
router.register("components", PayComponentViewSet, basename="pay-component")
router.register("structures", SalaryStructureViewSet, basename="salary-structure")
router.register("tax-slabs", TaxSlabViewSet, basename="tax-slab")
router.register("schemes", ContributionSchemeViewSet, basename="contribution-scheme")

urlpatterns = [
    # Before the router, so "payable" is not read as a run reference.
    path("payable/", PayablePreviewView.as_view(), name="payroll-payable"),
    path("", include(router.urls)),
]
