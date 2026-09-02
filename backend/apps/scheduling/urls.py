from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.scheduling.views import (
    AppointmentViewSet,
    AvailabilityView,
    ProviderScheduleViewSet,
    QueueViewSet,
)

router = DefaultRouter()
router.register("schedules", ProviderScheduleViewSet, basename="schedule")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("queue", QueueViewSet, basename="queue")

urlpatterns = [
    path("availability/", AvailabilityView.as_view(), name="availability"),
    path("", include(router.urls)),
]
