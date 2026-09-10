"""Booking a patient in, and who is allowed to.

§20 was built and unreachable. Provider schedules, slot generation, capacity,
overbooking, the walk-in reserve, schedule exceptions, booking with double-book
prevention, cancellation with a reason, no-show as distinct from cancellation --
twelve ticked items, no screen, and **no test that booked anything as the person
who books**.

That gap hid a real defect for the whole life of the feature. Booking required
`encounter.create`, which only `doctor` and `nurse` hold, so the `receptionist`
role -- whose own description reads "Registration, appointments and front-desk
billing" -- could not make an appointment. Nothing caught it because the demo
tenant had no receptionist either: `counter@` is the pharmacy till.

So these tests run as the receptionist deliberately. A test written as the owner
passes whatever the permissions are, and a test written as the doctor passes
whatever they were before this fix.
"""

import json
from datetime import date, datetime, timedelta

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
#: The front desk. The subject of almost every test here, because the front desk
#: is who books.
RECEPTION = f"reception@{DEMO}.test"
#: The pharmacy till -- not reception. Used to prove the diary stays shut to
#: somebody with no business in it.
TILL = f"counter@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


def _body(response):
    return json.loads(response.content.decode())


@pytest.fixture
def desk(tenant):
    client = _client(RECEPTION, tenant)
    if client is None:
        pytest.skip(f"no {RECEPTION}; run manage.py seed_demo")
    return client


@pytest.fixture
def facility(tenant):
    from apps.organization.models import Facility

    row = (
        Facility.objects.filter(facility_type="clinic").first()
        or Facility.objects.first()
    )
    if row is None:
        pytest.skip("no facility in the demo tenant")
    return row


@pytest.fixture
def session_day(tenant, facility):
    """A future date on which somebody is holding a session, and that session.

    Looks forward rather than using today, for two reasons. Today's slots may
    all be in the past, and `available_slots` rightly does not offer a time that
    has already gone; and booking into the future leaves today's demo diary
    alone.
    """
    from apps.scheduling.models import ProviderSchedule

    schedules = list(
        ProviderSchedule.objects.filter(facility=facility, is_active=True)
    )
    if not schedules:
        pytest.skip("no provider schedules in the demo tenant")

    # **`applies_on` decides, not this fixture.** The first version grouped the
    # schedules by `schedule.weekday` and looked them up by `day.weekday()` --
    # mixing two conventions, because this model numbers from Sunday and
    # Python's `weekday()` numbers from Monday. Every test skipped with "no
    # session in the next fortnight" against a tenant holding eighteen of them.
    # Asking the model is both correct and shorter than being correct by hand.
    for offset in range(1, 15):
        day = date.today() + timedelta(days=offset)
        for schedule in schedules:
            if schedule.applies_on(day):
                return day, schedule
    pytest.skip("no session in the next fortnight")


@pytest.fixture
def patient(tenant):
    from apps.patients.models import Patient, PatientStatus

    row = Patient.objects.exclude(status=PatientStatus.MERGED).first()
    if row is None:
        pytest.skip("no patients in the demo tenant")
    return row


@pytest.fixture
def booked(tenant):
    """Delete whatever a test booked, and only that.

    These run against the shared development tenant. An appointment left behind
    would sit in the demo diary forever and, worse, would consume capacity that
    a later run of these same tests needs.
    """
    made = []
    yield made
    from apps.scheduling.models import Appointment

    if made:
        Appointment.objects.filter(uuid__in=made).delete()


def _free_slots(client, schedule, day):
    response = client.get(
        f"/api/clinical/schedules/{schedule.uuid}/slots/?date={day.isoformat()}"
    )
    assert response.status_code == 200, response.content[:300]
    return _body(response)["free_slots"]


def _book(client, *, patient, facility, schedule, when, booked, **extra):
    response = client.post(
        "/api/clinical/appointments/",
        data=json.dumps({
            "patient_uuid": str(patient.uuid),
            "facility_uuid": str(facility.uuid),
            "scheduled_for": when,
            "schedule_uuid": str(schedule.uuid),
            "provider_uuid": str(schedule.provider_uuid),
            "provider_name": schedule.provider_name,
            "source": "counter",
            **extra,
        }),
        content_type="application/json",
    )
    if response.status_code == 201:
        booked.append(_body(response)["uuid"])
    return response


