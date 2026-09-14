"""The same script, written once — and still read before it is signed.

A template is a prescribing aid, and the danger in one is that it stops being
read. So what these check is not that it saves: it is that applying one writes
nothing, that a quantity is computed rather than guessed, that a template
which cannot compute one must carry it, that somebody else's personal template
does not exist as far as you are concerned, and that the organization's
formulary is not editable by everybody who can prescribe from it.
"""

import json

import pytest
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

URL = "/api/clinical/prescription-templates/"


def _client(user, tenant):
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


@pytest.fixture
def doctor(tenant):
    from apps.identity.models import User

    user = User.objects.filter(email="doctor@manakamana.test").first()
    if user is None:
        pytest.skip("no demo doctor; run seed_demo_population")
    return _client(user, tenant), user


@pytest.fixture
def owner(tenant):
    from apps.identity.models import User

    return _client(User.objects.get(email="owner@manakamana.test"), tenant)


URTI = {
    "name": "Adult URTI",
    "description": "Sore throat, no red flags",
    "patient_instructions": "Drink plenty of fluids. Come back if the fever passes three days.",
    "lines": [
        {
            "generic_name": "Amoxicillin", "strength": "500 mg", "dosage_form": "capsule",
            "dose": "1 capsule", "route": "PO", "frequency": "TDS", "duration_days": 5,
            "instructions": "After food",
        },
        {
            "generic_name": "Paracetamol", "strength": "500 mg", "dosage_form": "tablet",
            "dose": "1 tablet", "route": "PO", "frequency": "PRN", "duration_days": 3,
            "is_prn": True, "prn_indication": "Fever or pain", "quantity": "12",
        },
    ],
}


def test_a_template_computes_the_quantity_it_can(doctor):
    client, _ = doctor
    saved = client.post(URL, data=json.dumps(URTI), content_type="application/json")
    assert saved.status_code == 201, saved.content[:300]
    body = json.loads(saved.content)

    amox = body["lines"][0]
    # 1 capsule x three times a day x five days. Nobody should be doing this
    # arithmetic forty times a morning.
    assert amox["quantity"] == "15.00"
    assert amox["frequency_label"] == "Three times daily"

    prn = body["lines"][1]
    assert prn["quantity"] == "12.00", "a when-required line must carry its own quantity"


def test_a_line_whose_quantity_cannot_be_computed_must_carry_one(doctor):
    client, _ = doctor
    refused = client.post(URL, data=json.dumps({
        "name": "Bad one",
        "lines": [{
            "generic_name": "Salbutamol", "dose": "2 puffs", "frequency": "PRN",
            "is_prn": True, "prn_indication": "Wheeze",
        }],
    }), content_type="application/json")
    assert refused.status_code == 400
    assert "quantity" in json.loads(refused.content)["error"]["message"].lower()


def test_a_when_required_medicine_must_say_when(doctor):
    client, _ = doctor
    refused = client.post(URL, data=json.dumps({
        "name": "No indication",
        "lines": [{
            "generic_name": "Tramadol", "dose": "1 tablet", "frequency": "PRN",
            "is_prn": True, "quantity": "10",
        }],
    }), content_type="application/json")
    assert refused.status_code == 400


def test_applying_a_template_writes_no_prescription(doctor):
    from apps.prescriptions.models import Prescription

    client, _ = doctor
    saved = json.loads(client.post(URL, data=json.dumps(URTI), content_type="application/json").content)
    before = Prescription.objects.count()

    applied = client.post(f"{URL}{saved['uuid']}/", content_type="application/json")
    assert applied.status_code == 200, applied.content[:300]
    body = json.loads(applied.content)
    assert len(body["lines"]) == 2
    assert body["times_used"] == 1, "use is counted, so the list can rank by it"
    assert Prescription.objects.count() == before, (
        "applying a template prescribed something on its own"
    )


def test_my_template_is_mine_and_nobody_else_sees_it(doctor, owner):
    client, _ = doctor
    saved = json.loads(client.post(URL, data=json.dumps(URTI), content_type="application/json").content)
    assert saved["shared"] is False

    mine = json.loads(client.get(URL).content)["results"]
    assert any(row["uuid"] == saved["uuid"] for row in mine)

    theirs = json.loads(owner.get(URL).content)["results"]
    assert not any(row["uuid"] == saved["uuid"] for row in theirs), (
        "another prescriber's personal template is visible"
    )
    # And not found rather than forbidden, which is the same statement.
    assert owner.post(f"{URL}{saved['uuid']}/").status_code == 404


def test_sharing_a_template_is_formulary_curation(doctor, owner):
    client, _ = doctor
    refused = client.post(
        URL, data=json.dumps({**URTI, "shared": True}), content_type="application/json",
    )
    assert refused.status_code == 400
    assert json.loads(refused.content)["error"]["code"] == "not_yours_to_share"

    # Somebody who curates the catalogue may, and then everybody sees it.
    shared = owner.post(
        URL, data=json.dumps({**URTI, "name": "House URTI", "shared": True}),
        content_type="application/json",
    )
    assert shared.status_code == 201, shared.content[:300]
    visible = json.loads(client.get(URL).content)["results"]
    assert any(row["name"] == "House URTI" and row["shared"] for row in visible)


def test_a_shared_template_is_not_editable_by_everyone_who_prescribes(doctor, owner):
    client, _ = doctor
    shared = json.loads(owner.post(
        URL, data=json.dumps({**URTI, "name": "House cough", "shared": True}),
        content_type="application/json",
    ).content)

    refused = client.post(URL, data=json.dumps({
        **URTI, "uuid": shared["uuid"], "name": "Changed by me",
    }), content_type="application/json")
    assert refused.status_code == 400
    assert json.loads(refused.content)["error"]["code"] in {
        "not_yours_to_share", "not_yours_to_edit",
    }


