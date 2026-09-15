"""The follow-up register: who is due, who did not come, who already has.

What these hold: status is derived from what happened rather than stored, so a
patient who came back is not chased; a recall says nothing clinical and is
sent once per follow-up however often the button is pressed; and reading the
register is a read while recalling is a write.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def encounter(tenant):
    from apps.encounters.models import Encounter

    row = Encounter.objects.select_related("patient").first()
    if row is None:
        pytest.skip("no demo encounters")
    return row


def _due(encounter, days):
    encounter.follow_up_date = timezone.localdate() + timedelta(days=days)
    encounter.follow_up_instructions = "Review the wound."
    encounter.save(update_fields=["follow_up_date", "follow_up_instructions", "updated_at"])


def test_a_date_ahead_is_due_and_a_date_passed_is_overdue(encounter):
    from apps.scheduling.followups import register

    _due(encounter, 5)
    rows = {row["reference"]: row for row in register()["results"]}
    assert rows[encounter.reference]["status"] in {"due", "booked", "attended"}

    _due(encounter, -10)
    row = {row["reference"]: row for row in register()["results"]}[encounter.reference]
    assert row["status"] in {"overdue", "booked", "attended"}
    if row["status"] == "overdue":
        assert row["days_overdue"] == 10


def test_somebody_who_came_back_is_not_chased(encounter, tenant):
    """The whole point of deriving the status: a stored one would have to be
    updated from four places, and the day one forgets, a patient who attended
    is asked to come in again."""
    from apps.encounters.models import Encounter
    from apps.scheduling.followups import register

    _due(encounter, -20)
    Encounter.objects.create(
        patient=encounter.patient,
        facility=encounter.facility,
        encounter_type=encounter.encounter_type,
        status=encounter.status,
        started_at=timezone.now() - timedelta(days=2),
        reference=f"ENC-FUP-{timezone.now().timestamp():.0f}",
    )
    row = {row["reference"]: row for row in register()["results"]}[encounter.reference]
    assert row["status"] == "attended"


def test_a_recall_says_nothing_clinical_and_is_sent_once(encounter, tenant):
    from apps.notifications.patient_outreach import PatientMessage
    from apps.scheduling.followups import recall

    patient = encounter.patient
    patient.consent_sms = True
    patient.phone = patient.phone or "9800000000"
    patient.save(update_fields=["consent_sms", "phone", "updated_at"])

    due_on = (timezone.localdate() - timedelta(days=2)).isoformat()
    PatientMessage.objects.filter(dedupe_key=f"followup:{encounter.reference}:{due_on}").delete()

    first = recall(patient, due_on, encounter.reference, overdue=True)
    assert first is not None
    assert "follow-up" in first.body.lower() or "फलोअप" in first.body
    for word in ("diagnos", "test", "result", encounter.reference.lower()):
        assert word not in first.body.lower(), "a recall message carried clinical detail"

    assert recall(patient, due_on, encounter.reference, overdue=True) is None, (
        "the same follow-up was chased twice"
    )


def test_the_register_opens_for_the_desk_and_recall_takes_a_write(tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    def client_for(email):
        user = User.objects.filter(email=email).first()
        if user is None:
            pytest.skip(f"no demo {email}")
        return Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=tenant.slug,
        )

    owner = client_for("owner@manakamana.test")
    listing = owner.get("/api/clinical/follow-ups/")
    assert listing.status_code == 200, listing.content
    assert set(listing.json()["counts"]) == {"due", "overdue", "booked", "attended"}

    auditor = client_for("auditor@manakamana.test")
    assert auditor.get("/api/clinical/follow-ups/").status_code == 200, (
        "read-only oversight could not read the register"
    )
    refused = auditor.post(
        "/api/clinical/follow-ups/recall/",
        {"patient": "00000000-0000-0000-0000-000000000000", "due_on": "2026-01-01", "reference": "X"},
        content_type="application/json",
    )
    assert refused.status_code == 403, "read-only oversight could send a patient a message"


def test_the_lapsed_report_is_registered(tenant):
    from apps.reporting.registry import get_report

    report = get_report("clinical.followups_lapsed")
    assert report is not None
    assert report.permission == "report.read"
