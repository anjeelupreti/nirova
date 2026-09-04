"""The patient-facing half, mounted at `/api/me/`.

Its own module rather than a second list inside the staff urls, so that
mounting one cannot accidentally mount the other. The two halves share no
view and no permission class.
"""

from django.urls import path

from apps.portal.api import MeView, PortalAuthView

urlpatterns = [
    path("auth/", PortalAuthView.as_view(), name="portal-auth"),
    path("", MeView.as_view(), name="portal-me"),
]
