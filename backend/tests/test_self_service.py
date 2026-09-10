"""What an employee may see about themselves, and what they still may not.

**The contradiction these tests close.** Self-service was built on permissions
that answer a different question. `attendance.read` means "may see the
facility's attendance"; `salary.read` means "may see what everybody was paid".
Requiring either one before showing somebody *their own* row meant a doctor
could not open their own timesheet unless an administrator also made them an
HR clerk. Measured with `manage.py audit_screens --screen SelfService`: six of
the fourteen endpoints the screen calls returned 403 to the demo doctor,
counter assistant and pharmacist -- three of the five roles that have the most
use for it.

The fix is the principle already used by `/api/auth/me/`: **an endpoint whose
subject and object are the same person authenticates, then scopes to the
caller.** `scope_or_own` is that principle as one function.

The tests worth having are therefore in two halves, and the second half is the
important one:

1. the employee can reach their own rows without the HR permission, and
2. **they still cannot reach anybody else's.** A fix that opened the list to
   everybody would pass the first half perfectly. Every test below that names
   a refusal exists to prove the fix did not do that -- particularly
   `test_the_staff_directory_is_still_closed`, because the dropdown this work
   fixed was being fed from the staff directory, and the tempting fix was to
   open it.
"""

import json
from datetime import timedelta

import pytest

# `transaction=False` deliberately: these run against the shared development
# tenant (see `conftest.django_db_setup`), and `transaction=True` truncates it.
pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"

#: The demo doctor holds none of `attendance.read`, `employee.read` or
#: `salary.read` -- which is exactly why they are the right subject here. A
#: test written as the owner would pass no matter how broken the scoping was.
EMPLOYEE_EMAIL = f"doctor@{DEMO}.test"


def _client(email, tenant):
    """A signed-in Django test client for one demo account.

    Mints a token directly rather than POSTing to `/api/auth/login/`: the
    subject here is authorization, and routing every test through the login
    view would make a login regression look like six scoping failures.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None, None
    return (
        Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=tenant.slug,
        ),
        user,
    )


def _body(response):
    return json.loads(response.content.decode())


def _rows(payload):
    """Both list shapes this API returns, so a test reads the same either way."""
    if isinstance(payload, dict):
        return payload.get("results", [])
    return payload


@pytest.fixture
def employee(tenant):
    """The demo doctor's Employee record, skipping if the tenant is unseeded."""
    from apps.hr.models import Employee
    from apps.identity.models import User

    user = User.objects.filter(email=EMPLOYEE_EMAIL).first()
    if user is None:
        pytest.skip(f"no {EMPLOYEE_EMAIL}; run manage.py bootstrap")
    record = Employee.for_user(user.uuid)
    if record is None:
        pytest.skip(f"{EMPLOYEE_EMAIL} is not linked to an employee record")
    return record


@pytest.fixture
def colleague(tenant, employee):
    """Another active employee, needed to prove the scoping actually excludes.

    Without a second person in the data, "you see only your own rows" is
    indistinguishable from "you see every row", and a test that cannot tell
    those apart is not a test. Skipping is honest where passing would not be.
    """
    from apps.hr.models import Employee, EmployeeStatus

    other = (
        Employee.objects.filter(status=EmployeeStatus.ACTIVE)
        .exclude(pk=employee.pk)
        .first()
    )
    if other is None:
        pytest.skip("only one active employee in the demo tenant")
    return other


@pytest.fixture
def two_attendance_rows(tenant, employee, colleague):
    """One attendance row for the caller and one for somebody else.

    Created here rather than relied upon in the seed. The seeded volume drifts
    as the seeds change, and a scoping test that silently passes because the
    table happens to be empty is the exact failure mode this whole audit is
    about. Deleted afterwards, and **only the two rows this created** -- these
    run against a shared development tenant, so a broad cleanup would delete
    somebody's real demo data.
    """
    from django.utils import timezone

    from apps.hr.attendance_models import Attendance

    # Far enough back that no seeded or hand-made row shares the date, so the
    # `get_or_create` below cannot adopt and then delete a pre-existing row.
    date = timezone.localdate() - timedelta(days=275)
    facility_id = employee.facility_id or colleague.facility_id
    if facility_id is None:
        pytest.skip("demo employees have no facility")

    mine, mine_created = Attendance.objects.get_or_create(
        employee=employee, date=date,
        defaults={"facility_id": facility_id, "status": "present"},
    )
    theirs, theirs_created = Attendance.objects.get_or_create(
        employee=colleague, date=date,
        defaults={"facility_id": colleague.facility_id or facility_id,
                  "status": "present"},
    )
    try:
        yield mine, theirs
    finally:
        if mine_created:
            mine.delete()
        if theirs_created:
            theirs.delete()


