"""What the portal shows a patient about their own past and their next step.

Two things were missing from an application whose whole purpose is that the
patient does not have to telephone: **where have I been**, and **when am I
meant to come back**. The second is the loop `apps.scheduling.followups`
opened at the front desk; this checks the patient sees the same answer the
desk does, because a patient told on their phone that nothing is outstanding
while the register says they are three weeks overdue is the one failure that
would make both untrustworthy.

The clinical line matters as much as the content: a visit shows where, when,
who and what the patient came in saying -- never the note and never the
diagnosis, which reach them through results and documents, deliberately
released.
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

    return Portal()


def _section(portal, name):
    response = portal.get(f"/api/me/?section={name}")
    assert response.status_code == 200, response.content[:300]
    return json.loads(response.content)


def test_a_patient_can_see_where_they_have_been(portal):
    visits = _section(portal, "visits")["visits"]
    if not visits:
        pytest.skip("the demo account's patient has never attended")

    for visit in visits:
        assert visit["when"], "a visit with no date is not a visit"
        assert visit["kind"], visit
    # Newest first: the last visit is the one somebody opens this to check.
    dates = [visit["when"] for visit in visits]
    assert dates == sorted(dates, reverse=True)


def test_a_visit_does_not_carry_the_note_or_the_diagnosis(portal):
    """The release model for clinical findings is results and documents.

    A diagnosis arriving on a phone before anybody has explained it is the
    harm `result_visibility` exists to prevent, and a visit list is not a
    back door around it.
    """
    visits = _section(portal, "visits")["visits"]
    if not visits:
        pytest.skip("the demo account's patient has never attended")

    forbidden = {"diagnoses", "diagnosis", "notes", "note", "assessment", "plan"}
    for visit in visits:
        assert not (forbidden & set(visit)), f"{sorted(forbidden & set(visit))} in {visit}"


def test_the_patient_and_the_front_desk_agree_about_follow_ups(portal, tenant):
    """Same derivation, one person's slice of it.

    Not "a similar query": the portal calls
    `apps.scheduling.followups.register` with a patient, so a change to how
    overdue is decided cannot move for one audience and not the other.
    """
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context
    from apps.portal.models import PortalAccount
    from apps.scheduling.followups import register

    mine = _section(portal, "follow-ups")

    with tenant_context(context_for_organization(tenant)):
        account = PortalAccount.objects.filter(
            login_identifier__isnull=False
        ).select_related("patient").first()
        assert account is not None
        desk = register(ahead=365, behind=365, patient=account.patient)

    ours = {(row["due_on"], row["status"]) for row in mine["results"]}
    theirs = {
        (row["due_on"], row["status"])
        for row in desk["results"]
        if row["status"] in {"due", "overdue", "booked"}
    }
    assert ours == theirs


def test_a_recall_still_says_nothing_clinical(portal):
    """The follow-up rows carry the advice the clinician gave the patient.

    That is the patient's own copy of what they were told at the door, which
    is different from a text message somebody else may read over their
    shoulder -- and different again from the note.
    """
    rows = _section(portal, "follow-ups")["results"]
    for row in rows:
        assert row["status"] in {"due", "overdue", "booked"}
        assert "reason" not in row and "diagnosis" not in row


def test_the_home_screen_says_a_follow_up_is_waiting(portal):
    """A count on the first screen, or the feature may as well not exist.

    Somebody who opens the application once a month does not go looking
    through a menu for a section they have never used.
    """
    home = _section(portal, "home")
    assert "follow_ups_due" in home
    assert "visits" in home

    rows = _section(portal, "follow-ups")["results"]
    expected = len([row for row in rows if row["status"] in {"due", "overdue"}])
    assert home["follow_ups_due"] == expected
    assert home["follow_up_overdue"] == any(row["status"] == "overdue" for row in rows)


def test_an_unknown_section_names_the_new_ones(portal):
    response = portal.get("/api/me/?section=nonsense")
    assert response.status_code == 400
    available = json.loads(response.content)["available"]
    assert "visits" in available and "follow-ups" in available
