"""Dynamic registration of per-tenant database connections.

Django expects `settings.DATABASES` to be fully known at startup. With a
database per tenant that is impossible -- customers are created while the
process is running. This module registers connections on demand and keeps a
small in-process cache so the control plane is not queried on every request.
"""

import logging

# threading: guards the module-level alias registry with an RLock. Two
# requests for the same new tenant can arrive concurrently on different
# worker threads; without the lock they would both mutate settings.DATABASES.
import threading

# settings: DATABASES is *mutated* here at runtime. That is unusual and
# deliberate -- Django expects the set of databases to be known at startup,
# but tenants are created while the process is running.
from django.conf import settings

# connections: Django's connection handler. Used to hand back live
# connections for newly registered aliases and to close them on unregister.
from django.db import connections

# ConnectionHandler: needed for the isinstance check when invalidating the
# handler's memoised settings -- the mechanism that makes a brand-new alias
# visible to an already-running process.
# OperationalError: the expected failure when a tenant database is
# unreachable, caught in check_tenant_connection so a dead tenant is a
# reported state rather than an unhandled exception.
from django.db.utils import ConnectionHandler, OperationalError

# TenantUnavailable: raised when a tenant exists but its database is not
# ready. A domain error, not a bug -- it is the normal state during
# onboarding, and the API renders it as a 503 with an explanation.
from apps.common.exceptions import TenantUnavailable

# CONTROL_PLANE_ALIAS: used only to refuse unregistering the control plane.
# TenantContext: the value object returned to callers, carrying the
# organization identity and the alias its data lives in.
from apps.tenancy.context import CONTROL_PLANE_ALIAS, TenantContext

logger = logging.getLogger("nirova.tenancy")

# alias -> connection settings dict, for aliases already added to
# settings.DATABASES in this process.
_registered_aliases: set[str] = set()
_registry_lock = threading.RLock()


def _ensure_handler_knows(alias: str, config: dict) -> None:
    """Teach this process's connection handler about a database alias.

    `settings.DATABASES` is mutated and the handler's cached copy invalidated.
    Django rebuilds `connections.databases` lazily from settings, so clearing
    the cached attribute is enough; each thread still gets its own connection
    object from the handler's thread-local storage.
    """
    settings.DATABASES[alias] = config
    if hasattr(connections, "_settings"):
        connections._settings = connections.configure_settings(settings.DATABASES)
    if isinstance(connections, ConnectionHandler):
        # Drop the memoised per-alias settings so the new alias is picked up.
        connections.settings = connections.configure_settings(settings.DATABASES)
    _registered_aliases.add(alias)


def register_tenant_connection(tenant_database) -> str:
    """Make `tenant_database`'s alias usable, and return it.

    Safe to call repeatedly: registration is idempotent and cheap once the
    alias is known to this process.
    """
    alias = tenant_database.alias
    if alias in _registered_aliases and alias in settings.DATABASES:
        return alias

    with _registry_lock:
        if alias in _registered_aliases and alias in settings.DATABASES:
            return alias
        _ensure_handler_knows(alias, tenant_database.as_connection_settings())
        logger.info("Registered tenant connection %s -> %s", alias, tenant_database.db_name)
    return alias


def unregister_tenant_connection(alias: str) -> None:
    """Close and forget a tenant connection (after archival or a host move)."""
    if alias == CONTROL_PLANE_ALIAS:
        raise ValueError("Refusing to unregister the control-plane connection.")
    with _registry_lock:
        if alias in connections:
            try:
                connections[alias].close()
            except Exception:  # pragma: no cover - closing must never raise
                logger.warning("Error closing connection %s", alias, exc_info=True)
        settings.DATABASES.pop(alias, None)
        _registered_aliases.discard(alias)
        connections.settings = connections.configure_settings(settings.DATABASES)


def context_for_organization(organization) -> TenantContext:
    """Build a tenant context for an organization, registering its connection.

    Raises `TenantUnavailable` when the tenant's database has not finished
    provisioning, which is a normal state during onboarding rather than a bug.
    """
    from apps.tenancy.models import TenantDatabaseStatus

    tenant_db = getattr(organization, "database", None)
    if tenant_db is None:
        raise TenantUnavailable(
            "This organization has not been provisioned yet.",
            detail={"organization": str(organization.uuid)},
        )
    if tenant_db.status != TenantDatabaseStatus.READY:
        raise TenantUnavailable(
            f"The organization's database is {tenant_db.get_status_display().lower()}.",
            detail={
                "organization": str(organization.uuid),
                "database_status": tenant_db.status,
            },
        )

    alias = register_tenant_connection(tenant_db)
    return TenantContext(
        organization_id=str(organization.uuid),
        organization_slug=organization.slug,
        database_alias=alias,
    )


def check_tenant_connection(alias: str) -> bool:
    """Cheap liveness probe used by provisioning and the health endpoint."""
    try:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except (OperationalError, KeyError):
        logger.warning("Tenant connection %s is not reachable", alias, exc_info=True)
        return False


def registered_aliases() -> set[str]:
    return set(_registered_aliases)