# -- the employee can reach their own ---------------------------------------


def test_an_employee_sees_their_own_attendance_without_the_hr_permission(
    tenant, employee, two_attendance_rows
):
    """403 before this work; the screen showed an error instead of a timesheet."""
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/attendance/")
    assert response.status_code == 200, response.content[:400]

    uuids = {row["uuid"] for row in _rows(_body(response))}
    assert str(two_attendance_rows[0].uuid) in uuids, (
        "the caller's own attendance row is missing from their own list"
    )


def test_attendance_does_not_show_an_employee_anybody_else_s(
    tenant, employee, two_attendance_rows
):
    """The half that proves the fix scoped rather than opened.

    A `scope_or_own` that fell through to "return everything" -- which is what
    `apply_scope_filter` itself did before it was fixed, and for three
    separate scopes -- would pass the test above and fail this one.
    """
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/attendance/")
    assert response.status_code == 200

    rows = _rows(_body(response))
    assert rows, "no rows at all; this test would pass vacuously"
    theirs = str(two_attendance_rows[1].uuid)
    assert theirs not in {row["uuid"] for row in rows}, (
        "an employee with no attendance.read is being shown a colleague's "
        "attendance"
    )


def test_mine_true_narrows_even_for_somebody_who_could_see_more(
    tenant, two_attendance_rows
):
    """`?mine=true` is a narrowing, not a no-op.

    The self-service screen passes it so that a ward manager opening their own
    timesheet gets their own and not the whole ward's. Checked as the owner,
    who can see everything, because that is the only caller for whom the
    parameter can be observed to do anything at all.
    """
    client, _ = _client(f"owner@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no owner account")

    everything = _rows(_body(client.get("/api/hr/attendance/")))
    mine = _rows(_body(client.get("/api/hr/attendance/?mine=true")))
    assert len(mine) < len(everything) or not everything, (
        "?mine=true returned as much as the unfiltered list, so it is "
        "filtering nothing"
    )


@pytest.fixture
def two_regularisations(tenant, two_attendance_rows):
    """A correction request from the caller and one from somebody else.

    Created rather than sought, and for a sharper reason than the attendance
    fixture: the demo tenant seeds **no** regularisations, so a test that
    looked for them skipped -- which left the most serious defect in this
    change set (a list that checked a permission and then ignored it) with no
    guard at all. A skip is honest about data and silent about safety.
    """
    from apps.hr.attendance_models import AttendanceRegularisation

    mine, theirs = two_attendance_rows
    rows = [
        AttendanceRegularisation.objects.create(
            attendance=attendance,
            reason="self-service scoping test",
            requested_by_name="test",
        )
        for attendance in (mine, theirs)
    ]
    try:
        yield rows[0], rows[1]
    finally:
        for row in rows:
            row.delete()


def test_regularisations_are_scoped_to_the_caller(
    tenant, employee, two_regularisations
):
    """This list had no scope filter at all.

    `attendance.read` was *checked* and then the queryset was returned
    unfiltered, so the grant the `staff` role hands every employee returned
    every correction request in the organization -- with the reason text, which
    is where people write "child's surgery". The permission gate made it look
    guarded.
    """
    mine, theirs = two_regularisations

    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/regularisations/")
    assert response.status_code == 200, response.content[:400]

    uuids = {row["uuid"] for row in _rows(_body(response))}
    assert str(mine.uuid) in uuids, "the caller cannot see their own request"
    assert str(theirs.uuid) not in uuids, (
        "an employee is being shown other people's correction requests"
    )


def test_leave_types_are_readable_by_anybody_signed_in(tenant, employee):
    """You cannot request leave from a dropdown you are forbidden to load.

    This required `attendance.read`, so the reference list needed to *ask for*
    leave depended on permission to read everybody's attendance. Leave types
    are published policy -- the entitlement and whether it is paid is on the
    notice board -- so there was never anything here to withhold.
    """
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/leave-types/")
    assert response.status_code == 200, response.content[:400]
    assert _rows(_body(response)), "no leave types seeded; nothing to request"


def test_the_swap_peer_list_carries_only_what_the_dropdown_renders(
    tenant, employee, colleague
):
    """Three fields, and not the caller.

    The swap form was filling this dropdown from `/hr/employees/` -- the staff
    directory, which carries salary band, address, citizenship number and
    documents. The fix answers the smaller question instead. If this ever
    grows a fourth field, that is worth noticing deliberately rather than
    discovering in a response body.
    """
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/shift-swaps/peers/")
    assert response.status_code == 200, response.content[:400]

    rows = _rows(_body(response))
    assert rows, "no peers returned; the swap dropdown would be empty"
    assert all(
        set(row) == {"uuid", "full_name", "code"} for row in rows
    ), f"peer rows carry unexpected fields: {sorted(rows[0])}"
    assert str(employee.uuid) not in {row["uuid"] for row in rows}, (
        "you are offered a shift swap with yourself"
    )