# -- the front desk can do front-desk work ---------------------------------


def test_the_receptionist_can_book_an_appointment(
    desk, patient, facility, session_day, booked
):
    """The test that would have caught it.

    The receptionist holds `visit.schedule` and **not** `encounter.create`. Until
    this was fixed, booking asked for the latter, so this returned 403 -- for the
    one role the feature exists to serve.
    """
    day, schedule = session_day
    slots = _free_slots(desk, schedule, day)
    assert slots, f"no free slots on {day} for {schedule.provider_name}"

    response = _book(
        desk, patient=patient, facility=facility, schedule=schedule,
        when=slots[0], booked=booked, reason="Cough for a week",
    )
    assert response.status_code == 201, response.content[:400]

    made = _body(response)
    assert made["patient_name"] == patient.full_name
    assert made["provider_name"] == schedule.provider_name
    assert made["reference"], "an appointment with no reference cannot be quoted"
    assert made["status"] == "scheduled", made["status"]


def test_the_receptionist_holds_none_of_encounter_create(tenant):
    """Stated as a fact, so the test above cannot quietly stop proving anything.

    If somebody later grants `encounter.create` to the receptionist, the booking
    test would keep passing while no longer testing the thing it was written
    for. This fails instead, and says why.
    """
    from apps.rbac.models import Role

    role = Role.objects.filter(code="receptionist").first()
    if role is None:
        pytest.skip("no receptionist role; run manage.py sync_roles")

    assert "visit.schedule" in role.permissions, (
        "the receptionist cannot book. Run manage.py sync_roles."
    )
    assert "encounter.create" not in role.permissions, (
        "the receptionist now holds encounter.create, which at facility scope "
        "also allows emergency triage and recording a blood transfusion. If "
        "that grant is deliberate, this test needs rewriting -- but the "
        "booking test above no longer proves that booking is separable from "
        "clinical recording, which is the whole point of visit.schedule."
    )


def test_a_free_slot_stops_being_free_once_it_is_booked(
    desk, patient, facility, session_day, booked
):
    """Double-book prevention, observed rather than assumed.

    Checked through the slots endpoint rather than by booking twice and reading
    the error, because it is the *diary the receptionist is looking at* that has
    to be right. A slot still offered after it is taken is a slot somebody will
    offer to a patient.
    """
    day, schedule = session_day
    if schedule.slot_capacity != 1:
        pytest.skip(
            f"{schedule.provider_name} allows {schedule.slot_capacity} per slot; "
            "this asserts the single-capacity case"
        )

    before = _free_slots(desk, schedule, day)
    assert before

    assert _book(
        desk, patient=patient, facility=facility, schedule=schedule,
        when=before[0], booked=booked,
    ).status_code == 201

    after = _free_slots(desk, schedule, day)
    assert before[0] not in after, (
        "the slot just booked is still being offered as free"
    )
    assert len(after) == len(before) - 1


def test_a_cancellation_must_say_why(
    desk, patient, facility, session_day, booked
):
    """"Why was this cancelled" is asked whenever a patient rings back."""
    day, schedule = session_day
    slots = _free_slots(desk, schedule, day)
    assert slots
    reference = _body(
        _book(desk, patient=patient, facility=facility, schedule=schedule,
              when=slots[0], booked=booked)
    )["uuid"]

    empty = desk.post(
        f"/api/clinical/appointments/{reference}/cancel/",
        data=json.dumps({"reason": ""}),
        content_type="application/json",
    )
    assert empty.status_code == 400

    good = desk.post(
        f"/api/clinical/appointments/{reference}/cancel/",
        data=json.dumps({"reason": "Patient rang to postpone"}),
        content_type="application/json",
    )
    assert good.status_code == 200, good.content[:300]
    assert _body(good)["status"] == "cancelled"
    assert _body(good)["cancellation_reason"] == "Patient rang to postpone"


