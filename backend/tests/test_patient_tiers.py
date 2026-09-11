"""Two patient endpoints that answered for a tier they did not belong to.

`docs/ACCESS_DESIGN.md` divides a patient's record into three tiers:

| Tier | Permission | Who |
|---|---|---|
| Identity | `patient.read` | every front desk — name, MRN, contact |
| Safety | `patient.safety.read` | clinical and pharmacy roles — allergies, active medications. Logged |
| Clinical | `patient.clinical.read` + a care relationship | encounters, diagnoses, results |

Found while building the patient record page, which would have put both of
these one click from every front desk:

* **`/clinical/patients/<uuid>/medications/`** — Safety-tier data behind
  the Identity permission, and the read was not logged at all.
* **`/clinical/patients/<uuid>/summary/`** — Clinical-tier data (recent
  encounters *and their diagnoses*) behind the Identity permission, with no
  care-relationship check. It was logged, which made the read discoverable
  afterwards and did nothing to prevent it.

`PatientResultsView` had been written correctly all along and is the pattern
both now follow.

**Each test asserts the refusal and the legitimate path together.** A test that
only checks the receptionist is refused passes just as happily when the change
has refused the doctor too, which is the more dangerous regression: a clinician
locked out of the medication list is how somebody prescribes a duplicate.
"""
import pytest

pytestmark = pytest.mark.django_db(databases="__all__")


def _client(email: str, slug: str):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        pytest.skip(f"demo user {email} missing; run seed_demo")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=slug,
    )


def _any_patient():
    from apps.patients.models import Patient

    patient = Patient.objects.exclude(status="merged").first()
    if patient is None:
        pytest.skip("no patients seeded")
    return patient


# ---------------------------------------------------------------------------
# Safety tier — active medications
# ---------------------------------------------------------------------------


def test_a_receptionist_cannot_read_active_medications(tenant):
    """Identity tier holds name and MRN, not what somebody is taking."""
    patient = _any_patient()
    client = _client("reception@manakamana.test", tenant.slug)

    response = client.get(f"/api/clinical/patients/{patient.uuid}/medications/")
    assert response.status_code == 403, (
        "a front-desk role read a patient's active medications — the Safety "
        f"tier requires patient.safety.read; got {response.status_code}"
    )


def test_a_doctor_can_still_read_active_medications(tenant):
    """The legitimate path, asserted beside the refusal.

    Safety is organization-wide by design — "withholding this is the dangerous
    option" — so a doctor needs no care relationship here, and this must keep
    returning 200 whether or not the relationship switch is on.
    """
    from tests.test_invariants import _privacy_switch

    patient = _any_patient()
    client = _client("doctor@manakamana.test", tenant.slug)
    path = f"/api/clinical/patients/{patient.uuid}/medications/"

    try:
        _privacy_switch(True)
        response = client.get(path)
        assert response.status_code == 200, (
            "a doctor was refused the medication list with the relationship "
            "switch on. Safety is deliberately not relationship-gated; a "
            "clinician who cannot see what a patient is taking prescribes a "
            f"duplicate. Got {response.status_code}"
        )
    finally:
        _privacy_switch(None)


def test_reading_active_medications_is_logged(tenant):
    """The design requires it, and the view did not do it."""
    from apps.audit.models import AuditEvent

    patient = _any_patient()
    client = _client("doctor@manakamana.test", tenant.slug)

    before = AuditEvent.objects.filter(
        entity_type="patients.Patient", entity_id=str(patient.uuid),
    ).count()
    response = client.get(f"/api/clinical/patients/{patient.uuid}/medications/")
    assert response.status_code == 200, response.content

    after = AuditEvent.objects.filter(
        entity_type="patients.Patient", entity_id=str(patient.uuid),
    ).count()
    assert after == before + 1, (
        "reading a patient's active medications left no audit record — "
        "'who looked at this?' is the question asked after a privacy "
        "complaint, and it cannot be answered unless the read was recorded"
    )


# ---------------------------------------------------------------------------
# Clinical tier — the clinical summary
# ---------------------------------------------------------------------------


def test_a_receptionist_cannot_read_the_clinical_summary(tenant):
    """Diagnoses are Clinical tier. The front desk holds Identity."""
    patient = _any_patient()
    client = _client("reception@manakamana.test", tenant.slug)

    response = client.get(f"/api/clinical/patients/{patient.uuid}/summary/")
    assert response.status_code == 403, (
        "a front-desk role read a patient's diagnoses through the clinical "
        f"summary; got {response.status_code}"
    )


def test_the_clinical_summary_honours_the_care_relationship(tenant):
    """Off by default, then on — the same shape as the results test.

    With the switch off (the default, because a single-site clinic gains
    nothing from it) a doctor reads any patient's summary. With it on, a doctor
    with no relationship to this patient is refused — and the refusal must
    come from the object-level check, which a plain `APIView` only runs when
    `check_object_permissions` is called explicitly.
    """
    from apps.identity.models import Membership, User
    from apps.patients.models import Patient
    from apps.rbac.models import BreakGlassGrant
    from apps.rbac.relationships import related_patient_ids
    from apps.rbac.services import resolve_authorization
    from tests.test_invariants import _privacy_switch

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("demo users missing")

    authorization = resolve_authorization(
        doctor, Membership.objects.get(user=doctor, organization=tenant),
    )
    mine = related_patient_ids(doctor.uuid, authorization) or set()
    stranger = Patient.objects.exclude(pk__in=mine).exclude(status="merged").first()
    if stranger is None:
        pytest.skip("this doctor is treating everybody")

    BreakGlassGrant.all_objects.filter(user_id=doctor.uuid).delete()
    client = _client(doctor.email, tenant.slug)
    path = f"/api/clinical/patients/{stranger.uuid}/summary/"

    _privacy_switch(None)
    try:
        assert client.get(path).status_code == 200, (
            "with the relationship switch off a doctor must still read a "
            "summary — the default must not change for clinics that never "
            "opted in"
        )
        _privacy_switch(True)
        refused = client.get(path)
        assert refused.status_code == 403, (
            "with the switch on, a doctor with no care relationship read a "
            "stranger's diagnoses — the object-level check did not run"
        )
        assert "treating" in refused.content.decode().lower(), (
            "the refusal must name the way out; a bare 403 on a clinical record "
            "at three in the morning is how somebody borrows a colleague's login"
        )
    finally:
        _privacy_switch(None)
