"""What the hospital says to the patient, and what it does not.

A clinic loses a fifth of its outpatient slots to people who simply forgot,
and the fix is a text the evening before. The danger in that text is the other
half: a message read off a lock screen by whoever is holding the phone. So
these check the reminder goes once, in the patient's language, to somebody who
agreed to be contacted — and that a result message says a result exists and
nothing whatever about what it says.
"""

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def tomorrow(tenant):
    """One appointment tomorrow, for a patient who accepts texts."""
    from datetime import timedelta

    from apps.patients.models import Patient
    from apps.scheduling.models import Appointment, AppointmentStatus

    appointment = (
        Appointment.objects.select_related("patient", "facility")
        .filter(patient__isnull=False)
        .order_by("-scheduled_for")
        .first()
    )
    if appointment is None:
        pytest.skip("no appointments in the demo diary")

    when = timezone.localtime() + timedelta(days=1)
    Appointment.objects.filter(pk=appointment.pk).update(
        scheduled_for=when.replace(hour=11, minute=15, second=0, microsecond=0),
        status=AppointmentStatus.SCHEDULED,
    )
    Patient.objects.filter(pk=appointment.patient_id).update(
        phone="+977-9800000777", consent_sms=True, preferred_language="ne",
    )
    appointment.refresh_from_db()
    appointment.patient.refresh_from_db()
    return appointment


@pytest.fixture
def gateway(monkeypatch):
    """A gateway that accepts everything and remembers what it was given."""
    from apps.notifications import delivery

    sent = []
    monkeypatch.setattr(
        delivery, "send_sms",
        lambda to, text: (sent.append((to, text)) or (True, "ok")),
    )
    monkeypatch.setattr(
        delivery, "send_email",
        lambda to, subject, body: (sent.append((to, body)) or (True, "ok")),
    )
    return sent


def test_tomorrows_appointment_is_reminded_once(tomorrow, gateway):
    from apps.notifications.patient_outreach import (
        OutreachStatus,
        PatientMessage,
        remind_tomorrows_appointments,
    )

    first = remind_tomorrows_appointments()
    assert first["sent"] >= 1, first

    row = PatientMessage.objects.filter(
        dedupe_key=f"appointment:{tomorrow.reference}",
    ).first()
    assert row is not None and row.status == OutreachStatus.SENT
    assert row.language == "ne"
    assert "११:१५" in row.body or "11:15" in row.body, row.body
    assert tomorrow.facility.name in row.body

    before = len(gateway)
    second = remind_tomorrows_appointments()
    assert second["already"] >= 1
    assert len(gateway) == before, "the sweep texted the same patient twice"


def test_the_reminder_says_nothing_about_why_they_are_coming(tomorrow, gateway):
    from apps.notifications.patient_outreach import (
        PatientMessage,
        remind_tomorrows_appointments,
    )

    remind_tomorrows_appointments()
    row = PatientMessage.objects.get(dedupe_key=f"appointment:{tomorrow.reference}")
    forbidden = [
        tomorrow.patient.full_name,          # a name identifies the patient to a reader
        tomorrow.provider_name or "\0",      # and a consultant identifies the specialty
    ]
    for word in forbidden:
        assert word not in row.body, f"the reminder discloses {word!r}"


def test_a_patient_who_refused_is_recorded_as_refusing(tomorrow, gateway):
    from apps.notifications.patient_outreach import (
        OutreachStatus,
        PatientMessage,
        remind_tomorrows_appointments,
    )
    from apps.patients.models import Patient

    Patient.objects.filter(pk=tomorrow.patient_id).update(
        consent_sms=False, consent_email=False, email="",
    )
    remind_tomorrows_appointments()

    row = PatientMessage.objects.get(dedupe_key=f"appointment:{tomorrow.reference}")
    assert row.status == OutreachStatus.DECLINED
    assert gateway == [], "a patient who said no was messaged anyway"
    assert "not agreed" in row.detail


def test_a_patient_with_no_number_is_recorded_as_unreachable(tomorrow, gateway):
    from apps.notifications.patient_outreach import (
        OutreachStatus,
        PatientMessage,
        remind_tomorrows_appointments,
    )
    from apps.patients.models import Patient

    Patient.objects.filter(pk=tomorrow.patient_id).update(phone="", email="")
    remind_tomorrows_appointments()

    row = PatientMessage.objects.get(dedupe_key=f"appointment:{tomorrow.reference}")
    assert row.status == OutreachStatus.UNREACHABLE
    assert "No phone number" in row.detail


def test_a_cancelled_appointment_is_not_reminded(tomorrow, gateway):
    from apps.notifications.patient_outreach import (
        PatientMessage,
        remind_tomorrows_appointments,
    )
    from apps.scheduling.models import Appointment, AppointmentStatus

    Appointment.objects.filter(pk=tomorrow.pk).update(
        status=AppointmentStatus.CANCELLED,
    )
    remind_tomorrows_appointments()
    assert not PatientMessage.objects.filter(
        dedupe_key=f"appointment:{tomorrow.reference}",
    ).exists()
    assert gateway == []


def test_a_result_message_never_carries_the_result(tenant, gateway):
    """"Your HIV result is ready" read off a lock screen by somebody else is a
    disclosure the hospital made."""
    from apps.diagnostics.models import DiagnosticOrder, OrderStatus
    from apps.notifications.patient_outreach import (
        PatientMessage,
        tell_patient_result_ready,
    )
    from apps.patients.models import Patient

    order = (
        DiagnosticOrder.objects.filter(status=OrderStatus.RELEASED, patient__isnull=False)
        .select_related("patient", "test", "facility")
        .first()
    )
    if order is None:
        pytest.skip("no released orders in the demo data")
    Patient.objects.filter(pk=order.patient_id).update(
        phone="+977-9800000778", consent_sms=True, preferred_language="ne",
    )
    order.patient.refresh_from_db()

    row = tell_patient_result_ready(order)
    assert row is not None
    body = row.body
    assert order.test.name not in body, "the message names the test"
    assert order.patient.full_name not in body
    assert order.reference not in body
    assert PatientMessage.objects.filter(dedupe_key=f"result:{order.reference}").exists()
