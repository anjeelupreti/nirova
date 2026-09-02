"""Database router: sends every query to the right database.

The rules are deliberately absolute, because a routing mistake here is a
cross-tenant data leak rather than a bug:

* A control-plane model is *always* read from and written to `default`.
* A tenant model is *always* read from and written to the active tenant's
  alias. With no active tenant, a tenant model raises rather than silently
  falling back to `default` -- a silent fallback would write one customer's
  facility into the control-plane database.
* `allow_migrate` keeps control-plane tables out of tenant databases and
  tenant tables out of the control plane, so `migrate --database=tenant_x`
  produces a schema containing only that tenant's tables.
"""

# settings: read once at router construction to learn which app labels are
# control-plane and which are tenant. Read at construction rather than per
# query because the router is on the hot path of every single database call.
from django.conf import settings

# CONTROL_PLANE_ALIAS: the literal "default" alias, imported rather than
# hard-coded so the control-plane database is named in exactly one place.
# get_current_tenant: reads the per-coroutine context variable set by
# TenantContextMiddleware. This is the only reason the router can pick a
# database without the caller passing one down through every function.
from apps.tenancy.context import CONTROL_PLANE_ALIAS, get_current_tenant


class TenantRoutingError(RuntimeError):
    """Raised when a tenant model is used with no organization selected."""


def _app_labels(dotted_paths):
    return {path.rsplit(".", 1)[-1] for path in dotted_paths}


class TenantDatabaseRouter:
    def __init__(self):
        self.control_labels = _app_labels(settings.CONTROL_PLANE_APPS) | set(
            settings.CONTROL_PLANE_DJANGO_LABELS
        )
        self.tenant_labels = _app_labels(settings.TENANT_APPS)

    # -- helpers ---------------------------------------------------------

    def _is_tenant_model(self, model) -> bool:
        return model._meta.app_label in self.tenant_labels

    def _is_control_model(self, model) -> bool:
        return model._meta.app_label in self.control_labels

    def _tenant_alias(self, model) -> str:
        tenant = get_current_tenant()
        if tenant is None:
            raise TenantRoutingError(
                f"{model._meta.label} is a tenant model but no organization is "
                "active. Wrap the call in tenant_context(...) or resolve the "
                "organization from the request before querying."
            )
        return tenant.database_alias

    # -- router protocol -------------------------------------------------

    def db_for_read(self, model, **hints):
        if self._is_control_model(model):
            return CONTROL_PLANE_ALIAS
        if self._is_tenant_model(model):
            return self._tenant_alias(model)
        return None

    def db_for_write(self, model, **hints):
        if self._is_control_model(model):
            return CONTROL_PLANE_ALIAS
        if self._is_tenant_model(model):
            return self._tenant_alias(model)
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """Permit relations only inside one database.

        Control-plane and tenant objects are never related by a foreign key;
        where they need to reference each other they store a bare UUID (see
        `FacilityRegistryEntry.facility_uuid`).
        """
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 is None or db2 is None:
            return None
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        is_control_db = db == CONTROL_PLANE_ALIAS
        if app_label in self.control_labels:
            return is_control_db
        if app_label in self.tenant_labels:
            return not is_control_db
        # Third-party apps without an explicit classification live in the
        # control plane; a tenant database holds only what this project puts
        # there.
        return is_control_db
