from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.identity.views import (
    LoginView,
    LogoutView,
    SessionView,
    SwitchOrganizationView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("session/", SessionView.as_view(), name="session"),
    path("switch/", SwitchOrganizationView.as_view(), name="switch-organization"),
]
