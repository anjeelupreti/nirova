from django.urls import path

from apps.identity.me_api import (
    ChangePasswordView,
    MeView,
    MyPreferencesView,
    MySecondFactorView,
)
from apps.identity.views import (
    ForgotPasswordView,
    LoginView,
    LogoutView,
    RefreshView,
    ResetPasswordView,
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
    path("refresh/", RefreshView.as_view(), name="token-refresh"),
    # Forgotten passwords: a link by email (apps/identity/password_reset.py).
    path("password/forgot/", ForgotPasswordView.as_view(), name="password-forgot"),
    path("password/reset/", ResetPasswordView.as_view(), name="password-reset"),
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
