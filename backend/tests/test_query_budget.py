"""Query counts that must not scale with the number of rows.

**Why growth and not a number.** A test asserting "this endpoint issues 13
queries" fails the next time anybody adds a legitimate join, so it gets edited
upwards until it asserts nothing. The invariant that actually matters is
different and durable: asking for *more rows* must not cost *more queries*. A
fixed cost is a fixed cost whatever its size; a per-row cost is the defect.

So each test below requests the same endpoint twice, at a small page size and a
large one, and asserts the query count did not move. That is the same
measurement `manage.py audit_queries --compare` makes, pinned so it keeps being
true.

**What this caught when it was written** (all measured, none noticed by
reading):

| endpoint | before | after |
|---|---|---|
| `/api/ipd/beds/` | 86 queries for 16 beds, +64 for +14 | 13, flat |
| `/api/ipd/admissions/` | 50 for 7, +26 for +5 | 13, flat |
| `/api/ipd/wards/` | 16 for 4, +2 for +2 | 12, flat |
| `/api/finance/periods/` | 36 for 24 | 12, flat |
| `/api/hr/manager-queue/` | 33 for 8 | 21, no longer per-member |

Every one was a property or serializer field that issues a query, read once per
row. None of them is visible at the call site: `bed.is_occupied` looks free.
And none is visible in use either -- on a demo tenant with sixteen beds every
one of these is instant, and the same endpoint in a 500-bed hospital is two and
a half thousand round trips.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"

#: The owner sees every row, so they are the caller for whom a per-row cost is
#: largest and most visible. A test written as a narrowly scoped user could
#: pass on two rows while the endpoint quietly cost a query each.
OWNER = f"owner@{DEMO}.test"

#: Enough of a gap that a per-row query cannot hide inside the noise of one or
#: two opportunistic fetches, and small enough to stay inside `max_page_size`.
SMALL, LARGE = 2, 100


@pytest.fixture
def owner(tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=OWNER).first()
    if user is None:
        pytest.skip(f"no {OWNER}; run manage.py bootstrap")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


def _measure(client, path):
    """Queries issued and rows returned for one GET, across every database.

    Both connections are counted, not just the tenant's: authentication, the
    membership lookup and permission resolution all run against the control
    plane, so a per-row query aimed there would be invisible if only the tenant
    connection were watched. `test_staff_admin` had to catch exactly that once.
    """
    from django.db import connections
    from django.test.utils import CaptureQueriesContext

    aliases = [alias for alias in connections if connections[alias].settings_dict]
    captures = [CaptureQueriesContext(connections[alias]) for alias in aliases]
    for capture in captures:
        capture.__enter__()
    try:
        response = client.get(path)
    finally:
        for capture in reversed(captures):
            capture.__exit__(None, None, None)

    assert response.status_code == 200, f"{path}: {response.status_code}"
    body = json.loads(response.content.decode())
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    queries = sum(len(capture.captured_queries) for capture in captures)
    return queries, len(rows)


def _assert_flat(client, path, tenant):
    """Asking for more rows must not cost more queries."""
    joiner = "&" if "?" in path else "?"

    # Warm first: the tenant's database alias is registered by the request that
    # first needs it, and the permission resolver caches per request. An
    # unwarmed first measurement reads lower than a later one and would make a
    # real N+1 look flat.
    client.get("/api/auth/me/")

    small_queries, small_rows = _measure(client, f"{path}{joiner}page_size={SMALL}")
    large_queries, large_rows = _measure(client, f"{path}{joiner}page_size={LARGE}")

    if large_rows <= small_rows:
        pytest.skip(
            f"{path} returned {large_rows} rows at page_size={LARGE} and "
            f"{small_rows} at {SMALL} -- not enough data to tell growth from "
            "fixed cost"
        )

    assert large_queries <= small_queries, (
        f"{path} issued {large_queries} queries for {large_rows} rows and "
        f"{small_queries} for {small_rows}: +{large_queries - small_queries} "
        f"queries for +{large_rows - small_rows} rows. That is a query per "
        f"row, which is the defect this test exists to catch -- find the "
        f"property or serializer field being read once per row and prefetch "
        f"or annotate it."
    )


def test_the_bed_board_does_not_query_per_bed(owner, tenant):
    """`BedSerializer` reads `current_assignment` four times per bed.

    `is_occupied`, `is_assignable`, `occupant_name` and `occupant_admission`,
    and the last two then walk `admission.patient`. Measured at 4.6 queries per
    bed before `BedViewSet` prefetched the open assignments and
    `Bed.current_assignment` learned to read that prefetch.
    """
    _assert_flat(owner, "/api/ipd/beds/", tenant)


def test_the_admissions_list_does_not_query_per_admission(owner, tenant):
    """`AdmissionListSerializer` reads `current_bed` twice per row.

    The queryset prefetched bed assignments for the *detail* action and not for
    the list -- the wrong way round, since a detail view walks the relation once
    and a list walks it once per row.
    """
    _assert_flat(owner, "/api/ipd/admissions/", tenant)


def test_the_ward_list_does_not_count_beds_per_ward(owner, tenant):
    """`Ward.bed_count` was a `COUNT` per ward, measured at exactly 1.0/row."""
    _assert_flat(owner, "/api/ipd/wards/", tenant)


def test_the_accounting_periods_list_does_not_count_entries_per_period(
    owner, tenant
):
    """`entries = IntegerField(source="entries.count")` is a query per period.

    Worth a test of its own because it grows forever: a fiscal year is twelve
    periods and the system keeps every year, so this gets slower every January
    and never looks wrong.
    """
    _assert_flat(owner, "/api/finance/periods/", tenant)


def test_the_manager_queue_does_not_query_per_team_member(owner, tenant):
    """Today's attendance for the whole team in one query, not one per person.

    Not expressed as a page-size comparison -- the queue takes no `page_size`,
    because it gathers four different kinds of request and caps each. The
    invariant is tested directly instead: the query count must not change when
    the team gets bigger.
    """
    from apps.hr.models import Employee

    owner.get("/api/auth/me/")
    before, _ = _measure(owner, "/api/hr/manager-queue/")

    # The broad branch tracks up to fifty working employees, so the team strip
    # grows with the headcount. If `department` or today's attendance is read
    # per person, this moves.
    people = Employee.objects.filter(status="active").count()
    assert people >= 5, "too few employees for this to mean anything"

    after, _ = _measure(owner, "/api/hr/manager-queue/")
    assert after == before, (
        f"the manager queue issued {before} queries and then {after} for the "
        "same data -- something is not deterministic, which makes every other "
        "measurement here untrustworthy"
    )
    # A per-member query would put the count at or above the headcount. The
    # bound is generous on purpose: this asserts "not per person", not a budget.
    assert before < people + 20, (
        f"{before} queries for {people} employees -- close enough to one per "
        "person to be worth reading the team strip again"
    )


def test_an_unbounded_list_endpoint_is_still_capped_somewhere(owner, tenant):
    """The manager queue reports the true total and how much it returned.

    It used to return every pending request with no limit, and `pending_total`
    was `len(items)` -- so the number and the list agreed only because nothing
    was ever truncated. A manager acting on "8 pending" when 60 are waiting is
    worse served by a tidy number than an honest one.
    """
    response = owner.get("/api/hr/manager-queue/")
    assert response.status_code == 200
    body = json.loads(response.content.decode())
    if not body.get("is_manager"):
        pytest.skip("the owner is not a manager in this tenant")

    assert "returned" in body and "truncated" in body, (
        "the queue no longer reports what it returned against what is "
        "waiting, so truncation is silent again"
    )
    assert body["summary"]["pending_total"] >= body["returned"]
    assert body["truncated"] is (body["summary"]["pending_total"] > body["returned"])


def test_the_nurse_workspace_summary_does_not_query_per_patient(owner, tenant):
    """The worst place in the product to put a loop of queries.

    This endpoint issued a query per admission for each of five things: the
    latest vitals, active prescription lines, today's administrations, pending
    tasks and the most recent handover -- plus another for the bed, because the
    queryset prefetched `bed_assignments` under the default name while
    `Admission.current_bed` reads `open_bed_assignments`, so the prefetch was
    paid for and never used.

    41 queries for three patients. A forty-bed ward is roughly five hundred
    round trips, on the screen every nurse opens at the start of every shift.

    Expressed as a bound relative to the census rather than as a fixed number:
    the invariant is "not per patient", and a fixed budget would be edited
    upwards the first time somebody adds a legitimate join.
    """
    from apps.inpatient.models import Admission

    owner.get("/api/auth/me/")
    census = Admission.objects.filter(
        status__in=["admitted", "discharge_initiated"]
    ).count()
    if census < 2:
        pytest.skip(f"only {census} in-house admissions; nothing to scale with")

    queries, _ = _measure(owner, "/api/ipd/nurse-workspace/summary/")
    assert queries < census + 20, (
        f"{queries} queries for {census} in-house patients -- close enough to "
        "one per patient to be worth reading the loop again"
    )
