"""Discharge templates: a starting point, written for the patient too.

What these hold: applying a template writes nothing and turns the follow-up
into a date; somebody else's personal template is invisible; sharing needs
curation; and the patient's half of the summary -- diet, activity, specific
warning signs -- is kept on the stay when it is discharged.
"""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def people(tenant):
    from apps.identity.models import User

    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    owner = User.objects.get(email="owner@manakamana.test")
    if doctor is None:
        pytest.skip("no demo doctor")
    return doctor, owner


def _template(user, **overrides):
    from apps.inpatient.discharge_templating import save_template

    data = {
        "name": "Pneumonia, test",
        "course": "Treated with ___ for ___ days.",
        "advice": "Finish the antibiotic.",
        "warning_signs": ["Breathing gets harder", "  ", "Fever comes back"],
        "follow_up_days": 7,
        **overrides,
    }
    return save_template(user=user, data=data)


def test_applying_turns_the_follow_up_into_a_date_and_writes_nothing(people):
    from apps.inpatient.discharge_templating import apply
    from apps.inpatient.models import Admission

    doctor, _ = people
    in_house = Admission.objects.filter(discharged_at__isnull=True).count()
    template = _template(doctor)
    applied = apply(template, doctor, today=date(2026, 9, 15))
    assert Admission.objects.filter(discharged_at__isnull=True).count() == in_house, (
        "applying a template discharged somebody"
    )

    assert applied["follow_up_on"] == (date(2026, 9, 15) + timedelta(days=7)).isoformat()
    assert applied["warning_signs"] == ["Breathing gets harder", "Fever comes back"], (
        "blank warning signs were kept"
    )
    assert applied["times_used"] == 1


def test_somebody_elses_personal_template_is_invisible(people):
    from apps.inpatient.discharge_templating import visible_to

    doctor, owner = people
    mine = _template(doctor, name="Doctor's own")
    assert visible_to(doctor).filter(pk=mine.pk).exists()
    assert not visible_to(owner).filter(pk=mine.pk).exists()


def test_sharing_needs_curation(people):
    from apps.inpatient.discharge_templating import TemplateError, save_template

    doctor, _ = people
    with pytest.raises(TemplateError):
        save_template(
            user=doctor,
            data={"name": "Ours", "advice": "Rest."},
            shared=True,
            may_curate=False,
        )


def test_an_empty_template_is_refused(people):
    from apps.inpatient.discharge_templating import TemplateError, save_template

    doctor, _ = people
    with pytest.raises(TemplateError):
        save_template(user=doctor, data={"name": "Nothing in it"})


def test_the_patients_half_is_kept_on_the_stay(people, tenant):
    from apps.inpatient.models import Admission, AdmissionStatus
    from apps.inpatient.services import discharge

    doctor, _ = people
    admission = Admission.objects.filter(status=AdmissionStatus.ADMITTED).first()
    if admission is None:
        pytest.skip("nobody in house")

    discharged = discharge(
        admission,
        actor=doctor,
        summary="Treated for pneumonia.",
        advice="Finish the antibiotic.",
        diet="Normal food.",
        activity="No heavy work for two weeks.",
        warning_signs=["Breathing gets harder", "", "Chest pain"],
        override_reason="Test discharge past any open clearance.",
    )
    discharged.refresh_from_db()
    assert discharged.discharge_diet == "Normal food."
    assert discharged.discharge_activity == "No heavy work for two weeks."
    assert discharged.discharge_warning_signs == ["Breathing gets harder", "Chest pain"]


def test_the_list_opens_for_somebody_who_discharges(people, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    doctor, _ = people
    client = Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(doctor).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )
    response = client.get("/api/ipd/discharge-templates/")
    assert response.status_code == 200, response.content
    assert "results" in response.json()
