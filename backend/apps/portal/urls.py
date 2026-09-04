"""Two routers, kept apart on purpose.

`apps.portal.me_urls` is mounted at `/api/me/` and authenticated by a
portal session token. This module is the staff side at `/api/portal/`. They
share
no view and no permission class, because the module exists to keep the two
audiences apart and a shared viewset with a branch is one bad condition away
from a patient reading a ward list.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.portal.api import (
    MeView,
    PatientCorrectionViewSet,
    PortalAccountViewSet,
    PortalAdoptionView,
    PortalAuthView,
    PortalMessageViewSet,
    ProxyViewSet,
)

router = DefaultRouter()
router.register("accounts", PortalAccountViewSet, basename="portal-account")
router.register("proxies", ProxyViewSet, basename="portal-proxy")
router.register("messages", PortalMessageViewSet, basename="portal-message")
router.register("corrections", PatientCorrectionViewSet, basename="portal-correction")

urlpatterns = [
    path("adoption/", PortalAdoptionView.as_view(), name="portal-adoption"),
    path("", include(router.urls)),
]
