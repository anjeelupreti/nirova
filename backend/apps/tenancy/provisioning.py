"""Creating, migrating and retiring tenant databases.

Provisioning is deliberately idempotent and resumable. Creating a customer
touches a remote database server, runs migrations and seeds reference data;
any of those can fail halfway. Each step therefore checks whether it has
already been done, so re-running after a failure completes the job instead
of erroring or duplicating.
"""

import logging
import re

from django.conf import settings
from django.core.management import call_command
from django.db import connections, transaction
from django.utils import timezone

from apps.tenancy.connections import (
    check_tenant_connection,
    register_tenant_connection,
    unregister_tenant_connection,
)
from apps.tenancy.context import TenantContext, tenant_context
from apps.tenancy.models import (
    Organization,
    OrganizationStatus,
    TenantDatabase,
    TenantDatabaseStatus,
)

logger = logging.getLogger("nirova.provisioning")

SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


class ProvisioningError(RuntimeError):
    pass


def _validate_identifier(value: str, label: str) -> str:
    """Guard every identifier that reaches raw SQL.

    Database and role names cannot be passed as bound parameters in
    CREATE DATABASE, so they are interpolated. This is the only thing
    standing between a crafted organization slug and SQL injection at
    provisioning time, hence the strict allowlist.
    """
    if not SAFE_IDENTIFIER.match(value):
        raise ProvisioningError(
            f"Unsafe {label} {value!r}: expected lowercase letters, digits "
            "and underscores, starting with a letter."
        )
    return value


def build_tenant_database_record(organization: Organization) -> TenantDatabase:
    """Create (or return) the control-plane row describing the tenant's DB."""
    existing = TenantDatabase.objects.filter(organization=organization).first()
    if existing:
        return existing

    template = settings.TENANT_DATABASE
    slug = _validate_identifier(organization.slug, "organization slug")
    db_name = _validate_identifier(f"{template['NAME_PREFIX']}{slug}", "database name")

    return TenantDatabase.objects.create(
        organization=organization,
        alias=f"tenant_{slug}",
        db_name=db_name,
        host=template["HOST"],
        port=str(template["PORT"]),
        db_user=template["USER"],
        db_password=template["PASSWORD"],
        status=TenantDatabaseStatus.PENDING,
    )


def database_exists(db_name: str) -> bool:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [db_name])
        return cursor.fetchone() is not None


def create_physical_database(tenant_db: TenantDatabase) -> bool:
    """Issue CREATE DATABASE. Returns True if it was created, False if present.

    CREATE DATABASE cannot run inside a transaction block, so the connection
    is put into autocommit for the statement.
    """
    db_name = _validate_identifier(tenant_db.db_name, "database name")
    if database_exists(db_name):
        logger.info("Database %s already exists; skipping creation", db_name)
        return False

    connection = connections["default"]
    previous_autocommit = connection.get_autocommit()
    connection.set_autocommit(True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE DATABASE "{db_name}" '
                f"ENCODING 'UTF8' TEMPLATE template0"
            )
        logger.info("Created tenant database %s", db_name)
        return True
    finally:
        connection.set_autocommit(previous_autocommit)


def drop_physical_database(tenant_db: TenantDatabase) -> None:
    """Destroy a tenant database. Only ever called for abandoned trials.

    Cancelled paying customers are archived, never dropped: their records
    have retention obligations that outlive the subscription.
    """
    db_name = _validate_identifier(tenant_db.db_name, "database name")
    unregister_tenant_connection(tenant_db.alias)
    connection = connections["default"]
    previous_autocommit = connection.get_autocommit()
    connection.set_autocommit(True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [db_name],
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        logger.warning("Dropped tenant database %s", db_name)
    finally:
        connection.set_autocommit(previous_autocommit)


def migrate_tenant(tenant_db: TenantDatabase, verbosity: int = 0) -> None:
    """Apply tenant-app migrations to one tenant database."""
    alias = register_tenant_connection(tenant_db)
    if not check_tenant_connection(alias):
        raise ProvisioningError(f"Cannot reach tenant database {tenant_db.db_name}.")

    tenant_db.status = TenantDatabaseStatus.MIGRATING
    tenant_db.save(update_fields=["status", "updated_at"])

    try:
        call_command(
            "migrate",
            database=alias,
            interactive=False,
            verbosity=verbosity,
            run_syncdb=False,
        )
    except Exception as exc:
        tenant_db.status = TenantDatabaseStatus.FAILED
        tenant_db.last_error = str(exc)[:2000]
        tenant_db.save(update_fields=["status", "last_error", "updated_at"])
        raise

    tenant_db.status = TenantDatabaseStatus.READY
    tenant_db.last_migrated_at = timezone.now()
    tenant_db.last_error = ""
    tenant_db.save(
        update_fields=["status", "last_migrated_at", "last_error", "updated_at"]
    )


def seed_tenant(organization: Organization, tenant_db: TenantDatabase) -> None:
    """Populate a fresh tenant database with the reference data it needs.

    Currently the system role set. Master data (services, tax rules, chart of
    accounts) is seeded by the onboarding flow, because it varies by the
    customer's business type.
    """
    from apps.rbac.services import seed_system_roles

    context = TenantContext(
        organization_id=str(organization.uuid),
        organization_slug=organization.slug,
        database_alias=tenant_db.alias,
    )
    with tenant_context(context):
        seed_system_roles()


def provision_organization(organization: Organization, verbosity: int = 0) -> TenantDatabase:
    """Take an organization from `pending` to a migrated, seeded tenant database.

    Safe to re-run: each step is a no-op when already complete.
    """
    tenant_db = build_tenant_database_record(organization)

    tenant_db.status = TenantDatabaseStatus.PROVISIONING
    tenant_db.save(update_fields=["status", "updated_at"])

    try:
        create_physical_database(tenant_db)
        migrate_tenant(tenant_db, verbosity=verbosity)
        seed_tenant(organization, tenant_db)
    except Exception as exc:
        logger.exception("Provisioning failed for %s", organization.slug)
        tenant_db.status = TenantDatabaseStatus.FAILED
        tenant_db.last_error = str(exc)[:2000]
        tenant_db.save(update_fields=["status", "last_error", "updated_at"])
        raise

    with transaction.atomic():
        if organization.status == OrganizationStatus.PENDING:
            organization.status = (
                OrganizationStatus.TRIAL
                if organization.trial_ends_at
                else OrganizationStatus.ACTIVE
            )
            organization.activated_at = timezone.now()
            organization.save(
                update_fields=["status", "activated_at", "updated_at"]
            )

    logger.info("Provisioned organization %s", organization.slug)
    return tenant_db


def migrate_all_tenants(verbosity: int = 0) -> dict:
    """Roll migrations across every ready tenant. Used on deploy.

    Failures are collected rather than raised, so one broken tenant does not
    stop the rest of the fleet from being upgraded.
    """
    results = {"migrated": [], "failed": []}
    queryset = TenantDatabase.objects.filter(
        status__in=[TenantDatabaseStatus.READY, TenantDatabaseStatus.FAILED]
    ).select_related("organization")

    for tenant_db in queryset:
        try:
            migrate_tenant(tenant_db, verbosity=verbosity)
            results["migrated"].append(tenant_db.alias)
        except Exception as exc:
            logger.exception("Migration failed for %s", tenant_db.alias)
            results["failed"].append({"alias": tenant_db.alias, "error": str(exc)})
    return results
