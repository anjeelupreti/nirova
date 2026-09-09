from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.identity.me_api import (
    ChangePasswordView,
    MeView,
    MyPreferencesView,
)
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
    # A person's own account. Authenticated only -- no permission code, because
    # needing `user.update` to edit your own name would tie editing yourself to
    # the authority to edit colleagues.
    path("me/", MeView.as_view(), name="me"),
    path("me/preferences/", MyPreferencesView.as_view(), name="my-preferences"),
    path("me/password/", ChangePasswordView.as_view(), name="change-password"),
    path("switch/", SwitchOrganizationView.as_view(), name="switch-organization"),
]
