from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.notifications.api import (
    AnnouncementView,
    NotificationViewSet,
    PreferenceView,
)

router = DefaultRouter()
router.register("", NotificationViewSet, basename="notification")

urlpatterns = [
    # Before the router, so neither is ever read as a notification UUID.
    path("preferences/", PreferenceView.as_view(), name="notification-preferences"),
    path("announce/", AnnouncementView.as_view(), name="notification-announce"),
    path("", include(router.urls)),
]