def test_a_no_show_is_not_a_cancellation(
    desk, patient, facility, session_day, booked
):
    """Different facts, and a clinic acts on them differently.

    A cancellation frees the slot and is somebody telling you in advance. A
    no-show is a patient who did not come, and repeated ones are a reason to ask
    for a deposit. Collapsing them into one status loses the second question
    permanently.
    """
    day, schedule = session_day
    slots = _free_slots(desk, schedule, day)
    assert slots
    reference = _body(
        _book(desk, patient=patient, facility=facility, schedule=schedule,
              when=slots[0], booked=booked)
    )["uuid"]

    response = desk.post(f"/api/clinical/appointments/{reference}/no-show/")
    assert response.status_code == 200, response.content[:300]
    assert _body(response)["status"] == "no_show"
    assert _body(response)["cancelled_at"] is None, (
        "a no-show was recorded as a cancellation"
    )


def test_the_diary_answers_for_the_day_the_desk_asks_about(
    desk, patient, facility, session_day, booked
):
    """The screen asks by date, and the default is today.

    Worth pinning: an appointment list with no date filter grows without bound
    and is never what anybody wants, so the viewset defaults to today. A screen
    passing a date must get that date.
    """
    day, schedule = session_day
    slots = _free_slots(desk, schedule, day)
    assert slots
    made = _body(
        _book(desk, patient=patient, facility=facility, schedule=schedule,
              when=slots[0], booked=booked)
    )

    response = desk.get(
        f"/api/clinical/appointments/?facility={facility.uuid}"
        f"&date={day.isoformat()}"
    )
    assert response.status_code == 200
    uuids = {row["uuid"] for row in _body(response)["results"]}
    assert made["uuid"] in uuids

    # And it is *not* on a different day.
    other = day + timedelta(days=1)
    elsewhere = desk.get(
        f"/api/clinical/appointments/?facility={facility.uuid}"
        f"&date={other.isoformat()}"
    )
    assert made["uuid"] not in {r["uuid"] for r in _body(elsewhere)["results"]}


def test_the_availability_view_counts_room_not_slots(desk, facility, session_day):
    """Remaining capacity is what a receptionist needs, and they differ.

    With a slot capacity of two, a session of nine slots holding four bookings
    still has nine slots with room in them -- which reads as an empty diary. The
    number that answers "can I fit this patient in" is the remaining capacity.
    """
    day, _ = session_day
    response = desk.get(
        f"/api/clinical/availability/?facility={facility.uuid}&date={day.isoformat()}"
    )
    assert response.status_code == 200, response.content[:300]
    sessions = _body(response)["sessions"]
    assert sessions, f"no sessions on {day}, but session_day found one"

    for entry in sessions:
        assert entry["capacity"] == entry["total_slots"] * entry["slot_capacity"]
        assert entry["remaining_capacity"] == max(
            entry["capacity"] - entry["booked"], 0
        )
        assert entry["provider_name"]


# -- and the diary stays shut to everybody else ----------------------------


def test_the_pharmacy_till_cannot_open_the_consultation_diary(tenant):
    """`counter@` is the pharmacy counter, not reception.

    Named explicitly because the two are easy to confuse -- the confusion is
    exactly why this feature's permissions went unnoticed for so long.
    """
    till = _client(TILL, tenant)
    if till is None:
        pytest.skip(f"no {TILL}")
    assert till.get("/api/clinical/appointments/").status_code == 403


def test_booking_is_refused_without_the_permission(tenant, patient, facility):
    """A 403 on the write, not a silent no-op."""
    till = _client(TILL, tenant)
    if till is None:
        pytest.skip(f"no {TILL}")
    response = till.post(
        "/api/clinical/appointments/",
        data=json.dumps({
            "patient_uuid": str(patient.uuid),
            "facility_uuid": str(facility.uuid),
            "scheduled_for": datetime.now().isoformat(),
            "source": "counter",
        }),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content[:300]
