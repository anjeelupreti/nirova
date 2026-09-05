"""Shared fixtures.

These tests talk to a real PostgreSQL and a real provisioned tenant, because
that is what they are for. The defects this suite exists to catch -- a table
that did not match its model, a partial constraint that disagreed with its
manager, a seed that only worked once -- are all invisible to anything that
mocks the database away.
"""

import pytest


@pytest.fixture(scope="session")
def django_db_setup():
    """Use the running development databases rather than creating test ones.

    Deliberate, and the trade-off is worth stating. `pytest-django` would
    normally create and destroy a `test_` database per run, but this project
    is database-per-tenant: a tenant's schema lives in its own database, is
    registered at runtime, and is reached through a router that reads a
    context variable. Reproducing that for a throwaway test database means
    reimplementing provisioning inside the test harness, and a harness that
    reimplements the thing it is testing does not test it.

    So these run against the development stack, which is the same shape as
    production. The cost is that they are not hermetic and will not run
    without `docker compose up`. The benefit is that they exercise the router,
    the migrations and the constraints exactly as the application does.
    """
    yield


@pytest.fixture(scope="session")
def organization(django_db_setup, django_db_blocker):
    """The demo tenant, with its connection registered before any test runs.

    Registration matters for more than convenience. `@pytest.mark.django_db`
    decides at setup which database aliases a test may touch, and a tenant
    alias is added to `connections` at runtime by
    `context_for_organization`. If the first test is the thing that registers
    it, the alias does not exist when the mark is evaluated and every query
    against it is refused as a test-isolation violation. Doing it here, once,
    at session scope, means `databases="__all__"` covers it.
    """
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.models import Organization

    with django_db_blocker.unblock():
        org = Organization.objects.filter(slug="manakamana").first()
        if org is None:
            pytest.skip(
                "no 'manakamana' tenant; run `manage.py seed_demo` first"
            )
        context_for_organization(org)
        return org


@pytest.fixture
def tenant(organization, django_db_blocker):
    """Bind the tenant context, the way a request would."""
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context

    with django_db_blocker.unblock():
        with tenant_context(context_for_organization(organization)):
            yield organization
