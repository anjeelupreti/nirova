"""Staff administration routes.

Separate from `apps/rbac/urls.py`, which is mounted at `/api/privacy/` and is
about break-glass access and access-pattern review. Administering colleagues
and auditing emergency overrides are different jobs done by different people;
sharing a URL prefix would be the routing equivalent of sharing a permission.
"""

from django.urls import path

from apps.rbac.admin_api import (
    PermissionCatalogueView,
    RoleDetailView,
    RoleListView,
    StaffDeactivateView,
    StaffPasswordView,
    StaffSecondFactorResetView,
    StaffListView,
    StaffMemberView,
    StaffRolesView,
)

urlpatterns = [
    path("staff/", StaffListView.as_view(), name="staff-list"),
    path("staff/<uuid:uuid>/", StaffMemberView.as_view(), name="staff-detail"),
    # Before the role routes: `staff/<uuid>/deactivate/` and
    # `staff/<uuid>/roles/` are distinct paths, but keeping the more specific
    # literal first means a future `<str:action>` pattern cannot swallow it.
    path("staff/<uuid:uuid>/password/", StaffPasswordView.as_view(),
         name="staff-password"),
    path("staff/<uuid:uuid>/mfa-reset/", StaffSecondFactorResetView.as_view(),
         name="staff-mfa-reset"),
    path("staff/<uuid:uuid>/deactivate/", StaffDeactivateView.as_view(),
         name="staff-deactivate"),
    path("staff/<uuid:uuid>/roles/", StaffRolesView.as_view(),
         name="staff-roles"),
    path("staff/<uuid:uuid>/roles/<uuid:assignment_uuid>/",
         StaffRolesView.as_view(), name="staff-role-detail"),
    path("roles/", RoleListView.as_view(), name="role-list"),
    # Before the detail route, so the literal cannot be swallowed by the uuid
    # converter if one is ever loosened to `<str:...>`. Same ordering rule as
    # the staff routes above.
    path("permissions/", PermissionCatalogueView.as_view(),
         name="permission-catalogue"),
    path("roles/<uuid:uuid>/", RoleDetailView.as_view(), name="role-detail"),
]