def test_a_template_is_retired_never_deleted(doctor):
    from apps.prescriptions.templates_models import PrescriptionTemplate

    client, _ = doctor
    saved = json.loads(client.post(URL, data=json.dumps(URTI), content_type="application/json").content)
    assert client.delete(f"{URL}{saved['uuid']}/").status_code == 204

    row = PrescriptionTemplate.objects.filter(uuid=saved["uuid"]).first()
    assert row is not None and row.is_active is False, (
        "the row is gone, so what was prescribed from it no longer names anything"
    )
    assert not any(
        entry["uuid"] == saved["uuid"]
        for entry in json.loads(client.get(URL).content)["results"]
    )


def test_a_nurse_cannot_write_prescribing_templates(tenant):
    from apps.identity.models import User

    nurse = User.objects.filter(email="nurse@manakamana.test").first()
    if nurse is None:
        pytest.skip("no demo nurse")
    client = _client(nurse, tenant)
    assert client.get(URL).status_code == 403
    assert client.post(URL, data=json.dumps(URTI), content_type="application/json").status_code == 403


def test_an_applied_template_passes_the_prescribing_form(doctor, tenant):
    """The regression: a template saved `route="oral"` — the word, not the
    code — which stored happily and was rejected by the safety preview the
    moment a doctor applied it. A template that cannot be prescribed from is
    worse than no template."""
    from apps.patients.models import Patient

    client, _ = doctor
    saved = json.loads(client.post(URL, data=json.dumps(URTI), content_type="application/json").content)
    applied = json.loads(client.post(f"{URL}{saved['uuid']}/").content)

    patient = Patient.objects.filter(merged_into__isnull=True).first()
    preview = client.post("/api/clinical/prescriptions/preview/", data=json.dumps({
        "patient_uuid": str(patient.uuid),
        "lines": [
            {
                "generic_name": line["generic_name"], "strength": line["strength"],
                "dose": line["dose"], "route": line["route"],
                "frequency": line["frequency"], "duration_days": line["duration_days"],
                "is_prn": line["is_prn"], "prn_indication": line["prn_indication"],
                "instructions": line["instructions"],
            }
            for line in applied["lines"]
        ],
    }), content_type="application/json")
    assert preview.status_code == 200, preview.content[:300]


def test_a_route_that_is_not_a_route_is_refused(doctor):
    client, _ = doctor
    refused = client.post(URL, data=json.dumps({
        "name": "Wrong route",
        "lines": [{
            "generic_name": "Amoxicillin", "dose": "1 capsule", "route": "oral",
            "frequency": "TDS", "duration_days": 5,
        }],
    }), content_type="application/json")
    assert refused.status_code == 400
    assert "route" in json.loads(refused.content)["error"]["message"].lower()


CHEST_PAIN = {
    "name": "Chest pain, low risk",
    "description": "Typical workup before discharge",
    "note": {
        "subjective": "Central chest discomfort. Onset, duration, radiation, exertion:",
        "objective": "Observations stable. Chest clear. Heart sounds normal.",
        "assessment": "Low-risk chest pain. Acute coronary syndrome not excluded on one troponin.",
        "plan": "Repeat troponin at three hours. Discharge advice given if both negative.",
    },
    "lines": [{
        "generic_name": "Aspirin", "strength": "300 mg", "dose": "1 tablet",
        "route": "PO", "frequency": "STAT", "duration_days": 1, "quantity": "1",
    }],
    "investigations": [
        {"test_code": "ECG", "test_name": "Electrocardiogram", "priority": "urgent",
         "clinical_indication": "Chest pain"},
        {"test_code": "CBC", "test_name": "Complete blood count", "priority": "routine"},
    ],
}


def test_a_template_carries_investigations_and_the_note(doctor):
    """An order set: what a presentation is worked up with, not only what it
    is treated with. A template carrying only the medicines leaves the
    ordering half to memory."""
    client, _ = doctor
    saved = client.post(URL, data=json.dumps(CHEST_PAIN), content_type="application/json")
    assert saved.status_code == 201, saved.content[:300]
    body = json.loads(saved.content)

    assert [row["test_code"] for row in body["investigations"]] == ["ECG", "CBC"]
    assert body["investigations"][0]["priority"] == "urgent"
    assert "Repeat troponin" in body["note"]["plan"]

    applied = json.loads(client.post(f"{URL}{body['uuid']}/").content)
    assert len(applied["investigations"]) == 2
    assert applied["note"]["subjective"].startswith("Central chest")


def test_an_urgent_investigation_must_say_what_is_being_looked_for(doctor):
    """The same rule the ordering form applies, applied where the template is
    written — otherwise the template is one that cannot be ordered from."""
    client, _ = doctor
    refused = client.post(URL, data=json.dumps({
        "name": "Urgent, no reason",
        "investigations": [{"test_code": "ECG", "priority": "urgent"}],
    }), content_type="application/json")
    assert refused.status_code == 400
    assert "looked for" in json.loads(refused.content)["error"]["message"]


def test_a_template_of_investigations_alone_is_a_template(doctor):
    """A workup with no medicines in it is an ordinary thing: "pre-operative
    bloods" prescribes nothing."""
    client, _ = doctor
    saved = client.post(URL, data=json.dumps({
        "name": "Pre-operative bloods",
        "investigations": [{"test_code": "CBC", "test_name": "Complete blood count"}],
    }), content_type="application/json")
    assert saved.status_code == 201, saved.content[:300]
    assert json.loads(saved.content)["lines"] == []


def test_an_empty_template_is_refused(doctor):
    client, _ = doctor
    refused = client.post(URL, data=json.dumps({"name": "Nothing"}),
                          content_type="application/json")
    assert refused.status_code == 400
