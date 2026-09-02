"""The ambient tenant context.

Every request, task and management command runs against exactly one
organization, or against the control plane. That choice is held here in
context variables rather than passed through every function signature,
because the database router needs it at query time -- far below the layer
that knows which organization it is serving.

Context variables (not thread locals) are used deliberately: they are
inherited correctly by asyncio tasks and are isolated per coroutine, so an
ASGI deployment cannot leak one tenant's context into another's request.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

CONTROL_PLANE_ALIAS = "default"


@dataclass(frozen=True)
class TenantContext:
    """Identifies the organization a unit of work is running for."""

    organization_id: str
    organization_slug: str
    database_alias: str
    #: Facility the user has narrowed to, if any. `None` means the whole
    #: organization, which is what the "All Organization" context switcher
    #: option selects.
    facility_id: str | None = None


_current_tenant: ContextVar[TenantContext | None] = ContextVar(
    "nirova_current_tenant", default=None
)


def get_current_tenant() -> TenantContext | None:
    return _current_tenant.get()


def get_current_database_alias() -> str:
    """Database alias tenant models should be read from and written to."""
    tenant = _current_tenant.get()
    return tenant.database_alias if tenant else CONTROL_PLANE_ALIAS


def get_current_organization_id() -> str | None:
    tenant = _current_tenant.get()
    return tenant.organization_id if tenant else None


def get_current_facility_id() -> str | None:
    tenant = _current_tenant.get()
    return tenant.facility_id if tenant else None


def set_current_tenant(context: TenantContext | None):
    """Set the context and return the token needed to restore the previous one."""
    return _current_tenant.set(context)


def reset_current_tenant(token) -> None:
    _current_tenant.reset(token)


@contextmanager
def tenant_context(context: TenantContext | None):
    """Run a block against one organization, restoring the previous context after.

        with tenant_context(ctx):
            Facility.objects.count()

    Always prefer this to bare set/reset: it restores the previous context
    even when the block raises, which is what stops a failed request from
    leaving a stale tenant bound to a reused worker.
    """
    token = _current_tenant.set(context)
    try:
        yield context
    finally:
        _current_tenant.reset(token)


@contextmanager
def control_plane_context():
    """Run a block against the control plane, ignoring any active tenant."""
    with tenant_context(None):
        yield


def with_facility(facility_id: str | None) -> TenantContext:
    """Narrow the active tenant context to a single facility."""
    tenant = _current_tenant.get()
    if tenant is None:
        raise RuntimeError("Cannot select a facility with no active organization.")
    return TenantContext(
        organization_id=tenant.organization_id,
        organization_slug=tenant.organization_slug,
        database_alias=tenant.database_alias,
        facility_id=facility_id,
    )
