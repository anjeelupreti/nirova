"""Transaction helpers for tenant-routed code.

`django.db.transaction.atomic()` with no arguments opens a transaction on the
**default** database. Under database-per-tenant that is the control plane —
which is almost never the database the code is actually writing to.

The failure is quiet and nasty. A service decorated with `@transaction.atomic`
that writes tenant rows appears to work: the writes succeed, because Django
autocommits them on the tenant connection. What is lost is the guarantee. The
block is not atomic, a failure half-way leaves the tenant database with
partial data, and `select_for_update` raises `TransactionManagementError`
because there is no transaction on the connection it is locking.

So: **never write a bare `@transaction.atomic` in code that touches tenant
models.** Use `tenant_atomic()` or `@tenant_atomic_method`, which resolve the
alias from the active tenant context.

Code that spans both databases must nest deliberately, and must accept that
the two cannot commit together — see `apps/organization/services.py` and
`docs/adr/0001-database-per-tenant.md`.
"""

from contextlib import contextmanager
from functools import wraps

from django.db import transaction

from apps.tenancy.context import CONTROL_PLANE_ALIAS, get_current_database_alias


class NoTenantBound(RuntimeError):
    """Raised when tenant-scoped work runs with no organization selected."""


@contextmanager
def tenant_atomic(require_tenant: bool = True):
    """Open a transaction on the active tenant's database.

    `require_tenant` guards against the mistake this module exists to prevent:
    running tenant work with no context bound, which would silently open a
    transaction on the control plane. Pass `False` only for code that
    genuinely serves both cases and knows what it is doing.
    """
    alias = get_current_database_alias()
    if require_tenant and alias == CONTROL_PLANE_ALIAS:
        raise NoTenantBound(
            "tenant_atomic() was called with no organization bound, which "
            "would open a transaction on the control plane. Wrap the call in "
            "tenant_context(...), or resolve the organization from the request."
        )
    with transaction.atomic(using=alias):
        yield alias


def tenant_atomic_method(func):
    """Decorator form of `tenant_atomic`, for service functions.

    Used in place of `@transaction.atomic` throughout tenant-scoped services.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        with tenant_atomic():
            return func(*args, **kwargs)

    return wrapper


@contextmanager
def control_plane_atomic():
    """Open a transaction on the control plane, whatever tenant is bound.

    For writes to subscriptions, entitlements or usage while a tenant context
    happens to be active.
    """
    with transaction.atomic(using=CONTROL_PLANE_ALIAS):
        yield CONTROL_PLANE_ALIAS
