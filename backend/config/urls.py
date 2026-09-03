from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("apps.common.urls")),
    path("api/auth/", include("apps.identity.urls")),
    path("api/platform/", include("apps.platform_api.urls")),
    path("api/org/", include("apps.organization.urls")),
    path("api/clinical/", include("apps.patients.urls")),
    path("api/clinical/", include("apps.scheduling.urls")),
    path("api/clinical/", include("apps.encounters.urls")),
    path("api/clinical/", include("apps.prescriptions.urls")),
    path("api/billing/", include("apps.billing.urls")),
    path("api/diagnostics/", include("apps.diagnostics.urls")),
    path("api/pharmacy/", include("apps.pharmacy.urls")),
    path("api/procurement/", include("apps.procurement.urls")),
    path("api/pos/", include("apps.pos.urls")),
    path("api/hr/", include("apps.hr.urls")),
    path("api/payroll/", include("apps.payroll.urls")),
    path("api/ipd/", include("apps.inpatient.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
