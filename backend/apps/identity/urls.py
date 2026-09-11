from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.identity.me_api import (
    ChangePasswordView,
    MeView,
    MyPreferencesView,
    MySecondFactorView,
)
from apps.identity.views import (
    LoginView,
    LogoutView,
    SecondFactorView,
    SessionView,
    SwitchOrganizationView,
)
from apps.provisioning.registration import RegisterView

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    # The second step, when two-step sign-in is on: challenge + code -> tokens.
    path("login/verify/", SecondFactorView.as_view(), name="login-verify"),
    path("register/", RegisterView.as_view(), name="register"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("session/", SessionView.as_view(), name="session"),
    # A person's own account. Authenticated only -- no permission code, because
    # needing `user.update` to edit your own name would tie editing yourself to
    # the authority to edit colleagues.
    path("me/", MeView.as_view(), name="me"),
    path("me/preferences/", MyPreferencesView.as_view(), name="my-preferences"),
    path("me/password/", ChangePasswordView.as_view(), name="change-password"),
    path("me/mfa/", MySecondFactorView.as_view(), name="my-mfa"),
    path("switch/", SwitchOrganizationView.as_view(), name="switch-organization"),
]