# -- and still cannot reach anybody else's ---------------------------------


def test_the_staff_directory_is_still_closed(tenant, employee):
    """The tempting fix, and why it was not taken.

    `/hr/employees/` was 403 for the doctor and the screen needed names from
    it, so the one-line fix was to drop its permission. That list is the HR
    record. It stays shut; `peers` exists because of it.
    """
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.get("/api/hr/employees/")
    assert response.status_code == 403, (
        "the staff directory is open to an employee with no employee.read: "
        f"{response.status_code} {response.content[:200]}"
    )


def test_everybody_s_payslips_still_need_salary_read(tenant, employee):
    """`payslips/mine/` is open; `payslips/` is not, and that asymmetry is the point."""
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    assert client.get("/api/payroll/payslips/").status_code == 403
    assert client.get("/api/payroll/payslips/mine/").status_code in (200, 204)


def test_an_employee_cannot_create_a_leave_type(tenant, employee):
    """Creation is refused -- though not by the permission class.

    Worth being exact about, because I first wrote this test believing it
    proved the `write=` declaration and it does not: `perform_create` calls
    `require("config.read", Scope.ORGANIZATION)` itself, so the POST is
    refused even with the permission class defeated. The test is still worth
    keeping -- it pins the outcome that matters -- but the guard it exercises
    is the one in the service layer. `test_an_employee_cannot_edit_a_leave_type`
    below is the one that exercises the permission class.
    """
    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.post(
        "/api/hr/leave-types/",
        data=json.dumps({"code": "test_ss", "name": "Self-service test",
                         "annual_entitlement": "99.00"}),
        content_type="application/json",
    )
    assert response.status_code == 403, (
        "an employee can create a leave type: "
        f"{response.status_code} {response.content[:300]}"
    )


def test_an_employee_cannot_edit_a_leave_type(tenant, employee):
    """The read is open; the write is not -- and that nearly went wrong.

    **Measured, not assumed.** Declaring the open read as
    `HasPermission.of(None, write="employee.manage")` exposed a latent hole:
    `has_permission` used to `return True` outright on an empty read code, so
    the `write=` branch below it was never reached. Putting that line back and
    running this test as the demo doctor changed a real leave type's annual
    entitlement **from 18 days to 97, with a 200** -- no second check
    anywhere, because `perform_update` has none. Removing it again returned
    403 with the value untouched.

    That is why this asserts the stored value as well as the status. A 403 with
    the row already written would look like a pass.

    PATCH rather than POST because PATCH is the verb with nothing behind it,
    and an entitlement decides accrual, which decides attendance, which decides
    payroll -- an employee editing this is an employee editing their own pay.
    """
    from apps.hr.attendance_models import LeaveType

    leave = LeaveType.objects.filter(is_active=True).first()
    if leave is None:
        pytest.skip("no leave types seeded")
    before = leave.annual_entitlement

    client, _ = _client(EMPLOYEE_EMAIL, tenant)
    response = client.patch(
        f"/api/hr/leave-types/{leave.code}/",
        data=json.dumps({"annual_entitlement": "97.00"}),
        content_type="application/json",
    )
    leave.refresh_from_db()
    # Put it back before asserting, so a failure does not also leave the demo
    # tenant with a 97-day leave entitlement for everybody to puzzle over.
    written = leave.annual_entitlement
    if written != before:
        LeaveType.objects.filter(pk=leave.pk).update(annual_entitlement=before)

    assert response.status_code == 403, (
        f"an employee can edit leave entitlements: {response.status_code}"
    )
    assert written == before, (
        f"the entitlement was written anyway: {before} -> {written}"
    )


def test_none_of_this_is_reachable_without_signing_in(tenant):
    """Self-service scopes to the caller, so there must *be* a caller.

    An `IsAuthenticated`-only viewset is one forgotten permission class away
    from `AllowAny`, and the failure is invisible -- the list simply returns
    something. Worth one cheap test across all four.
    """
    from django.test import Client

    anonymous = Client(HTTP_X_ORGANIZATION=tenant.slug)
    for path in (
        "/api/hr/attendance/",
        "/api/hr/regularisations/",
        "/api/hr/leave-types/",
        "/api/hr/shift-swaps/peers/",
    ):
        assert anonymous.get(path).status_code in (401, 403), (
            f"{path} answered an anonymous caller"
        )
