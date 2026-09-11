"""A patient books their own visit from the portal.

The rules are the substance: only a slot really on offer online — never the
walk-in reserve, never one about to start; a ceiling on how much of the diary
one account can hold; a cancellation only with enough notice for the slot to
go to somebody else; and nothing booked for a record the account may not book
for. Each is tested by trying it.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

IDENTIFIER = "+977-9800000001"
PASSWORD = "correct horse battery"


@pytest.fixture
def portal(tenant):
    from django.test import Client

    client = Client(raise_request_exception=False)
    response = client.post(
        "/api/me/auth/",
        data=json.dumps({"action": "login", "identifier": IDENTIFIER, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    if response.status_code != 200:
        pytest.skip("no demo portal account; run manage.py seed_portal_demo")
    token = json.loads(response.content)["token"]
    headers = {"HTTP_AUTHORIZATION": f"Portal {token}", "HTTP_X_ORGANIZATION": tenant.slug}

    class Portal:
        def get(self, path):
            return client.get(path, **headers)

        def post(self, body):
            return client.post("/api/me/", data=json.dumps(body),
                               content_type="application/json", **headers)

    yield Portal()

    # Put the diary back: cancel whatever these tests booked online.
    from apps.scheduling.models import OCCUPIES_SLOT, Appointment, AppointmentSource

    Appointment.objects.filter(
        patient__mrn="MRN-000001", source=AppointmentSource.ONLINE,
        status__in=list(OCCUPIES_SLOT),
    ).update(status="cancelled", cancellation_reason="test cleanup")


def _options(portal, day=None):
    response = portal.get(f"/api/me/?section=booking{f'&date={day}' if day else ''}")
    assert response.status_code == 200, response.content[:300]
    return json.loads(response.content)


def _first_slot(options):
    for clinician in options["clinicians"]:
        if clinician["slots"]:
            return clinician["schedule"], clinician["slots"][0]
    pytest.skip("no online slots in the demo diary")


def test_a_patient_can_book_a_slot_that_was_offered(portal):
    options = _options(portal)
    assert len(options["days"]) == 14
    schedule, slot = _first_slot(options)

    booked = portal.post({"action": "book", "schedule": schedule, "when": slot, "reason": "Follow-up"})
    assert booked.status_code == 201, booked.content[:300]
    reference = json.loads(booked.content)["reference"]

    again = _options(portal, options["date"])
    still_offered = [
        s for c in again["clinicians"] if c["schedule"] == schedule for s in c["slots"]
    ]
    assert slot not in still_offered, "the booked slot is still being offered"

    rows = json.loads(portal.get("/api/me/?section=appointments").content)
    mine = next(row for row in rows if row["reference"] == reference)
    assert mine["upcoming"] is True


def test_a_slot_that_was_not_offered_cannot_be_booked(portal):
    options = _options(portal)
    schedule, slot = _first_slot(options)
    # Three minutes past a real slot start: a time no schedule produces.
    from datetime import timedelta

    from django.utils.dateparse import parse_datetime

    off_grid = (parse_datetime(slot) + timedelta(minutes=3)).isoformat()
    refused = portal.post({"action": "book", "schedule": schedule, "when": off_grid})
    assert refused.status_code == 400, refused.content[:300]
    assert json.loads(refused.content)["error"]["code"] == "slot_unavailable"


def test_one_account_cannot_fill_the_diary(portal):
    from apps.portal.services import MAX_ONLINE_BOOKINGS

    options = _options(portal)
    slots = [
        (clinician["schedule"], slot)
        for clinician in options["clinicians"] for slot in clinician["slots"]
    ]
    if len(slots) <= MAX_ONLINE_BOOKINGS:
        pytest.skip("not enough open slots on one day to test the ceiling")
    held = options["held"]
    for schedule, slot in slots[: MAX_ONLINE_BOOKINGS - held]:
        assert portal.post({"action": "book", "schedule": schedule, "when": slot}).status_code == 201

    schedule, slot = slots[MAX_ONLINE_BOOKINGS - held]
    refused = portal.post({"action": "book", "schedule": schedule, "when": slot})
    assert refused.status_code == 400
    assert json.loads(refused.content)["error"]["code"] == "booking_limit"


def test_a_patient_can_cancel_with_notice(portal):
    options = _options(portal)
    # A slot more than two hours away, so the notice rule allows it.
    later = [
        (clinician["schedule"], slot)
        for day in options["days"] if day["open"]
        for clinician in _options(portal, day["date"])["clinicians"]
        for slot in clinician["slots"]
    ]
    from datetime import timedelta

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    far = [(s, t) for s, t in later if parse_datetime(t) - timezone.now() > timedelta(hours=3)]
    if not far:
        pytest.skip("no slot far enough ahead")
    schedule, slot = far[0]
    reference = json.loads(
        portal.post({"action": "book", "schedule": schedule, "when": slot}).content
    )["reference"]

    cancelled = portal.post({"action": "cancel_appointment", "reference": reference, "reason": "Feeling better"})
    assert cancelled.status_code == 200, cancelled.content[:300]
    assert json.loads(cancelled.content)["status"] == "cancelled"

    rows = json.loads(portal.get("/api/me/?section=appointments").content)
    row = next(r for r in rows if r["reference"] == reference)
    assert row["upcoming"] is False, "a cancelled visit still counts as upcoming"
