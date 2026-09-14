"""The discussion about a patient: who may read it, and who is told.

What these hold: somebody with clinical access can post and read; somebody
without it (a receptionist) cannot read a word; a colleague added to a message
is notified, with an urgent message raised as a warning; somebody who is not a
member of this organization cannot be notified through it; and a new message
rings the patient's doorbell only after it is committed.
"""

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


def _client(tenant, email):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.get(email=email)
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    ), user


def _patient():
    from apps.patients.models import Patient

    patient = Patient.objects.exclude(status="merged").first()
    if patient is None:
        pytest.skip("no demo patients")
    return patient


def test_a_clinician_can_post_and_read(tenant):
    client, owner = _client(tenant, "owner@manakamana.test")
    patient = _patient()

    posted = client.post(
        f"/api/clinical/patients/{patient.uuid}/discussion/",
        {"body": "BP 88/50 on the last round, please review."},
        content_type="application/json",
    )
    assert posted.status_code == 201, posted.content

    listed = client.get(f"/api/clinical/patients/{patient.uuid}/discussion/")
    assert listed.status_code == 200
    bodies = [row["body"] for row in listed.json()["results"]]
    assert "BP 88/50 on the last round, please review." in bodies
    mine = [row for row in listed.json()["results"] if row["body"].startswith("BP 88/50")][0]
    assert mine["is_mine"] is True and mine["author_name"]


def test_a_receptionist_cannot_read_the_discussion(tenant):
    from apps.identity.models import User

    if not User.objects.filter(email="reception@manakamana.test").exists():
        pytest.skip("no demo receptionist")
    client, _ = _client(tenant, "reception@manakamana.test")
    response = client.get(f"/api/clinical/patients/{_patient().uuid}/discussion/")
    assert response.status_code == 403


def test_an_added_colleague_is_notified_and_urgent_is_a_warning(tenant):
    from apps.identity.models import User
    from apps.notifications.models import NotificationCategory, NotificationReceipt

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor")
    client, _ = _client(tenant, "owner@manakamana.test")
    patient = _patient()

    response = client.post(
        f"/api/clinical/patients/{patient.uuid}/discussion/",
        {"body": "Potassium 6.1, please see now.", "urgent": True, "mentions": [str(doctor.uuid)]},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content

    receipt = (
        NotificationReceipt.objects.filter(recipient_id=doctor.uuid)
        .select_related("notification")
        .order_by("-created_at")
        .first()
    )
    assert receipt is not None, "the colleague added to the message was not told"
    assert receipt.notification.category == NotificationCategory.WARNING
    assert str(patient.uuid) in receipt.notification.link


def test_a_stranger_cannot_be_notified_through_the_record(tenant):
    """A mention is resolved against this organization's members; any other id
    is dropped, so the discussion cannot be used to reach outside it."""
    import uuid

    from apps.notifications.models import NotificationReceipt

    client, _ = _client(tenant, "owner@manakamana.test")
    stranger = uuid.uuid4()
    response = client.post(
        f"/api/clinical/patients/{_patient().uuid}/discussion/",
        {"body": "Anybody?", "mentions": [str(stranger)]},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.json()["mentions"] == []
    assert not NotificationReceipt.objects.filter(recipient_id=stranger).exists()


def test_an_empty_message_is_refused(tenant):
    client, _ = _client(tenant, "owner@manakamana.test")
    response = client.post(
        f"/api/clinical/patients/{_patient().uuid}/discussion/",
        {"body": "   "},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_a_message_rings_the_patient_after_commit(tenant, django_capture_on_commit_callbacks, monkeypatch):
    from apps.identity.models import User
    from apps.patients.discussion import post_message
    from apps.realtime import publish

    rung = []
    monkeypatch.setattr(publish, "ring", lambda topic, **kwargs: rung.append(topic))
    owner = User.objects.get(email="owner@manakamana.test")
    patient = _patient()

    with django_capture_on_commit_callbacks(execute=True):
        post_message(patient, owner, "Seen and reviewed.")
    assert f"patient.{patient.uuid}" in rung


def test_colleagues_are_searchable_by_name(tenant):
    client, _ = _client(tenant, "owner@manakamana.test")
    response = client.get("/api/clinical/colleagues/?q=sa")
    assert response.status_code == 200
    assert all({"id", "name"} <= set(row) for row in response.json()["results"])
